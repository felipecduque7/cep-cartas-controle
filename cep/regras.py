"""Sinais de alerta: regras Western Electric e tendência.

Regras usadas no Montgomery & Runger (zonas de 1σ, 2σ e 3σ da estatística):
  1. Um ponto além dos limites de controle (3σ).
  2. Dois de três pontos consecutivos além de 2σ, do mesmo lado.
  3. Quatro de cinco pontos consecutivos além de 1σ, do mesmo lado.
  4. Oito pontos consecutivos do mesmo lado da linha central.
Alerta complementar:
  T. Seis pontos seguidos sempre subindo ou sempre descendo (tendência).

Janelas sobrepostas que disparam a mesma regra, do mesmo lado, são unidas em
um único sinal, para o relatório não repetir o mesmo trecho várias vezes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from . import config
from .cartas import Serie


def descricao_regra(regra: str) -> str:
    return {
        "1": "Regra 1 – ponto além do limite de controle (3σ)",
        "2": (f"Regra 2 – {config.REGRA2_MINIMO} de {config.REGRA2_JANELA} pontos consecutivos além de "
              f"{config.REGRA2_SIGMAS:g}σ do mesmo lado"),
        "3": (f"Regra 3 – {config.REGRA3_MINIMO} de {config.REGRA3_JANELA} pontos consecutivos além de "
              f"{config.REGRA3_SIGMAS:g}σ do mesmo lado"),
        "4": f"Regra 4 – {config.REGRA4_SEQUENCIA} pontos consecutivos do mesmo lado da linha central",
        "T": f"Tendência – {config.TENDENCIA_SEQUENCIA} pontos seguidos sempre subindo ou sempre descendo",
    }[regra]


@dataclass
class Sinal:
    regra: str            # "1", "2", "3", "4" ou "T"
    lado: str             # "acima", "abaixo", "subindo", "descendo"
    serie: str            # chave da série
    pontos: List[int]     # números (1-based) dos pontos que caracterizam o sinal
    inicio: int           # número do primeiro ponto do trecho
    fim: int              # número do último ponto do trecho

    @property
    def descricao(self) -> str:
        return descricao_regra(self.regra)

    @property
    def fora_de_controle(self) -> bool:
        return self.regra == "1"


def _tolerancia(*valores: float) -> float:
    return 1e-9 * max([1.0] + [abs(v) for v in valores])


def pontos_fora(serie: Serie, apenas: Optional[Set[int]] = None) -> List[Tuple[int, str]]:
    """[(posição, 'acima'|'abaixo')] dos pontos além dos limites (regra 1)."""
    resultado = []
    for k, pos in enumerate(serie.pos):
        if apenas is not None and pos not in apenas:
            continue
        valor, lsc, lic = serie.valores[k], serie.lsc[k], serie.lic[k]
        tol = _tolerancia(valor, lsc, lic)
        if valor > lsc + tol:
            resultado.append((pos, "acima"))
        elif valor < lic - tol:
            resultado.append((pos, "abaixo"))
    return resultado


def _unir(eventos: List[Tuple[int, int, List[int]]]) -> List[Tuple[int, int, List[int]]]:
    """Une janelas que se sobrepõem ou se tocam (índices na sequência avaliada)."""
    unidos: List[Tuple[int, int, List[int]]] = []
    for inicio, fim, pontos in sorted(eventos):
        if unidos and inicio <= unidos[-1][1] + 1:
            ini, fi, pts = unidos[-1]
            unidos[-1] = (ini, max(fi, fim), sorted(set(pts) | set(pontos)))
        else:
            unidos.append((inicio, fim, list(pontos)))
    return unidos


def avaliar(serie: Serie, apenas: Optional[Set[int]] = None) -> List[Sinal]:
    """Aplica as regras da série aos seus pontos (opcionalmente só a alguns)."""
    seq = [k for k, pos in enumerate(serie.pos) if apenas is None or pos in apenas]
    if not seq:
        return []
    ids = serie.ids
    z: List[Optional[float]] = []
    for k in seq:
        s = serie.sigma[k]
        z.append(None if s <= 0 else (serie.valores[k] - serie.lc[k]) / s)
    sinais: List[Sinal] = []

    def registrar(regra: str, lado: str, eventos: List[Tuple[int, int, List[int]]]) -> None:
        for inicio, fim, pontos in _unir(eventos):
            sinais.append(Sinal(regra, lado, serie.chave, [ids[seq[j]] for j in pontos],
                                ids[seq[inicio]], ids[seq[fim]]))

    # Regra 1 – além dos limites
    if "1" in serie.regras:
        for j, k in enumerate(seq):
            valor, lsc, lic = serie.valores[k], serie.lsc[k], serie.lic[k]
            tol = _tolerancia(valor, lsc, lic)
            if valor > lsc + tol:
                sinais.append(Sinal("1", "acima", serie.chave, [ids[k]], ids[k], ids[k]))
            elif valor < lic - tol:
                sinais.append(Sinal("1", "abaixo", serie.chave, [ids[k]], ids[k], ids[k]))

    # Regras 2 e 3 – k de m pontos além de uma zona, do mesmo lado
    for regra, janela, minimo, limite in (
        ("2", config.REGRA2_JANELA, config.REGRA2_MINIMO, config.REGRA2_SIGMAS),
        ("3", config.REGRA3_JANELA, config.REGRA3_MINIMO, config.REGRA3_SIGMAS),
    ):
        if regra not in serie.regras:
            continue
        for lado, cond in (("acima", lambda v: v is not None and v > limite),
                           ("abaixo", lambda v: v is not None and v < -limite)):
            eventos = []
            for fim in range(janela - 1, len(seq)):
                janela_idx = list(range(fim - janela + 1, fim + 1))
                envolvidos = [j for j in janela_idx if cond(z[j])]
                if len(envolvidos) >= minimo:
                    eventos.append((janela_idx[0], janela_idx[-1], envolvidos))
            registrar(regra, lado, eventos)

    # Regra 4 – sequência do mesmo lado da linha central
    if "4" in serie.regras:
        for lado, cond in (("acima", lambda v: v is not None and v > 0),
                           ("abaixo", lambda v: v is not None and v < 0)):
            eventos = []
            for inicio, fim in _corridas([cond(v) for v in z]):
                if fim - inicio + 1 >= config.REGRA4_SEQUENCIA:
                    eventos.append((inicio, fim, list(range(inicio, fim + 1))))
            registrar("4", lado, eventos)

    # Tendência – pontos sempre subindo ou sempre descendo
    if "T" in serie.regras and len(seq) >= 2:
        valores = [serie.valores[k] for k in seq]
        for lado, comparar in (("subindo", lambda a, b: b > a), ("descendo", lambda a, b: b < a)):
            passos = [False] + [comparar(valores[j - 1], valores[j]) for j in range(1, len(valores))]
            eventos = []
            for inicio, fim in _corridas(passos):
                comeco = inicio - 1          # a corrida inclui o ponto anterior ao 1º passo
                if fim - comeco + 1 >= config.TENDENCIA_SEQUENCIA:
                    eventos.append((comeco, fim, list(range(comeco, fim + 1))))
            registrar("T", lado, eventos)

    ordem = {"1": 0, "2": 1, "3": 2, "4": 3, "T": 4}
    sinais.sort(key=lambda s: (s.inicio, ordem[s.regra]))
    return sinais


def _corridas(marcas: Sequence[bool]) -> Iterable[Tuple[int, int]]:
    """Trechos máximos de valores verdadeiros consecutivos: (início, fim)."""
    inicio = None
    for j, marca in enumerate(list(marcas) + [False]):
        if marca and inicio is None:
            inicio = j
        elif not marca and inicio is not None:
            yield inicio, j - 1
            inicio = None


def pontos_com_alerta(sinais: Iterable[Sinal]) -> Set[int]:
    """Números dos pontos envolvidos em sinais das regras 2, 3, 4 e T."""
    return {p for s in sinais if not s.fora_de_controle for p in s.pontos}


def pontos_fora_de_controle(sinais: Iterable[Sinal]) -> Set[int]:
    return {p for s in sinais if s.fora_de_controle for p in s.pontos}
