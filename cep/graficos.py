"""Figuras das cartas de controle, da capacidade e da curva de detecção.

As figuras são salvas em PNG (para o relatório PDF) com estilo discreto:
traço fino para os dados, linha central em cinza, limites de controle
tracejados em vermelho, zonas de 1σ e 2σ em linhas bem claras. A cor nunca é
o único código: pontos fora de controle têm marcador próprio e número, sinais
de alerta são triângulos e pontos retirados do cálculo ficam vazados.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

# Pasta de cache do matplotlib gravável mesmo em máquinas com permissões restritas.
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "cep-matplotlib"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from .cartas import Serie  # noqa: E402
from .regras import Sinal  # noqa: E402
from .util import fmt  # noqa: E402

COR = {
    "superficie": "#ffffff",
    "tinta": "#0b0b0b",
    "tinta2": "#52514e",
    "muda": "#898781",
    "grade": "#e1e0d9",
    "eixo": "#c3c2b7",
    "serie": "#2a78d6",
    "critico": "#d03b3b",
    "alerta": "#ec835a",
}
DPI = 160
LARGURA = 7.4

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8.5,
    "axes.titlesize": 9.5,
    "axes.titleweight": "bold",
    "axes.titlecolor": COR["tinta"],
    "axes.titlelocation": "left",
    "axes.labelsize": 8.5,
    "axes.labelcolor": COR["tinta2"],
    "figure.facecolor": COR["superficie"],
    "axes.facecolor": COR["superficie"],
    "savefig.facecolor": COR["superficie"],
})


def _decimais_eixo(minimo: float, maximo: float) -> int:
    faixa = abs(maximo - minimo)
    if faixa <= 0:
        return 2
    return int(min(6, max(0, math.ceil(-math.log10(faixa / 5)) + 1)))


def _estilo(ax, casas: Optional[int] = None) -> None:
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(COR["eixo"])
        ax.spines[lado].set_linewidth(0.8)
    ax.tick_params(colors=COR["muda"], labelsize=7.5, length=3, width=0.6)
    for rotulo in ax.get_xticklabels() + ax.get_yticklabels():
        rotulo.set_color(COR["tinta2"])


def _formatar_eixo_y(ax, casas: int) -> None:
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: fmt(v, casas)))


def _passos(x: Sequence[float], y: Sequence[float]):
    """Coordenadas em degraus para limites que variam de ponto a ponto."""
    xs, ys = [], []
    for i, (xi, yi) in enumerate(zip(x, y)):
        xs += [xi - 0.5, xi + 0.5]
        ys += [yi, yi]
    return xs, ys


def _linha_limite(ax, serie: Serie, valores: Sequence[float], **estilo) -> None:
    if serie.limites_constantes():
        ax.axhline(valores[0], **estilo)
    else:
        xs, ys = _passos(serie.ids, valores)
        ax.plot(xs, ys, **estilo)


def _painel(ax, serie: Serie, removidos: Set[int], fora: Set[int], alerta: Set[int],
            lse: Optional[float], lie: Optional[float], mostrar_especificacao: bool) -> List[str]:
    """Desenha uma carta em um eixo. Devolve notas de rodapé (limites fora da escala)."""
    notas: List[str] = []
    ids = serie.ids
    x = np.array(ids, dtype=float)
    y = np.array(serie.valores, dtype=float)
    # Zonas de 1σ e 2σ (referência para as regras de alerta)
    for k in (1, 2):
        for sinal in (1, -1):
            zona = [c + sinal * k * s for c, s in zip(serie.lc, serie.sigma)]
            if sinal < 0 and not serie.pode_ser_negativa and min(zona) < 0:
                continue
            _linha_limite(ax, serie, zona, color=COR["grade"], lw=0.7, zorder=1)

    _linha_limite(ax, serie, serie.lc, color=COR["tinta2"], lw=1.0, zorder=2)
    estilo_lim = dict(color=COR["critico"], lw=1.15, ls=(0, (5, 3)), zorder=2)
    _linha_limite(ax, serie, serie.lsc, **estilo_lim)
    _linha_limite(ax, serie, serie.lic, **estilo_lim)

    ax.plot(x, y, color=COR["serie"], lw=1.5, zorder=3, solid_joinstyle="round", solid_capstyle="round")

    normais = [j for j, i in enumerate(ids) if i not in removidos and i not in fora and i not in alerta]
    ax.scatter(x[normais], y[normais], s=26, color=COR["serie"], edgecolors=COR["superficie"],
               linewidths=1.1, zorder=4)
    lista_alerta = [j for j, i in enumerate(ids) if i in alerta and i not in fora and i not in removidos]
    if lista_alerta:
        ax.scatter(x[lista_alerta], y[lista_alerta], s=48, marker="^", color=COR["alerta"],
                   edgecolors=COR["superficie"], linewidths=1.0, zorder=5)
    lista_fora = [j for j, i in enumerate(ids) if i in fora and i not in removidos]
    if lista_fora:
        ax.scatter(x[lista_fora], y[lista_fora], s=58, marker="D", color=COR["critico"],
                   edgecolors=COR["superficie"], linewidths=1.1, zorder=6)
    lista_removidos = [j for j, i in enumerate(ids) if i in removidos]
    if lista_removidos:
        ax.scatter(x[lista_removidos], y[lista_removidos], s=40, facecolors=COR["superficie"],
                   edgecolors=COR["muda"], linewidths=1.3, zorder=6)

    # Número dos pontos fora de controle ou retirados
    destacados = sorted(set(lista_fora) | set(lista_removidos))
    for j in destacados:
        acima = y[j] >= serie.lc[j]
        ax.annotate(str(ids[j]), (x[j], y[j]), xytext=(0, 8 if acima else -12), textcoords="offset points",
                    ha="center", fontsize=7.5, color=COR["tinta"], zorder=7)

    # Escala vertical
    candidatos = list(y) + list(serie.lsc) + list(serie.lic)
    baixo, alto = min(candidatos), max(candidatos)
    especificacoes = []
    if mostrar_especificacao:
        faixa = max(alto - baixo, 1e-12)
        for nome, valor in (("LSE", lse), ("LIE", lie)):
            if valor is None:
                continue
            if baixo - 0.6 * faixa <= valor <= alto + 0.6 * faixa:
                especificacoes.append((nome, valor))
                baixo, alto = min(baixo, valor), max(alto, valor)
            else:
                notas.append(f"{nome} = {fmt(valor, serie.casas)} fora da escala")
    faixa_total = max(alto - baixo, 1e-12)
    ax.set_ylim(baixo - 0.12 * faixa_total, alto + 0.16 * faixa_total)
    ax.set_xlim(min(ids) - 0.6, max(ids) + 0.6)
    for nome, valor in especificacoes:
        ax.axhline(valor, color=COR["tinta"], lw=1.0, ls=(0, (6, 2, 1, 2)), zorder=2)

    # Rótulos dos limites à direita
    transf = ax.get_yaxis_transform()

    def sufixo(valores: Sequence[float]) -> str:
        varia = any(abs(v - valores[0]) > 1e-12 * max(1.0, abs(valores[0])) for v in valores)
        return " (var.)" if varia else ""
    rotulos = [(serie.lsc[-1], f"LSC {fmt(serie.lsc[-1], serie.casas)}{sufixo(serie.lsc)}"),
               (serie.lc[-1], f"LC {fmt(serie.lc[-1], serie.casas)}{sufixo(serie.lc)}"),
               (serie.lic[-1], f"LIC {fmt(serie.lic[-1], serie.casas)}{sufixo(serie.lic)}")]
    rotulos += [(valor, f"{nome} {fmt(valor, serie.casas)}") for nome, valor in especificacoes]
    rotulos.sort(key=lambda r: r[0])
    altura_px = ax.get_window_extent().height or 200
    faixa_dados = ax.get_ylim()[1] - ax.get_ylim()[0]
    minimo_dados = faixa_dados * 11 / altura_px
    posicoes = []
    for valor, _texto in rotulos:
        pos = valor if not posicoes else max(valor, posicoes[-1] + minimo_dados)
        posicoes.append(pos)
    for (valor, texto), pos in zip(rotulos, posicoes):
        ax.text(1.008, pos, texto, transform=transf, va="center", ha="left", fontsize=7.3,
                color=COR["tinta2"], clip_on=False)

    ax.set_title(serie.titulo, pad=6)
    ax.set_ylabel(serie.rotulo_y)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=min(20, max(4, len(ids)))))
    _formatar_eixo_y(ax, _decimais_eixo(*ax.get_ylim()))
    _estilo(ax)
    return notas


def grafico_cartas(series: List[Serie], sinais: Dict[str, List[Sinal]], caminho: Path, titulo: str,
                   subtitulo: str, removidos_ids: Iterable[int] = (), lse: Optional[float] = None,
                   lie: Optional[float] = None) -> Path:
    """Uma figura com uma carta por painel (ex.: X-barra em cima, R embaixo)."""
    removidos = set(removidos_ids)
    altura = 0.95 + 2.45 * len(series)
    fig, eixos = plt.subplots(len(series), 1, figsize=(LARGURA, altura), squeeze=False)
    presentes = {"normal": False, "alerta": False, "fora": False, "removido": bool(removidos)}
    notas_gerais: List[str] = []
    for ax, serie in zip(eixos[:, 0], series):
        lista = sinais.get(serie.chave, [])
        fora = {p for s in lista if s.fora_de_controle for p in s.pontos}
        alerta = {p for s in lista if not s.fora_de_controle for p in s.pontos}
        presentes["alerta"] |= bool(alerta - fora - removidos)
        presentes["fora"] |= bool(fora - removidos)
        presentes["normal"] = True
        mostrar_esp = serie.chave == "i"
        retirados = removidos
        if serie.chave == "am":
            # A amplitude móvel do ponto k usa os pontos k−1 e k: sai se um dos dois saiu.
            retirados = {k for k in serie.ids if k in removidos or k - 1 in removidos}
        notas = _painel(ax, serie, retirados, fora, alerta, lse, lie, mostrar_esp)
        notas_gerais += notas
        ax.set_xlabel(serie.rotulo_x)

    marcadores = [Line2D([], [], color=COR["serie"], lw=1.5, marker="o", markersize=5,
                         markeredgecolor=COR["superficie"], label="Pontos")]
    if presentes["alerta"]:
        marcadores.append(Line2D([], [], ls="", marker="^", markersize=7, color=COR["alerta"],
                                 markeredgecolor=COR["superficie"], label="Sinal de alerta (regras 2–4 ou tendência)"))
    if presentes["fora"]:
        marcadores.append(Line2D([], [], ls="", marker="D", markersize=6.5, color=COR["critico"],
                                 markeredgecolor=COR["superficie"], label="Fora de controle (regra 1)"))
    if presentes["removido"]:
        marcadores.append(Line2D([], [], ls="", marker="o", markersize=6.5, markerfacecolor=COR["superficie"],
                                 markeredgecolor=COR["muda"], markeredgewidth=1.3, label="Retirado do cálculo"))
    linhas = [Line2D([], [], color=COR["tinta2"], lw=1.0, label="Linha central (LC)"),
              Line2D([], [], color=COR["critico"], lw=1.15, ls=(0, (5, 3)), label="Limites de controle (LSC / LIC)"),
              Line2D([], [], color=COR["grade"], lw=1.2, label="Zonas de 1σ e 2σ")]
    colunas = max(len(marcadores), len(linhas))
    vazio = Line2D([], [], ls="", label=" ")
    marcadores += [vazio] * (colunas - len(marcadores))
    linhas += [vazio] * (colunas - len(linhas))
    # O matplotlib preenche a legenda por colunas: intercalando, a 1ª linha fica com
    # os marcadores e a 2ª com as linhas de referência.
    itens = [h for par in zip(marcadores, linhas) for h in par]
    fig.suptitle(titulo, x=0.01, ha="left", fontsize=11, fontweight="bold", color=COR["tinta"], y=0.995)
    fig.text(0.01, 1 - 0.42 / altura, subtitulo, ha="left", va="center", fontsize=8.3, color=COR["tinta2"])
    fig.legend(handles=itens, loc="upper left", bbox_to_anchor=(0.005, 1 - 0.55 / altura), ncol=colunas,
               frameon=False, fontsize=7.6, handlelength=2.2, columnspacing=1.4, labelcolor=COR["tinta2"])
    if notas_gerais:
        fig.text(0.01, 0.005, "; ".join(dict.fromkeys(notas_gerais)), fontsize=7.3, color=COR["muda"])
    fig.tight_layout(rect=(0, 0.02, 0.88, 1 - 1.02 / altura), h_pad=2.2)
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return caminho


def grafico_capacidade(valores: Sequence[float], mu: float, sigma: float, lse: Optional[float],
                       lie: Optional[float], unidade: str, titulo: str, casas: int, caminho: Path,
                       resumo: str = "") -> Path:
    """Histograma das medições individuais com a curva normal e a especificação."""
    valores = np.asarray(valores, dtype=float)
    fig, ax = plt.subplots(figsize=(LARGURA, 3.3))
    baixo, alto = float(valores.min()), float(valores.max())
    if sigma and sigma > 0:
        baixo, alto = min(baixo, mu - 4 * sigma), max(alto, mu + 4 * sigma)
    faixa = max(alto - baixo, 1e-12)
    especificacoes, notas = [], []
    for nome, valor in (("LIE", lie), ("LSE", lse)):
        if valor is None:
            continue
        if baixo - 0.75 * faixa <= valor <= alto + 0.75 * faixa:
            especificacoes.append((nome, valor))
            baixo, alto = min(baixo, valor), max(alto, valor)
        else:
            notas.append(f"{nome} = {fmt(valor, casas)} fora da escala")
    margem = 0.04 * (alto - baixo or 1.0)
    bordas = np.histogram_bin_edges(valores, bins="auto")
    if len(bordas) - 1 > 24:
        bordas = np.histogram_bin_edges(valores, bins=24)
    elif len(bordas) - 1 < 6:
        bordas = np.histogram_bin_edges(valores, bins=6)
    ax.hist(valores, bins=bordas, color=COR["serie"], edgecolor=COR["superficie"], linewidth=1.4, zorder=2)
    if sigma and sigma > 0:
        xs = np.linspace(baixo - margem, alto + margem, 400)
        largura = bordas[1] - bordas[0]
        ys = len(valores) * largura * np.exp(-0.5 * ((xs - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
        ax.plot(xs, ys, color=COR["tinta2"], lw=1.3, zorder=3)
    ax.axvline(mu, color=COR["tinta2"], lw=1.0, zorder=3)
    topo = ax.get_ylim()[1]
    ax.text(mu, topo * 1.01, f"μ {fmt(mu, casas)}", ha="center", va="bottom", fontsize=7.4, color=COR["tinta2"])
    esquerda, direita = baixo - margem, alto + margem
    for nome, valor in especificacoes:
        ax.axvline(valor, color=COR["tinta"], lw=1.2, ls=(0, (6, 2, 1, 2)), zorder=3)
        alinhamento = "center"
        if valor > direita - 0.1 * (direita - esquerda):
            alinhamento = "right"
        elif valor < esquerda + 0.1 * (direita - esquerda):
            alinhamento = "left"
        ax.text(valor, topo * 1.01, f"{nome} {fmt(valor, casas)}", ha=alinhamento, va="bottom", fontsize=7.4,
                color=COR["tinta"])
    ax.set_xlim(esquerda, direita)
    ax.set_ylim(0, topo * 1.12)
    ax.set_xlabel(f"Medição individual ({unidade})" if unidade else "Medição individual")
    ax.set_ylabel("Frequência")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: fmt(v, _decimais_eixo(baixo, alto))))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(titulo, pad=24 if resumo else 14)
    if resumo:
        # Acima da área do gráfico, para não colidir com os rótulos da especificação.
        ax.text(0.0, 1.035, resumo, transform=ax.transAxes, ha="left", va="bottom", fontsize=7.8,
                color=COR["tinta2"])
    if notas:
        fig.text(0.01, 0.005, "; ".join(notas), fontsize=7.3, color=COR["muda"])
    _estilo(ax)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return caminho


def grafico_deteccao(xs: Sequence[float], ys: Sequence[float], eixo_x: str, titulo: str, caminho: Path,
                     destaque: Optional[tuple] = None, formatar_x=None) -> Path:
    """Probabilidade de detectar o deslocamento em uma amostra (1 − β)."""
    fig, ax = plt.subplots(figsize=(LARGURA, 3.0))
    ax.plot(xs, ys, color=COR["serie"], lw=1.8, zorder=3, solid_capstyle="round")
    for nivel in (0.5, 0.9):
        ax.axhline(nivel, color=COR["grade"], lw=0.8, zorder=1)
    if destaque is not None:
        dx, dy, rotulo = destaque
        ax.scatter([dx], [dy], s=46, color=COR["tinta"], edgecolors=COR["superficie"], linewidths=1.2, zorder=5)
        ax.annotate(rotulo, (dx, dy), xytext=(8, -14 if dy > 0.6 else 8), textcoords="offset points",
                    fontsize=7.6, color=COR["tinta"])
    ax.set_ylim(0, 1.04)
    ax.set_xlim(min(xs), max(xs))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v * 100:.0f}%"))
    if formatar_x:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: formatar_x(v)))
    ax.set_xlabel(eixo_x)
    ax.set_ylabel("P(detectar em uma amostra)")
    ax.set_title(titulo, pad=8)
    _estilo(ax)
    fig.tight_layout()
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return caminho
