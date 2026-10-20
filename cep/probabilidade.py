"""Recursos de probabilidade usados no CEP.

- Análise combinatória: combinações C(n, k), arranjos A(n, k), permutações.
- Binomial: P(X = k), P(X <= k), P(a <= X <= b) – "sucessos em n tentativas".
- Geométrica: tentativas até o primeiro sucesso (base do CMC).
- Poisson (carta c e u) e Normal (cartas por variáveis).
- t de Student (teste da tendência e da mudança de nível).
- Desempenho das cartas: β (não detectar), 1 − β (detectar = "sucesso")
  e CMC (comprimento médio de corrida) para um deslocamento do processo.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .constantes import prob_amplitude_entre


class ErroDeProbabilidade(ValueError):
    """Parâmetro inválido (mensagem pronta para o usuário)."""


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _inteiro(valor, nome: str, minimo: int = 0) -> int:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErroDeProbabilidade(f"{nome} deve ser um número inteiro.")
    if not numero.is_integer():
        raise ErroDeProbabilidade(f"{nome} deve ser inteiro (recebido {valor}).")
    numero = int(numero)
    if numero < minimo:
        raise ErroDeProbabilidade(f"{nome} deve ser maior ou igual a {minimo}.")
    return numero


def _probabilidade(valor, nome: str = "p") -> float:
    try:
        p = float(valor)
    except (TypeError, ValueError):
        raise ErroDeProbabilidade(f"{nome} deve ser um número entre 0 e 1.")
    if not 0.0 <= p <= 1.0:
        raise ErroDeProbabilidade(f"{nome} deve estar entre 0 e 1 (recebido {valor}).")
    return p


# ---------------------------------------------------------------------------
# Análise combinatória
# ---------------------------------------------------------------------------
def combinacoes(n, k) -> int:
    """C(n, k) = n! / (k! (n − k)!): grupos de k elementos sem importar a ordem."""
    n, k = _inteiro(n, "n"), _inteiro(k, "k")
    return math.comb(n, k) if k <= n else 0


def arranjos(n, k) -> int:
    """A(n, k) = n! / (n − k)!: sequências de k elementos em que a ordem importa."""
    n, k = _inteiro(n, "n"), _inteiro(k, "k")
    return math.perm(n, k) if k <= n else 0


def permutacoes(n) -> int:
    """P(n) = n!"""
    return math.factorial(_inteiro(n, "n"))


# ---------------------------------------------------------------------------
# Normal
# ---------------------------------------------------------------------------
def normal_densidade(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def normal_acumulada(z: float) -> float:
    """Φ(z) = P(Z <= z)."""
    if z == math.inf:
        return 1.0
    if z == -math.inf:
        return 0.0
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def normal_inversa(p: float) -> float:
    """z tal que Φ(z) = p (algoritmo de Acklam com um passo de refinamento)."""
    p = _probabilidade(p)
    if p == 0.0:
        return -math.inf
    if p == 1.0:
        return math.inf
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    p_baixo = 0.02425
    if p < p_baixo:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= 1.0 - p_baixo:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    erro = normal_acumulada(x) - p
    u = erro * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


# ---------------------------------------------------------------------------
# Binomial
# ---------------------------------------------------------------------------
def binomial_pmf(k, n, p) -> float:
    """P(X = k): exatamente k sucessos em n tentativas com probabilidade p."""
    n = _inteiro(n, "n")
    p = _probabilidade(p)
    k = float(k)
    if not k.is_integer() or k < 0 or k > n:
        return 0.0
    k = int(k)
    if p == 0.0:
        return 1.0 if k == 0 else 0.0
    if p == 1.0:
        return 1.0 if k == n else 0.0
    log_prob = (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                + k * math.log(p) + (n - k) * math.log1p(-p))
    return math.exp(log_prob)


def binomial_acumulada(k, n, p) -> float:
    """P(X <= k)."""
    n = _inteiro(n, "n")
    p = _probabilidade(p)
    k = math.floor(float(k) + 1e-12)
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(binomial_pmf(i, n, p) for i in range(k + 1)))


def binomial_intervalo(a, b, n, p) -> float:
    """P(a <= X <= b)."""
    a = math.ceil(float(a) - 1e-12)
    b = math.floor(float(b) + 1e-12)
    if b < a:
        return 0.0
    return max(0.0, binomial_acumulada(b, n, p) - binomial_acumulada(a - 1, n, p))


def binomial_resumo(n, p) -> Dict[str, float]:
    n = _inteiro(n, "n")
    p = _probabilidade(p)
    return {"media": n * p, "variancia": n * p * (1 - p), "desvio": math.sqrt(n * p * (1 - p))}


# ---------------------------------------------------------------------------
# Geométrica: tentativas até o primeiro sucesso
# ---------------------------------------------------------------------------
def prob_primeiro_sucesso_em(m, p) -> float:
    """P(o 1º sucesso ocorre exatamente na tentativa m) = (1 − p)^(m−1) p."""
    m = _inteiro(m, "m", 1)
    p = _probabilidade(p)
    return (1.0 - p) ** (m - 1) * p


def prob_sucesso_ate(m, p) -> float:
    """P(pelo menos um sucesso em até m tentativas) = 1 − (1 − p)^m."""
    m = _inteiro(m, "m", 0)
    p = _probabilidade(p)
    return 1.0 - (1.0 - p) ** m


def tentativas_esperadas(p) -> float:
    """Número médio de tentativas até o 1º sucesso = 1/p (é o CMC das cartas)."""
    p = _probabilidade(p)
    return math.inf if p == 0 else 1.0 / p


def tentativas_para_atingir(alvo, p) -> Optional[int]:
    """Menor m tal que P(sucesso em até m tentativas) >= alvo."""
    alvo = _probabilidade(alvo, "probabilidade-alvo")
    p = _probabilidade(p)
    if alvo == 0:
        return 0
    if p == 0 or alvo == 1:
        return None if p < 1 else 1
    if p == 1:
        return 1
    return max(1, math.ceil(math.log(1.0 - alvo) / math.log(1.0 - p) - 1e-12))


# ---------------------------------------------------------------------------
# Poisson
# ---------------------------------------------------------------------------
def poisson_pmf(k, lam) -> float:
    lam = float(lam)
    if lam < 0:
        raise ErroDeProbabilidade("λ deve ser >= 0.")
    k = float(k)
    if not k.is_integer() or k < 0:
        return 0.0
    k = int(k)
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))


def poisson_acumulada(k, lam) -> float:
    k = math.floor(float(k) + 1e-12)
    if k < 0:
        return 0.0
    return min(1.0, sum(poisson_pmf(i, lam) for i in range(k + 1)))


def poisson_intervalo(a, b, lam) -> float:
    a = math.ceil(float(a) - 1e-12)
    b = math.floor(float(b) + 1e-12)
    if b < a:
        return 0.0
    return max(0.0, poisson_acumulada(b, lam) - poisson_acumulada(a - 1, lam))


# ---------------------------------------------------------------------------
# t de Student (via função beta incompleta regularizada)
# ---------------------------------------------------------------------------
def _fracao_continua_beta(a: float, b: float, x: float) -> float:
    minimo = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > minimo else minimo)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > minimo else minimo)
        c = 1.0 + aa / c
        c = c if abs(c) > minimo else minimo
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > minimo else minimo)
        c = 1.0 + aa / c
        c = c if abs(c) > minimo else minimo
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def beta_incompleta_regularizada(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
              + a * math.log(x) + b * math.log1p(-x))
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _fracao_continua_beta(a, b, x) / a
    return 1.0 - bt * _fracao_continua_beta(b, a, 1.0 - x) / b


def t_p_valor_bilateral(t: float, gl: float) -> float:
    """P(|T| >= |t|) para T ~ t de Student com gl graus de liberdade."""
    if gl <= 0 or math.isnan(t):
        return float("nan")
    if math.isinf(t):
        return 0.0
    return beta_incompleta_regularizada(gl / 2.0, 0.5, gl / (gl + t * t))


# ---------------------------------------------------------------------------
# Desempenho das cartas de controle
# ---------------------------------------------------------------------------
def resumo_desempenho(beta: float) -> Dict[str, float]:
    """β = P(não detectar numa amostra); 1 − β = P(detectar) = "sucesso"."""
    beta = min(max(float(beta), 0.0), 1.0)
    p = 1.0 - beta
    return {"beta": beta, "p_detectar": p, "cmc": (1.0 / p) if p > 0 else math.inf}


def desempenho_media(delta: float, n: float, l_sup: float = 3.0, l_inf: float = 3.0) -> Dict[str, float]:
    """Carta X-barra (ou I, com n = 1): a média desloca delta·σ do processo.

    β = Φ(L − δ√n) − Φ(−L − δ√n)   (Montgomery & Runger)
    """
    raiz = math.sqrt(n)
    beta = normal_acumulada(l_sup - delta * raiz) - normal_acumulada(-l_inf - delta * raiz)
    return resumo_desempenho(beta)


def desempenho_amplitude(razao: float, n: int, lsc_rel: float, lic_rel: float) -> Dict[str, float]:
    """Carta R (ou AM): o desvio-padrão passa de σ0 para razao·σ0.

    lsc_rel = LSC/σ0 e lic_rel = LIC/σ0. β = P(LIC <= R <= LSC | σ1).
    """
    beta = prob_amplitude_entre(lic_rel / razao, lsc_rel / razao, n)
    return resumo_desempenho(beta)


def desempenho_p(p1: float, n: int, lic: float, lsc: float) -> Dict[str, float]:
    """Carta p: a fração defeituosa passa a ser p1. β vem da binomial."""
    n = int(round(n))
    d_max = math.floor(n * lsc + 1e-9)
    d_min = 0 if lic <= 0 else math.ceil(n * lic - 1e-9)
    beta = binomial_intervalo(d_min, d_max, n, min(max(p1, 0.0), 1.0))
    return resumo_desempenho(beta)


def desempenho_np(p1: float, n: int, lic: float, lsc: float) -> Dict[str, float]:
    """Carta np: limites em número de defeituosos; β vem da binomial."""
    n = int(round(n))
    beta = binomial_intervalo(0 if lic <= 0 else math.ceil(lic - 1e-9), math.floor(lsc + 1e-9),
                              n, min(max(p1, 0.0), 1.0))
    return resumo_desempenho(beta)


def desempenho_c(c1: float, lic: float, lsc: float) -> Dict[str, float]:
    """Carta c: o número médio de defeitos passa a ser c1. β vem da Poisson."""
    beta = poisson_intervalo(0 if lic <= 0 else math.ceil(lic - 1e-9), math.floor(lsc + 1e-9), c1)
    return resumo_desempenho(beta)


def desempenho_u(u1: float, unidades: float, lic: float, lsc: float) -> Dict[str, float]:
    """Carta u: defeitos por unidade passa a u1; total de defeitos ~ Poisson(unidades·u1)."""
    beta = poisson_intervalo(0 if lic <= 0 else math.ceil(unidades * lic - 1e-9),
                             math.floor(unidades * lsc + 1e-9), unidades * u1)
    return resumo_desempenho(beta)


def detectar_ate(p_detectar: float, amostras: Sequence[int]) -> List[Tuple[int, float]]:
    """[(m, P(detectar em até m amostras))]."""
    return [(m, prob_sucesso_ate(m, p_detectar)) for m in amostras]
