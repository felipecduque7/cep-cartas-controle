"""Capacidade do processo em relação aos limites de especificação.

  RCP  = (LSE − LIE) / 6σ                         (dispersão)
  RCPk = min(LSE − μ, μ − LIE) / 3σ               (dispersão e centralização)
  Pp, Ppk: as mesmas contas com o desvio-padrão total s das medições

O livro chama essas razões de RCP e RCPk (Cp e Cpk em inglês). Com só um
limite de especificação, calcula-se apenas o lado correspondente. A fração
fora da especificação é estimada supondo distribuição normal, e também são
contadas as medições que de fato caíram fora.

Lembrete importante (Montgomery): limites de especificação são definidos pelo
projeto ou pelo cliente; limites de controle vêm do próprio processo. Um ponto
pode estar dentro dos limites de controle e fora da especificação, e vice-versa.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from . import config
from .probabilidade import normal_acumulada


def classificar(rcpk: Optional[float]) -> str:
    if rcpk is None:
        return "indeterminado"
    if rcpk >= config.RCPK_CAPAZ:
        return "capaz"
    if rcpk >= config.RCPK_MINIMO:
        return "marginalmente capaz"
    return "não capaz"


def _desempenho(amostra: List[float], mu: float, lse: Optional[float], lie: Optional[float]) -> Dict[str, object]:
    """Pp e Ppk: as mesmas razões com o desvio-padrão total s das medições.

    O σ da carta (R̄/d2 ou AM̄/1,128) mede só a variação de curto prazo, dentro dos
    subgrupos; s inclui também as mudanças de nível entre eles. RCPk mostra o que o
    processo pode fazer; Ppk, o que ele fez de fato nesses dados.
    """
    if len(amostra) < 2:
        return {}
    media = sum(amostra) / len(amostra)
    s = math.sqrt(sum((v - media) ** 2 for v in amostra) / (len(amostra) - 1))
    resultado: Dict[str, object] = {"s": s, "n_desempenho": len(amostra)}
    if s <= 0:
        return resultado
    pp = (lse - lie) / (6 * s) if (lse is not None and lie is not None) else None
    ppk_sup = (lse - mu) / (3 * s) if lse is not None else None
    ppk_inf = (mu - lie) / (3 * s) if lie is not None else None
    lados = [v for v in (ppk_sup, ppk_inf) if v is not None]
    resultado.update({"pp": pp, "ppk_sup": ppk_sup, "ppk_inf": ppk_inf, "ppk": min(lados) if lados else None})
    return resultado


def capacidade_variaveis(valores: List[float], posicoes: List[str], mu: float, sigma: float,
                         lse: Optional[float], lie: Optional[float],
                         valores_desempenho: Optional[List[float]] = None) -> Dict[str, object]:
    """valores: medições individuais; posicoes: descrição de onde está cada uma.

    valores_desempenho: medições usadas no desvio-padrão total s (Pp e Ppk). Na
    calibração, só as dos pontos mantidos; no acompanhamento, todas.
    """
    resultado: Dict[str, object] = {"tipo": "variaveis", "mu": mu, "sigma": sigma, "lse": lse, "lie": lie}
    fora = [(onde, v) for onde, v in zip(posicoes, valores)
            if (lse is not None and v > lse) or (lie is not None and v < lie)]
    resultado["fora"] = fora
    resultado["total"] = len(valores)
    resultado.update(_desempenho(list(valores if valores_desempenho is None else valores_desempenho), mu, lse, lie))
    if not sigma or sigma <= 0:
        resultado["aviso"] = "Desvio-padrão estimado igual a zero: as razões de capacidade não podem ser calculadas."
        return resultado
    rcp = (lse - lie) / (6 * sigma) if (lse is not None and lie is not None) else None
    rcpk_sup = (lse - mu) / (3 * sigma) if lse is not None else None
    rcpk_inf = (mu - lie) / (3 * sigma) if lie is not None else None
    lados = [v for v in (rcpk_sup, rcpk_inf) if v is not None]
    rcpk = min(lados) if lados else None
    p_sup = 1 - normal_acumulada((lse - mu) / sigma) if lse is not None else 0.0
    p_inf = normal_acumulada((lie - mu) / sigma) if lie is not None else 0.0
    resultado.update({
        "rcp": rcp, "rcpk": rcpk, "rcpk_sup": rcpk_sup, "rcpk_inf": rcpk_inf,
        "p_fora_sup": p_sup, "p_fora_inf": p_inf, "p_fora": p_sup + p_inf,
        "ppm": (p_sup + p_inf) * 1e6, "classificacao": classificar(rcpk),
    })
    if lse is not None and lie is not None:
        meio = (lse + lie) / 2
        resultado["descentralizacao"] = (mu - meio) / ((lse - lie) / 2)
    return resultado


def capacidade_atributos(ids: List[int], valores: List[float], lse: Optional[float],
                         lie: Optional[float]) -> Dict[str, object]:
    """Para cartas de atributos, compara a estatística de cada amostra com a especificação."""
    fora = [(str(i), v) for i, v in zip(ids, valores)
            if (lse is not None and v > lse) or (lie is not None and v < lie)]
    return {"tipo": "atributos", "lse": lse, "lie": lie, "fora": fora, "total": len(valores)}
