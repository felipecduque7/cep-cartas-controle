"""Dados aleatórios de todos os tipos: o programa nunca pode quebrar nem gerar limites incoerentes."""

import math
import random

import pytest

from cep import apresentacao
from cep.analise import acompanhar, calibrar
from cep.leitura import plano_de_dicionario
from cep.relatorio import Relatorio


def _dados(rng, tipo):
    m = rng.randint(2, 45)
    if tipo in ("X", "R"):
        n = rng.randint(2, 12)
        media, desvio = rng.uniform(-50, 50), rng.uniform(0.001, 5)
        return [[round(rng.gauss(media, desvio), rng.randint(0, 4)) for _ in range(n)] for _ in range(m)]
    if tipo == "IMR":
        media, desvio = rng.uniform(-50, 50), rng.uniform(0.001, 5)
        return [[round(rng.gauss(media, desvio), 3)] for _ in range(max(m, 3))]
    if tipo in ("P", "NP"):
        n = rng.randint(5, 300)
        p = rng.uniform(0, 0.5)
        return [[sum(rng.random() < p for _ in range(n)), n] for _ in range(m)]
    if tipo == "C":
        return [[rng.randint(0, 20)] for _ in range(m)]
    return [[rng.randint(0, 15), rng.choice([0.5, 1, 2, 3])] for _ in range(m)]


@pytest.mark.parametrize("semente", range(60))
def test_dados_aleatorios(semente):
    rng = random.Random(semente)
    tipo = rng.choice(["X", "R", "IMR", "P", "NP", "C", "U"])
    conteudo = {"Type": tipo, "Goal": "Calibrar", "Data": _dados(rng, tipo)}
    if rng.random() < 0.5:
        conteudo["LSE"], conteudo["LIE"] = 60, -60
    plano = plano_de_dicionario(conteudo, f"aleatorio_{semente}.json")
    r = calibrar(plano)
    for serie in r.series_finais + r.series_tentativas:
        for lic, lc, lsc, v in zip(serie.lic, serie.lc, serie.lsc, serie.valores):
            assert all(math.isfinite(x) for x in (lic, lc, lsc, v))
            assert lic <= lc + 1e-9 and lc <= lsc + 1e-9
    assert r.nivel in ("ok", "alerta", "critico")
    # acompanhamento de novos dados do mesmo tipo com os parâmetros calibrados
    conteudo_novo = {"Type": tipo, "Goal": "Acompanhar", "Data": _dados(rng, tipo)}
    plano_novo = plano_de_dicionario(conteudo_novo, "novo.json")
    if plano_novo.familia == plano.familia:
        a = acompanhar(plano_novo, r.params, "teste")
        assert a.series_finais
    # textos e resumo não podem falhar
    apresentacao.resumo_terminal(r)
    apresentacao.interpretacao(r)
    apresentacao.textos_deslocamento(r)


def test_relatorio_com_dados_degenerados(tmp_path):
    """Todos os valores iguais (variabilidade zero) e nenhum defeito."""
    for conteudo in ({"Type": "X", "Goal": "Calibrar", "Data": [[5, 5, 5]] * 6},
                     {"Type": "C", "Goal": "Calibrar", "Data": [[0]] * 6},
                     {"Type": "P", "Goal": "Calibrar", "Data": [[0, 50]] * 6},
                     {"Type": "IMR", "Goal": "Calibrar", "Data": [1, 1, 1, 1]}):
        r = calibrar(plano_de_dicionario(conteudo, "degenerado.json"))
        assert r.ressalvas
        relatorio = Relatorio(tmp_path / conteudo["Type"])
        apresentacao.registrar(r, relatorio, {})
        assert relatorio.salvar().exists()
