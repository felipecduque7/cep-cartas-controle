import json

import pytest

from cep.leitura import ACOMPANHAR, CALIBRAR, ErroDeLeitura, carregar_plano, plano_de_dicionario

from conftest import SIMULADO


def test_arquivo_do_professor():
    p = carregar_plano(SIMULADO)
    assert (p.tipo, p.objetivo, p.unidade, p.criado_por) == ("XBAR_R", CALIBRAR, "mm", "Henrique")
    assert (p.lse, p.lie) == (5.0, 4.0)
    assert p.num_pontos == 20 and all(len(s) == 5 for s in p.subgrupos)
    assert p.avisos == []


@pytest.mark.parametrize("conteudo, tipo, objetivo", [
    ({"type": "x", "goal": "calibração", "data": [["4,95", "4,96"], [4.94, 4.97]]}, "XBAR_R", CALIBRAR),
    ({"Tipo": "X-barra", "Objetivo": "Calibracao", "Dados": [[1, 2], [3, 4]]}, "XBAR_R", CALIBRAR),
    ({"TYPE": "I-MR", "GOAL": "ACOMPANHAMENTO", "DATA": [1, 2, 3, 4]}, "IMR", ACOMPANHAR),
    ({"Type": "mri", "Goal": "Monitorar", "Data": [[1], [2], [3]]}, "IMR", ACOMPANHAR),
    ({"Type": "R", "Goal": "Calibrar", "Data": [[1, 2, 3], [2, 3, 4]]}, "R", CALIBRAR),
    ({"Type": "P", "Goal": "Calibrar", "Data": [[3, 100], [5, 100], [2, 100]]}, "P", CALIBRAR),
    ({"Type": "NP", "Goal": "Calibrar", "n": 50, "Data": [3, 5, 2]}, "NP", CALIBRAR),
    ({"Type": "C", "Goal": "Calibrar", "Data": [[3], [5], [2]]}, "C", CALIBRAR),
    ({"Type": "U", "Goal": "Calibrar", "Data": [[3, 2], [5, 2.5], [2, 2]]}, "U", CALIBRAR),
])
def test_variacoes_de_formato(conteudo, tipo, objetivo):
    p = plano_de_dicionario(conteudo, "teste.json")
    assert p.tipo == tipo and p.objetivo == objetivo


def test_formatos_da_carta_p():
    pares = plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "Data": [[3, 100], [5, 90]]})
    assert pares.defeituosos == [3, 5] and pares.tamanhos == [100, 90]
    itens = plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "Data": [[0, 1, 0, 0], [1, 1, 0, 0]]})
    assert itens.defeituosos == [1, 2] and itens.tamanhos == [4, 4]
    contagens = plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "n": 50, "Data": [3, 5]})
    assert contagens.defeituosos == [3, 5] and contagens.tamanhos == [50, 50]
    fracoes = plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "n": 50, "Data": [[0.06], [0.1]]})
    assert fracoes.defeituosos == [3, 5]
    with pytest.raises(ErroDeLeitura, match="campo 'n'"):
        plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "Data": [3, 5]})


def test_ajustes_viram_avisos():
    p = plano_de_dicionario({"Type": "X", "Data": [[1], [2], [3]], "LSE": 1, "LIE": 9, "Extra": 1})
    assert p.tipo == "IMR"                       # subgrupos de 1 valor → individuais
    assert (p.lie, p.lse) == (1, 9)              # especificação invertida foi corrigida
    texto = " ".join(p.avisos)
    assert "Goal" in texto and "trocados" in texto and "Extra" in texto
    np_variavel = plano_de_dicionario({"Type": "NP", "Goal": "Calibrar", "Data": [[3, 100], [5, 90]]})
    assert np_variavel.tipo == "P"


def test_limites_informados_no_arquivo():
    p = plano_de_dicionario({"Type": "X", "Goal": "Acompanhar", "LSC": 5, "LC": 4.5, "LIC": 4,
                             "Data": [[1, 2], [2, 3]]})
    assert p.limites_informados["primaria"] == {"lsc": 5.0, "lc": 4.5, "lic": 4.0}
    p = plano_de_dicionario({"Type": "X", "Goal": "Acompanhar", "Limites": {"X": {"LSC": 5, "LC": 4.5},
                                                                           "R": {"LC": 0.2}},
                             "Data": [[1, 2], [2, 3]]})
    assert set(p.limites_informados["por_serie"]) == {"xbarra", "r"}


def test_limites_agrupados_por_tipo_de_limite():
    """Formato "LSC": {"X": ..., "R": ...} (usado, por exemplo, por outros programas da turma)."""
    p = plano_de_dicionario({"Type": "X", "LSC": {"X": 4.97, "R": 0.0425}, "LIC": {"X": 4.95, "R": 0},
                             "LC": {"X": 4.96}, "Data": [[1, 2], [2, 3]]})
    assert p.objetivo == ACOMPANHAR          # sem Goal, mas com limites: acompanhamento
    assert p.limites_informados["por_serie"] == {"xbarra": {"lsc": 4.97, "lic": 4.95, "lc": 4.96},
                                                 "r": {"lsc": 0.0425, "lic": 0.0}}
    p = plano_de_dicionario({"Type": "P", "Goal": "Acompanhar", "Limites": {"LC": {"p": 0.05}, "LSC": {"p": 0.12}},
                             "Data": [[3, 100], [4, 100]]})
    assert p.limites_informados["por_serie"] == {"p": {"lc": 0.05, "lsc": 0.12}}
    with pytest.raises(ErroDeLeitura, match="carta não reconhecida"):
        plano_de_dicionario({"Type": "X", "Goal": "Acompanhar", "LSC": {"Z": 1}, "Data": [[1, 2], [2, 3]]})


@pytest.mark.parametrize("conteudo, trecho", [
    ({"Type": "Z", "Goal": "Calibrar", "Data": [[1, 2]]}, "não reconhecido"),
    ({"Type": "X", "Goal": "Calibrar", "Data": [[1, 2], [3, "abc"]]}, "amostra 2, valor 2"),
    ({"Type": "X", "Goal": "Calibrar", "Data": [[1, 2], [3]]}, "O subgrupo 2 tem só 1 valor"),
    ({"Type": "X", "Goal": "Fazer", "Data": [[1, 2], [3, 4]]}, "Calibrar"),
    ({"Goal": "Calibrar", "Data": [[1, 2], [3, 4]]}, "Type"),
    ({"Type": "X", "Goal": "Calibrar", "Data": [[1, 2], [3, True]]}, "valor lógico"),
    ({"Type": "X", "Goal": "Calibrar", "Data": []}, "vazio"),
    ({"Type": "X", "Goal": "Calibrar", "Data": [[1, 2], [3, None]]}, "null"),
    ({"Type": "P", "Goal": "Calibrar", "Data": [[30, 10], [5, 100]]}, "defeituosos inválido"),
    ([1, 2, 3], "objeto"),
])
def test_erros_com_mensagem_clara(conteudo, trecho):
    with pytest.raises(ErroDeLeitura, match=trecho):
        plano_de_dicionario(conteudo, "teste.json")


def test_json_invalido_indica_linha(tmp_path):
    arquivo = tmp_path / "ruim.json"
    arquivo.write_text('{"Type": "X",\n "Data": [[1, 2],, [3, 4]]}', encoding="utf-8")
    with pytest.raises(ErroDeLeitura, match="linha 2"):
        carregar_plano(arquivo)


def test_caminho_com_aspas_e_bom(tmp_path):
    arquivo = tmp_path / "com bom.json"
    arquivo.write_text(json.dumps({"Type": "C", "Goal": "Calibrar", "Data": [[1], [2], [3]]}), encoding="utf-8-sig")
    assert carregar_plano(f'"{arquivo}"').tipo == "C"
