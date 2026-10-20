"""Relatório PDF cumulativo da sessão.

Cada atividade (processar um JSON, registrar medições, calcular uma
probabilidade...) acrescenta blocos ao registro da sessão. O registro fica
salvo em registro.json e o PDF é gerado de novo a cada atividade, sempre com
tudo o que foi feito desde o início da sessão (o "append" pedido no trabalho).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from . import __version__

TINTA = colors.HexColor("#0b0b0b")
TINTA2 = colors.HexColor("#52514e")
MUDA = colors.HexColor("#898781")
GRADE = colors.HexColor("#e1e0d9")
FUNDO_CAB = colors.HexColor("#f0efec")
NIVEIS = {
    "critico": (colors.HexColor("#d03b3b"), colors.HexColor("#fbeceb"), "Atenção"),
    "alerta": (colors.HexColor("#ec835a"), colors.HexColor("#fdf1ec"), "Ressalva"),
    "ok": (colors.HexColor("#0ca30c"), colors.HexColor("#ecf7ec"), "Situação"),
    "info": (colors.HexColor("#2a78d6"), colors.HexColor("#edf3fc"), "Nota"),
}

_FONTE, _FONTE_NEGRITO = "Helvetica", "Helvetica-Bold"
_UNICODE_OK = False


def _registrar_fontes() -> None:
    """Usa a DejaVu Sans que vem com o matplotlib (tem σ, β, ≈, ≤...)."""
    global _FONTE, _FONTE_NEGRITO, _UNICODE_OK
    if _UNICODE_OK:
        return
    try:
        import matplotlib
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVu", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(base / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(base / "DejaVuSans-Oblique.ttf")))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique",
                           boldItalic="DejaVu-Bold")
        _FONTE, _FONTE_NEGRITO, _UNICODE_OK = "DejaVu", "DejaVu-Bold", True
    except Exception:  # pragma: no cover - só se a fonte não existir
        _FONTE, _FONTE_NEGRITO, _UNICODE_OK = "Helvetica", "Helvetica-Bold", False


_TROCAS_SEM_UNICODE = {"σ": "sigma", "β": "beta", "α": "alfa", "μ": "mi", "≈": "~", "≤": "<=", "≥": ">=",
                       "∞": "infinito", "√": "raiz", "Δ": "delta", "→": "->", "·": "x", "−": "-", "λ": "lambda"}


def _texto(texto: Any) -> str:
    """Escapa o texto para o PDF e converte **negrito**."""
    texto = "" if texto is None else str(texto)
    if not _UNICODE_OK:
        for de, para in _TROCAS_SEM_UNICODE.items():
            texto = texto.replace(de, para)
    texto = escape(texto)
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    return texto.replace("\n", "<br/>")


class Relatorio:
    """Registro da sessão e geração do PDF."""

    def __init__(self, pasta: Path, titulo: str = "Relatório de Controle Estatístico de Processos",
                 iniciado_em: Optional[str] = None, blocos: Optional[List[Dict[str, Any]]] = None):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.titulo = titulo
        self.iniciado_em = iniciado_em or datetime.now().strftime("%d/%m/%Y %H:%M")
        self.blocos: List[Dict[str, Any]] = blocos or []
        self.ultimo_pdf: Optional[Path] = None

    # --- caminhos -------------------------------------------------------------
    @property
    def caminho_pdf(self) -> Path:
        return self.pasta / "relatorio.pdf"

    @property
    def caminho_registro(self) -> Path:
        return self.pasta / "registro.json"

    @property
    def pasta_graficos(self) -> Path:
        pasta = self.pasta / "graficos"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    @property
    def num_secoes(self) -> int:
        return sum(1 for b in self.blocos if b["tipo"] == "secao")

    # --- blocos ---------------------------------------------------------------
    def secao(self, titulo: str) -> int:
        numero = self.num_secoes + 1
        self.blocos.append({"tipo": "secao", "numero": numero, "titulo": titulo,
                            "quando": datetime.now().strftime("%d/%m/%Y %H:%M:%S")})
        return numero

    def subtitulo(self, texto: str) -> None:
        self.blocos.append({"tipo": "subtitulo", "texto": texto})

    def paragrafo(self, texto: str) -> None:
        self.blocos.append({"tipo": "paragrafo", "texto": texto})

    def lista(self, itens: Sequence[str]) -> None:
        if itens:
            self.blocos.append({"tipo": "lista", "itens": list(itens)})

    def tabela(self, cabecalho: Sequence[str], linhas: Sequence[Sequence[Any]],
               larguras: Optional[Sequence[float]] = None) -> None:
        self.blocos.append({"tipo": "tabela", "cabecalho": list(map(str, cabecalho)),
                            "linhas": [list(map(str, l)) for l in linhas],
                            "larguras": list(larguras) if larguras else None})

    def pares(self, itens: Sequence[Tuple[str, Any]]) -> None:
        self.blocos.append({"tipo": "pares", "itens": [[str(a), str(b)] for a, b in itens]})

    def imagem(self, caminho: Path, largura_cm: float = 17.0) -> None:
        caminho = Path(caminho)
        try:
            relativo = str(caminho.resolve().relative_to(self.pasta.resolve()))
        except ValueError:
            relativo = str(caminho.resolve())
        self.blocos.append({"tipo": "imagem", "caminho": relativo, "largura_cm": largura_cm})

    def destaque(self, texto: str, nivel: str = "info") -> None:
        self.blocos.append({"tipo": "destaque", "nivel": nivel, "texto": texto})

    def quebra(self) -> None:
        self.blocos.append({"tipo": "quebra"})

    # --- persistência -----------------------------------------------------------
    def salvar(self) -> Path:
        """Grava o registro e gera o PDF com tudo o que foi feito na sessão."""
        dados = {"titulo": self.titulo, "iniciado_em": self.iniciado_em, "versao": __version__,
                 "blocos": self.blocos}
        self.caminho_registro.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.gerar_pdf()

    @classmethod
    def abrir(cls, pasta: Path) -> "Relatorio":
        pasta = Path(pasta)
        dados = json.loads((pasta / "registro.json").read_text(encoding="utf-8"))
        return cls(pasta, dados.get("titulo", "Relatório"), dados.get("iniciado_em"), dados.get("blocos", []))

    # --- PDF -------------------------------------------------------------------
    def _estilos(self) -> Dict[str, ParagraphStyle]:
        base = ParagraphStyle("base", fontName=_FONTE, fontSize=9.2, leading=12.8, textColor=TINTA,
                              spaceAfter=4)
        return {
            "base": base,
            "titulo": ParagraphStyle("titulo", parent=base, fontName=_FONTE_NEGRITO, fontSize=18, leading=22,
                                     spaceAfter=6),
            "subtitulo_capa": ParagraphStyle("subcapa", parent=base, textColor=TINTA2, fontSize=10, leading=14),
            "h1": ParagraphStyle("h1", parent=base, fontName=_FONTE_NEGRITO, fontSize=13, leading=16,
                                 spaceBefore=4, spaceAfter=2),
            "quando": ParagraphStyle("quando", parent=base, fontSize=8, textColor=MUDA, spaceAfter=8),
            "h2": ParagraphStyle("h2", parent=base, fontName=_FONTE_NEGRITO, fontSize=10.3, leading=13,
                                 spaceBefore=9, spaceAfter=4),
            "celula": ParagraphStyle("celula", parent=base, fontSize=7.8, leading=9.6, spaceAfter=0),
            "celula_neg": ParagraphStyle("celula_neg", parent=base, fontName=_FONTE_NEGRITO, fontSize=7.8,
                                         leading=9.6, spaceAfter=0),
            "item": ParagraphStyle("item", parent=base, leftIndent=12, bulletIndent=2, spaceAfter=2),
        }

    def _cabecalho_rodape(self, canvas, doc) -> None:
        canvas.saveState()
        largura, altura = A4
        canvas.setFont(_FONTE, 7.5)
        canvas.setFillColor(MUDA)
        canvas.drawString(2 * cm, altura - 1.25 * cm, self.titulo)
        canvas.drawRightString(largura - 2 * cm, altura - 1.25 * cm, f"Página {doc.page}")
        canvas.setStrokeColor(GRADE)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, altura - 1.4 * cm, largura - 2 * cm, altura - 1.4 * cm)
        canvas.drawString(2 * cm, 1.1 * cm, f"Sessão iniciada em {self.iniciado_em} · cep-cartas-controle {__version__}")
        canvas.restoreState()

    def _tabela(self, cabecalho: List[str], linhas: List[List[str]], estilos, larguras_cm=None) -> Table:
        largura_util = A4[0] - 4 * cm
        dados = [[Paragraph(_texto(c), estilos["celula_neg"]) for c in cabecalho]]
        for linha in linhas:
            dados.append([Paragraph(_texto(c), estilos["celula"]) for c in linha])
        if larguras_cm:
            total = sum(larguras_cm)
            larguras = [largura_util * w / total for w in larguras_cm]
        else:
            larguras = _larguras_automaticas([cabecalho] + linhas, largura_util)
        tabela = Table(dados, colWidths=larguras, repeatRows=1, hAlign="LEFT")
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), FUNDO_CAB),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRADE),
            ("LINEABOVE", (0, 0), (-1, 0), 0.4, GRADE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return tabela

    def gerar_pdf(self) -> Path:
        _registrar_fontes()
        estilos = self._estilos()
        historia: List[Any] = []
        historia.append(Paragraph(_texto(self.titulo), estilos["titulo"]))
        historia.append(Paragraph(_texto(f"Sessão iniciada em {self.iniciado_em}. Gerado pelo programa "
                                         f"cep-cartas-controle {__version__} em "
                                         f"{datetime.now().strftime('%d/%m/%Y %H:%M')}."),
                                  estilos["subtitulo_capa"]))
        secoes = [b for b in self.blocos if b["tipo"] == "secao"]
        historia.append(Spacer(1, 8))
        if secoes:
            historia.append(Paragraph(_texto("Atividades desta sessão"), estilos["h2"]))
            for b in secoes:
                historia.append(Paragraph(_texto(f"{b['numero']}. {b['titulo']} ({b['quando']})"), estilos["item"],
                                          bulletText="•"))
        else:
            historia.append(Paragraph(_texto("Nenhuma atividade registrada ainda."), estilos["base"]))

        for bloco in self.blocos:
            tipo = bloco["tipo"]
            if tipo == "secao":
                historia.append(PageBreak())
                historia.append(Paragraph(_texto(f"{bloco['numero']}. {bloco['titulo']}"), estilos["h1"]))
                historia.append(Paragraph(_texto(f"Registrado em {bloco['quando']}"), estilos["quando"]))
            elif tipo == "subtitulo":
                historia.append(CondPageBreak(3 * cm))
                historia.append(Paragraph(_texto(bloco["texto"]), estilos["h2"]))
            elif tipo == "paragrafo":
                historia.append(Paragraph(_texto(bloco["texto"]), estilos["base"]))
            elif tipo == "lista":
                for item in bloco["itens"]:
                    historia.append(Paragraph(_texto(item), estilos["item"], bulletText="•"))
            elif tipo == "tabela":
                historia.append(self._tabela(bloco["cabecalho"], bloco["linhas"], estilos, bloco.get("larguras")))
                historia.append(Spacer(1, 6))
            elif tipo == "pares":
                tabela = self._tabela(["Item", "Valor"], bloco["itens"], estilos, [5.5, 11.5])
                historia.append(tabela)
                historia.append(Spacer(1, 6))
            elif tipo == "imagem":
                caminho = Path(bloco["caminho"])
                if not caminho.is_absolute():
                    caminho = self.pasta / caminho
                if caminho.exists():
                    largura_pts = min(bloco.get("largura_cm", 17.0) * cm, A4[0] - 4 * cm)
                    lw, lh = ImageReader(str(caminho)).getSize()
                    altura_pts = largura_pts * lh / lw
                    maximo = A4[1] - 6.5 * cm
                    if altura_pts > maximo:
                        largura_pts, altura_pts = largura_pts * maximo / altura_pts, maximo
                    historia.append(KeepTogether([Image(str(caminho), width=largura_pts, height=altura_pts),
                                                  Spacer(1, 6)]))
                else:
                    historia.append(Paragraph(_texto(f"[imagem não encontrada: {bloco['caminho']}]"), estilos["base"]))
            elif tipo == "destaque":
                cor, fundo, rotulo = NIVEIS.get(bloco.get("nivel", "info"), NIVEIS["info"])
                celula = Paragraph(f"<b>{_texto(rotulo)}:</b> {_texto(bloco['texto'])}", estilos["base"])
                caixa = Table([[celula]], colWidths=[A4[0] - 4 * cm], hAlign="LEFT")
                caixa.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), fundo),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, cor),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                historia.append(caixa)
                historia.append(Spacer(1, 6))
            elif tipo == "quebra":
                historia.append(PageBreak())

        destino = self.caminho_pdf
        temporario = destino.with_name(destino.stem + "_gerando.pdf")
        documento = SimpleDocTemplate(str(temporario), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                                      topMargin=2 * cm, bottomMargin=1.8 * cm, title=self.titulo,
                                      author="cep-cartas-controle")
        documento.build(historia, onFirstPage=self._cabecalho_rodape, onLaterPages=self._cabecalho_rodape)
        try:
            os.replace(temporario, destino)
        except PermissionError:
            # No Windows o PDF aberto em um leitor fica bloqueado: salva com outro nome.
            destino = destino.with_name(f"relatorio_{datetime.now().strftime('%H%M%S')}.pdf")
            os.replace(temporario, destino)
        self.ultimo_pdf = destino
        return destino


def _larguras_automaticas(linhas: List[List[str]], largura_util: float) -> List[float]:
    """Larguras das colunas: as curtas (números) cabem sem quebrar; as longas dividem o resto."""
    colunas = len(linhas[0])
    por_caractere, folga = 4.6, 10.0
    natural = []
    for c in range(colunas):
        corpo = [len(str(l[c])) for l in linhas[1:] if c < len(l)] or [0]
        cabecalho = max(len(palavra) for palavra in str(linhas[0][c]).split() or [""])
        caracteres = max(max(corpo), cabecalho, 3)
        natural.append(min(caracteres, 70) * por_caractere + folga)
    if sum(natural) <= largura_util:
        extra = largura_util - sum(natural)
        return [w + extra * w / sum(natural) for w in natural]
    media = largura_util / colunas
    curtas = [c for c in range(colunas) if natural[c] <= media]
    usado = sum(natural[c] for c in curtas)
    longas = [c for c in range(colunas) if c not in curtas]
    restante = max(largura_util - usado, 40.0 * len(longas))
    total_longas = sum(natural[c] for c in longas) or 1.0
    larguras = list(natural)
    for c in longas:
        larguras[c] = restante * natural[c] / total_longas
    escala = largura_util / sum(larguras)
    return [w * escala for w in larguras]


def ultima_pasta_sessao(pasta_saida: Path) -> Optional[Path]:
    """Pasta do relatório mais recente que tem registro (para continuar depois de fechar o programa)."""
    pastas = [p for p in Path(pasta_saida).glob("relatorio_*") if (p / "registro.json").is_file()]
    return max(pastas, key=lambda p: (p / "registro.json").stat().st_mtime) if pastas else None


def nova_pasta_sessao(pasta_saida: Path) -> Path:
    momento = datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
    pasta = Path(pasta_saida) / f"relatorio_{momento}"
    contador = 1
    while pasta.exists():
        contador += 1
        pasta = Path(pasta_saida) / f"relatorio_{momento}_{contador}"
    pasta.mkdir(parents=True)
    return pasta
