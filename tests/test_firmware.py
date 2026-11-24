"""A lógica do firmware (firmware/esp32_cep_embarcado/cep_embarcado.h) calcula o mesmo que o software do PC.

Compila o teste em C++ com o g++ do computador; sem compilador, os testes são pulados.
"""

import json
import os
import random
import shutil
import subprocess

import pytest

from cep.analise import calibrar
from cep.leitura import plano_de_dicionario

from conftest import RAIZ, SIMULADO

FONTE = RAIZ / "firmware" / "testes" / "teste_cep.cpp"


@pytest.fixture(scope="module")
def executavel(tmp_path_factory):
    compilador = shutil.which("g++")
    if not compilador:
        pytest.skip("g++ não encontrado")
    saida = tmp_path_factory.mktemp("firmware") / ("teste_cep.exe" if os.name == "nt" else "teste_cep")
    subprocess.run([compilador, "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(saida), str(FONTE)],
                   check=True, capture_output=True, text=True)
    return str(saida)


def rodar(executavel, entrada):
    return subprocess.run([executavel], input=entrada, capture_output=True, text=True, check=True).stdout


def comparar(executavel, subgrupos):
    n = len(subgrupos[0])
    entrada = f"cal {n} {len(subgrupos)}\n" + "\n".join(" ".join(map(str, s)) for s in subgrupos)
    lic, lc, lsc, rlc, rlsc, retirados, confiavel = rodar(executavel, entrada).split()
    r = calibrar(plano_de_dicionario({"Type": "X", "Goal": "Calibrar", "Data": subgrupos}))
    x, rr = r.series_finais
    assert float(lc) == pytest.approx(x.lc[0], abs=1e-4)
    assert float(lsc) == pytest.approx(x.lsc[0], abs=1e-4)
    assert float(lic) == pytest.approx(x.lic[0], abs=1e-4)
    assert float(rlc) == pytest.approx(rr.lc[0], abs=1e-4)
    assert float(rlsc) == pytest.approx(rr.lsc[0], abs=1e-4)
    assert int(retirados) == len(r.removidos)


def test_calibracao_igual_ao_pc_no_simulado(executavel):
    dados = json.loads(SIMULADO.read_text(encoding="utf-8"))["Data"]
    comparar(executavel, dados)


@pytest.mark.parametrize("semente", range(8))
def test_calibracao_igual_ao_pc_em_dados_aleatorios(executavel, semente):
    gerador = random.Random(semente)
    n = gerador.choice([3, 4, 5, 6, 8])
    subgrupos = [[round(gerador.gauss(35, 0.2), 2) for _ in range(n)] for _ in range(gerador.randint(15, 30))]
    for _ in range(gerador.randint(0, 3)):                 # alguns subgrupos com causa especial
        subgrupos[gerador.randrange(len(subgrupos))] = [round(gerador.gauss(36.5, 0.2), 2) for _ in range(n)]
    comparar(executavel, subgrupos)


def test_malha_embarcada_compensa_a_perturbacao(executavel):
    fim = rodar(executavel, "sim 180 100 4").strip().splitlines()[-1]
    campos = dict(item.split("=") for item in fim.split()[1:])
    assert campos["fase"] == "acompanhamento"
    assert abs(float(campos["lc"]) - 35) < 0.4
    assert int(campos["pwm"]) > int(campos["pwm_antes"]) + 30          # compensou o ambiente mais frio
    assert abs(float(campos["media_final"]) - float(campos["lc"])) < 0.4
