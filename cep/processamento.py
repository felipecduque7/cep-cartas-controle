"""Sessão de trabalho: processa planos, gera gráficos e alimenta o relatório.

É o ponto de encontro entre o "motor" (leitura, cartas, análise) e as
interfaces (menu e linha de comando). Mantém as calibrações feitas na sessão
para que um acompanhamento logo em seguida já as encontre.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import apresentacao, calibracoes, config, graficos
from .analise import Resultado, acompanhar, calibrar
from .deslocamento import desempenho_personalizado
from .leitura import CALIBRAR, ErroDeLeitura, Plano, carregar_plano
from .relatorio import Relatorio, nova_pasta_sessao, ultima_pasta_sessao
from .util import fmt, slug

# Função que recebe a lista de calibrações compatíveis e devolve a escolhida (ou None).
Escolhedor = Callable[[Plano, List[Tuple[Path, Dict[str, Any]]]], Optional[Dict[str, Any]]]


class Sessao:
    def __init__(self, pasta_saida: Path = config.PASTA_SAIDA, relatorio: Optional[Relatorio] = None):
        self.pasta_saida = Path(pasta_saida)
        self.pasta_saida.mkdir(parents=True, exist_ok=True)
        self.relatorio = relatorio or Relatorio(nova_pasta_sessao(self.pasta_saida))
        self.calibracoes_sessao: List[Dict[str, Any]] = []
        self.ultimo: Optional[Resultado] = None
        self._contador = self._graficos_existentes()

    def _graficos_existentes(self) -> int:
        """Ao continuar um relatório, os gráficos novos não podem sobrescrever os antigos."""
        return len(list(self.relatorio.pasta_graficos.glob("*.png")))

    def usar_relatorio(self, relatorio: Relatorio) -> None:
        """Troca o relatório da sessão (novo ou um anterior que vai continuar)."""
        self.relatorio = relatorio
        self._contador = self._graficos_existentes()

    def continuar_ultimo_relatorio(self) -> Optional[Path]:
        """Retoma o relatório mais recente da pasta de saída. Devolve a pasta, ou None se não houver."""
        pasta = ultima_pasta_sessao(self.pasta_saida)
        if pasta is None:
            return None
        atual = self.relatorio
        self.usar_relatorio(Relatorio.abrir(pasta))
        # A sessão recém-aberta, ainda vazia, não precisa ficar como relatório perdido.
        if atual.pasta != pasta and not atual.blocos and not atual.caminho_registro.exists():
            shutil.rmtree(atual.pasta, ignore_errors=True)
        self.relatorio.salvar()
        return pasta

    # ------------------------------------------------------------------
    def processar_arquivo(self, caminho, escolher: Optional[Escolhedor] = None,
                          calibracao_forcada: Optional[str] = None,
                          avisar: Callable[[str], None] = print) -> Resultado:
        plano = carregar_plano(caminho)
        return self.processar_plano(plano, escolher, calibracao_forcada, avisar)

    def processar_plano(self, plano: Plano, escolher: Optional[Escolhedor] = None,
                        calibracao_forcada: Optional[str] = None,
                        avisar: Callable[[str], None] = print) -> Resultado:
        if (plano.objetivo != CALIBRAR and calibracao_forcada is None and not plano.limites_informados
                and not plano.arquivo_calibracao and not self.calibracoes_candidatas(plano)):
            # Monitorar sem limites e sem nenhuma calibração: os próprios dados estabelecem os limites.
            plano.objetivo = CALIBRAR
            plano.avisos.append("O arquivo pede acompanhamento, mas não traz limites e não há calibração "
                                "disponível; os limites foram calculados (Fase I) com os próprios dados.")
            avisar("Sem limites nem calibração disponível: calibrando com os próprios dados.")
        if plano.objetivo == CALIBRAR:
            resultado = calibrar(plano)
            caminho = calibracoes.salvar(resultado, self.pasta_saida)
            resultado.calibracao_salva = str(caminho)
            self.calibracoes_sessao.append(calibracoes.carregar(caminho))
        else:
            params, origem = self._parametros_acompanhamento(plano, escolher, calibracao_forcada, avisar)
            resultado = acompanhar(plano, params, origem)
        figuras = self._gerar_graficos(resultado)
        resultado.graficos = list(figuras.values())
        apresentacao.registrar(resultado, self.relatorio, figuras)
        self.relatorio.salvar()
        self.ultimo = resultado
        return resultado

    # ------------------------------------------------------------------
    def _parametros_acompanhamento(self, plano: Plano, escolher: Optional[Escolhedor],
                                   calibracao_forcada: Optional[str],
                                   avisar: Callable[[str], None]) -> Tuple[Dict[str, Any], str]:
        from .cartas import criar_carta
        carta = criar_carta(plano)

        def usar_registro(registro: Dict[str, Any], descricao: str) -> Tuple[Dict[str, Any], str]:
            if not calibracoes.compativel(registro, plano):
                raise ErroDeLeitura(f"A calibração {Path(registro.get('_arquivo', '')).name} é de outro tipo de "
                                    f"carta ({registro.get('Type')}) e não serve para dados do tipo {plano.codigo_tipo}.")
            params = calibracoes.params_de_registro(registro, carta)
            arquivo = Path(registro.get("_arquivo", "")).name
            texto = f"{descricao} {arquivo}, calibrada em {registro.get('Calibrado_em', '?')} a partir de " \
                    f"{registro.get('Arquivo_origem', '?')}"
            if registro.get("Unit", "") != plano.unidade:
                plano.avisos.append(f"A calibração usa a unidade '{registro.get('Unit', '')}' e os dados, "
                                    f"'{plano.unidade}'. Confira se são o mesmo processo.")
            return params, texto

        if calibracao_forcada:
            return usar_registro(calibracoes.carregar(calibracao_forcada), "arquivo de calibração")
        if plano.limites_informados:
            params = calibracoes.params_de_limites(plano.limites_informados, carta, plano.avisos)
            return params, "limites informados no próprio arquivo JSON"
        if plano.arquivo_calibracao:
            caminho = calibracoes.resolver_arquivo_calibracao(plano.arquivo_calibracao, plano)
            return usar_registro(calibracoes.carregar(caminho), "arquivo de calibração indicado no JSON:")
        candidatos = self.calibracoes_candidatas(plano)
        if not candidatos:
            raise ErroDeLeitura(
                "Não há calibração disponível para este acompanhamento. Processe antes um JSON de calibração "
                f"do mesmo tipo de carta ({plano.codigo_tipo}) ou informe os limites (LSC, LC, LIC) no arquivo."
            )
        if escolher is not None:
            escolhido = escolher(plano, candidatos)
            if escolhido is None:
                raise ErroDeLeitura("Acompanhamento cancelado: nenhuma calibração escolhida.")
            return usar_registro(escolhido, "arquivo de calibração")
        caminho, registro = candidatos[0]
        unidade_cal = registro.get("Unit", "") or ""
        if unidade_cal and plano.unidade and unidade_cal != plano.unidade:
            raise ErroDeLeitura(
                f"A calibração disponível mais próxima ({caminho.name}) usa a unidade '{unidade_cal}', mas os dados "
                f"estão em '{plano.unidade}'. Indique a calibração certa com --calibracao ou pelo menu."
            )
        distancia = registro.get("_distancia", 0.0)
        if distancia > calibracoes.DISTANCIA_PLAUSIVEL:
            raise ErroDeLeitura(
                f"A calibração mais próxima ({caminho.name}) tem linha central a {fmt(distancia, 1)}σ do nível dos "
                "dados: parece ser de outro processo. Indique a calibração certa com --calibracao ou pelo menu."
            )
        avisar(f"Usando a calibração {caminho.name} (feita a partir de {registro.get('Arquivo_origem', '?')}).")
        return usar_registro(registro, "arquivo de calibração")

    def calibracoes_candidatas(self, plano: Plano) -> List[Tuple[Path, Dict[str, Any]]]:
        """Calibrações compatíveis, da mais adequada para a menos adequada.

        Critérios, nesta ordem: mesma unidade, mesmo tipo de carta, feita nesta
        sessão, mesma descrição e, por fim, a mais recente.
        """
        itens, vistos = [], set()
        for registro in reversed(self.calibracoes_sessao):
            chave = str(Path(registro["_arquivo"]).resolve())
            if calibracoes.compativel(registro, plano) and chave not in vistos:
                vistos.add(chave)
                itens.append((Path(registro["_arquivo"]), registro, True))
        for caminho, registro in calibracoes.listar(self.pasta_saida, plano):
            chave = str(caminho.resolve())
            if chave not in vistos:
                vistos.add(chave)
                itens.append((caminho, registro, False))

        from .cartas import criar_carta
        carta = criar_carta(plano)
        for _caminho, registro, _sessao in itens:
            try:
                registro["_distancia"] = calibracoes.distancia_ao_centro(
                    carta, calibracoes.params_de_registro(registro, carta))
            except (ErroDeLeitura, KeyError, TypeError, ValueError, ZeroDivisionError):
                registro["_distancia"] = float("inf")

        def nota(item):
            caminho, registro, da_sessao = item
            return ((registro.get("Unit", "") or "") == (plano.unidade or ""),
                    registro.get("Tipo_normalizado") == plano.tipo,
                    registro["_distancia"] <= calibracoes.DISTANCIA_PLAUSIVEL, da_sessao,
                    registro.get("Label", "") == plano.rotulo,
                    caminho.stat().st_mtime if caminho.exists() else 0.0,
                    -registro["_distancia"])
        itens.sort(key=nota, reverse=True)
        return [(caminho, registro) for caminho, registro, _ in itens]

    # ------------------------------------------------------------------
    def _nome_grafico(self, plano: Plano, sufixo: str) -> Path:
        self._contador += 1
        return self.relatorio.pasta_graficos / f"{self._contador:02d}_{slug(Path(plano.arquivo).stem, 30)}_{sufixo}.png"

    def _gerar_graficos(self, resultado: Resultado) -> Dict[str, str]:
        plano, carta = resultado.plano, resultado.carta
        figuras: Dict[str, str] = {}
        n_texto = ""
        if carta.familia == "variaveis":
            n_texto = f" · n = {carta.n_const}" if carta.n_const else f" · n de {min(carta.n)} a {max(carta.n)}"
        total = apresentacao.quantos(carta, carta.num_pontos())
        nomes = ("Cartas " if len(resultado.series_finais) > 1 else "Carta ") + \
            " e ".join(s.nome for s in resultado.series_finais)
        if resultado.calibracao:
            mudou = bool(resultado.removidos) or any(resultado.sinais_tentativos.values())
            if mudou and resultado.removidos:
                figuras["tentativos"] = str(graficos.grafico_cartas(
                    resultado.series_tentativas, resultado.sinais_tentativos,
                    self._nome_grafico(plano, "limites_tentativos"),
                    f"{nomes} – limites tentativos", f"{plano.arquivo}{n_texto} · {total} no cálculo",
                    lse=plano.lse, lie=plano.lie))
            usados = apresentacao.quantos(carta, len(resultado.usados))
            figuras["revisados"] = str(graficos.grafico_cartas(
                resultado.series_finais, resultado.sinais_finais if resultado.removidos else resultado.sinais_tentativos,
                self._nome_grafico(plano, "limites_calibrados"),
                f"{nomes} – limites {'revisados' if resultado.removidos else 'calibrados'}",
                f"{plano.arquivo}{n_texto} · {usados} de {carta.num_pontos()} no cálculo",
                removidos_ids=[i + 1 for i in resultado.removidos], lse=plano.lse, lie=plano.lie))
        else:
            figuras["carta"] = str(graficos.grafico_cartas(
                resultado.series_finais, resultado.sinais_finais, self._nome_grafico(plano, "acompanhamento"),
                f"{nomes} – acompanhamento", f"{plano.arquivo}{n_texto} · {total} · limites calibrados",
                lse=plano.lse, lie=plano.lie))
        cap = resultado.capacidade
        if cap and cap.get("tipo") == "variaveis" and cap.get("sigma") and cap.get("rcpk") is not None:
            partes = []
            if cap.get("rcp") is not None:
                partes.append(f"RCP = {fmt(cap['rcp'], 2)}")
            partes.append(f"RCPk = {fmt(cap['rcpk'], 2)} ({cap['classificacao']})")
            if cap.get("ppk") is not None:
                partes.append(f"Ppk = {fmt(cap['ppk'], 2)}")
            figuras["capacidade"] = str(graficos.grafico_capacidade(
                carta.valores_individuais(), cap["mu"], cap["sigma"], plano.lse, plano.lie, plano.unidade,
                "Capacidade do processo – medições individuais e especificação", carta.casas,
                self._nome_grafico(plano, "capacidade"), "   ".join(partes)))
        curva = curva_deteccao(resultado)
        if curva:
            xs, ys, eixo, destaque, formatar = curva
            figuras["deteccao"] = str(graficos.grafico_deteccao(
                xs, ys, eixo, "Probabilidade de detectar um deslocamento em uma amostra (1 − β)",
                self._nome_grafico(plano, "deteccao"), destaque, formatar))
        return figuras


def curva_deteccao(resultado: Resultado):
    """Pontos da curva 1 − β para o gráfico de detecção."""
    d = resultado.deslocamento
    if not d or d.get("aviso") or "avaliado" not in d:
        return None
    aval = d["avaliado"]
    tipo = d["tipo"]
    if tipo == "media":
        alvo = abs(aval["delta"])
        maximo = max(3.5, alvo * 1.2)
        xs = [i * maximo / 200 for i in range(201)]
        ys = [desempenho_personalizado(d, x)["p_detectar"] for x in xs]
        destaque = (alvo, desempenho_personalizado(d, alvo)["p_detectar"],
                    f"estimado: {fmt(alvo, 2)}σ → {fmt(100 * desempenho_personalizado(d, alvo)['p_detectar'], 0)}%")
        return xs, ys, f"Deslocamento da média (em σ do processo; n = {d['n']})", destaque, lambda v: f"{fmt(v, 1)}σ"
    if tipo == "variabilidade":
        alvo = aval["razao"]
        maximo = max(3.5, alvo * 1.2)
        xs = [1 + i * (maximo - 1) / 200 for i in range(201)]
        ys = [desempenho_personalizado(d, x)["p_detectar"] for x in xs]
        destaque = None
        if alvo >= 1:
            p = desempenho_personalizado(d, alvo)["p_detectar"]
            destaque = (alvo, p, f"estimado: {fmt(alvo, 2)}·σ0 → {fmt(100 * p, 0)}%")
        return xs, ys, "Razão σ1/σ0 (aumento do desvio-padrão)", destaque, lambda v: fmt(v, 2)
    centro = d["centro"]
    alvo = aval["novo"]
    maximo = max(3 * centro, alvo * 1.2)
    if tipo == "fracao":
        maximo = min(1.0, maximo)
    xs = [centro + i * (maximo - centro) / 200 for i in range(201)]
    ys = [desempenho_personalizado(d, x)["p_detectar"] for x in xs]
    destaque = None
    if alvo >= centro:
        p = desempenho_personalizado(d, alvo)["p_detectar"]
        destaque = (alvo, p, f"estimado: {fmt(alvo, 4 if tipo != 'contagem' else 2)} → {fmt(100 * p, 0)}%")
    casas = 3 if tipo != "contagem" else 1
    return xs, ys, d["eixo"], destaque, lambda v: fmt(v, casas)
