"""Calibração (Fase I) e acompanhamento (Fase II).

Calibração, como no Montgomery & Runger:
  1. calcula os limites tentativos com todos os subgrupos;
  2. retira os pontos além dos limites (regra 1) e recalcula;
  3. repete até nenhum ponto restante cair fora (limites revisados);
  4. aplica as regras de alerta aos pontos mantidos e avisa o que restar.
  Os pontos só deveriam sair do cálculo depois de identificada a causa
  atribuível; o programa faz a retirada automaticamente e registra a ressalva.

Acompanhamento: usa os limites calibrados (fixos) para avaliar novos dados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config
from . import deslocamento
from .capacidade import capacidade_atributos, capacidade_variaveis
from .cartas import Carta, Serie, criar_carta
from .leitura import ACOMPANHAR, CALIBRAR, ErroDeLeitura, Plano
from .regras import Sinal, avaliar, pontos_fora
from .util import lista_ids, plural


@dataclass
class Iteracao:
    numero: int
    usados: List[int]                       # posições (0-based)
    params: Dict[str, Any]
    series: List[Serie]
    fora: Dict[str, List[tuple]]            # chave da série -> [(posição, lado)]
    removidos: List[int]                    # posições retiradas ao fim desta iteração


@dataclass
class Resultado:
    plano: Plano
    carta: Carta
    objetivo: str
    params: Dict[str, Any]
    series_finais: List[Serie]
    sinais_finais: Dict[str, List[Sinal]]
    usados: List[int]
    removidos: List[int]
    status: str
    nivel: str                               # "ok", "alerta" ou "critico"
    ressalvas: List[str] = field(default_factory=list)
    iteracoes: List[Iteracao] = field(default_factory=list)
    series_tentativas: List[Serie] = field(default_factory=list)
    sinais_tentativos: Dict[str, List[Sinal]] = field(default_factory=dict)
    capacidade: Optional[Dict[str, Any]] = None
    deslocamento: Optional[Dict[str, Any]] = None
    origem_limites: str = ""
    graficos: List[str] = field(default_factory=list)
    calibracao_salva: Optional[str] = None

    @property
    def serie_principal(self) -> Serie:
        return self.series_finais[0]

    @property
    def calibracao(self) -> bool:
        return self.objetivo == CALIBRAR

    def nome_serie(self, chave: str) -> str:
        for s in self.series_finais:
            if s.chave == chave:
                return s.nome
        return chave


def _avaliar_todas(series: List[Serie], apenas=None) -> Dict[str, List[Sinal]]:
    return {s.chave: avaliar(s, apenas) for s in series}


def calibrar(plano: Plano) -> Resultado:
    carta = criar_carta(plano)
    m = carta.num_pontos()
    usados = list(range(m))
    iteracoes: List[Iteracao] = []
    ressalvas: List[str] = []
    convergiu = False
    for numero in range(config.MAX_ITERACOES_REVISAO + 1):
        params = carta.estimar(usados)
        series = carta.series(params)
        fora = {s.chave: pontos_fora(s, set(usados)) for s in series}
        remover = set()
        for chave in carta.remover_por():
            remover |= {pos for pos, _ in fora.get(chave, [])}
        iteracao = Iteracao(numero, list(usados), params, series, fora, sorted(remover))
        iteracoes.append(iteracao)
        if not remover:
            convergiu = True
            break
        restantes = [i for i in usados if i not in remover]
        if len(restantes) < carta.minimo_pontos():
            iteracao.removidos = []
            ressalvas.append("A revisão retiraria quase todos os pontos; os limites ficaram na última "
                             "iteração possível.")
            break
        usados = restantes

    final = iteracoes[-1]
    params, series_finais = final.params, final.series
    usados = final.usados
    removidos = sorted(set(range(m)) - set(usados))
    sinais_tentativos = _avaliar_todas(iteracoes[0].series)
    sinais_finais = _avaliar_todas(series_finais, set(usados))
    nome = carta.nome_ponto

    alertas = {chave: [s for s in sinais if not s.fora_de_controle] for chave, sinais in sinais_finais.items()}
    ainda_fora = {chave: [s for s in sinais if s.fora_de_controle] for chave, sinais in sinais_finais.items()}
    tem_alerta = any(alertas.values())
    tem_fora = any(ainda_fora.values())
    fracao_removida = len(removidos) / m

    if tem_fora or not convergiu:
        status, nivel = "Calibração não confiável: a revisão não eliminou os pontos fora de controle.", "critico"
    elif fracao_removida > config.FRACAO_MAXIMA_REMOVIDA:
        status, nivel = (f"Calibração não confiável: {_quantos(removidos, nome)} de {m} "
                         "ficaram fora dos limites."), "critico"
    elif not removidos and not tem_alerta:
        status, nivel = "Processo sob controle estatístico: limites calibrados.", "ok"
    elif not tem_alerta:
        feminino = nome in ("amostra", "observação")
        retirado = ("retirada" if feminino else "retirado") + ("s" if len(removidos) > 1 else "")
        status, nivel = (f"Limites calibrados após revisão ({_quantos(removidos, nome)} {retirado} "
                         "do cálculo)."), "alerta"
    else:
        status, nivel = "Limites calibrados com ressalvas: restam sinais de alerta entre os pontos mantidos.", "alerta"

    if removidos:
        ressalvas.append(
            f"Os pontos {lista_ids([i + 1 for i in removidos])} saíram do cálculo por estarem fora dos limites. "
            "Pelo Montgomery, um ponto só deve ser descartado depois de identificada a causa atribuível; "
            "se não houver causa, vale reavaliar a decisão."
        )
    if tem_alerta:
        partes = []
        for chave, lista in alertas.items():
            for s in lista:
                partes.append(f"{_nome_regra_curto(s)} na carta {_nome(series_finais, chave)} "
                              f"(pontos {lista_ids(s.pontos)})")
        ressalvas.append("Restam sinais de alerta nos pontos mantidos: " + "; ".join(partes) +
                         ". Os limites só devem ser usados no acompanhamento depois de investigar essas causas.")
    if m < config.SUBGRUPOS_RECOMENDADOS:
        ressalvas.append(f"Foram usados {m} {nome}s; o Montgomery recomenda pelo menos "
                         f"{config.SUBGRUPOS_RECOMENDADOS} a 25 na calibração.")
    ressalvas.extend(_ressalvas_degeneradas(carta, params))

    resultado = Resultado(plano=plano, carta=carta, objetivo=CALIBRAR, params=params,
                          series_finais=series_finais, sinais_finais=sinais_finais, usados=usados,
                          removidos=removidos, status=status, nivel=nivel, ressalvas=ressalvas,
                          iteracoes=iteracoes, series_tentativas=iteracoes[0].series,
                          sinais_tentativos=sinais_tentativos,
                          origem_limites="calculados a partir dos próprios dados (calibração)")
    resultado.capacidade = _capacidade(carta, params, plano, series_finais[0], usar_media_dos_dados=False,
                                       usados=usados)
    resultado.deslocamento = deslocamento.analisar(carta, series_finais[0], params)
    return resultado


def acompanhar(plano: Plano, params: Dict[str, Any], origem: str) -> Resultado:
    carta = criar_carta(plano)
    if params.get("familia") and params["familia"] != carta.familia:
        raise ErroDeLeitura("A calibração escolhida é de outro tipo de carta e não serve para estes dados.")
    series = carta.series(params)
    sinais = _avaliar_todas(series)
    m = carta.num_pontos()
    fora = {chave: [s for s in lista if s.fora_de_controle] for chave, lista in sinais.items()}
    alertas = {chave: [s for s in lista if not s.fora_de_controle] for chave, lista in sinais.items()}
    principal = series[0].chave
    pts_fora = sorted({p for s in fora.get(principal, []) for p in s.pontos})
    outros_fora = {chave: sorted({p for s in lista for p in s.pontos}) for chave, lista in fora.items()
                   if chave != principal and lista}
    nome = carta.nome_ponto
    if pts_fora or outros_fora:
        detalhes = []
        if pts_fora:
            detalhes.append(f"{_quantos(pts_fora, nome)} além dos limites na carta {series[0].nome}")
        for chave, pts in outros_fora.items():
            detalhes.append(f"{_quantos(pts, nome)} na carta {_nome(series, chave)}")
        status, nivel = "Processo fora de controle: " + "; ".join(detalhes) + ".", "critico"
    elif any(alertas.values()):
        status, nivel = "Sinais de alerta: o processo pode estar mudando em relação à calibração.", "alerta"
    else:
        status, nivel = "Processo sob controle em relação aos limites calibrados.", "ok"
    ressalvas = _ressalvas_degeneradas(carta, params)
    resultado = Resultado(plano=plano, carta=carta, objetivo=ACOMPANHAR, params=params,
                          series_finais=series, sinais_finais=sinais, usados=list(range(m)), removidos=[],
                          status=status, nivel=nivel, ressalvas=ressalvas, origem_limites=origem)
    resultado.capacidade = _capacidade(carta, params, plano, series[0], usar_media_dos_dados=True)
    resultado.deslocamento = deslocamento.analisar(carta, series[0], params)
    return resultado


def _capacidade(carta: Carta, params: Dict[str, Any], plano: Plano, serie: Serie,
                usar_media_dos_dados: bool, usados: Optional[List[int]] = None) -> Optional[Dict[str, Any]]:
    if plano.lse is None and plano.lie is None:
        return None
    valores = carta.valores_individuais()
    if valores is not None and params.get("sigma") is not None:
        mantidos = set(range(carta.num_pontos())) if usados is None else set(usados)
        if carta.familia == "variaveis":
            posicoes = [f"subgrupo {i + 1}, valor {j + 1}" for i, s in enumerate(carta.subgrupos) for j in range(len(s))]
            desempenho = [v for i, s in enumerate(carta.subgrupos) if i in mantidos for v in s]
        else:
            posicoes = [f"observação {i + 1}" for i in range(len(valores))]
            desempenho = [v for i, v in enumerate(valores) if i in mantidos]
        mu = sum(valores) / len(valores) if usar_media_dos_dados else float(params["centro"])
        resultado = capacidade_variaveis(valores, posicoes, mu, float(params["sigma"]), plano.lse, plano.lie,
                                         valores_desempenho=desempenho)
        resultado["origem_mu"] = "média dos dados de acompanhamento" if usar_media_dos_dados else "linha central calibrada"
        return resultado
    return capacidade_atributos(serie.ids, serie.valores, plano.lse, plano.lie)


def _ressalvas_degeneradas(carta: Carta, params: Dict[str, Any]) -> List[str]:
    sigma = params.get("sigma")
    if sigma is not None and sigma <= 0:
        return ["A variabilidade estimada é zero (todos os valores iguais nos subgrupos usados): "
                "os limites colapsam na linha central e qualquer diferença aparece como fora de controle."]
    if carta.familia in ("fracao", "contagem", "taxa") and float(params.get("centro") or 0) <= 0:
        return ["A linha central é zero (nenhum defeito): a carta não consegue distinguir variação "
                "natural de mudança no processo."]
    if carta.familia == "fracao" and float(params.get("centro") or 0) >= 1:
        return ["A fração defeituosa média é 1 (todos os itens defeituosos): a carta p não se aplica."]
    return []


def _quantos(ids: List[int], nome: str) -> str:
    plural_nome = "observações" if nome.endswith("ção") else nome + "s"
    return plural(len(ids), nome, plural_nome)


def _nome(series: List[Serie], chave: str) -> str:
    for s in series:
        if s.chave == chave:
            return s.nome
    return chave


def _nome_regra_curto(sinal: Sinal) -> str:
    if sinal.regra == "T":
        return f"tendência ({sinal.lado})"
    return f"regra {sinal.regra} ({sinal.lado})"
