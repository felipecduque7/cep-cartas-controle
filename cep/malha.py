"""CEP em malha fechada: o software decide, a cada subgrupo medido, se o processo precisa de ajuste.

Fluxo de um processo físico (ex.: a estufa com ESP32):

1. Aquecimento: enquanto a média dos subgrupos está longe do alvo, o PWM é corrigido
   proporcionalmente para levar o processo até o alvo.
2. Calibração (Fase I): com o PWM fixo, os primeiros subgrupos estáveis viram a
   calibração da carta X-barra e R, com retirada dos pontos fora e limites revisados,
   exatamente como no menu.
3. Acompanhamento (Fase II): cada novo subgrupo é avaliado contra os limites calibrados.
   O PWM só muda quando a carta dá um sinal (regra 1 a 4 ou tendência). Sem sinal,
   nada é ajustado, para não "mexer no processo à toa" (o erro do funil de Deming).

A correção é proporcional ao deslocamento estimado: PWM novo = PWM + ganho·(LC − nível),
em que o nível é a média dos pontos que formaram o sinal. Depois de um ajuste, a contagem
das regras recomeça, para o mesmo sinal não provocar correções repetidas.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .analise import Resultado, acompanhar, calibrar
from .leitura import plano_de_dicionario
from .util import fmt

AQUECIMENTO, CALIBRACAO, ACOMPANHAMENTO = "aquecimento", "calibracao", "acompanhamento"
NOMES_FASE = {AQUECIMENTO: "Aquecimento", CALIBRACAO: "Calibração", ACOMPANHAMENTO: "Acompanhamento"}


@dataclass
class Configuracao:
    alvo: float = 35.0                      # temperatura desejada
    lse: Optional[float] = 38.0             # limites de especificação do processo
    lie: Optional[float] = 32.0
    n: int = 5                              # medições por subgrupo
    subgrupos_calibracao: int = 20          # subgrupos usados na Fase I
    unidade: str = "°C"
    rotulo: str = "Temperatura da estufa"
    dispositivo: str = "esp32-estufa"
    ganho: float = 10.0                     # ajuste no acompanhamento: PWM por unidade de desvio (ex.: 10 PWM por °C)
    kp: float = 20.0                        # controlador PI do aquecimento (forma incremental)
    ki: float = 5.0
    pwm_inicial: int = 128
    pwm_min: int = 0
    pwm_max: int = 255
    tolerancia_aquecimento: float = 0.3     # |média − alvo| para considerar o processo no alvo
    subgrupos_estaveis: int = 5             # quantos seguidos no alvo (e sem deriva) para começar a calibrar
    espera_apos_ajuste: int = 8             # subgrupos sem novo ajuste, para o processo responder ao anterior
    janela_maxima: int = 30                 # subgrupos avaliados no acompanhamento


@dataclass
class Decisao:
    numero: int                  # número do subgrupo recebido (1, 2, 3, ...)
    fase: str
    acao: str                    # "manter", "aumentar", "reduzir", "desligar", "verificar"
    pwm: int
    alarme: bool
    motivo: str
    media: float
    amplitude: float
    quando: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def resposta(self, limites: Optional[Dict[str, float]]) -> Dict[str, Any]:
        """O que o servidor devolve ao microcontrolador."""
        dados = asdict(self)
        if limites:
            dados.update(limites)
        return dados


class MalhaCEP:
    def __init__(self, config: Optional[Configuracao] = None, sessao=None):
        self.config = config or Configuracao()
        if self.config.n < 2:
            raise ValueError("A carta X-barra e R precisa de subgrupos com pelo menos 2 medições.")
        self.sessao = sessao                     # Sessao do pacote, para gravar no relatório PDF (opcional)
        self.fase = AQUECIMENTO
        self.pwm = int(self.config.pwm_inicial)
        self.subgrupos: List[List[float]] = []   # tudo o que chegou, na ordem
        self.historico: List[Decisao] = []
        self.inicio_calibracao: Optional[int] = None   # posição do primeiro subgrupo da calibração
        self.inicio_acompanhamento: Optional[int] = None
        self.inicio_janela: Optional[int] = None       # a contagem das regras recomeça daqui
        self.calibracao: Optional[Resultado] = None
        self.ultimo_acompanhamento: Optional[Resultado] = None
        self._estaveis = 0
        self._erro_anterior: Optional[float] = None
        self._medias_aquecimento: List[float] = []
        self._espera = 0
        self._trava = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def params(self) -> Optional[Dict[str, Any]]:
        return self.calibracao.params if self.calibracao else None

    def limites(self) -> Optional[Dict[str, float]]:
        if not self.calibracao:
            return None
        x, r = self.calibracao.series_finais[0], self.calibracao.series_finais[1]
        return {"lic": x.lic[0], "lc": x.lc[0], "lsc": x.lsc[0], "r_lc": r.lc[0], "r_lsc": r.lsc[0]}

    def _limitar(self, pwm: float) -> int:
        return int(round(min(self.config.pwm_max, max(self.config.pwm_min, pwm))))

    def _plano(self, subgrupos: Sequence[Sequence[float]], objetivo: str):
        c = self.config
        conteudo = {"Type": "X", "Goal": objetivo, "Unit": c.unidade, "Label": c.rotulo,
                    "Created_by": c.dispositivo, "Measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Data": [list(s) for s in subgrupos]}
        if c.lse is not None:
            conteudo["LSE"] = c.lse
        if c.lie is not None:
            conteudo["LIE"] = c.lie
        return plano_de_dicionario(conteudo, f"malha_{c.dispositivo}.json")

    # ------------------------------------------------------------------
    def receber(self, subgrupo: Sequence[Any], pwm_atual: Optional[Any] = None) -> Decisao:
        """Recebe um subgrupo medido e devolve a decisão para o atuador."""
        try:
            valores = [float(v) for v in subgrupo]
        except (TypeError, ValueError):
            raise ValueError("O subgrupo precisa ser uma lista de números.") from None
        if len(valores) != self.config.n:
            raise ValueError(f"O subgrupo tem {len(valores)} medições; a malha espera {self.config.n}.")
        if any(v != v or abs(v) == float("inf") for v in valores):
            raise ValueError("O subgrupo tem um valor inválido (NaN ou infinito): confira o sensor.")
        with self._trava:
            if pwm_atual is not None:
                try:
                    self.pwm = self._limitar(float(pwm_atual))
                except (TypeError, ValueError):
                    pass
            self.subgrupos.append(valores)
            media = sum(valores) / len(valores)
            amplitude = max(valores) - min(valores)
            if self.fase == AQUECIMENTO:
                decisao = self._aquecer(media, amplitude)
            elif self.fase == CALIBRACAO:
                decisao = self._calibrar(media, amplitude)
            else:
                decisao = self._acompanhar(media, amplitude)
            self.pwm = decisao.pwm
            self.historico.append(decisao)
            return decisao

    def _decisao(self, acao: str, pwm: float, alarme: bool, motivo: str, media: float, amplitude: float,
                 fase: Optional[str] = None) -> Decisao:
        return Decisao(numero=len(self.subgrupos), fase=fase or self.fase, acao=acao, pwm=self._limitar(pwm),
                       alarme=alarme, motivo=motivo, media=media, amplitude=amplitude)

    # --- Fase 0: levar o processo ao alvo --------------------------------------
    def _aquecer(self, media: float, amplitude: float) -> Decisao:
        """Controlador PI incremental: ΔPWM = kp·(e − e_anterior) + ki·e, com e = alvo − média."""
        c = self.config
        erro = c.alvo - media
        self._medias_aquecimento.append(media)
        recentes = self._medias_aquecimento[-c.subgrupos_estaveis:]
        # Sem deriva: as últimas médias variam menos que a tolerância entre si.
        parado = len(recentes) < 2 or max(recentes) - min(recentes) <= c.tolerancia_aquecimento
        if abs(erro) <= c.tolerancia_aquecimento and parado:
            self._estaveis += 1
            if self._estaveis >= c.subgrupos_estaveis:
                self.fase = CALIBRACAO
                self.inicio_calibracao = len(self.subgrupos)     # o próximo subgrupo é o 1º da calibração
                return self._decisao("manter", self.pwm, False,
                                     f"Processo no alvo; PWM fixo em {self.pwm} e início da calibração "
                                     f"({c.subgrupos_calibracao} subgrupos).", media, amplitude, AQUECIMENTO)
            return self._decisao("manter", self.pwm, False,
                                 f"Média {fmt(media, 2)} dentro da tolerância do alvo "
                                 f"({self._estaveis}/{c.subgrupos_estaveis}).", media, amplitude)
        self._estaveis = 0
        delta = c.ki * erro + (c.kp * (erro - self._erro_anterior) if self._erro_anterior is not None else 0.0)
        self._erro_anterior = erro
        novo = self.pwm + delta
        acao = "aumentar" if novo > self.pwm else "reduzir" if novo < self.pwm else "manter"
        return self._decisao(acao, novo, False,
                             f"Aquecimento: média {fmt(media, 2)}, alvo {fmt(c.alvo, 2)}.", media, amplitude)

    # --- Fase I: calibração -------------------------------------------------------
    def _calibrar(self, media: float, amplitude: float) -> Decisao:
        c = self.config
        dados = self.subgrupos[self.inicio_calibracao:]
        if len(dados) < c.subgrupos_calibracao:
            return self._decisao("manter", self.pwm, False,
                                 f"Calibrando: {len(dados)}/{c.subgrupos_calibracao} subgrupos com PWM fixo.",
                                 media, amplitude)
        plano = self._plano(dados, "Calibrar")
        if self.sessao is not None:
            self.calibracao = self.sessao.processar_plano(plano, avisar=lambda _t: None)
        else:
            self.calibracao = calibrar(plano)
        self.fase = ACOMPANHAMENTO
        self.inicio_acompanhamento = self.inicio_janela = len(self.subgrupos)
        lim = self.limites()
        motivo = (f"Calibração concluída: X-barra {fmt(lim['lic'], 3)} / {fmt(lim['lc'], 3)} / {fmt(lim['lsc'], 3)}"
                  f"; {self.calibracao.status}")
        alarme = self.calibracao.nivel == "critico"
        return self._decisao("manter", self.pwm, alarme, motivo, media, amplitude, CALIBRACAO)

    # --- Fase II: acompanhamento com ajuste só quando a carta sinaliza -------------
    def _acompanhar(self, media: float, amplitude: float) -> Decisao:
        c = self.config
        janela = self.subgrupos[self.inicio_janela:][-c.janela_maxima:]
        deslocamento_janela = len(self.subgrupos) - len(janela)     # posição do 1º ponto da janela
        if len(janela) < 2:
            # Logo depois de um ajuste a janela tem 1 ponto: só a regra 1 se aplica.
            janela = self.subgrupos[-2:]
            deslocamento_janela = len(self.subgrupos) - 2
            so_regra_1 = True
        else:
            so_regra_1 = False
        resultado = acompanhar(self._plano(janela, "Acompanhar"), self.params, "calibração da malha fechada")
        self.ultimo_acompanhamento = resultado
        ultimo = len(janela)
        centro = self.params["centro"]
        medias = [sum(s) / len(s) for s in janela]
        def do_ultimo(chave: str):
            return [s for s in resultado.sinais_finais.get(chave, [])
                    if ultimo in s.pontos and (s.regra == "1" or not so_regra_1)]
        sinais_x = do_ultimo("xbarra")
        sinais_r = do_ultimo("r")

        # Segurança primeiro: passou da especificação superior, o aquecedor desliga.
        if c.lse is not None and media > c.lse:
            self._recomecar_contagem()
            return self._decisao("desligar", c.pwm_min, True,
                                 f"Média {fmt(media, 2)} acima do LSE {fmt(c.lse, 2)}: aquecedor desligado.",
                                 media, amplitude)
        if self._espera > 0:
            self._espera -= 1
            if self._espera == 0:
                self._recomecar_contagem()       # o transitório do ajuste não entra nas regras
            texto = (f"Aguardando o efeito do último ajuste ({self._espera} subgrupo(s) restante(s))."
                     if self._espera else "Fim da espera: a contagem das regras recomeça no próximo subgrupo.")
            return self._decisao("manter", self.pwm, False, texto, media, amplitude)
        if sinais_x:
            # A regra mais grave define o tipo de aviso; o nível estimado vem dos pontos do sinal.
            ordem = {"1": 0, "2": 1, "3": 2, "4": 3, "T": 4}
            sinal = min(sinais_x, key=lambda s: ordem.get(s.regra, 9))
            pontos = [p for p in sinal.pontos if 1 <= p <= ultimo]
            nivel = sum(medias[p - 1] for p in pontos) / len(pontos)
            novo = self.pwm + c.ganho * (centro - nivel)
            acao = "aumentar" if novo > self.pwm else "reduzir" if novo < self.pwm else "manter"
            ponto_global = deslocamento_janela + ultimo
            descricao = "fora dos limites" if sinal.regra == "1" else f"regra {sinal.regra}"
            motivo = (f"Subgrupo {ponto_global}: {descricao} ({sinal.lado}) na carta X-barra; nível estimado "
                      f"{fmt(nivel, 2)} contra LC {fmt(centro, 2)}. PWM {self.pwm} → {self._limitar(novo)}.")
            self._recomecar_contagem()
            self._espera = c.espera_apos_ajuste
            return self._decisao(acao, novo, sinal.regra == "1", motivo, media, amplitude)
        if sinais_r:
            sinal = sinais_r[0]
            if sinal.regra == "1":
                return self._decisao("verificar", self.pwm, True,
                                     f"Amplitude {fmt(amplitude, 2)} acima do LSC da carta R: variação anormal "
                                     "(porta aberta, ventilação ou sensor). PWM mantido.", media, amplitude)
        return self._decisao("manter", self.pwm, False, "Sem sinais: processo sob controle, PWM mantido.",
                             media, amplitude)

    def _recomecar_contagem(self) -> None:
        self.inicio_janela = len(self.subgrupos)

    # ------------------------------------------------------------------
    def estado(self) -> Dict[str, Any]:
        """Resumo para o painel web e para o endpoint /estado."""
        with self._trava:
            ultimas = [asdict(d) for d in self.historico[-60:]]
            ajustes = sum(1 for d in self.historico if d.fase == ACOMPANHAMENTO and d.acao != "manter")
            return {
                "dispositivo": self.config.dispositivo,
                "fase": self.fase,
                "nome_fase": NOMES_FASE[self.fase],
                "pwm": self.pwm,
                "alvo": self.config.alvo,
                "unidade": self.config.unidade,
                "lse": self.config.lse,
                "lie": self.config.lie,
                "subgrupos_recebidos": len(self.subgrupos),
                "limites": self.limites(),
                "status_calibracao": self.calibracao.status if self.calibracao else None,
                "ajustes_no_acompanhamento": ajustes,
                "ultimas_decisoes": ultimas,
            }

    def subgrupos_acompanhamento(self) -> List[List[float]]:
        if self.inicio_acompanhamento is None:
            return []
        return self.subgrupos[self.inicio_acompanhamento:]


# ----------------------------------------------------------------------
# Relatório da malha fechada
# ----------------------------------------------------------------------
def grafico_malha(malha: MalhaCEP, caminho) -> str:
    """Média de cada subgrupo com os limites calibrados (em cima) e o PWM aplicado (embaixo)."""
    from . import graficos  # importa o matplotlib só quando precisa
    plt = graficos.plt
    cor = graficos.COR
    decisoes = malha.historico
    x = [d.numero for d in decisoes]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(graficos.LARGURA, 4.6), sharex=True,
                                   gridspec_kw={"height_ratios": [2.2, 1]})
    inicio_cal = (malha.inicio_calibracao or 0) + 0.5
    inicio_ac = (malha.inicio_acompanhamento or len(decisoes)) + 0.5
    for ax in (ax1, ax2):
        if malha.inicio_calibracao is not None:
            ax.axvspan(inicio_cal, inicio_ac, color=cor["grade"], alpha=0.45, lw=0, zorder=0)
        graficos._estilo(ax)
    ax1.plot(x, [d.media for d in decisoes], color=cor["serie"], lw=1.3, marker="o", ms=2.6, zorder=3)
    lim = malha.limites()
    if lim:
        ax1.hlines([lim["lic"], lim["lsc"]], inicio_ac, x[-1] + 0.5, colors=cor["critico"], lw=1.0,
                   linestyles=(0, (5, 3)), zorder=2)
        ax1.hlines(lim["lc"], inicio_ac, x[-1] + 0.5, colors=cor["tinta2"], lw=1.0, zorder=2)
    ax1.axhline(malha.config.alvo, color=cor["muda"], lw=0.8, ls=":", zorder=1)
    ajustes = [d for d in decisoes if d.fase == ACOMPANHAMENTO and d.acao != "manter"]
    if ajustes:
        ax1.scatter([d.numero for d in ajustes], [d.media for d in ajustes], s=46, marker="D",
                    color=cor["alerta"], edgecolors=cor["superficie"], zorder=5, label="ajuste da malha")
        ax1.legend(loc="lower right", fontsize=7, frameon=False)
    ax1.set_ylabel(f"Média do subgrupo ({malha.config.unidade})")
    ax1.set_title(f"{malha.config.rotulo}: aquecimento, calibração (faixa cinza) e acompanhamento",
                  loc="left")
    ax2.step(x, [d.pwm for d in decisoes], where="post", color=cor["tinta2"], lw=1.2)
    ax2.set_ylabel("PWM")
    ax2.set_xlabel("Subgrupo")
    fig.tight_layout()
    fig.savefig(caminho, dpi=graficos.DPI)
    plt.close(fig)
    return str(caminho)


def registrar_no_relatorio(malha: MalhaCEP, sessao) -> Optional[str]:
    """Acrescenta ao PDF o acompanhamento (com a carta) e a seção da malha fechada. Devolve o PDF."""
    if not malha.historico:
        return None
    acompanhados = malha.subgrupos_acompanhamento()
    if malha.calibracao is not None and len(acompanhados) >= 2:
        plano = malha._plano(acompanhados, "Acompanhar")
        sessao.processar_plano(plano, calibracao_forcada=malha.calibracao.calibracao_salva,
                               avisar=lambda _t: None)
    rel = sessao.relatorio
    c = malha.config
    rel.secao(f"Malha fechada – {c.rotulo}")
    rel.paragrafo(
        "O microcontrolador mede o processo e envia cada subgrupo ao servidor. O servidor leva o processo ao "
        "alvo (aquecimento, com controlador PI), calibra a carta X-barra e R com o PWM fixo e, no "
        "acompanhamento, só altera o PWM quando a carta dá um sinal. A correção é proporcional ao "
        "deslocamento estimado: PWM novo = PWM + ganho × (LC − nível), e depois de cada ajuste o servidor "
        "espera o processo responder antes de avaliar de novo."
    )
    rel.pares([
        ("Dispositivo", c.dispositivo), ("Alvo", f"{fmt(c.alvo, 2)} {c.unidade}"),
        ("Especificação", f"{fmt(c.lie, 2) if c.lie is not None else '–'} a "
                          f"{fmt(c.lse, 2) if c.lse is not None else '–'} {c.unidade}"),
        ("Medições por subgrupo", c.n), ("Subgrupos da calibração", c.subgrupos_calibracao),
        ("Ganho do ajuste", f"{fmt(c.ganho, 1)} PWM por {c.unidade}"),
        ("Espera após ajuste", f"{c.espera_apos_ajuste} subgrupos"),
        ("Subgrupos recebidos", len(malha.subgrupos)),
    ])
    pasta = rel.pasta_graficos
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"malha_{len(list(pasta.glob('malha_*.png'))) + 1:02d}.png"
    rel.imagem(grafico_malha(malha, caminho))
    ajustes = [d for d in malha.historico if d.acao != "manter" and d.fase == ACOMPANHAMENTO]
    if ajustes:
        rel.subtitulo("Ajustes feitos no acompanhamento")
        rel.tabela(["Subgrupo", "Hora", "Ação", "PWM", "Motivo"],
                   [[d.numero, d.quando, d.acao, d.pwm, d.motivo] for d in ajustes],
                   larguras=[2.0, 1.9, 1.8, 1.3, 10.0])
    else:
        rel.paragrafo("Nenhum ajuste foi necessário no acompanhamento: a carta não deu sinais.")
    return str(rel.salvar())
