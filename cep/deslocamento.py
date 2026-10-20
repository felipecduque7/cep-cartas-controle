"""Análise de deslocamento e tendência, curva característica de operação e CMC.

Responde a quatro perguntas:
  1. O processo mudou de nível? (nível recente, ponto de mudança e tendência)
  2. Se mudou, qual a chance de a carta detectar isso a cada amostra?
     ("sucesso" = detectar = 1 − β; "falha" = não detectar = β)
  3. Quantas amostras (tentativas) até detectar? CMC = 1/(1 − β) e
     P(detectar em até m amostras) = 1 − β^m (distribuição geométrica).
  4. E para outros deslocamentos possíveis? (tabela da curva CO)

A mudança de nível é estimada pela divisão da sequência em dois trechos que
mais reduz a soma dos quadrados dos desvios; o teste usa o desvio-padrão
conhecido da estatística e a correção de Bonferroni, porque o ponto de corte
foi escolhido olhando os próprios dados. A tendência é a inclinação da reta de
mínimos quadrados, testada pela distribuição t.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

from . import config
from .cartas import Carta, Serie
from .constantes import fatores
from .probabilidade import (desempenho_amplitude, desempenho_c, desempenho_media, desempenho_np,
                            desempenho_p, desempenho_u, detectar_ate, normal_acumulada,
                            normal_inversa, t_p_valor_bilateral)


# ---------------------------------------------------------------------------
# Ferramentas estatísticas
# ---------------------------------------------------------------------------
def mudanca_de_nivel(valores: Sequence[float], sigma_ponto: float, ids: Sequence[int]) -> Optional[Dict[str, float]]:
    """Melhor divisão da sequência em dois níveis e teste da diferença."""
    m = len(valores)
    minimo = config.SEGMENTO_MINIMO
    if m < 2 * minimo or sigma_ponto is None or sigma_ponto <= 0:
        return None
    melhor = None
    for corte in range(minimo, m - minimo + 1):
        a, b = valores[:corte], valores[corte:]
        media_a, media_b = sum(a) / len(a), sum(b) / len(b)
        sq = sum((v - media_a) ** 2 for v in a) + sum((v - media_b) ** 2 for v in b)
        if melhor is None or sq < melhor[0] - 1e-15:
            melhor = (sq, corte, media_a, media_b)
    _, corte, media_a, media_b = melhor
    na, nb = corte, m - corte
    z = (media_b - media_a) / (sigma_ponto * math.sqrt(1 / na + 1 / nb))
    p = 2 * (1 - normal_acumulada(abs(z)))
    candidatos = m - 2 * minimo + 1
    p_ajustado = min(1.0, p * candidatos)
    return {"apos_ponto": ids[corte - 1], "primeiro_ponto_novo": ids[corte], "antes": media_a,
            "depois": media_b, "pontos_antes": na, "pontos_depois": nb, "z": z, "p_valor": p,
            "p_ajustado": p_ajustado, "significativa": p_ajustado < config.NIVEL_SIGNIFICANCIA}


def tendencia_linear(valores: Sequence[float], ids: Sequence[int]) -> Optional[Dict[str, float]]:
    """Reta de mínimos quadrados valor = a + b·ordem e teste t da inclinação."""
    m = len(valores)
    if m < 6:
        return None
    x = list(range(1, m + 1))
    mx, my = sum(x) / m, sum(valores) / m
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, valores))
    b = sxy / sxx
    a = my - b * mx
    residuos = [yi - (a + b * xi) for xi, yi in zip(x, valores)]
    sqr = sum(r * r for r in residuos)
    s = math.sqrt(sqr / (m - 2)) if m > 2 else 0.0
    if s == 0:
        t, p = (math.inf if b != 0 else 0.0), (0.0 if b != 0 else 1.0)
    else:
        t = b / (s / math.sqrt(sxx))
        p = t_p_valor_bilateral(t, m - 2)
    sqt = sum((yi - my) ** 2 for yi in valores)
    return {"inclinacao": b, "intercepto": a, "t": t, "p_valor": p, "gl": m - 2,
            "r2": (1 - sqr / sqt) if sqt > 0 else 0.0, "ultimo_ajustado": a + b * m,
            "significativa": p < config.NIVEL_SIGNIFICANCIA}


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores)


def _projecao(tendencia: Dict[str, float], alvo: float) -> Optional[float]:
    """Quantos pontos além do último até a reta ajustada atingir o alvo."""
    b = tendencia["inclinacao"]
    if b == 0:
        return None
    k = (alvo - tendencia["ultimo_ajustado"]) / b
    return k if k > 0 else None


# ---------------------------------------------------------------------------
# Análise principal
# ---------------------------------------------------------------------------
def analisar(carta: Carta, serie: Serie, params: Dict[str, object]) -> Dict[str, object]:
    """Deslocamento da estatística da série principal em relação à linha central."""
    valores = list(serie.valores)
    ids = serie.ids
    k = min(config.JANELA_RECENTE, len(valores))
    if serie.chave in ("xbarra", "i"):
        return _analisar_media(carta, serie, params, valores, ids, k)
    if serie.chave in ("r", "am"):
        return _analisar_variabilidade(carta, serie, params, valores, ids, k)
    return _analisar_atributo(carta, serie, params, valores, ids, k)


def _analisar_media(carta, serie, params, valores, ids, k) -> Dict[str, object]:
    sigma = float(params.get("sigma") or 0.0)
    centro = float(params["centro"])
    if serie.chave == "xbarra":
        n_ref = params.get("n") or round(sum(carta.n) / len(carta.n))
    else:
        n_ref = 1
    resultado: Dict[str, object] = {"tipo": "media", "centro": centro, "sigma": sigma, "n": n_ref,
                                    "unidade": carta.unidade, "casas": serie.casas,
                                    "eixo": "Deslocamento da média (em σ do processo)"}
    if sigma <= 0:
        resultado["aviso"] = "Desvio-padrão estimado igual a zero: não há como avaliar deslocamentos."
        return resultado
    sigma_ponto = sigma / math.sqrt(n_ref)
    l_sup = (serie.lsc[0] - serie.lc[0]) / sigma_ponto
    l_inf = (serie.lc[0] - serie.lic[0]) / sigma_ponto
    resultado.update({"l_sup": l_sup, "l_inf": l_inf})

    nivel = _media(valores[-k:])
    resultado["recente"] = {"k": k, "nivel": nivel, "delta": (nivel - centro) / sigma,
                            "diferenca": nivel - centro}
    mudanca = mudanca_de_nivel(valores, sigma_ponto, ids)
    if mudanca:
        mudanca["delta"] = (mudanca["depois"] - mudanca["antes"]) / sigma
        mudanca["diferenca"] = mudanca["depois"] - mudanca["antes"]
    resultado["mudanca"] = mudanca
    tendencia = tendencia_linear(valores, ids)
    if tendencia:
        tendencia["inclinacao_sigma"] = tendencia["inclinacao"] / sigma
        if tendencia["significativa"]:
            alvo = serie.lsc[0] if tendencia["inclinacao"] > 0 else serie.lic[0]
            tendencia["pontos_ate_limite"] = _projecao(tendencia, alvo)
            lse, lie = carta.plano.lse, carta.plano.lie
            if tendencia["inclinacao"] > 0 and lse is not None:
                tendencia["pontos_ate_rcpk1"] = _projecao(tendencia, lse - 3 * sigma)
                tendencia["pontos_ate_especificacao"] = _projecao(tendencia, lse)
            elif tendencia["inclinacao"] < 0 and lie is not None:
                tendencia["pontos_ate_rcpk1"] = _projecao(tendencia, lie + 3 * sigma)
                tendencia["pontos_ate_especificacao"] = _projecao(tendencia, lie)
    resultado["tendencia"] = tendencia

    if mudanca and mudanca["significativa"]:
        delta, origem = mudanca["delta"], "mudança de nível estimada"
    else:
        delta, origem = resultado["recente"]["delta"], f"nível dos últimos {k} pontos"
    desempenho = desempenho_media(delta, n_ref, l_sup, l_inf)
    resultado["avaliado"] = {"origem": origem, "delta": delta, **desempenho,
                             "ate": detectar_ate(desempenho["p_detectar"], config.AMOSTRAS_ATE_DETECTAR)}
    zero = desempenho_media(0.0, n_ref, l_sup, l_inf)
    resultado["alarme_falso"] = {"alfa": zero["p_detectar"], "cmc0": zero["cmc"]}
    resultado["tabela"] = [
        {"rotulo": f"{d:g}σ".replace(".", config.SEPARADOR_DECIMAL), "valor": d, "nivel": centro + d * sigma,
         **desempenho_media(d, n_ref, l_sup, l_inf)}
        for d in config.DESLOCAMENTOS_SIGMA
    ]
    raiz = math.sqrt(n_ref)
    resultado["detectavel"] = {
        "50": (l_sup - normal_inversa(0.5)) / raiz,
        "90": (l_sup - normal_inversa(0.1)) / raiz,
    }
    lse, lie = carta.plano.lse, carta.plano.lie
    especificacao = {}
    if lse is not None:
        d1 = (lse - 3 * sigma - centro) / sigma
        d2 = (lse - centro) / sigma
        especificacao["superior"] = {"delta_rcpk1": d1, "delta_limite": d2,
                                     "p_rcpk1": desempenho_media(d1, n_ref, l_sup, l_inf)["p_detectar"] if d1 > 0 else None}
    if lie is not None:
        d1 = (lie + 3 * sigma - centro) / sigma
        d2 = (lie - centro) / sigma
        especificacao["inferior"] = {"delta_rcpk1": d1, "delta_limite": d2,
                                     "p_rcpk1": desempenho_media(d1, n_ref, l_sup, l_inf)["p_detectar"] if d1 < 0 else None}
    resultado["especificacao"] = especificacao or None
    return resultado


def _analisar_variabilidade(carta, serie, params, valores, ids, k) -> Dict[str, object]:
    sigma0 = float(params.get("sigma") or 0.0)
    n = params.get("n") if serie.chave == "r" else 2
    if serie.chave == "r" and not n:
        n = round(sum(carta.n) / len(carta.n))
    n = int(n)
    resultado: Dict[str, object] = {"tipo": "variabilidade", "centro": float(serie.lc[0]), "sigma": sigma0,
                                    "n": n, "unidade": carta.unidade, "casas": serie.casas,
                                    "eixo": "Razão σ1/σ0 (aumento do desvio-padrão)"}
    if sigma0 <= 0:
        resultado["aviso"] = "Desvio-padrão estimado igual a zero: não há como avaliar mudanças de variabilidade."
        return resultado
    d2 = fatores(n).d2
    lsc_rel, lic_rel = serie.lsc[0] / sigma0, serie.lic[0] / sigma0
    resultado.update({"lsc_rel": lsc_rel, "lic_rel": lic_rel})
    nivel = _media(valores[-k:])
    resultado["recente"] = {"k": k, "nivel": nivel, "razao": (nivel / d2) / sigma0}
    mudanca = mudanca_de_nivel(valores, float(serie.sigma[0]), ids)
    if mudanca and mudanca["antes"] > 0:
        mudanca["razao"] = mudanca["depois"] / mudanca["antes"]
    resultado["mudanca"] = mudanca
    resultado["tendencia"] = tendencia_linear(valores, ids)
    if mudanca and mudanca["significativa"] and mudanca.get("razao"):
        razao, origem = mudanca["razao"], "mudança de nível estimada"
    else:
        razao, origem = resultado["recente"]["razao"], f"nível dos últimos {k} pontos"
    razao = max(razao, 1e-6)
    desempenho = desempenho_amplitude(razao, n, lsc_rel, lic_rel)
    resultado["avaliado"] = {"origem": origem, "razao": razao, **desempenho,
                             "ate": detectar_ate(desempenho["p_detectar"], config.AMOSTRAS_ATE_DETECTAR)}
    zero = desempenho_amplitude(1.0, n, lsc_rel, lic_rel)
    resultado["alarme_falso"] = {"alfa": zero["p_detectar"], "cmc0": zero["cmc"]}
    resultado["tabela"] = [
        {"rotulo": f"{r:g}".replace(".", config.SEPARADOR_DECIMAL) + "·σ0", "valor": r, "nivel": r * sigma0,
         **desempenho_amplitude(r, n, lsc_rel, lic_rel)}
        for r in config.RAZOES_SIGMA
    ]
    return resultado


def _analisar_atributo(carta, serie, params, valores, ids, k) -> Dict[str, object]:
    centro = float(params["centro"])
    chave = serie.chave
    resultado: Dict[str, object] = {"tipo": {"p": "fracao", "np": "fracao", "c": "contagem", "u": "taxa"}[chave],
                                    "centro": centro, "unidade": "", "casas": serie.casas}
    if chave in ("p", "np"):
        n_ref = int(params.get("n") or round(params.get("n_medio") or sum(carta.n) / len(carta.n)))
        s = math.sqrt(max(centro * (1 - centro), 0.0) / n_ref)
        lsc, lic = min(1.0, centro + config.L_SIGMA * s), max(0.0, centro - config.L_SIGMA * s)
        resultado.update({"n": n_ref, "eixo": "Nova fração defeituosa p1", "simbolo": "p"})

        def desempenho(p1):
            if chave == "p":
                return desempenho_p(p1, n_ref, lic, lsc)
            return desempenho_np(p1, n_ref, lic * n_ref, lsc * n_ref)
        recentes_d = carta.d[-k:]
        recentes_n = carta.n[-k:]
        nivel = sum(recentes_d) / sum(recentes_n)
        sigma_ponto = s if chave == "p" else s * n_ref
        serie_valores = valores
        converter = (lambda v: v) if chave == "p" else (lambda v: v / n_ref)
    elif chave == "c":
        s = math.sqrt(max(centro, 0.0))
        lsc, lic = centro + config.L_SIGMA * s, max(0.0, centro - config.L_SIGMA * s)
        resultado.update({"eixo": "Novo número médio de defeitos c1", "simbolo": "c"})

        def desempenho(c1):
            return desempenho_c(c1, lic, lsc)
        nivel = _media(valores[-k:])
        sigma_ponto = s
        serie_valores = valores
        converter = lambda v: v  # noqa: E731
    else:
        n_ref = float(params.get("n_medio") or sum(carta.unidades) / len(carta.unidades))
        s = math.sqrt(max(centro, 0.0) / n_ref)
        lsc, lic = centro + config.L_SIGMA * s, max(0.0, centro - config.L_SIGMA * s)
        resultado.update({"n": n_ref, "eixo": "Novo número de defeitos por unidade u1", "simbolo": "u"})

        def desempenho(u1):
            return desempenho_u(u1, n_ref, lic, lsc)
        nivel = sum(carta.d[-k:]) / sum(carta.unidades[-k:])
        sigma_ponto = s
        serie_valores = valores
        converter = lambda v: v  # noqa: E731

    resultado["limites_referencia"] = {"lic": lic, "lsc": lsc}
    if centro <= 0 or sigma_ponto <= 0:
        resultado["aviso"] = ("A linha central é zero (nenhum defeito na calibração): a carta não tem como "
                              "avaliar deslocamentos; qualquer defeito já fica acima do limite.")
        return resultado
    resultado["recente"] = {"k": k, "nivel": nivel, "razao": nivel / centro}
    mudanca = mudanca_de_nivel(serie_valores, sigma_ponto, ids)
    if mudanca:
        mudanca["antes"], mudanca["depois"] = converter(mudanca["antes"]), converter(mudanca["depois"])
        mudanca["razao"] = mudanca["depois"] / mudanca["antes"] if mudanca["antes"] > 0 else None
    resultado["mudanca"] = mudanca
    resultado["tendencia"] = tendencia_linear(serie_valores, ids)
    if mudanca and mudanca["significativa"]:
        novo, origem = mudanca["depois"], "mudança de nível estimada"
    else:
        novo, origem = nivel, f"nível dos últimos {k} pontos"
    if chave in ("p", "np"):
        novo = min(max(novo, 0.0), 1.0)
    d = desempenho(novo)
    resultado["avaliado"] = {"origem": origem, "novo": novo, "razao": novo / centro, **d,
                             "ate": detectar_ate(d["p_detectar"], config.AMOSTRAS_ATE_DETECTAR)}
    zero = desempenho(centro)
    resultado["alarme_falso"] = {"alfa": zero["p_detectar"], "cmc0": zero["cmc"]}
    tabela = []
    for f in config.FATORES_ATRIBUTOS:
        novo_f = centro * f
        if chave in ("p", "np"):
            novo_f = min(novo_f, 1.0)
        tabela.append({"rotulo": f"{f:g}".replace(".", config.SEPARADOR_DECIMAL) + "×", "valor": novo_f,
                       "nivel": novo_f, **desempenho(novo_f)})
    resultado["tabela"] = tabela
    return resultado


def desempenho_personalizado(analise: Dict[str, object], valor: float) -> Dict[str, float]:
    """Desempenho da carta para um deslocamento escolhido pelo usuário.

    valor: deslocamento em σ (média), razão σ1/σ0 (variabilidade) ou o novo
    valor de p, c ou u (atributos).
    """
    tipo = analise["tipo"]
    if tipo == "media":
        return desempenho_media(valor, analise["n"], analise["l_sup"], analise["l_inf"])
    if tipo == "variabilidade":
        return desempenho_amplitude(max(valor, 1e-6), analise["n"], analise["lsc_rel"], analise["lic_rel"])
    lim = analise["limites_referencia"]
    if tipo == "fracao":
        return desempenho_p(min(max(valor, 0.0), 1.0), analise["n"], lim["lic"], lim["lsc"])
    if tipo == "contagem":
        return desempenho_c(max(valor, 0.0), lim["lic"], lim["lsc"])
    return desempenho_u(max(valor, 0.0), analise["n"], lim["lic"], lim["lsc"])
