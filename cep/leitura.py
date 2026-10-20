"""Leitura e validação do arquivo JSON (o "plano" da análise).

O formato usado em sala é:

    {
      "Unit": "mm",
      "Measured_at": "2026-10-09 12:00:00",
      "Created_by": "Henrique",
      "Type": "X",              # X, R, IMR (ou I, MR), P, NP, C, U
      "Goal": "Calibrar",       # Calibrar ou Acompanhar
      "LSE": 5.0,
      "LIE": 4.0,
      "Data": [[...], [...], ...]
    }

A leitura é tolerante: aceita maiúsculas/minúsculas, acentos, nomes em
português ou inglês ("Tipo", "Objetivo", "Dados"...), números com vírgula e
campos opcionais ausentes. Tudo o que for ajustado vira um aviso, para nada
acontecer em silêncio. Quando algo não pode ser interpretado, a mensagem de
erro diz exatamente onde está o problema.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


class ErroDeLeitura(Exception):
    """Problema no arquivo, com mensagem pronta para o usuário."""


CALIBRAR = "CALIBRAR"
ACOMPANHAR = "ACOMPANHAR"

NOMES_TIPOS = {
    "XBAR_R": "X-barra e R (média e amplitude dos subgrupos)",
    "R": "R (amplitude dos subgrupos), com X-barra",
    "I": "I (valores individuais), com amplitude móvel",
    "MR": "AM (amplitude móvel), com valores individuais",
    "IMR": "I-AM (valores individuais e amplitude móvel)",
    "P": "p (fração de itens defeituosos)",
    "NP": "np (número de itens defeituosos)",
    "C": "c (número de defeitos)",
    "U": "u (defeitos por unidade)",
}

# Código de cada tipo no formato do professor (usado ao gravar JSON).
CODIGO_TIPO = {"XBAR_R": "X", "R": "R", "I": "I", "MR": "MR", "IMR": "IMR",
               "P": "P", "NP": "NP", "C": "C", "U": "U"}

FAMILIA = {"XBAR_R": "variaveis", "R": "variaveis", "I": "individuais", "MR": "individuais",
           "IMR": "individuais", "P": "fracao", "NP": "fracao", "C": "contagem", "U": "taxa"}


def normalizar(texto: Any) -> str:
    """'Measured_at' -> 'measuredat'; 'Calibração' -> 'calibracao'."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texto.lower())


# Nomes aceitos para cada campo (já normalizados).
ALIASES: Dict[str, List[str]] = {
    "tipo": ["type", "tipo", "chart", "carta", "charttype", "tipodacarta", "tipocarta",
             "grafico", "tipografico", "tipodegrafico", "controlchart"],
    "objetivo": ["goal", "objetivo", "atividade", "activity", "mode", "modo", "tipodaatividade",
                 "tipoatividade", "fase", "phase", "acao", "task", "tarefa", "finalidade"],
    "dados": ["data", "dados", "amostras", "samples", "medicoes", "measurements", "valores",
              "values", "subgrupos", "subgroups", "observacoes", "observations"],
    "lse": ["lse", "usl", "limitesuperiordeespecificacao", "limitesuperiorespecificacao",
            "especificacaosuperior", "upperspec", "upperspecificationlimit", "lse1"],
    "lie": ["lie", "lsl", "limiteinferiordeespecificacao", "limiteinferiorespecificacao",
            "especificacaoinferior", "lowerspec", "lowerspecificationlimit"],
    "especificacao": ["especificacao", "especificacoes", "limitedeespecificacao",
                      "limitesdeespecificacao", "limiteespecificacao", "limitesespecificacao",
                      "spec", "specs", "specification", "specifications", "specificationlimits"],
    "unidade": ["unit", "unidade", "units", "unidades", "unidadedemedida"],
    "medido_em": ["measuredat", "medidoem", "datamedicao", "datadamedicao", "datahora",
                  "timestamp", "measured", "date", "datetime", "quando"],
    "criado_por": ["createdby", "criadopor", "autor", "author", "operador", "operator",
                   "responsavel", "criador", "by"],
    "rotulo": ["label", "rotulo", "descricao", "description", "titulo", "title", "nome", "name",
               "processo", "process", "caracteristica", "characteristic", "desc"],
    "tamanho_amostra": ["n", "tamanhoamostra", "tamanhodaamostra", "samplesize", "tamanho",
                        "size", "tamanhosubgrupo", "tamanhodosubgrupo", "subgroupsize",
                        "unidadesinspecionadas", "inspecionados", "itensinspecionados"],
    "limites": ["limites", "limits", "limitesdecontrole", "limitescontrole", "controllimits",
                "calibracao", "calibration", "parametros", "parameters"],
    "lsc": ["lsc", "ucl", "limitesuperiordecontrole", "limitesuperiorcontrole"],
    "lc": ["lc", "cl", "linhacentral", "centerline", "centralline"],
    "lic": ["lic", "lcl", "limiteinferiordecontrole", "limiteinferiorcontrole"],
    "arquivo_calibracao": ["arquivocalibracao", "arquivodecalibracao", "calibrationfile",
                           "calibracaoarquivo", "calibrationpath", "referenciacalibracao"],
}

_SINONIMOS_TIPO = {
    "XBAR_R": {"x", "xbar", "xbarra", "xr", "xbarr", "xbarrar", "xbarraer", "xer", "xmedia",
               "media", "medias", "mean", "means", "average", "xbarchart", "xbarrachart", "xs"},
    "R": {"r", "amplitude", "amplitudes", "range", "rchart"},
    "I": {"i", "individual", "individuais", "individuo", "medidasindividuais",
          "valoresindividuais", "individuals", "ind"},
    "MR": {"mr", "am", "amplitudemovel", "movingrange", "mrchart"},
    "IMR": {"imr", "xmr", "iam", "iamr", "mri", "ami", "mrx", "mri", "imovingrange",
            "individuaisam", "individuaiseam", "individuaisamplitudemovel", "xam", "ixmr"},
    "P": {"p", "pchart", "fracao", "fracaodefeituosa", "fracaodefeituosos", "proporcao",
          "fracaonaoconforme", "proportion"},
    "NP": {"np", "npchart", "numerodefeituosos", "numerodedefeituosos", "defeituosos"},
    "C": {"c", "cchart", "defeitos", "numerodedefeitos", "contagem", "naoconformidades",
          "numerodenaoconformidades"},
    "U": {"u", "uchart", "defeitosporunidade", "naoconformidadesporunidade"},
}


def normalizar_tipo(valor: Any) -> Optional[str]:
    chave = normalizar(valor)
    for tipo, sinonimos in _SINONIMOS_TIPO.items():
        if chave in sinonimos:
            return tipo
    return None


def normalizar_objetivo(valor: Any) -> Optional[str]:
    chave = normalizar(valor)
    if not chave:
        return None
    if chave.startswith(("calib", "fase1", "fasei", "phase1", "phasei", "estabelec", "setup")):
        return CALIBRAR
    if chave.startswith(("acompanh", "monitor", "fase2", "faseii", "phase2", "phaseii",
                         "control", "track", "vigil", "verific")):
        return ACOMPANHAR
    return None


@dataclass
class Plano:
    """Conteúdo do JSON já validado e normalizado."""

    arquivo: str
    tipo: str
    tipo_original: str
    objetivo: str
    objetivo_original: str
    unidade: str = ""
    medido_em: str = ""
    criado_por: str = ""
    rotulo: str = ""
    lse: Optional[float] = None
    lie: Optional[float] = None
    subgrupos: Optional[List[List[float]]] = None    # X-barra/R
    valores: Optional[List[float]] = None            # I, AM, I-AM
    defeituosos: Optional[List[float]] = None        # p, np
    tamanhos: Optional[List[float]] = None           # p, np (n de cada amostra); u (unidades)
    contagens: Optional[List[float]] = None          # c e u (defeitos)
    formato_dados: str = ""
    limites_informados: Optional[Dict[str, Any]] = None
    arquivo_calibracao: Optional[str] = None
    avisos: List[str] = field(default_factory=list)
    campos_extras: Dict[str, Any] = field(default_factory=dict)
    caminho: Optional[str] = None

    @property
    def nome_tipo(self) -> str:
        return NOMES_TIPOS[self.tipo]

    @property
    def familia(self) -> str:
        return FAMILIA[self.tipo]

    @property
    def codigo_tipo(self) -> str:
        return CODIGO_TIPO[self.tipo]

    @property
    def num_pontos(self) -> int:
        for lista in (self.subgrupos, self.valores, self.defeituosos, self.contagens):
            if lista is not None:
                return len(lista)
        return 0

    @property
    def nome_objetivo(self) -> str:
        return "Calibração (Fase I)" if self.objetivo == CALIBRAR else "Acompanhamento (Fase II)"


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def limpar_caminho(texto: str) -> Path:
    """Remove aspas e espaços (caminhos arrastados para o terminal vêm com aspas)."""
    texto = str(texto).strip()
    if texto.startswith("& "):  # PowerShell ao arrastar arquivo
        texto = texto[2:].strip()
    return Path(texto.strip('"').strip("'"))


def carregar_plano(caminho) -> Plano:
    """Lê o arquivo JSON e devolve o plano validado."""
    caminho = limpar_caminho(caminho)
    if not caminho.exists():
        raise ErroDeLeitura(f"Arquivo não encontrado: {caminho}")
    if caminho.is_dir():
        raise ErroDeLeitura(f"{caminho} é uma pasta, não um arquivo JSON.")
    avisos: List[str] = []
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        texto = caminho.read_text(encoding="latin-1")
        avisos.append("O arquivo não estava em UTF-8; foi lido como Latin-1.")
    if not texto.strip():
        raise ErroDeLeitura(f"O arquivo {caminho.name} está vazio.")
    try:
        conteudo = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise ErroDeLeitura(
            f"{caminho.name} não é um JSON válido (linha {erro.lineno}, coluna {erro.colno}): "
            f"{erro.msg}. Confira vírgulas, aspas e colchetes perto desse ponto."
        ) from None
    plano = plano_de_dicionario(conteudo, arquivo=caminho.name)
    plano.caminho = str(caminho)
    plano.avisos[:0] = avisos
    return plano


def plano_de_dicionario(conteudo: Any, arquivo: str = "(sem nome)") -> Plano:
    """Valida o conteúdo de um JSON já carregado."""
    if isinstance(conteudo, list):
        raise ErroDeLeitura(
            "O JSON começa com uma lista. O formato esperado é um objeto { ... } com os campos "
            "Type, Goal, Data (e opcionalmente Unit, LSE, LIE, Measured_at, Created_by)."
        )
    if not isinstance(conteudo, dict):
        raise ErroDeLeitura("O JSON precisa ser um objeto { ... } com os campos da análise.")

    mapa: Dict[str, str] = {}
    for chave in conteudo:
        mapa.setdefault(normalizar(chave), chave)
    usadas: set = set()
    avisos: List[str] = []

    def pegar(campo: str, origem: Optional[Dict[str, Any]] = None) -> Tuple[Any, Optional[str]]:
        fonte = conteudo if origem is None else origem
        mapa_fonte = mapa if origem is None else {normalizar(k): k for k in origem}
        for alias in ALIASES[campo]:
            if alias in mapa_fonte:
                original = mapa_fonte[alias]
                if origem is None:
                    usadas.add(original)
                return fonte[original], original
        return None, None

    # --- tipo da carta -----------------------------------------------------
    tipo_bruto, chave_tipo = pegar("tipo")
    if tipo_bruto is None or str(tipo_bruto).strip() == "":
        raise ErroDeLeitura(
            "Campo do tipo da carta não encontrado (esperado 'Type'). "
            f"Campos presentes: {', '.join(map(str, conteudo.keys())) or 'nenhum'}."
        )
    tipo = normalizar_tipo(tipo_bruto)
    if tipo is None:
        raise ErroDeLeitura(
            f"Tipo de carta '{tipo_bruto}' não reconhecido. Use X (X-barra e R), R, IMR "
            "(ou I / MR), P, NP, C ou U."
        )

    # --- objetivo (calibração ou acompanhamento) -------------------------------
    objetivo_bruto, _ = pegar("objetivo")
    objetivo = normalizar_objetivo(objetivo_bruto) if objetivo_bruto is not None else None
    if objetivo_bruto is not None and objetivo is None and not isinstance(objetivo_bruto, dict):
        raise ErroDeLeitura(
            f"Objetivo '{objetivo_bruto}' não reconhecido. Use 'Calibrar' ou 'Acompanhar'."
        )

    # --- metadados ---------------------------------------------------------------
    unidade = _texto(pegar("unidade")[0])
    medido_em = _texto(pegar("medido_em")[0])
    criado_por = _texto(pegar("criado_por")[0])
    rotulo = _texto(pegar("rotulo")[0])
    if not rotulo:
        rotulo = Path(arquivo).stem

    # --- limites de especificação ---------------------------------------------
    lse_bruto, _ = pegar("lse")
    lie_bruto, _ = pegar("lie")
    especificacao, chave_esp = pegar("especificacao")
    if isinstance(especificacao, dict):
        lse_bruto = lse_bruto if lse_bruto is not None else pegar("lse", especificacao)[0]
        lie_bruto = lie_bruto if lie_bruto is not None else pegar("lie", especificacao)[0]
    elif isinstance(especificacao, (list, tuple)) and len(especificacao) == 2:
        valores_esp = sorted(_numero(v, f"{chave_esp}") for v in especificacao)
        lie_bruto = lie_bruto if lie_bruto is not None else valores_esp[0]
        lse_bruto = lse_bruto if lse_bruto is not None else valores_esp[1]
    lse = _numero_opcional(lse_bruto, "LSE")
    lie = _numero_opcional(lie_bruto, "LIE")
    if lse is not None and lie is not None:
        if lie > lse:
            avisos.append(f"LIE ({lie}) era maior que o LSE ({lse}); os valores foram trocados.")
            lse, lie = lie, lse
        elif lie == lse:
            avisos.append("LSE e LIE são iguais; os limites de especificação foram ignorados.")
            lse = lie = None

    # --- limites já calibrados (para acompanhamento) ---------------------------
    limites_brutos, chave_limites = pegar("limites")
    arquivo_cal, _ = pegar("arquivo_calibracao")
    arquivo_calibracao = None
    if isinstance(limites_brutos, str):
        arquivo_calibracao = limites_brutos.strip()
        limites_brutos = None
    if isinstance(arquivo_cal, str) and arquivo_cal.strip():
        arquivo_calibracao = arquivo_cal.strip()
    limites_informados = _ler_limites(conteudo, mapa, limites_brutos, usadas)

    if objetivo is None:
        objetivo = ACOMPANHAR if (limites_informados or arquivo_calibracao) else CALIBRAR
        avisos.append(
            "O arquivo não informa o objetivo (Goal); usando "
            f"'{'Acompanhar' if objetivo == ACOMPANHAR else 'Calibrar'}'."
        )

    # --- dados ---------------------------------------------------------------------
    dados_brutos, chave_dados = pegar("dados")
    if dados_brutos is None:
        raise ErroDeLeitura("Campo de dados não encontrado (esperado 'Data').")
    n_bruto, chave_n = pegar("tamanho_amostra")

    plano = Plano(
        arquivo=arquivo,
        tipo=tipo,
        tipo_original=str(tipo_bruto),
        objetivo=objetivo,
        objetivo_original="" if objetivo_bruto is None else str(objetivo_bruto),
        unidade=unidade,
        medido_em=medido_em,
        criado_por=criado_por,
        rotulo=rotulo,
        lse=lse,
        lie=lie,
        limites_informados=limites_informados,
        arquivo_calibracao=arquivo_calibracao,
        avisos=avisos,
    )
    _ler_dados(plano, dados_brutos, n_bruto, chave_dados or "Data", chave_n or "n")

    plano.campos_extras = {k: v for k, v in conteudo.items() if k not in usadas}
    if plano.campos_extras:
        avisos.append("Campos não utilizados pelo programa: " + ", ".join(map(str, plano.campos_extras)))
    return plano


# ---------------------------------------------------------------------------
# Números e textos
# ---------------------------------------------------------------------------
def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _numero(valor: Any, onde: str) -> float:
    """Converte um valor do JSON em número, aceitando texto com vírgula decimal."""
    if isinstance(valor, bool):
        raise ErroDeLeitura(f"{onde}: valor lógico ({str(valor).lower()}) não é uma medição numérica.")
    if isinstance(valor, (int, float)):
        numero = float(valor)
    elif isinstance(valor, str):
        texto = valor.strip().replace(" ", "")
        if texto.count(",") == 1 and "." not in texto:
            texto = texto.replace(",", ".")
        elif texto.count(",") >= 1 and texto.count(".") == 1 and texto.index(",") < texto.index("."):
            texto = texto.replace(",", "")
        elif texto.count(".") >= 1 and texto.count(",") == 1 and texto.index(".") < texto.index(","):
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = float(texto)
        except ValueError:
            raise ErroDeLeitura(f"{onde}: '{valor}' não é um número.") from None
    elif valor is None:
        raise ErroDeLeitura(f"{onde}: valor vazio (null).")
    else:
        raise ErroDeLeitura(f"{onde}: esperado um número, mas veio {_descrever(valor)}.")
    if math.isnan(numero) or math.isinf(numero):
        raise ErroDeLeitura(f"{onde}: valor inválido ({valor}).")
    return numero


def _numero_opcional(valor: Any, onde: str) -> Optional[float]:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    return _numero(valor, onde)


def _descrever(valor: Any) -> str:
    if isinstance(valor, list):
        return f"uma lista com {len(valor)} elementos"
    if isinstance(valor, dict):
        return "um objeto { }"
    return f"o valor {valor!r}"


def _eh_lista(valor: Any) -> bool:
    return isinstance(valor, (list, tuple))


def _eh_escalar(valor: Any) -> bool:
    return isinstance(valor, (int, float, str)) and not isinstance(valor, bool)


def _inteiro_proximo(x: float) -> bool:
    return abs(x - round(x)) < 1e-9


# ---------------------------------------------------------------------------
# Limites informados no próprio JSON (acompanhamento)
# ---------------------------------------------------------------------------
_CHAVES_SERIE = {
    "xbarra": {"x", "xbar", "xbarra", "media", "medias", "mean"},
    "r": {"r", "amplitude", "range"},
    "i": {"i", "individual", "individuais", "valoresindividuais"},
    "am": {"am", "mr", "amplitudemovel", "movingrange"},
    "p": {"p"}, "np": {"np"}, "c": {"c"}, "u": {"u"},
}


def _vazio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _trinca(origem: Dict[str, Any], onde: str) -> Optional[Dict[str, float]]:
    """Extrai {lsc, lc, lic} numéricos de um dicionário (nomes em português ou inglês)."""
    mapa = {normalizar(k): k for k in origem}
    resultado = {}
    for campo in ("lsc", "lc", "lic"):
        for alias in ALIASES[campo]:
            if alias in mapa:
                valor = origem[mapa[alias]]
                if not isinstance(valor, dict) and not _vazio(valor):
                    resultado[campo] = _numero(valor, f"{onde} → {mapa[alias]}")
                break
    return resultado or None


def _serie_da_chave(chave: Any) -> Optional[str]:
    """'X' -> 'xbarra'; 'MR' -> 'am'; 'p' -> 'p'..."""
    nome = normalizar(chave)
    for serie, nomes in _CHAVES_SERIE.items():
        if nome in nomes:
            return serie
    return None


def _distribuir_por_carta(valor: Dict[str, Any], campo: str, onde: str,
                          destino: Dict[str, Dict[str, float]]) -> None:
    """Limites agrupados por tipo de limite: "LSC": {"X": 4.97, "R": 0.04}."""
    for chave, numero in valor.items():
        if _vazio(numero):
            continue
        serie = _serie_da_chave(chave)
        if serie is None:
            raise ErroDeLeitura(f"{onde} → {chave}: carta não reconhecida (use X, R, I, AM, p, np, c ou u).")
        destino.setdefault(serie, {})[campo] = _numero(numero, f"{onde} → {chave}")


def _ler_limites(conteudo: Dict[str, Any], mapa: Dict[str, str], limites_brutos: Any,
                 usadas: set) -> Optional[Dict[str, Any]]:
    """Limites já calibrados informados no JSON. Formas aceitas:

    - "LSC": 4.97, "LC": 4.96, "LIC": 4.95                  (carta principal)
    - "LSC": {"X": 4.97, "R": 0.04}, "LIC": {...}, "LC": {...}   (por tipo de limite)
    - "Limites": {"X": {"LSC": ..., "LC": ...}, "R": {...}}       (por carta)
    - "Limites": {"LSC": {"X": ...}, ...}                           (por tipo, dentro de Limites)
    """
    resultado: Dict[str, Any] = {}
    por_serie: Dict[str, Dict[str, float]] = {}
    # Limites no nível principal do JSON: "LSC", "LC", "LIC".
    topo = {}
    for campo in ("lsc", "lc", "lic"):
        for alias in ALIASES[campo]:
            if alias in mapa:
                original = mapa[alias]
                usadas.add(original)
                valor = conteudo[original]
                if isinstance(valor, dict):
                    _distribuir_por_carta(valor, campo, original, por_serie)
                elif not _vazio(valor):
                    topo[campo] = _numero(valor, original)
                break
    if topo:
        resultado["primaria"] = topo
    if isinstance(limites_brutos, dict):
        mapa_lim = {normalizar(k): k for k in limites_brutos}
        if "parametros" in mapa_lim and isinstance(limites_brutos[mapa_lim["parametros"]], dict):
            # Arquivo de calibração deste programa embutido no JSON.
            resultado["calibracao"] = limites_brutos
        trinca = _trinca(limites_brutos, "Limites")
        if trinca:
            resultado["primaria"] = trinca
        for campo in ("lsc", "lc", "lic"):
            for alias in ALIASES[campo]:
                if alias in mapa_lim:
                    if isinstance(limites_brutos[mapa_lim[alias]], dict):
                        _distribuir_por_carta(limites_brutos[mapa_lim[alias]], campo,
                                              f"Limites → {mapa_lim[alias]}", por_serie)
                    break
        for chave_serie, nomes in _CHAVES_SERIE.items():
            for nome in nomes:
                if nome in mapa_lim and isinstance(limites_brutos[mapa_lim[nome]], dict):
                    sub = _trinca(limites_brutos[mapa_lim[nome]], f"Limites → {mapa_lim[nome]}")
                    if sub:
                        por_serie.setdefault(chave_serie, {}).update(sub)
                    break
    if por_serie:
        resultado["por_serie"] = por_serie
    return resultado or None


# ---------------------------------------------------------------------------
# Dados, conforme o tipo de carta
# ---------------------------------------------------------------------------
def _ler_dados(plano: Plano, dados: Any, n_bruto: Any, chave: str, chave_n: str) -> None:
    if not _eh_lista(dados):
        raise ErroDeLeitura(f"'{chave}' deve ser uma lista (por exemplo [[4.95, 4.96], [4.94, 4.97]]).")
    if len(dados) == 0:
        raise ErroDeLeitura(f"'{chave}' está vazio: não há medições para analisar.")
    n_informado = _ler_n(n_bruto, chave_n, len(dados))
    familia = FAMILIA[plano.tipo]
    if familia == "variaveis":
        _ler_variaveis(plano, dados, n_informado, chave)
    elif familia == "individuais":
        _ler_individuais(plano, dados, chave)
    elif familia == "fracao":
        _ler_defeituosos(plano, dados, n_informado, chave, chave_n)
    elif plano.tipo == "C":
        _ler_contagens(plano, dados, chave)
    else:
        _ler_defeitos_por_unidade(plano, dados, n_informado, chave, chave_n)


def _ler_n(n_bruto: Any, chave_n: str, quantidade: int) -> Optional[List[float]]:
    """Tamanho de amostra informado à parte (número único ou lista)."""
    if n_bruto is None or (isinstance(n_bruto, str) and not n_bruto.strip()):
        return None
    if _eh_lista(n_bruto):
        if len(n_bruto) != quantidade:
            raise ErroDeLeitura(
                f"'{chave_n}' tem {len(n_bruto)} tamanhos, mas há {quantidade} amostras em Data."
            )
        valores = [_numero(v, f"{chave_n}, posição {i + 1}") for i, v in enumerate(n_bruto)]
    else:
        valores = [_numero(n_bruto, chave_n)] * quantidade
    if any(v <= 0 for v in valores):
        raise ErroDeLeitura(f"'{chave_n}' deve ser maior que zero.")
    return valores


def _numeros_do_elemento(elemento: Any, i: int, chave: str) -> List[float]:
    """Converte o i-ésimo elemento de Data (lista, número ou objeto) em lista de números."""
    if _eh_escalar(elemento):
        return [_numero(elemento, f"{chave}, amostra {i + 1}")]
    if isinstance(elemento, dict):
        mapa = {normalizar(k): k for k in elemento}
        for nome in ("valores", "values", "amostra", "medicoes", "dados", "data", "sample"):
            if nome in mapa and _eh_lista(elemento[mapa[nome]]):
                elemento = elemento[mapa[nome]]
                break
        else:
            raise ErroDeLeitura(f"{chave}, amostra {i + 1}: objeto sem lista de valores reconhecível.")
    if not _eh_lista(elemento):
        raise ErroDeLeitura(f"{chave}, amostra {i + 1}: esperado uma lista de medições, mas veio {_descrever(elemento)}.")
    if len(elemento) == 0:
        raise ErroDeLeitura(f"{chave}, amostra {i + 1}: a lista está vazia.")
    return [_numero(v, f"{chave}, amostra {i + 1}, valor {j + 1}") for j, v in enumerate(elemento)]


def _ler_variaveis(plano: Plano, dados: Sequence[Any], n_informado: Optional[List[float]], chave: str) -> None:
    if all(_eh_escalar(v) for v in dados):
        valores = [_numero(v, f"{chave}, valor {i + 1}") for i, v in enumerate(dados)]
        n = int(n_informado[0]) if n_informado and len(set(n_informado)) == 1 else 0
        if n >= 2:
            sobra = len(valores) % n
            if sobra:
                plano.avisos.append(f"Os últimos {sobra} valores não completam um subgrupo de {n} e foram ignorados.")
                valores = valores[: len(valores) - sobra]
            subgrupos = [valores[i:i + n] for i in range(0, len(valores), n)]
            plano.formato_dados = f"lista simples agrupada em subgrupos de {n} (campo n)"
        else:
            _virar_individuais(plano, valores, "'Data' é uma lista simples de valores")
            return
    else:
        subgrupos = [_numeros_do_elemento(e, i, chave) for i, e in enumerate(dados)]
        plano.formato_dados = "lista de subgrupos"

    tamanhos = [len(s) for s in subgrupos]
    if all(t == 1 for t in tamanhos):
        _virar_individuais(plano, [s[0] for s in subgrupos], "todos os subgrupos têm um único valor")
        return
    unitarios = [i + 1 for i, t in enumerate(tamanhos) if t == 1]
    if unitarios:
        quais = (f"O subgrupo {unitarios[0]} tem" if len(unitarios) == 1
                 else f"Os subgrupos {', '.join(map(str, unitarios))} têm")
        raise ErroDeLeitura(
            f"{quais} só 1 valor. A carta X-barra e R precisa de pelo menos 2 valores por "
            "subgrupo (amplitude)."
        )
    if len(subgrupos) < 2:
        raise ErroDeLeitura("É preciso pelo menos 2 subgrupos para calcular limites de controle.")
    if len(set(tamanhos)) > 1:
        plano.avisos.append(
            f"Os subgrupos têm tamanhos diferentes (n de {min(tamanhos)} a {max(tamanhos)}). "
            "Os limites são calculados para cada subgrupo a partir do desvio-padrão estimado."
        )
    if max(tamanhos) > 10:
        plano.avisos.append(
            "Subgrupos com mais de 10 valores: o Montgomery recomenda a carta S nesse caso; "
            "a análise segue com a amplitude R."
        )
    plano.subgrupos = subgrupos


def _virar_individuais(plano: Plano, valores: List[float], motivo: str) -> None:
    novo = "MR" if plano.tipo == "R" else "IMR"
    plano.avisos.append(
        f"{motivo[0].upper() + motivo[1:]}: não há amplitude dentro do subgrupo, então a análise usa a carta "
        f"de valores individuais e amplitude móvel ({'AM' if novo == 'MR' else 'I-AM'}) no lugar de "
        f"'{plano.tipo_original}'."
    )
    plano.tipo = novo
    _validar_individuais(plano, valores)
    plano.formato_dados = "valores individuais"


def _ler_individuais(plano: Plano, dados: Sequence[Any], chave: str) -> None:
    valores: List[float] = []
    agrupados = False
    for i, elemento in enumerate(dados):
        numeros = _numeros_do_elemento(elemento, i, chave)
        agrupados = agrupados or len(numeros) > 1
        valores.extend(numeros)
    if agrupados:
        plano.avisos.append(
            "Há amostras com mais de um valor; para a carta de valores individuais elas foram "
            "lidas em sequência, na ordem do arquivo."
        )
    _validar_individuais(plano, valores)
    plano.formato_dados = "valores individuais"


def _validar_individuais(plano: Plano, valores: List[float]) -> None:
    if len(valores) < 3:
        raise ErroDeLeitura("A carta de valores individuais precisa de pelo menos 3 valores.")
    plano.valores = valores
    plano.subgrupos = None


def _ler_defeituosos(plano: Plano, dados: Sequence[Any], n_informado: Optional[List[float]],
                     chave: str, chave_n: str) -> None:
    """Carta p / np. Formatos aceitos para cada amostra:
       - [0, 1, 0, ...]   itens inspecionados (1 = defeituoso): D = soma, n = quantidade
       - [D, n]           par (defeituosos, tamanho da amostra)
       - D (ou [D])       com o tamanho da amostra no campo "n"
       - fração p (ou [p]) com o tamanho da amostra no campo "n"
       - {"defeituosos": D, "n": n}
    """
    defeituosos: List[float] = []
    tamanhos: List[float] = []
    if all(isinstance(e, dict) for e in dados):
        for i, e in enumerate(dados):
            mapa = {normalizar(k): k for k in e}
            d = next((e[mapa[k]] for k in ("defeituosos", "defeituoso", "d", "defectives", "defeitos", "naoconformes") if k in mapa), None)
            n = next((e[mapa[k]] for k in ("n", "tamanho", "tamanhoamostra", "size", "inspecionados") if k in mapa), None)
            if d is None or n is None:
                raise ErroDeLeitura(f"{chave}, amostra {i + 1}: informe 'defeituosos' e 'n'.")
            defeituosos.append(_numero(d, f"{chave}, amostra {i + 1}, defeituosos"))
            tamanhos.append(_numero(n, f"{chave}, amostra {i + 1}, n"))
        plano.formato_dados = "objetos {defeituosos, n}"
    else:
        linhas = [_numeros_do_elemento(e, i, chave) for i, e in enumerate(dados)]
        todos = [v for linha in linhas for v in linha]
        binarios = all(v in (0.0, 1.0) for v in todos)
        if all(len(linha) == 1 for linha in linhas):
            if n_informado is None:
                raise ErroDeLeitura(
                    f"Cada amostra tem um único valor. Para a carta {plano.codigo_tipo}, informe o "
                    "tamanho da amostra no campo 'n' (ou use pares [defeituosos, n])."
                )
            valores = [linha[0] for linha in linhas]
            if all(_inteiro_proximo(v) for v in valores) and not (all(0 <= v <= 1 for v in valores) and any(0 < v < 1 for v in valores)):
                defeituosos = valores
                plano.formato_dados = f"número de defeituosos por amostra, com n no campo '{chave_n}'"
            else:
                defeituosos = []
                for i, (p, n) in enumerate(zip(valores, n_informado)):
                    if not 0 <= p <= 1:
                        raise ErroDeLeitura(f"{chave}, amostra {i + 1}: fração {p} fora do intervalo [0, 1].")
                    d = p * n
                    if not _inteiro_proximo(d):
                        plano.avisos.append(f"Amostra {i + 1}: p·n = {d:.3f} não é inteiro; arredondado para {round(d)}.")
                    defeituosos.append(float(round(d)))
                plano.formato_dados = f"fração defeituosa por amostra, com n no campo '{chave_n}'"
            tamanhos = list(n_informado)
        elif binarios:
            # Só zeros e uns: cada valor é um item inspecionado (1 = defeituoso).
            defeituosos = [sum(linha) for linha in linhas]
            tamanhos = [float(len(linha)) for linha in linhas]
            plano.formato_dados = "itens inspecionados por amostra (1 = defeituoso, 0 = bom)"
        elif all(len(linha) == 2 for linha in linhas):
            defeituosos = [linha[0] for linha in linhas]
            tamanhos = [linha[1] for linha in linhas]
            plano.formato_dados = "pares [defeituosos, tamanho da amostra]"
        else:
            raise ErroDeLeitura(
                f"Não consegui interpretar os dados da carta {plano.codigo_tipo}. Formatos aceitos "
                "por amostra: [D, n] (defeituosos e tamanho), [0, 1, 0, ...] (itens bons/defeituosos) "
                "ou um número D com o tamanho da amostra no campo 'n'."
            )
    for i, (d, n) in enumerate(zip(defeituosos, tamanhos)):
        if n <= 0 or not _inteiro_proximo(n):
            raise ErroDeLeitura(f"{chave}, amostra {i + 1}: tamanho da amostra inválido ({n}).")
        if d < 0 or d > n or not _inteiro_proximo(d):
            raise ErroDeLeitura(
                f"{chave}, amostra {i + 1}: número de defeituosos inválido ({d}) para n = {int(n)}."
            )
    if len(defeituosos) < 2:
        raise ErroDeLeitura("É preciso pelo menos 2 amostras para calcular limites de controle.")
    if plano.tipo == "NP" and len(set(tamanhos)) > 1:
        plano.avisos.append("A carta np exige tamanho de amostra constante; como n varia, a análise usa a carta p.")
        plano.tipo = "P"
    plano.defeituosos = [float(round(d)) for d in defeituosos]
    plano.tamanhos = [float(round(n)) for n in tamanhos]


def _ler_contagens(plano: Plano, dados: Sequence[Any], chave: str) -> None:
    """Carta c: um número de defeitos por amostra (unidade de inspeção constante)."""
    contagens: List[float] = []
    somadas = False
    for i, elemento in enumerate(dados):
        if isinstance(elemento, dict):
            mapa = {normalizar(k): k for k in elemento}
            valor = next((elemento[mapa[k]] for k in ("defeitos", "c", "contagem", "defects", "count") if k in mapa), None)
            if valor is None:
                raise ErroDeLeitura(f"{chave}, amostra {i + 1}: informe 'defeitos'.")
            numeros = [_numero(valor, f"{chave}, amostra {i + 1}")]
        else:
            numeros = _numeros_do_elemento(elemento, i, chave)
        somadas = somadas or len(numeros) > 1
        contagens.append(sum(numeros))
    if somadas:
        plano.avisos.append(
            "Há amostras com vários valores; na carta c cada amostra é uma unidade de inspeção, "
            "então os defeitos de cada amostra foram somados."
        )
    for i, c in enumerate(contagens):
        if c < 0:
            raise ErroDeLeitura(f"{chave}, amostra {i + 1}: número de defeitos negativo ({c}).")
    if not all(_inteiro_proximo(c) for c in contagens):
        plano.avisos.append("Há contagens de defeitos não inteiras; a análise segue com os valores informados.")
    if len(contagens) < 2:
        raise ErroDeLeitura("É preciso pelo menos 2 amostras para calcular limites de controle.")
    plano.contagens = contagens
    plano.formato_dados = "número de defeitos por amostra" + (" (soma dos valores de cada amostra)" if somadas else "")


def _ler_defeitos_por_unidade(plano: Plano, dados: Sequence[Any], n_informado: Optional[List[float]],
                              chave: str, chave_n: str) -> None:
    """Carta u. Formatos aceitos para cada amostra:
       - [d, unidades]    par (defeitos, número de unidades inspecionadas)
       - d (ou [d])       com o número de unidades no campo "n"
       - [d1, d2, ...]    defeitos em cada unidade inspecionada (unidades = quantidade)
       - {"defeitos": d, "unidades": k}
    """
    defeitos: List[float] = []
    unidades: List[float] = []
    if all(isinstance(e, dict) for e in dados):
        for i, e in enumerate(dados):
            mapa = {normalizar(k): k for k in e}
            d = next((e[mapa[k]] for k in ("defeitos", "d", "c", "defects") if k in mapa), None)
            u = next((e[mapa[k]] for k in ("unidades", "n", "units", "tamanho") if k in mapa), None)
            if d is None or u is None:
                raise ErroDeLeitura(f"{chave}, amostra {i + 1}: informe 'defeitos' e 'unidades'.")
            defeitos.append(_numero(d, f"{chave}, amostra {i + 1}, defeitos"))
            unidades.append(_numero(u, f"{chave}, amostra {i + 1}, unidades"))
        plano.formato_dados = "objetos {defeitos, unidades}"
    else:
        linhas = [_numeros_do_elemento(e, i, chave) for i, e in enumerate(dados)]
        if all(len(l) == 1 for l in linhas):
            if n_informado is None:
                raise ErroDeLeitura(
                    "Cada amostra tem um único valor. Para a carta U, informe o número de unidades "
                    "inspecionadas no campo 'n' (ou use pares [defeitos, unidades])."
                )
            defeitos = [l[0] for l in linhas]
            unidades = list(n_informado)
            plano.formato_dados = f"defeitos por amostra, com unidades no campo '{chave_n}'"
        elif all(len(l) == 2 for l in linhas) and n_informado is None:
            defeitos = [l[0] for l in linhas]
            unidades = [l[1] for l in linhas]
            plano.formato_dados = "pares [defeitos, unidades inspecionadas]"
            plano.avisos.append("Cada amostra foi lida como o par [defeitos, unidades inspecionadas].")
        else:
            defeitos = [sum(l) for l in linhas]
            unidades = [float(len(l)) for l in linhas]
            plano.formato_dados = "defeitos de cada unidade inspecionada"
    for i, (d, u) in enumerate(zip(defeitos, unidades)):
        if u <= 0:
            raise ErroDeLeitura(f"{chave}, amostra {i + 1}: número de unidades inválido ({u}).")
        if d < 0:
            raise ErroDeLeitura(f"{chave}, amostra {i + 1}: número de defeitos negativo ({d}).")
    if len(defeitos) < 2:
        raise ErroDeLeitura("É preciso pelo menos 2 amostras para calcular limites de controle.")
    plano.contagens = defeitos
    plano.tamanhos = unidades
