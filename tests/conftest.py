import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

SIMULADO = RAIZ / "dados" / "dados_simulado_prova_1_0226.json"
EXEMPLOS = RAIZ / "exemplos"


@pytest.fixture
def raiz():
    return RAIZ


@pytest.fixture
def saida(tmp_path):
    return tmp_path / "saida"
