"""Salvar e carregar calibrações (limites calibrados) em JSON.

A calibração guarda os PARÂMETROS estimados do processo (linha central,
desvio-padrão, R̄, AM̄, p̄, c̄ ou ū). Com eles, o acompanhamento reconstrói os
limites para os novos dados, inclusive quando o tamanho do subgrupo ou da
amostra muda. Os limites calculados também ficam gravados, para consulta.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .cartas import Carta
from .constantes import fatores
from .leitura import FAMILIA, ErroDeLeitura, Plano, limpar_caminho, normalizar
from .util import slug

FORMATO = "cep-calibracao/1"


def pasta_calibracoes(pasta_saida: Path) -> Path:
    pasta = Path(pasta_saida) / config.PASTA_CALIBRACOES
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def montar_registro(resultado) -> Dict[str, Any]:
    plano: Plano = resultado.plano
    limites = {}
    for serie in resultado.series_finais:
        r = serie.resumo()
        if r["variavel"]:
            limites[serie.nome] = {"LIC": list(serie.lic), "LC": list(serie.lc), "LSC": list(serie.lsc),
                                   "obs": "limites variam com o tamanho de cada amostra"}
        else:
            limites[serie.nome] = {"LIC": r["lic"], "LC": r["lc"], "LSC": r["lsc"]}
    params = {k: v for k, v in resultado.params.items() if v is not None}
    return {
        "Formato": FORMATO,
        "Type": plano.codigo_tipo,
        "Tipo_normalizado": plano.tipo,
        "Familia": plano.familia,
        "Unit": plano.unidade,
        "Label": plano.rotulo,
        "Arquivo_origem": plano.arquivo,
        "Measured_at": plano.medido_em,
        "Created_by": plano.criado_por,
        "Calibrado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "LSE": plano.lse,
        "LIE": plano.lie,
        "Parametros": params,
        "Limites": limites,
        "Pontos_usados": [i + 1 for i in resultado.usados],
        "Pontos_removidos": [i + 1 for i in resultado.removidos],
        "Status": resultado.status,
        "Ressalvas": list(resultado.ressalvas),
    }


def salvar(resultado, pasta_saida: Path) -> Path:
    registro = montar_registro(resultado)
    plano: Plano = resultado.plano
    momento = datetime.now().strftime("%Y%m%d-%H%M%S")
    nome = f"calibracao_{plano.codigo_tipo}_{slug(plano.rotulo, 30)}_{momento}.json"
    caminho = pasta_calibracoes(pasta_saida) / nome
    contador = 1
    while caminho.exists():
        contador += 1
        caminho = caminho.with_name(f"{caminho.stem}_{contador}.json")
    caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def carregar(caminho) -> Dict[str, Any]:
    caminho = limpar_caminho(caminho)
    if not caminho.exists():
        raise ErroDeLeitura(f"Arquivo de calibração não encontrado: {caminho}")
    try:
        registro = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as erro:
        raise ErroDeLeitura(f"Arquivo de calibração inválido ({caminho.name}): {erro.msg}") from None
    if not isinstance(registro, dict) or not isinstance(registro.get("Parametros"), dict):
        raise ErroDeLeitura(f"{caminho.name} não é um arquivo de calibração gerado por este programa.")
    registro["_arquivo"] = str(caminho)
    return registro


def compativel(registro: Dict[str, Any], plano: Plano) -> bool:
    familia = registro.get("Familia") or FAMILIA.get(registro.get("Tipo_normalizado", ""), "")
    return familia == plano.familia


def listar(pasta_saida: Path, plano: Optional[Plano] = None) -> List[Tuple[Path, Dict[str, Any]]]:
    """Calibrações salvas; se houver plano, só as compatíveis, mais relevantes primeiro."""
    pasta = Path(pasta_saida) / config.PASTA_CALIBRACOES
    if not pasta.exists():
        return []
    itens = []
    for arquivo in pasta.glob("*.json"):
        try:
            registro = carregar(arquivo)
        except ErroDeLeitura:
            continue
        if plano is not None and not compativel(registro, plano):
            continue
        itens.append((arquivo, registro))

    def prioridade(item):
        arquivo, registro = item
        mesmo_tipo = plano is not None and registro.get("Tipo_normalizado") == plano.tipo
        mesma_unidade = plano is not None and registro.get("Unit", "") == plano.unidade
        mesmo_rotulo = plano is not None and registro.get("Label", "") == plano.rotulo
        return (mesmo_rotulo, mesmo_tipo, mesma_unidade, arquivo.stat().st_mtime)
    itens.sort(key=prioridade, reverse=True)
    return itens


def distancia_ao_centro(carta: Carta, params: Dict[str, Any]) -> float:
    """Distância entre o nível médio dos dados e a linha central calibrada, em desvios-padrão.

    Serve para perceber quando uma calibração é de outro processo (por exemplo,
    outra peça com a mesma unidade): distâncias muito grandes indicam isso.
    """
    centro = float(params.get("centro") or 0.0)
    if carta.familia in ("variaveis", "individuais"):
        valores = carta.valores_individuais()
        media = sum(valores) / len(valores)
        sigma = float(params.get("sigma") or 0.0)
        if sigma <= 0:
            return 0.0 if abs(media - centro) < 1e-12 else math.inf
        return abs(media - centro) / sigma
    if carta.familia == "fracao":
        nivel = sum(carta.d) / sum(carta.n)
        n_medio = sum(carta.n) / len(carta.n)
        sigma = math.sqrt(max(centro * (1 - centro), 0.0) / n_medio)
    elif carta.familia == "contagem":
        nivel = sum(carta.c) / len(carta.c)
        sigma = math.sqrt(max(centro, 0.0))
    else:
        nivel = sum(carta.d) / sum(carta.unidades)
        sigma = math.sqrt(max(centro, 0.0) / (sum(carta.unidades) / len(carta.unidades)))
    if sigma <= 0:
        return 0.0 if abs(nivel - centro) < 1e-12 else math.inf
    return abs(nivel - centro) / sigma


DISTANCIA_PLAUSIVEL = 6.0   # acima disso, a calibração provavelmente é de outro processo


def params_de_registro(registro: Dict[str, Any], carta: Carta) -> Dict[str, Any]:
    params = dict(registro["Parametros"])
    params["familia"] = carta.familia
    if params.get("centro") is None:
        raise ErroDeLeitura("A calibração não tem a linha central (parâmetro 'centro').")
    return params


# ---------------------------------------------------------------------------
# Limites informados no próprio JSON de acompanhamento
# ---------------------------------------------------------------------------
def params_de_limites(limites: Dict[str, Any], carta: Carta, avisos: List[str]) -> Dict[str, Any]:
    """Converte limites (LSC/LC/LIC) escritos no JSON em parâmetros do processo."""
    if limites.get("calibracao"):
        bruto = limites["calibracao"]
        mapa = {normalizar(k): k for k in bruto}
        return params_de_registro({"Parametros": bruto[mapa["parametros"]]}, carta)
    por_serie = dict(limites.get("por_serie") or {})
    if limites.get("primaria"):
        por_serie.setdefault(carta.primaria, limites["primaria"])
    familia = carta.familia

    def centro_de(trinca: Dict[str, float]) -> Optional[float]:
        if "lc" in trinca:
            return trinca["lc"]
        if "lsc" in trinca and "lic" in trinca:
            return (trinca["lsc"] + trinca["lic"]) / 2
        return None

    def meia_largura(trinca: Dict[str, float], centro: float) -> Optional[float]:
        if "lsc" in trinca:
            return trinca["lsc"] - centro
        if "lic" in trinca:
            return centro - trinca["lic"]
        return None

    if familia == "variaveis":
        n = carta.n_const or round(sum(carta.n) / len(carta.n))
        f = fatores(n)
        x = por_serie.get("xbarra")
        r = por_serie.get("r")
        centro = centro_de(x) if x else None
        rbar = None
        if r and "lc" in r:
            rbar = r["lc"]
        elif r and "lsc" in r:
            rbar = r["lsc"] / f.D4
        elif x and centro is not None and meia_largura(x, centro) is not None:
            rbar = meia_largura(x, centro) / f.A2
        if centro is None:
            centro = sum(carta.medias) / len(carta.medias)
            avisos.append("Os limites informados não trazem a linha central da X-barra; usando a média dos dados.")
        if rbar is None or rbar <= 0:
            raise ErroDeLeitura("Os limites informados não permitem obter R̄ (informe LSC e LC da carta).")
        return {"familia": familia, "tipo": carta.tipo, "centro": centro, "rbar": rbar,
                "sigma": rbar / f.d2, "n": n, "m": None}
    if familia == "individuais":
        # Na carta de valores individuais, "X" também costuma significar os valores medidos.
        i = por_serie.get("i") or por_serie.get("xbarra")
        am = por_serie.get("am") or por_serie.get("r")
        centro = centro_de(i) if i else None
        if centro is None:
            raise ErroDeLeitura("Os limites informados não trazem a linha central da carta I.")
        if am and "lc" in am:
            ambar = am["lc"]
        elif i and meia_largura(i, centro) is not None:
            ambar = meia_largura(i, centro) / config.L_SIGMA * fatores(2).d2
        else:
            raise ErroDeLeitura("Os limites informados não permitem obter a amplitude móvel média.")
        return {"familia": familia, "tipo": carta.tipo, "centro": centro, "ambar": ambar,
                "sigma": ambar / fatores(2).d2, "m": None}
    chave_usada = carta.primaria if carta.primaria in por_serie else next(iter(por_serie), None)
    trinca = por_serie.get(chave_usada) if chave_usada else None
    if not trinca:
        raise ErroDeLeitura("Os limites informados no arquivo não foram reconhecidos.")
    centro = trinca.get("lc")
    if familia == "fracao":
        if centro is None:
            raise ErroDeLeitura("Informe a linha central (LC) da carta p.")
        if chave_usada == "np":
            # Limites da carta np estão em número de defeituosos: p̄ = LC / n.
            centro = centro / (carta.n_const or carta.n[0])
        return {"familia": familia, "tipo": carta.tipo, "centro": centro, "sigma": None, "n": carta.n_const,
                "n_medio": sum(carta.n) / len(carta.n), "m": None}
    if centro is None and "lsc" in trinca:
        # c̄ + 3√c̄ = LSC  →  √c̄ = (−3 + √(9 + 4·LSC)) / 2
        raiz = (-config.L_SIGMA + math.sqrt(config.L_SIGMA ** 2 + 4 * trinca["lsc"])) / 2
        centro = raiz ** 2
        avisos.append("A linha central foi obtida a partir do LSC informado.")
    if centro is None:
        raise ErroDeLeitura("Informe a linha central (LC) da carta.")
    params = {"familia": familia, "tipo": carta.tipo, "centro": centro, "sigma": None, "m": None}
    if familia == "taxa":
        params["n_medio"] = sum(carta.unidades) / len(carta.unidades)
    return params


def resolver_arquivo_calibracao(texto: str, plano: Plano) -> Path:
    """Caminho de calibração citado no JSON: relativo ao próprio JSON ou à pasta atual."""
    caminho = limpar_caminho(texto)
    if not caminho.is_absolute() and plano.caminho:
        candidato = Path(plano.caminho).parent / caminho
        if candidato.exists():
            return candidato
    return caminho
