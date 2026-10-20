"""Interface web (opcional): só roda se o Streamlit estiver instalado."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from conftest import EXEMPLOS, RAIZ, SIMULADO  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CEP_SAIDA", str(tmp_path / "saida"))
    app = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120)
    app.run()
    return app


def test_pagina_abre_sem_erro(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    assert not app.exception
    assert app.title[0].value == "CEP – Cartas de Controle"


def test_calibrar_e_acompanhar_pela_pagina(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    for arquivo in (SIMULADO, EXEMPLOS / "exemplo_x_acompanhar.json"):
        app.selectbox[0].set_value(arquivo).run()
        next(b for b in app.button if b.label == "Processar exemplo").click().run()
        assert not app.exception
    assert any("Processo fora de controle" in e.value for e in app.error)   # o acompanhamento achou o deslocamento
    assert len(app.tabs) == 6
    assert (tmp_path / "saida" / "calibracoes").is_dir()
