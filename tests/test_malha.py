"""Malha fechada: controlador CEP, estufa simulada, servidor HTTP e simulador do ESP32."""

import json
import threading
import urllib.request

import pytest

from cep.malha import ACOMPANHAMENTO, CALIBRACAO, Configuracao, MalhaCEP
from cep.processamento import Sessao
from cep.simulacao import Estufa


def rodar(malha, estufa, subgrupos, perturbacao=None):
    for k in range(1, subgrupos + 1):
        if perturbacao and k == perturbacao[0]:
            estufa.ambiente = perturbacao[1]
        malha.receber(estufa.subgrupo(malha.pwm, malha.config.n))


def calibrada(semente=3):
    malha, estufa = MalhaCEP(), Estufa(semente=semente)
    rodar(malha, estufa, 60)
    assert malha.fase == ACOMPANHAMENTO
    return malha, estufa


def test_aquece_calibra_e_acompanha():
    malha, _ = calibrada()
    lim = malha.limites()
    assert lim["lic"] < lim["lc"] < lim["lsc"]
    assert abs(lim["lc"] - malha.config.alvo) < 0.3          # calibrou perto do alvo
    fases = [d.fase for d in malha.historico]
    assert fases.index(CALIBRACAO) < fases.index(ACOMPANHAMENTO)
    # durante a calibração o PWM fica fixo
    pwms = {d.pwm for d in malha.historico if d.fase == CALIBRACAO}
    assert len(pwms) == 1


def test_perturbacao_e_corrigida_pelo_sinal_da_carta():
    malha, estufa = calibrada()
    pwm_antes = malha.pwm
    rodar(malha, estufa, 100, perturbacao=(1, estufa.ambiente - 4.0))   # ambiente esfria 4 °C
    ajustes = [d for d in malha.historico if d.fase == ACOMPANHAMENTO and d.acao == "aumentar"]
    assert ajustes and "carta X-barra" in ajustes[0].motivo
    assert malha.pwm > pwm_antes + 30                         # compensou o ambiente mais frio
    finais = [d.media for d in malha.historico[-15:]]
    assert abs(sum(finais) / len(finais) - malha.limites()["lc"]) < 0.4


def test_sem_sinal_nao_mexe_no_processo():
    malha, estufa = calibrada()
    inicio = len(malha.historico)
    rodar(malha, estufa, 15)
    for d in malha.historico[inicio:]:
        if d.acao == "manter":
            assert d.pwm == malha.historico[inicio - 1].pwm or "Aguardando" in d.motivo


def test_acima_do_lse_desliga_o_aquecedor():
    malha, _ = calibrada()
    d = malha.receber([38.6, 38.7, 38.5, 38.8, 38.6])
    assert d.acao == "desligar" and d.pwm == 0 and d.alarme


def test_amplitude_anormal_pede_verificacao():
    malha, _ = calibrada()
    lc = malha.limites()["lc"]
    d = malha.receber([lc - 1.5, lc + 1.5, lc, lc, lc])
    assert d.acao == "verificar" and d.alarme and d.pwm == malha.historico[-2].pwm


def test_subgrupo_invalido():
    malha = MalhaCEP()
    with pytest.raises(ValueError, match="espera 5"):
        malha.receber([35.0, 35.1])
    with pytest.raises(ValueError, match="inválido"):
        malha.receber([35.0, 35.1, float("nan"), 35.0, 35.0])
    with pytest.raises(ValueError, match="números"):
        malha.receber([35.0, "abc", 35.0, 35.0, 35.0])


def test_calibracao_entra_no_relatorio(saida):
    sessao = Sessao(saida)
    malha, estufa = MalhaCEP(Configuracao(), sessao=sessao), Estufa(semente=5)
    rodar(malha, estufa, 60)
    registro = json.loads(sessao.relatorio.caminho_registro.read_text(encoding="utf-8"))
    titulos = [b["titulo"] for b in registro["blocos"] if b["tipo"] == "secao"]
    assert any(t.startswith("Calibração") for t in titulos)
    assert malha.calibracao.calibracao_salva


def test_servidor_e_simulador_de_ponta_a_ponta(saida):
    servidor_mod = pytest.importorskip("servidor")
    from ferramentas.simulador_esp32 import simular
    app = servidor_mod.criar_servidor("127.0.0.1", 0, Configuracao(), saida)
    porta = app.server_address[1]
    fio = threading.Thread(target=app.serve_forever, daemon=True)
    fio.start()
    try:
        url = f"http://127.0.0.1:{porta}"
        respostas = simular(url, subgrupos=70, perturbacao=55, intervalo=0, semente=3, mostrar=lambda _t: None)
        assert respostas[-1]["fase"] == ACOMPANHAMENTO and "lsc" in respostas[-1]
        estado = json.loads(urllib.request.urlopen(url + "/estado").read())
        assert estado["subgrupos_recebidos"] == 70
        pagina = urllib.request.urlopen(url + "/").read().decode("utf-8")
        assert "Acompanhamento" in pagina
        # subgrupo com tamanho errado volta como erro 400, sem derrubar o servidor
        pedido = urllib.request.Request(url + "/medicoes", data=b'{"subgrupo": [1, 2]}',
                                        headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(pedido)
        assert erro.value.code == 400
        pdf = json.loads(urllib.request.urlopen(url + "/relatorio").read())["pdf"]
        assert pdf.endswith(".pdf")
    finally:
        app.shutdown()
        app.server_close()
