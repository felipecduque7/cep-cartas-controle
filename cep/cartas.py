"""Estatísticas e limites de controle de cada tipo de carta.

Cada classe sabe:
  - calcular a estatística de cada ponto (média, amplitude, fração...);
  - estimar os parâmetros do processo a partir de um conjunto de pontos
    (é o que muda de uma iteração da calibração para a outra);
  - montar as séries com linha central (LC) e limites (LSC, LIC) para
    parâmetros dados (da própria calibração ou de uma calibração salva).

Fórmulas (Montgomery & Runger):
  X-barra: LC = X̿            LSC/LIC = X̿ ± A2·R̄
  R:       LC = R̄            LSC = D4·R̄    LIC = D3·R̄
  I:       LC = x̄            LSC/LIC = x̄ ± 3·AM̄/d2   (d2 = 1,128)
  AM:      LC = AM̄           LSC = 3,267·AM̄  LIC = 0
  p:       LC = p̄            LSC/LIC = p̄ ± 3·√(p̄(1−p̄)/n)
  np:      LC = n·p̄          LSC/LIC = n·p̄ ± 3·√(n·p̄(1−p̄))
  c:       LC = c̄            LSC/LIC = c̄ ± 3·√c̄
  u:       LC = ū            LSC/LIC = ū ± 3·√(ū/n)
Limites inferiores negativos são truncados em zero quando a estatística não
pode ser negativa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import config
from .constantes import fatores
from .leitura import Plano
from .util import casas_decimais, fmt

TODAS_REGRAS = ("1", "2", "3", "4", "T")


@dataclass
class Serie:
    """Uma carta pronta para plotar e avaliar: pontos, LC, LSC e LIC."""

    chave: str
    nome: str
    titulo: str
    tex: str
    rotulo_y: str
    pos: List[int]          # posição (0-based) do ponto nos dados
    valores: List[float]
    lc: List[float]
    lsc: List[float]
    lic: List[float]
    sigma: List[float]      # desvio-padrão da estatística (largura de uma zona)
    regras: Tuple[str, ...]
    casas: int
    rotulo_x: str = "Subgrupo"
    pode_ser_negativa: bool = False

    @property
    def ids(self) -> List[int]:
        return [p + 1 for p in self.pos]

    def limites_constantes(self) -> bool:
        def constante(lista: Sequence[float]) -> bool:
            return all(abs(v - lista[0]) <= 1e-12 * max(1.0, abs(lista[0])) for v in lista)
        return constante(self.lc) and constante(self.lsc) and constante(self.lic)

    def resumo(self) -> Dict[str, object]:
        """Limites para o relatório (faixa quando variam de ponto a ponto)."""
        if self.limites_constantes():
            return {"variavel": False, "lic": self.lic[0], "lc": self.lc[0], "lsc": self.lsc[0]}
        return {"variavel": True, "lic": (min(self.lic), max(self.lic)), "lc": (min(self.lc), max(self.lc)),
                "lsc": (min(self.lsc), max(self.lsc))}

    def texto_limites(self) -> Tuple[str, str, str]:
        r = self.resumo()
        if not r["variavel"]:
            return fmt(r["lic"], self.casas), fmt(r["lc"], self.casas), fmt(r["lsc"], self.casas)

        def faixa(par):
            a, b = par
            return fmt(a, self.casas) if abs(a - b) < 1e-12 else f"{fmt(a, self.casas)} a {fmt(b, self.casas)}"
        return faixa(r["lic"]), faixa(r["lc"]), faixa(r["lsc"])


def _sufixo(unidade: str) -> str:
    return f" ({unidade})" if unidade else ""


class Carta:
    """Base comum a todas as cartas."""

    familia = ""
    rotulo_x = "Subgrupo"
    nome_ponto = "subgrupo"

    def __init__(self, plano: Plano):
        self.plano = plano
        self.tipo = plano.tipo
        self.unidade = plano.unidade
        self.primaria = ""

    # --- interface -----------------------------------------------------------
    def num_pontos(self) -> int:
        raise NotImplementedError

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        raise NotImplementedError

    def series(self, params: Dict[str, object]) -> List[Serie]:
        raise NotImplementedError

    def remover_por(self) -> Tuple[str, ...]:
        """Séries cujos pontos fora dos limites saem do cálculo na revisão."""
        return (self.primaria,)

    def minimo_pontos(self) -> int:
        return 2

    def sigma_processo(self, params: Dict[str, object]) -> Optional[float]:
        valor = params.get("sigma")
        return None if valor is None else float(valor)

    def valores_individuais(self) -> Optional[List[float]]:
        return None

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        raise NotImplementedError

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Variáveis em subgrupos: X-barra e R
# ---------------------------------------------------------------------------
class CartaXbarraR(Carta):
    familia = "variaveis"
    rotulo_x = "Subgrupo"
    nome_ponto = "subgrupo"

    def __init__(self, plano: Plano):
        super().__init__(plano)
        self.subgrupos = [list(map(float, s)) for s in plano.subgrupos]
        self.n = [len(s) for s in self.subgrupos]
        self.medias = [sum(s) / len(s) for s in self.subgrupos]
        self.amplitudes = [max(s) - min(s) for s in self.subgrupos]
        self.n_const = self.n[0] if len(set(self.n)) == 1 else None
        self.primaria = "xbarra" if plano.tipo == "XBAR_R" else "r"
        self.casas = min(6, max(2, casas_decimais(self.valores_individuais()) + 1))

    def num_pontos(self) -> int:
        return len(self.subgrupos)

    def valores_individuais(self) -> List[float]:
        return [v for s in self.subgrupos for v in s]

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        idx = list(idx)
        soma_n = sum(self.n[i] for i in idx)
        centro = sum(self.n[i] * self.medias[i] for i in idx) / soma_n
        if self.n_const:
            rbar = sum(self.amplitudes[i] for i in idx) / len(idx)
            sigma = rbar / fatores(self.n_const).d2
        else:
            rbar = None
            sigma = sum(self.amplitudes[i] / fatores(self.n[i]).d2 for i in idx) / len(idx)
        return {"familia": self.familia, "tipo": self.tipo, "centro": centro, "rbar": rbar,
                "sigma": sigma, "n": self.n_const, "m": len(idx)}

    def remover_por(self) -> Tuple[str, ...]:
        # Na carta X-barra, um subgrupo com amplitude fora de controle também
        # contamina R̄ (e portanto os limites da X-barra): sai das duas.
        return ("xbarra", "r") if self.primaria == "xbarra" else ("r",)

    def series(self, params: Dict[str, object]) -> List[Serie]:
        centro = float(params["centro"])
        sigma = float(params["sigma"])
        rbar = params.get("rbar")
        n_ref = params.get("n")
        L = config.L_SIGMA
        usar_tabela = (L == 3.0)
        lcx, lscx, licx, sx = [], [], [], []
        lcr, lscr, licr, sr = [], [], [], []
        for ni in self.n:
            f = fatores(ni)
            if usar_tabela and rbar is not None and n_ref == ni:
                lsc_x, lic_x = centro + f.A2 * rbar, centro - f.A2 * rbar
                lc_r, lsc_r, lic_r = rbar, f.D4 * rbar, f.D3 * rbar
            else:
                desvio_media = sigma / math.sqrt(ni)
                lsc_x, lic_x = centro + L * desvio_media, centro - L * desvio_media
                lc_r = f.d2 * sigma
                lsc_r = (f.d2 + L * f.d3) * sigma
                lic_r = max(0.0, (f.d2 - L * f.d3) * sigma)
            lcx.append(centro); lscx.append(lsc_x); licx.append(lic_x); sx.append((lsc_x - centro) / L)
            lcr.append(lc_r); lscr.append(lsc_r); licr.append(lic_r); sr.append((lsc_r - lc_r) / L)
        pos = list(range(len(self.n)))
        u = _sufixo(self.unidade)
        serie_x = Serie("xbarra", "X-barra", "Carta X-barra (média dos subgrupos)", r"$\bar{x}$",
                        f"Média do subgrupo{u}", pos, self.medias, lcx, lscx, licx, sx,
                        TODAS_REGRAS, self.casas, self.rotulo_x, pode_ser_negativa=True)
        serie_r = Serie("r", "R", "Carta R (amplitude dos subgrupos)", r"$R$",
                        f"Amplitude do subgrupo{u}", pos, self.amplitudes, lcr, lscr, licr, sr,
                        ("1", "4"), self.casas, self.rotulo_x)
        return [serie_x, serie_r] if self.primaria == "xbarra" else [serie_r, serie_x]

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        casas_dados = max(1, self.casas - 1)
        mostrar_valores = max(self.n) <= 8
        cab = ["Subgrupo", "n"] + (["Medições"] if mostrar_valores else []) + ["Média", "Amplitude"]
        linhas = []
        for i, s in enumerate(self.subgrupos):
            linha = [str(i + 1), str(self.n[i])]
            if mostrar_valores:
                linha.append("; ".join(fmt(v, casas_dados) for v in s))
            linha += [fmt(self.medias[i], self.casas), fmt(self.amplitudes[i], self.casas)]
            linhas.append(linha)
        return cab, linhas

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        c = self.casas
        itens = [("Média geral (X-duas-barras)", fmt(params["centro"], c))]
        if params.get("rbar") is not None:
            f = fatores(int(params["n"]))
            itens += [
                ("Amplitude média (R-barra)", fmt(params["rbar"], c)),
                ("Desvio-padrão do processo (σ = R-barra/d2)", fmt(params["sigma"], c + 1)),
                (f"Fatores para n = {f.n}" + (" (calculados)" if f.origem != "tabela" else ""),
                 f"A2 = {fmt(f.A2, 3)}; D3 = {fmt(f.D3, 3)}; D4 = {fmt(f.D4, 3)}; d2 = {fmt(f.d2, 3)}"),
            ]
        else:
            itens.append(("Desvio-padrão do processo (média de R/d2 de cada subgrupo)", fmt(params["sigma"], c + 1)))
        itens.append(("Subgrupos usados no cálculo", str(params["m"])))
        return itens


# ---------------------------------------------------------------------------
# Valores individuais e amplitude móvel: I e AM
# ---------------------------------------------------------------------------
class CartaIndividuais(Carta):
    familia = "individuais"
    rotulo_x = "Observação"
    nome_ponto = "observação"

    def __init__(self, plano: Plano):
        super().__init__(plano)
        self.x = list(map(float, plano.valores))
        self.am = [abs(self.x[i] - self.x[i - 1]) for i in range(1, len(self.x))]
        self.primaria = "am" if plano.tipo == "MR" else "i"
        self.casas = min(6, max(2, casas_decimais(self.x) + 1))

    def num_pontos(self) -> int:
        return len(self.x)

    def minimo_pontos(self) -> int:
        return 3

    def valores_individuais(self) -> List[float]:
        return list(self.x)

    def remover_por(self) -> Tuple[str, ...]:
        # A amplitude móvel envolve dois pontos vizinhos; a revisão retira os
        # pontos que saem dos limites da carta I (os AM que dependem deles
        # deixam de entrar no cálculo de AM̄).
        return ("i",)

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        idx = sorted(idx)
        escolhidos = set(idx)
        centro = sum(self.x[i] for i in idx) / len(idx)
        ams = [abs(self.x[i] - self.x[i - 1]) for i in idx if i - 1 in escolhidos]
        if not ams:
            ams = [abs(self.x[b] - self.x[a]) for a, b in zip(idx, idx[1:])]
        ambar = sum(ams) / len(ams) if ams else 0.0
        sigma = ambar / fatores(2).d2
        return {"familia": self.familia, "tipo": self.tipo, "centro": centro, "ambar": ambar,
                "sigma": sigma, "m": len(idx)}

    def series(self, params: Dict[str, object]) -> List[Serie]:
        centro = float(params["centro"])
        sigma = float(params["sigma"])
        ambar = params.get("ambar")
        ambar = float(ambar) if ambar is not None else sigma * fatores(2).d2
        L = config.L_SIGMA
        m = len(self.x)
        u = _sufixo(self.unidade)
        serie_i = Serie("i", "I", "Carta I (valores individuais)", r"$x$", f"Valor individual{u}",
                        list(range(m)), list(self.x), [centro] * m, [centro + L * sigma] * m,
                        [centro - L * sigma] * m, [sigma] * m, TODAS_REGRAS, self.casas,
                        self.rotulo_x, pode_ser_negativa=True)
        f2 = fatores(2)
        if L == 3.0:
            lsc_am, lic_am = f2.D4 * ambar, f2.D3 * ambar
        else:
            lsc_am, lic_am = (f2.d2 + L * f2.d3) * sigma, max(0.0, (f2.d2 - L * f2.d3) * sigma)
        k = len(self.am)
        serie_am = Serie("am", "AM", "Carta AM (amplitude móvel)", r"$AM$", f"Amplitude móvel{u}",
                         list(range(1, m)), list(self.am), [ambar] * k, [lsc_am] * k, [lic_am] * k,
                         [(lsc_am - ambar) / L] * k, ("1",), self.casas, self.rotulo_x)
        return [serie_i, serie_am] if self.primaria == "i" else [serie_am, serie_i]

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        casas_dados = max(1, self.casas - 1)
        linhas = [[str(i + 1), fmt(v, casas_dados), "—" if i == 0 else fmt(self.am[i - 1], self.casas)]
                  for i, v in enumerate(self.x)]
        return ["Observação", "Valor", "Amplitude móvel"], linhas

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        c = self.casas
        return [
            ("Média dos valores (x-barra)", fmt(params["centro"], c)),
            ("Amplitude móvel média (AM-barra)", fmt(params.get("ambar"), c)),
            ("Desvio-padrão do processo (σ = AM-barra/1,128)", fmt(params["sigma"], c + 1)),
            ("Observações usadas no cálculo", str(params["m"])),
        ]


# ---------------------------------------------------------------------------
# Atributos: p e np (itens defeituosos)
# ---------------------------------------------------------------------------
class CartaP(Carta):
    familia = "fracao"
    rotulo_x = "Amostra"
    nome_ponto = "amostra"

    def __init__(self, plano: Plano):
        super().__init__(plano)
        self.d = list(map(float, plano.defeituosos))
        self.n = list(map(float, plano.tamanhos))
        self.fracoes = [di / ni for di, ni in zip(self.d, self.n)]
        self.n_const = self.n[0] if len(set(self.n)) == 1 else None
        self.primaria = "np" if plano.tipo == "NP" else "p"

    def num_pontos(self) -> int:
        return len(self.d)

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        idx = list(idx)
        pbar = sum(self.d[i] for i in idx) / sum(self.n[i] for i in idx)
        return {"familia": self.familia, "tipo": self.tipo, "centro": pbar, "sigma": None,
                "n": self.n_const, "n_medio": sum(self.n[i] for i in idx) / len(idx), "m": len(idx)}

    def series(self, params: Dict[str, object]) -> List[Serie]:
        pbar = float(params["centro"])
        L = config.L_SIGMA
        pos = list(range(len(self.d)))
        if self.primaria == "p":
            sig = [math.sqrt(max(pbar * (1 - pbar), 0.0) / ni) for ni in self.n]
            return [Serie("p", "p", "Carta p (fração defeituosa)", r"$p$", "Fração defeituosa", pos,
                          list(self.fracoes), [pbar] * len(pos), [min(1.0, pbar + L * s) for s in sig],
                          [max(0.0, pbar - L * s) for s in sig], sig, TODAS_REGRAS, 4, self.rotulo_x)]
        lc = [ni * pbar for ni in self.n]
        sig = [math.sqrt(max(ni * pbar * (1 - pbar), 0.0)) for ni in self.n]
        return [Serie("np", "np", "Carta np (número de defeituosos)", r"$np$", "Defeituosos por amostra",
                      pos, list(self.d), lc, [min(ni, c + L * s) for ni, c, s in zip(self.n, lc, sig)],
                      [max(0.0, c - L * s) for c, s in zip(lc, sig)], sig, TODAS_REGRAS, 3, self.rotulo_x)]

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        linhas = [[str(i + 1), fmt(d, 0), fmt(n, 0), fmt(p, 4)]
                  for i, (d, n, p) in enumerate(zip(self.d, self.n, self.fracoes))]
        return ["Amostra", "Defeituosos", "Tamanho (n)", "Fração p"], linhas

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        itens = [("Fração defeituosa média (p-barra)", fmt(params["centro"], 5))]
        if self.primaria == "np" and params.get("n"):
            itens.append(("Linha central n·p-barra", fmt(float(params["n"]) * float(params["centro"]), 3)))
        itens.append(("Tamanho da amostra (n)", fmt(params["n"], 0) if params.get("n") else
                      f"variável (média {fmt(params['n_medio'], 1)})"))
        itens.append(("Amostras usadas no cálculo", str(params["m"])))
        return itens


# ---------------------------------------------------------------------------
# Atributos: c (defeitos por amostra) e u (defeitos por unidade)
# ---------------------------------------------------------------------------
class CartaC(Carta):
    familia = "contagem"
    rotulo_x = "Amostra"
    nome_ponto = "amostra"

    def __init__(self, plano: Plano):
        super().__init__(plano)
        self.c = list(map(float, plano.contagens))
        self.primaria = "c"

    def num_pontos(self) -> int:
        return len(self.c)

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        idx = list(idx)
        return {"familia": self.familia, "tipo": self.tipo, "centro": sum(self.c[i] for i in idx) / len(idx),
                "sigma": None, "m": len(idx)}

    def series(self, params: Dict[str, object]) -> List[Serie]:
        cbar = float(params["centro"])
        L = config.L_SIGMA
        s = math.sqrt(max(cbar, 0.0))
        m = len(self.c)
        return [Serie("c", "c", "Carta c (número de defeitos)", r"$c$", "Defeitos por amostra",
                      list(range(m)), list(self.c), [cbar] * m, [cbar + L * s] * m,
                      [max(0.0, cbar - L * s)] * m, [s] * m, TODAS_REGRAS, 3, self.rotulo_x)]

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        casas = 0 if all(abs(v - round(v)) < 1e-9 for v in self.c) else 2
        return ["Amostra", "Defeitos (c)"], [[str(i + 1), fmt(v, casas)] for i, v in enumerate(self.c)]

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        return [("Média de defeitos por amostra (c-barra)", fmt(params["centro"], 3)),
                ("Amostras usadas no cálculo", str(params["m"]))]


class CartaU(Carta):
    familia = "taxa"
    rotulo_x = "Amostra"
    nome_ponto = "amostra"

    def __init__(self, plano: Plano):
        super().__init__(plano)
        self.d = list(map(float, plano.contagens))
        self.unidades = list(map(float, plano.tamanhos))
        self.taxas = [d / n for d, n in zip(self.d, self.unidades)]
        self.primaria = "u"

    def num_pontos(self) -> int:
        return len(self.d)

    def estimar(self, idx: Sequence[int]) -> Dict[str, object]:
        idx = list(idx)
        ubar = sum(self.d[i] for i in idx) / sum(self.unidades[i] for i in idx)
        return {"familia": self.familia, "tipo": self.tipo, "centro": ubar, "sigma": None,
                "n_medio": sum(self.unidades[i] for i in idx) / len(idx), "m": len(idx)}

    def series(self, params: Dict[str, object]) -> List[Serie]:
        ubar = float(params["centro"])
        L = config.L_SIGMA
        sig = [math.sqrt(max(ubar, 0.0) / n) for n in self.unidades]
        m = len(self.d)
        return [Serie("u", "u", "Carta u (defeitos por unidade)", r"$u$", "Defeitos por unidade",
                      list(range(m)), list(self.taxas), [ubar] * m, [ubar + L * s for s in sig],
                      [max(0.0, ubar - L * s) for s in sig], sig, TODAS_REGRAS, 4, self.rotulo_x)]

    def tabela_pontos(self) -> Tuple[List[str], List[List[str]]]:
        linhas = [[str(i + 1), fmt(d, 0 if abs(d - round(d)) < 1e-9 else 2), fmt(n, 2 if n % 1 else 0), fmt(u, 4)]
                  for i, (d, n, u) in enumerate(zip(self.d, self.unidades, self.taxas))]
        return ["Amostra", "Defeitos", "Unidades", "u"], linhas

    def descricao_parametros(self, params: Dict[str, object]) -> List[Tuple[str, str]]:
        return [("Defeitos por unidade médio (u-barra)", fmt(params["centro"], 4)),
                ("Unidades por amostra (média)", fmt(params.get("n_medio"), 2)),
                ("Amostras usadas no cálculo", str(params["m"]))]


def criar_carta(plano: Plano) -> Carta:
    """Escolhe a classe da carta conforme o tipo informado no JSON."""
    if plano.tipo in ("XBAR_R", "R"):
        return CartaXbarraR(plano)
    if plano.tipo in ("I", "MR", "IMR"):
        return CartaIndividuais(plano)
    if plano.tipo in ("P", "NP"):
        return CartaP(plano)
    if plano.tipo == "C":
        return CartaC(plano)
    if plano.tipo == "U":
        return CartaU(plano)
    raise ValueError(f"Tipo de carta não suportado: {plano.tipo}")
