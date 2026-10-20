"""Funções auxiliares de formatação e texto."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Iterable, List, Optional, Sequence

from . import config


def fmt(x: Optional[float], casas: int = 4) -> str:
    """Formata um número com a vírgula decimal do relatório."""
    if x is None:
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(x):
        return "—"
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    if abs(x) < 0.5 * 10 ** (-casas):
        x = 0.0
    texto = f"{x:.{casas}f}"
    if config.SEPARADOR_DECIMAL != ".":
        texto = texto.replace(".", config.SEPARADOR_DECIMAL)
    return texto


def fmt_mais(x: Optional[float], casas: int = 4) -> str:
    """Como fmt, mas com sinal '+' explícito nos positivos."""
    if x is None:
        return "—"
    texto = fmt(x, casas)
    if not texto.startswith("-") and float(x) > 0 and texto.strip("0,.") != "":
        texto = "+" + texto
    return texto


def fmt_prob(p: Optional[float]) -> str:
    """Probabilidade com 4 casas; valores muito pequenos em notação científica."""
    if p is None:
        return "—"
    p = float(p)
    if p == 0:
        return "0"
    if 0 < p < 1e-4:
        return f"{p:.1e}".replace(".", config.SEPARADOR_DECIMAL)
    if 1 - 1e-4 < p < 1:
        return "> " + fmt(0.9999, 4)
    return fmt(p, 4)


def fmt_cmc(x: Optional[float]) -> str:
    """Comprimento médio de corrida (CMC)."""
    if x is None:
        return "—"
    if math.isinf(x):
        return "∞"
    if x >= 1000:
        return fmt(x, 0)
    if x >= 100:
        return fmt(x, 1)
    return fmt(x, 2)


def casas_decimais(valores: Iterable[float]) -> int:
    """Maior número de casas decimais presente nos dados (no máximo 6)."""
    maior = 0
    for v in valores:
        texto = repr(float(v))
        if "e" in texto or "E" in texto:
            return 6
        if "." in texto:
            decimais = texto.split(".")[1].rstrip("0")
            maior = max(maior, len(decimais))
    return min(maior, 6)


def slug(texto: str, maximo: int = 40) -> str:
    """Versão do texto segura para nome de arquivo."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-").lower()
    return (texto[:maximo].strip("-")) or "dados"


def lista_ids(ids: Sequence[int]) -> str:
    """[2, 3, 4, 9, 17] -> '2–4, 9 e 17'."""
    ids = sorted(set(int(i) for i in ids))
    if not ids:
        return "nenhum"
    partes: List[str] = []
    inicio = anterior = ids[0]
    for atual in ids[1:] + [None]:
        if atual is not None and atual == anterior + 1:
            anterior = atual
            continue
        if inicio == anterior:
            partes.append(str(inicio))
        elif anterior == inicio + 1:
            partes.extend([str(inicio), str(anterior)])
        else:
            partes.append(f"{inicio}–{anterior}")
        if atual is not None:
            inicio = anterior = atual
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " e " + partes[-1]


def plural(qtd: int, singular: str, plural_: Optional[str] = None) -> str:
    """'1 subgrupo', '3 subgrupos'."""
    if qtd == 1:
        return f"1 {singular}"
    return f"{qtd} {plural_ or singular + 's'}"


def tabela_texto(cabecalho: Sequence[str], linhas: Sequence[Sequence[object]]) -> str:
    """Tabela simples em texto, para o terminal."""
    todas = [list(map(str, cabecalho))] + [list(map(str, linha)) for linha in linhas]
    larguras = [max(len(linha[i]) for linha in todas) for i in range(len(cabecalho))]

    def montar(linha: List[str]) -> str:
        celulas = []
        for i, celula in enumerate(linha):
            if i > 0 and _parece_numero(celula):
                celulas.append(celula.rjust(larguras[i]))
            else:
                celulas.append(celula.ljust(larguras[i]))
        return "  ".join(celulas).rstrip()

    separador = "  ".join("-" * w for w in larguras)
    return "\n".join([montar(todas[0]), separador] + [montar(l) for l in todas[1:]])


def _parece_numero(texto: str) -> bool:
    return bool(re.fullmatch(r"[+\-−]?[\d.,]+(e[+\-]?\d+)?%?|[<>≈] ?[\d.,]+|∞|—", texto.strip()))
