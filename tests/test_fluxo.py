"""Testes de ponta a ponta: sessão, relatório, calibração salva, menu, entrada e linha de comando."""

import json
import os
import subprocess
import sys

import pytest

from cep import calibracoes
from cep.entrada import interpretar_linha, ler_serial, numeros_em_texto, registrar_medicoes
from cep.leitura import ErroDeLeitura, carregar_plano
from cep.menu import Menu
from cep.processamento import Sessao

from conftest import EXEMPLOS, RAIZ, SIMULADO


def test_calibrar_e_depois_acompanhar(saida):
    sessao = Sessao(saida)
    cal = sessao.processar_arquivo(SIMULADO)
    assert cal.calibracao_salva and (saida / "calibracoes").exists()
    acomp = sessao.processar_arquivo(EXEMPLOS / "exemplo_x_acompanhar.json", avisar=lambda _t: None)
    assert "dados_simulado_prova_1_0226.json" in acomp.origem_limites
    # os limites do acompanhamento são exatamente os revisados na calibração
    assert acomp.series_finais[0].lsc[0] == pytest.approx(cal.series_finais[0].lsc[0])
    # o deslocamento simulado (+0,013 mm ≈ 1,5σ a partir do subgrupo 9) é encontrado
    mud = acomp.deslocamento["mudanca"]
    assert mud["significativa"] and mud["apos_ponto"] == 8
    assert 1.0 < mud["delta"] < 2.0
    pdf = sessao.relatorio.ultimo_pdf
    assert pdf.exists() and pdf.stat().st_size > 50_000
    registro = json.loads(sessao.relatorio.caminho_registro.read_text(encoding="utf-8"))
    titulos = [b["titulo"] for b in registro["blocos"] if b["tipo"] == "secao"]
    assert titulos == ["Calibração – dados_simulado_prova_1_0226.json", "Acompanhamento – exemplo_x_acompanhar.json"]


def test_calibracao_salva_reproduz_os_limites(saida):
    sessao = Sessao(saida)
    cal = sessao.processar_arquivo(SIMULADO)
    registro = calibracoes.carregar(cal.calibracao_salva)
    assert registro["Pontos_removidos"] == [2, 9, 17]
    assert registro["Limites"]["X-barra"]["LSC"] == pytest.approx(cal.series_finais[0].lsc[0])
    # uma nova sessão (outro dia) encontra a calibração salva em disco
    nova = Sessao(saida)
    r = nova.processar_arquivo(EXEMPLOS / "exemplo_x_acompanhar.json", avisar=lambda _t: None)
    assert r.series_finais[0].lsc[0] == pytest.approx(cal.series_finais[0].lsc[0])


def test_acompanhamento_sem_calibracao_calibra_com_os_dados(saida):
    r = Sessao(saida).processar_arquivo(EXEMPLOS / "exemplo_c_acompanhar.json", avisar=lambda _t: None)
    assert r.calibracao and any("Fase I" in a for a in r.plano.avisos)


def test_calibracao_de_outro_processo_nao_e_usada(saida):
    sessao = Sessao(saida)
    sessao.processar_arquivo(EXEMPLOS / "exemplo_x_tamanho_variavel.json")   # 12 mm, outro processo
    with pytest.raises(ErroDeLeitura, match="outro processo"):
        sessao.processar_arquivo(EXEMPLOS / "exemplo_x_acompanhar.json", avisar=lambda _t: None)


def test_acompanhamento_com_limites_no_arquivo(saida):
    r = Sessao(saida).processar_arquivo(EXEMPLOS / "exemplo_p_acompanhar_limites_no_arquivo.json")
    assert r.origem_limites == "limites informados no próprio arquivo JSON"
    assert r.params["centro"] == pytest.approx(0.05)
    assert r.nivel == "critico"


def test_acompanhamento_com_limites_agrupados_por_tipo(saida, tmp_path):
    """Limites no formato "LSC": {"X": ..., "R": ...} reproduzem os limites da calibração."""
    cal = Sessao(saida).processar_arquivo(SIMULADO)
    x, r = cal.series_finais
    dados = json.loads((EXEMPLOS / "exemplo_x_acompanhar.json").read_text(encoding="utf-8"))["Data"]
    arquivo = tmp_path / "acompanhamento_limites.json"
    arquivo.write_text(json.dumps({"Type": "X", "Goal": "Acompanhar",
                                   "LSC": {"X": x.lsc[0], "R": r.lsc[0]}, "LIC": {"X": x.lic[0], "R": 0},
                                   "LC": {"X": x.lc[0]}, "Data": dados}), encoding="utf-8")
    acomp = Sessao(saida).processar_arquivo(arquivo)
    assert acomp.origem_limites == "limites informados no próprio arquivo JSON"
    xa, ra = acomp.series_finais
    assert (xa.lic[0], xa.lc[0], xa.lsc[0]) == pytest.approx((x.lic[0], x.lc[0], x.lsc[0]))
    assert (ra.lc[0], ra.lsc[0]) == pytest.approx((r.lc[0], r.lsc[0]))
    assert acomp.nivel == "critico"


def test_todos_os_exemplos(saida):
    sessao = Sessao(saida)
    # o acompanhamento de X é do mesmo processo do simulado: a calibração dele vem primeiro
    arquivos = [SIMULADO] + sorted(EXEMPLOS.glob("*.json"), key=lambda a: "acompanhar" in a.name)
    for arquivo in arquivos:
        r = sessao.processar_arquivo(arquivo, avisar=lambda _t: None)
        for serie in r.series_finais:
            assert all(a <= b + 1e-12 <= c + 2e-12 for a, b, c in zip(serie.lic, serie.lc, serie.lsc))
        assert all(__import__("pathlib").Path(g).exists() for g in r.graficos)
    assert sessao.relatorio.ultimo_pdf.exists()


def test_menu_completo(saida, monkeypatch, tmp_path):
    monkeypatch.chdir(RAIZ)
    respostas = iter([
        "1", str(SIMULADO), "",                 # processa o simulado
        "3", "2", "10", "0,1", "2", "0",         # binomial na calculadora
        "4", "1,5", "",                         # deslocamento personalizado
        "5", "s", "s", "",                      # guia de escolha
        "6", "",                                # calibrações salvas
        "0",
    ])
    saidas = []
    menu = Menu(saida, perguntar=lambda _t: next(respostas), mostrar=saidas.append)
    assert menu.executar() == 0
    texto = "\n".join(saidas)
    assert "Limites tentativos" in texto and "Carta recomendada: X-barra e R" in texto
    assert "P(X = 2)" in texto
    registro = json.loads(menu.sessao.relatorio.caminho_registro.read_text(encoding="utf-8"))
    titulos = [b["titulo"] for b in registro["blocos"] if b["tipo"] == "secao"]
    assert titulos[0].startswith("Calibração") and "Calculadora de probabilidades" in titulos
    assert any(t.startswith("Deslocamentos possíveis") for t in titulos)
    assert "Guia de escolha da carta" in titulos


def test_menu_sobrevive_a_arquivo_ruim(saida, tmp_path):
    ruim = tmp_path / "ruim.json"
    ruim.write_text('{"Type": "X", "Goal": "Calibrar", "Data": [[1, 2], [3, "x"]]}', encoding="utf-8")
    respostas = iter(["1", str(ruim), "", "9", "0"])
    saidas = []
    assert Menu(saida, perguntar=lambda _t: next(respostas), mostrar=saidas.append).executar() == 0
    assert any("não é um número" in s for s in saidas)


def test_modulo_de_entrada_teclado(tmp_path):
    respostas = iter(["1", "1", "Diâmetro", "mm", "Felipe", "5", "4", "1", "3",
                      "4,95 4,96 4,97", "4.94;4.95;4.99", "4,96", "4,97", "4,98", "4,99", "", ""])
    caminho = registrar_medicoes(lambda _t: next(respostas), lambda _t: None, pasta=tmp_path)
    plano = carregar_plano(caminho)
    assert plano.tipo == "XBAR_R" and plano.unidade == "mm" and plano.lse == 5
    assert plano.subgrupos == [[4.95, 4.96, 4.97], [4.94, 4.95, 4.99], [4.96, 4.97, 4.98]]


def test_leitura_de_linhas_e_serial():
    assert interpretar_linha("4,95 4,96; 4,97") == [4.95, 4.96, 4.97]
    assert interpretar_linha("4.95,4.96") == [4.95, 4.96]
    with pytest.raises(ValueError):
        interpretar_linha("abc")
    assert numeros_em_texto("T=23,5 C") == [23.5]

    class PlacaFalsa:
        def __init__(self):
            self.linhas = [b"iniciando\n", b"T=23,5\n", b"23.7\n", b"\n", b"24.1 24.0\n"]

        def readline(self):
            return self.linhas.pop(0) if self.linhas else b""

    valores = ler_serial("falsa", 4, mostrar=lambda _t: None, conexao=PlacaFalsa(), espera_maxima=0.2)
    assert valores == [23.5, 23.7, 24.1, 24.0]


def test_linha_de_comando(tmp_path):
    saida = tmp_path / "saida"
    comando = [sys.executable, str(RAIZ / "main.py"), str(EXEMPLOS / "exemplo_c_acompanhar.json"),
               str(EXEMPLOS / "exemplo_c_calibrar.json"), "--saida", str(saida)]
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", cwd=RAIZ,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert resultado.returncode == 0, resultado.stderr
    assert "calibração serão processados antes" in resultado.stdout
    assert list(saida.glob("relatorio_*/relatorio.pdf"))


def test_menu_lista_primeiro_os_json_baixados(saida, monkeypatch, tmp_path):
    casa = tmp_path / "casa"
    downloads = casa / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "prova_dia.json").write_text(SIMULADO.read_text(encoding="utf-8"), encoding="utf-8")
    (downloads / "config_de_outro_programa.json").write_text('{"tema": "escuro"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("USERPROFILE", str(casa))
    monkeypatch.chdir(RAIZ)
    respostas = iter(["1", "1", "", "0"])
    saidas = []
    assert Menu(saida, perguntar=lambda _t: next(respostas), mostrar=saidas.append).executar() == 0
    texto = "\n".join(saidas)
    lista = next(s for s in saidas if "Arquivos JSON encontrados" in s)
    assert "1) " in texto and "prova_dia.json" in texto and "baixado em" in texto
    assert "config_de_outro_programa" not in texto
    assert "Calibração – prova_dia.json" in texto
    assert lista


def test_continuar_o_ultimo_relatorio(saida):
    primeira = Sessao(saida)
    primeira.processar_arquivo(SIMULADO)
    graficos_antes = sorted(primeira.relatorio.pasta_graficos.glob("*.png"))
    # O programa é fechado e aberto de novo: a nova sessão retoma o mesmo relatório.
    segunda = Sessao(saida)
    pasta = segunda.continuar_ultimo_relatorio()
    assert pasta == primeira.relatorio.pasta
    assert len(list(saida.glob("relatorio_*"))) == 1          # a pasta vazia da 2ª sessão foi descartada
    segunda.processar_arquivo(EXEMPLOS / "exemplo_x_acompanhar.json", avisar=lambda _t: None)
    registro = json.loads(segunda.relatorio.caminho_registro.read_text(encoding="utf-8"))
    titulos = [b["titulo"] for b in registro["blocos"] if b["tipo"] == "secao"]
    assert titulos == ["Calibração – dados_simulado_prova_1_0226.json", "Acompanhamento – exemplo_x_acompanhar.json"]
    graficos_depois = sorted(segunda.relatorio.pasta_graficos.glob("*.png"))
    assert set(graficos_antes) < set(graficos_depois)          # nenhum gráfico antigo foi sobrescrito
    assert all(g.stat().st_size > 0 for g in graficos_antes)


def test_continuar_sem_relatorio_anterior(saida):
    assert Sessao(saida).continuar_ultimo_relatorio() is None
