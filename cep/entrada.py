"""Módulo de entrada de medições.

Três fontes possíveis:
  - teclado: digitar os valores (um subgrupo ou amostra por linha);
  - arquivo CSV/TXT: uma amostra por linha (vírgula decimal ou ponto);
  - porta serial (Arduino, ESP32...): a placa envia um número por linha.

Em todos os casos o resultado é um JSON no mesmo formato usado em sala
(Unit, Measured_at, Created_by, Type, Goal, LSE, LIE, Data), salvo na pasta
"entradas/" e pronto para ser processado pelo programa. A leitura serial é
a ponte para os projetos de CEP remoto da disciplina.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import config
from .leitura import limpar_caminho

Perguntar = Callable[[str], str]
Mostrar = Callable[[str], None]

TIPOS_ENTRADA = [
    ("X", "X-barra e R – medições em subgrupos (n >= 2)"),
    ("R", "R – amplitude dos subgrupos"),
    ("IMR", "I-AM – uma medição por vez (valores individuais)"),
    ("P", "p – itens defeituosos em amostras (n pode variar)"),
    ("NP", "np – itens defeituosos em amostras de tamanho fixo"),
    ("C", "c – número de defeitos por unidade de inspeção"),
    ("U", "u – defeitos por unidade, número de unidades variável"),
]

_NUMERO = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")


class EntradaCancelada(Exception):
    """O usuário desistiu do registro de medições."""


def interpretar_linha(texto: str) -> List[float]:
    """'4,95 4,96; 4,97' -> [4.95, 4.96, 4.97]. Aceita vírgula ou ponto como decimal.

    Separadores aceitos: espaço, tabulação e ponto e vírgula. Uma linha como
    '4.95,4.96' (decimal com ponto) também é aceita, com a vírgula separando.
    """
    texto = texto.strip()
    if not texto:
        return []
    if re.search(r"[;\s]", texto):
        partes = re.split(r"[;\s]+", texto)
    elif "," in texto and "." in texto:
        partes = texto.split(",")
    else:
        partes = [texto]
    valores = []
    for parte in partes:
        if not parte:
            continue
        convertido = parte.replace(",", ".")
        try:
            numero = float(convertido)
        except ValueError:
            raise ValueError(f"'{parte}' não é um número") from None
        if math.isnan(numero) or math.isinf(numero):
            raise ValueError(f"'{parte}' não é um número válido")
        valores.append(numero)
    return valores


def numeros_em_texto(texto: str) -> List[float]:
    """Extrai números de uma linha qualquer, por exemplo 'T=23,5 C' -> [23.5]."""
    return [float(n.replace(",", ".")) for n in _NUMERO.findall(texto)]


def agrupar(valores: Sequence[float], n: int) -> List[List[float]]:
    return [list(valores[i:i + n]) for i in range(0, len(valores) - len(valores) % n, n)]


def montar_json(tipo: str, objetivo: str, dados: List[Any], unidade: str = "", lse: Optional[float] = None,
                lie: Optional[float] = None, criado_por: str = "", rotulo: str = "",
                medido_em: Optional[str] = None, n: Optional[float] = None) -> Dict[str, Any]:
    """Monta o dicionário no formato usado em sala."""
    conteudo: Dict[str, Any] = {
        "Unit": unidade,
        "Measured_at": medido_em or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Created_by": criado_por,
        "Type": tipo,
        "Goal": "Calibrar" if objetivo.upper().startswith("C") else "Acompanhar",
        "LSE": lse,
        "LIE": lie,
    }
    if rotulo:
        conteudo["Label"] = rotulo
    if n is not None:
        conteudo["n"] = int(n) if float(n).is_integer() else n
    conteudo["Data"] = dados
    return conteudo


def salvar_json(conteudo: Dict[str, Any], pasta: Path = config.PASTA_ENTRADAS, nome: Optional[str] = None) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if not nome:
        nome = f"medicoes_{conteudo['Type']}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    if not nome.lower().endswith(".json"):
        nome += ".json"
    caminho = pasta / nome
    contador = 1
    while caminho.exists():
        contador += 1
        caminho = pasta / f"{Path(nome).stem}_{contador}.json"
    caminho.write_text(_json_compacto(conteudo), encoding="utf-8")
    return caminho


def _json_compacto(conteudo: Dict[str, Any]) -> str:
    """JSON legível, com cada subgrupo em uma linha."""
    linhas = ["{"]
    itens = list(conteudo.items())
    for i, (chave, valor) in enumerate(itens):
        fim = "," if i < len(itens) - 1 else ""
        if chave == "Data" and isinstance(valor, list):
            corpo = ",\n".join("    " + json.dumps(v, ensure_ascii=False) for v in valor)
            linhas.append(f'  "Data": [\n{corpo}\n  ]{fim}')
        else:
            linhas.append(f"  {json.dumps(chave, ensure_ascii=False)}: {json.dumps(valor, ensure_ascii=False)}{fim}")
    linhas.append("}")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------------
# Fontes de dados
# ---------------------------------------------------------------------------
def ler_csv(caminho) -> List[List[float]]:
    """Cada linha do arquivo vira uma lista de números; linhas de cabeçalho são ignoradas."""
    caminho = limpar_caminho(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
    linhas: List[List[float]] = []
    for numero, texto in enumerate(caminho.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        texto = texto.strip()
        if not texto or texto.startswith("#"):
            continue
        try:
            valores = interpretar_linha(texto)
        except ValueError:
            if not linhas:      # cabeçalho
                continue
            raise ValueError(f"Linha {numero} do arquivo: não consegui ler números em '{texto}'.") from None
        if valores:
            linhas.append(valores)
    if not linhas:
        raise ValueError("O arquivo não tem números.")
    return linhas


def listar_portas_seriais() -> List[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [f"{p.device} – {p.description}" for p in list_ports.comports()]


def ler_serial(porta: str, quantidade: int, baudrate: int = 9600, espera_maxima: float = 30.0,
               mostrar: Mostrar = print, conexao=None) -> List[float]:
    """Lê 'quantidade' números enviados pela placa (um ou mais por linha).

    Para antes se a placa ficar 'espera_maxima' segundos sem enviar nada ou se
    o usuário apertar Ctrl+C. 'conexao' permite testar sem placa (objeto com readline()).
    """
    fechar = False
    if conexao is None:
        try:
            import serial
        except ImportError:
            raise RuntimeError("Para ler da porta serial, instale o pyserial: pip install pyserial") from None
        conexao = serial.Serial(porta, baudrate, timeout=1)
        fechar = True
    valores: List[float] = []
    ultimo_dado = time.monotonic()
    try:
        while len(valores) < quantidade:
            bruto = conexao.readline()
            linha = bruto.decode("utf-8", errors="ignore").strip() if isinstance(bruto, bytes) else str(bruto).strip()
            if not linha:
                if time.monotonic() - ultimo_dado > espera_maxima:
                    mostrar(f"Nenhum dado há {espera_maxima:.0f} s; leitura encerrada.")
                    break
                continue
            ultimo_dado = time.monotonic()
            numeros = numeros_em_texto(linha)
            if not numeros:
                continue
            valores.extend(numeros[: quantidade - len(valores)])
            mostrar(f"  {len(valores)}/{quantidade}: {linha}")
    except KeyboardInterrupt:
        mostrar("Leitura interrompida pelo usuário.")
    finally:
        if fechar:
            conexao.close()
    return valores


# ---------------------------------------------------------------------------
# Registro interativo
# ---------------------------------------------------------------------------
def _perguntar_texto(perguntar: Perguntar, texto: str, padrao: str = "") -> str:
    resposta = perguntar(texto + (f" [{padrao}]" if padrao else "") + ": ").strip()
    if resposta.lower() in ("cancelar", "sair"):
        raise EntradaCancelada()
    return resposta or padrao


def _perguntar_numero(perguntar: Perguntar, mostrar: Mostrar, texto: str, opcional: bool = False,
                      inteiro: bool = False, minimo: Optional[float] = None) -> Optional[float]:
    while True:
        resposta = _perguntar_texto(perguntar, texto + (" (Enter para pular)" if opcional else ""))
        if not resposta:
            if opcional:
                return None
            mostrar("  Informe um valor.")
            continue
        try:
            valores = interpretar_linha(resposta)
            if len(valores) != 1:
                raise ValueError("informe um único número")
            valor = valores[0]
        except ValueError as erro:
            mostrar(f"  Valor inválido: {erro}.")
            continue
        if inteiro and not float(valor).is_integer():
            mostrar("  Informe um número inteiro.")
            continue
        if minimo is not None and valor < minimo:
            mostrar(f"  O valor deve ser pelo menos {minimo:g}.")
            continue
        return int(valor) if inteiro else valor


def _escolher(perguntar: Perguntar, mostrar: Mostrar, titulo: str, opcoes: Sequence[tuple]) -> str:
    mostrar(titulo)
    for i, (_codigo, descricao) in enumerate(opcoes, 1):
        mostrar(f"  {i}) {descricao}")
    while True:
        resposta = _perguntar_texto(perguntar, "Opção")
        if resposta.isdigit() and 1 <= int(resposta) <= len(opcoes):
            return opcoes[int(resposta) - 1][0]
        for codigo, _ in opcoes:
            if resposta.upper() == str(codigo).upper():
                return codigo
        mostrar("  Opção inválida.")


def _linhas_teclado(perguntar: Perguntar, mostrar: Mostrar, instrucao: str) -> List[List[float]]:
    mostrar(instrucao)
    mostrar("  (linha vazia termina; 'desfazer' apaga a última linha; 'cancelar' desiste)")
    linhas: List[List[float]] = []
    while True:
        resposta = perguntar(f"  {len(linhas) + 1}> ").strip()
        if not resposta:
            return linhas
        if resposta.lower() in ("cancelar", "sair"):
            raise EntradaCancelada()
        if resposta.lower() == "desfazer":
            if linhas:
                mostrar(f"  Linha {len(linhas)} apagada: {linhas.pop()}")
            continue
        try:
            valores = interpretar_linha(resposta)
        except ValueError as erro:
            mostrar(f"  Linha ignorada: {erro}.")
            continue
        linhas.append(valores)


def registrar_medicoes(perguntar: Perguntar = input, mostrar: Mostrar = print,
                       pasta: Path = config.PASTA_ENTRADAS) -> Optional[Path]:
    """Conduz o registro de medições e salva o JSON. Devolve o caminho ou None."""
    try:
        mostrar("\n--- Registro de medições (digite 'cancelar' a qualquer momento) ---")
        tipo = _escolher(perguntar, mostrar, "Tipo de carta:", TIPOS_ENTRADA)
        objetivo = _escolher(perguntar, mostrar, "Objetivo:", [("Calibrar", "Calibrar (estabelecer limites)"),
                                                                ("Acompanhar", "Acompanhar (usar limites já calibrados)")])
        rotulo = _perguntar_texto(perguntar, "Descrição do processo/característica medida")
        unidade = _perguntar_texto(perguntar, "Unidade de medida (ex.: mm, V, °C)") if tipo in ("X", "R", "IMR") else ""
        criado_por = _perguntar_texto(perguntar, "Responsável pela medição")
        lse = _perguntar_numero(perguntar, mostrar, "LSE – limite superior de especificação", opcional=True)
        lie = _perguntar_numero(perguntar, mostrar, "LIE – limite inferior de especificação", opcional=True)
        fonte = _escolher(perguntar, mostrar, "De onde vêm as medições?",
                          [("teclado", "Digitar agora"), ("arquivo", "Arquivo CSV/TXT (uma amostra por linha)"),
                           ("serial", "Porta serial (Arduino/ESP32 enviando um número por linha)")])
        dados, n_campo = _coletar(tipo, fonte, perguntar, mostrar)
        if not dados:
            mostrar("Nenhuma medição registrada; nada foi salvo.")
            return None
        conteudo = montar_json(tipo, objetivo, dados, unidade, lse, lie, criado_por, rotulo, n=n_campo)
        mostrar(f"\n{len(dados)} amostra(s) registrada(s).")
        nome = _perguntar_texto(perguntar, "Nome do arquivo (Enter para nome automático)")
        caminho = salvar_json(conteudo, pasta, nome or None)
        mostrar(f"Medições salvas em: {caminho}")
        return caminho
    except EntradaCancelada:
        mostrar("Registro cancelado.")
        return None


def _coletar(tipo: str, fonte: str, perguntar: Perguntar, mostrar: Mostrar):
    """Devolve (Data, n) conforme o tipo de carta e a fonte escolhida."""
    if tipo in ("X", "R"):
        n = int(_perguntar_numero(perguntar, mostrar, "Tamanho do subgrupo (n)", inteiro=True, minimo=2))
        if fonte == "teclado":
            linhas = _linhas_teclado(perguntar, mostrar, f"Digite as medições ({n} por subgrupo; pode ser uma por "
                                                         "linha ou o subgrupo inteiro numa linha):")
            valores = [v for l in linhas for v in l]
        elif fonte == "arquivo":
            linhas = ler_csv(_perguntar_texto(perguntar, "Caminho do arquivo"))
            if all(len(l) == n for l in linhas):
                return linhas, None
            valores = [v for l in linhas for v in l]
        else:
            m = int(_perguntar_numero(perguntar, mostrar, "Quantos subgrupos ler", inteiro=True, minimo=2))
            valores = _ler_da_placa(perguntar, mostrar, m * n)
        sobra = len(valores) % n
        if sobra:
            mostrar(f"  Atenção: {sobra} valor(es) no fim não completam um subgrupo e foram descartados.")
        return agrupar(valores, n), None
    if tipo == "IMR":
        if fonte == "teclado":
            linhas = _linhas_teclado(perguntar, mostrar, "Digite as medições individuais (uma ou mais por linha):")
        elif fonte == "arquivo":
            linhas = ler_csv(_perguntar_texto(perguntar, "Caminho do arquivo"))
        else:
            quantidade = int(_perguntar_numero(perguntar, mostrar, "Quantas medições ler", inteiro=True, minimo=3))
            linhas = [[v] for v in _ler_da_placa(perguntar, mostrar, quantidade)]
        return [[v] for l in linhas for v in l], None
    if tipo in ("P", "NP"):
        n = _perguntar_numero(perguntar, mostrar, "Tamanho da amostra n, se for sempre o mesmo", opcional=True,
                              inteiro=True, minimo=1)
        if n:
            instrucao = "Digite o número de itens defeituosos de cada amostra (um por linha):"
        else:
            instrucao = "Digite, para cada amostra, 'defeituosos tamanho' (ex.: 3 100):"
        linhas = _linhas_origem(fonte, perguntar, mostrar, instrucao, 1 if n else 2)
        if n:
            return [[l[0]] for l in linhas if l], n
        validas = [l[:2] for l in linhas if len(l) >= 2]
        if len(validas) < len(linhas):
            mostrar("  Linhas sem o par 'defeituosos tamanho' foram ignoradas.")
        return validas, None
    if tipo == "C":
        linhas = _linhas_origem(fonte, perguntar, mostrar, "Digite o número de defeitos de cada amostra (um por linha):", 1)
        return [[sum(l)] for l in linhas if l], None
    linhas = _linhas_origem(fonte, perguntar, mostrar, "Digite, para cada amostra, 'defeitos unidades' (ex.: 4 2,5):", 2)
    validas = [l[:2] for l in linhas if len(l) >= 2]
    if len(validas) < len(linhas):
        mostrar("  Linhas sem o par 'defeitos unidades' foram ignoradas.")
    return validas, None


def _linhas_origem(fonte: str, perguntar: Perguntar, mostrar: Mostrar, instrucao: str, por_amostra: int):
    if fonte == "teclado":
        return _linhas_teclado(perguntar, mostrar, instrucao)
    if fonte == "arquivo":
        return ler_csv(_perguntar_texto(perguntar, "Caminho do arquivo"))
    m = int(_perguntar_numero(perguntar, mostrar, "Quantas amostras ler", inteiro=True, minimo=2))
    valores = _ler_da_placa(perguntar, mostrar, m * por_amostra)
    return agrupar(valores, por_amostra)


def _ler_da_placa(perguntar: Perguntar, mostrar: Mostrar, quantidade: int) -> List[float]:
    portas = listar_portas_seriais()
    if portas:
        mostrar("Portas encontradas:")
        for p in portas:
            mostrar(f"  {p}")
    porta = _perguntar_texto(perguntar, "Porta serial (ex.: COM3 no Windows, /dev/ttyUSB0 no Linux)")
    baud = int(_perguntar_numero(perguntar, mostrar, "Velocidade (baud rate), ex.: 9600 ou 115200", inteiro=True,
                                 minimo=300))
    mostrar(f"Lendo {quantidade} valores de {porta}... (Ctrl+C para parar)")
    return ler_serial(porta, quantidade, baud, mostrar=mostrar)
