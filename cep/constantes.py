"""Fatores para cartas de controle por variáveis (A2, D3, D4, d2, d3).

Para subgrupos de n = 2 a 25 usamos a tabela do livro (Montgomery & Runger,
tabela de fatores para construção de cartas por variáveis). Assim os limites
calculados pelo programa batem com a conta feita à mão.

Para n > 25 os fatores são calculados numericamente a partir da distribuição
da amplitude relativa W = R/σ de n observações normais:
    P(W <= w) = n ∫ φ(x) [Φ(x + w) − Φ(x)]^(n−1) dx
    d2 = E[W]          d3 = desvio-padrão de W
Essa mesma distribuição é usada na curva característica de operação da carta R.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple

import numpy as np

# n: (A2, D3, D4, d2, d3)
TABELA = {
    2: (1.880, 0.000, 3.267, 1.128, 0.853),
    3: (1.023, 0.000, 2.574, 1.693, 0.888),
    4: (0.729, 0.000, 2.282, 2.059, 0.880),
    5: (0.577, 0.000, 2.114, 2.326, 0.864),
    6: (0.483, 0.000, 2.004, 2.534, 0.848),
    7: (0.419, 0.076, 1.924, 2.704, 0.833),
    8: (0.373, 0.136, 1.864, 2.847, 0.820),
    9: (0.337, 0.184, 1.816, 2.970, 0.808),
    10: (0.308, 0.223, 1.777, 3.078, 0.797),
    11: (0.285, 0.256, 1.744, 3.173, 0.787),
    12: (0.266, 0.283, 1.717, 3.258, 0.778),
    13: (0.249, 0.307, 1.693, 3.336, 0.770),
    14: (0.235, 0.328, 1.672, 3.407, 0.763),
    15: (0.223, 0.347, 1.653, 3.472, 0.756),
    16: (0.212, 0.363, 1.637, 3.532, 0.750),
    17: (0.203, 0.378, 1.622, 3.588, 0.744),
    18: (0.194, 0.391, 1.608, 3.640, 0.739),
    19: (0.187, 0.403, 1.597, 3.689, 0.734),
    20: (0.180, 0.415, 1.585, 3.735, 0.729),
    21: (0.173, 0.425, 1.575, 3.778, 0.724),
    22: (0.167, 0.434, 1.566, 3.819, 0.720),
    23: (0.162, 0.443, 1.557, 3.858, 0.716),
    24: (0.157, 0.451, 1.548, 3.895, 0.712),
    25: (0.153, 0.459, 1.541, 3.931, 0.708),
}


@dataclass(frozen=True)
class Fatores:
    n: int
    A2: float
    D3: float
    D4: float
    d2: float
    d3: float
    origem: str  # "tabela" ou "calculado"


def fatores(n: int) -> Fatores:
    """Fatores da carta para subgrupos de tamanho n (n >= 2)."""
    n = int(n)
    if n < 2:
        raise ValueError("Os fatores de cartas por variáveis exigem n >= 2.")
    if n in TABELA:
        A2, D3, D4, d2, d3 = TABELA[n]
        return Fatores(n, A2, D3, D4, d2, d3, "tabela")
    d2, d3 = d2_d3_calculados(n)
    return Fatores(
        n=n,
        A2=3.0 / (d2 * math.sqrt(n)),
        D3=max(0.0, 1.0 - 3.0 * d3 / d2),
        D4=1.0 + 3.0 * d3 / d2,
        d2=d2,
        d3=d3,
        origem="calculado",
    )


# ---------------------------------------------------------------------------
# Distribuição da amplitude relativa (cálculo numérico)
# ---------------------------------------------------------------------------
_PASSO = 0.01
_GRADE_X = np.arange(-8.0, 8.0 + _PASSO / 2, _PASSO)
_PHI_X = 0.5 * np.array([math.erfc(-v / math.sqrt(2.0)) for v in _GRADE_X])
_DENS_X = np.exp(-0.5 * _GRADE_X ** 2) / math.sqrt(2.0 * math.pi)
_W_MAX = 16.0


def _trapezios(y: np.ndarray, passo: float, eixo: int = 0) -> np.ndarray:
    """Regra dos trapézios (compatível com qualquer versão do numpy)."""
    soma = y.sum(axis=eixo) - 0.5 * (np.take(y, 0, axis=eixo) + np.take(y, -1, axis=eixo))
    return soma * passo


@lru_cache(maxsize=64)
def distribuicao_amplitude(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Retorna (w, F) com F(w) = P(R/σ <= w) para n observações normais."""
    n = int(n)
    if n < 2:
        raise ValueError("A amplitude exige n >= 2.")
    num_w = int(round(_W_MAX / _PASSO)) + 1
    w = np.arange(num_w) * _PASSO
    phi_estendido = np.concatenate([_PHI_X, np.ones(num_w)])
    base = np.arange(len(_GRADE_X))
    acumulada = np.empty(num_w)
    for inicio in range(0, num_w, 200):
        js = np.arange(inicio, min(num_w, inicio + 200))
        diferenca = phi_estendido[base[:, None] + js[None, :]] - _PHI_X[:, None]
        integrando = _DENS_X[:, None] * np.power(diferenca, n - 1)
        acumulada[js] = n * _trapezios(integrando, _PASSO, eixo=0)
    return w, np.clip(acumulada, 0.0, 1.0)


@lru_cache(maxsize=64)
def d2_d3_calculados(n: int) -> Tuple[float, float]:
    """d2 = E[R/σ] e d3 = DP[R/σ], calculados numericamente."""
    w, acumulada = distribuicao_amplitude(n)
    sobrevivencia = 1.0 - acumulada
    d2 = float(_trapezios(sobrevivencia, _PASSO))
    e_w2 = float(_trapezios(2.0 * w * sobrevivencia, _PASSO))
    d3 = math.sqrt(max(e_w2 - d2 * d2, 0.0))
    return d2, d3


def prob_amplitude_entre(a: float, b: float, n: int) -> float:
    """P(a <= R/σ <= b) para n observações normais."""
    w, acumulada = distribuicao_amplitude(n)
    fa = 0.0 if a <= 0 else float(np.interp(a, w, acumulada))
    fb = 1.0 if b >= w[-1] else float(np.interp(max(b, 0.0), w, acumulada))
    return max(0.0, min(1.0, fb - fa))
