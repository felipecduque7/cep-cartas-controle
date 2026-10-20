import pytest

from cep.analise import calibrar
from cep.cartas import Serie, criar_carta
from cep.leitura import carregar_plano, plano_de_dicionario
from cep.regras import avaliar

from conftest import SIMULADO


def _serie(valores, lc=0.0, sigma=1.0, regras=("1", "2", "3", "4", "T")):
    m = len(valores)
    return Serie("x", "X", "X", "x", "x", list(range(m)), list(valores), [lc] * m, [lc + 3 * sigma] * m,
                 [lc - 3 * sigma] * m, [sigma] * m, regras, 3)


def _regras(sinais):
    return sorted((s.regra, s.lado, tuple(s.pontos)) for s in sinais)


def test_regra_1():
    assert _regras(avaliar(_serie([0, 0, 3.5, 0, -3.2]))) == [("1", "abaixo", (5,)), ("1", "acima", (3,))]


def test_regra_2():
    sinais = avaliar(_serie([0, 2.5, 0.2, 2.6, 0], regras=("2",)))
    assert _regras(sinais) == [("2", "acima", (2, 4))]
    assert avaliar(_serie([0, 2.5, 0.2, 0.1, 2.6], regras=("2",))) == []


def test_regra_3():
    assert _regras(avaliar(_serie([1.5, 1.2, 0.5, 1.1, 1.3], regras=("3",)))) == [("3", "acima", (1, 2, 4, 5))]
    assert avaliar(_serie([1.5, 1.2, 0.5, 0.9, 1.3], regras=("3",))) == []


def test_regra_4():
    oito = [0.1 * (i + 1) for i in range(8)]
    assert _regras(avaliar(_serie(oito, regras=("4",)))) == [("4", "acima", tuple(range(1, 9)))]
    assert avaliar(_serie(oito[:7], regras=("4",))) == []


def test_tendencia():
    assert _regras(avaliar(_serie([0, 0.1, 0.2, 0.3, 0.4, 0.5], regras=("T",)))) == \
        [("T", "subindo", (1, 2, 3, 4, 5, 6))]
    assert avaliar(_serie([0, 0.1, 0.2, 0.3, 0.4], regras=("T",))) == []


def test_janelas_sobrepostas_viram_um_sinal():
    sinais = avaliar(_serie([2.5, 2.4, 2.6, 2.7, 0], regras=("2",)))
    assert len(sinais) == 1 and sinais[0].pontos == [1, 2, 3, 4]


def test_gabarito_do_simulado():
    """Valores conferidos à mão com A2 = 0,577, D3 = 0 e D4 = 2,114 (n = 5)."""
    r = calibrar(carregar_plano(SIMULADO))
    t = r.iteracoes[0].params
    assert t["centro"] == pytest.approx(4.96065)
    assert t["rbar"] == pytest.approx(0.02195)
    x, rr = r.series_tentativas
    assert x.lsc[0] == pytest.approx(4.96065 + 0.577 * 0.02195)
    assert x.lic[0] == pytest.approx(4.96065 - 0.577 * 0.02195)
    assert rr.lsc[0] == pytest.approx(2.114 * 0.02195)
    fora = {k: sorted(p + 1 for p, _ in v) for k, v in r.iteracoes[0].fora.items()}
    assert fora == {"xbarra": [2, 17], "r": [9]}
    assert [i + 1 for i in r.removidos] == [2, 9, 17]
    assert r.params["centro"] == pytest.approx(84.341 / 17)
    assert r.params["rbar"] == pytest.approx(0.342 / 17)
    xf, rf = r.series_finais
    assert xf.lsc[0] == pytest.approx(84.341 / 17 + 0.577 * 0.342 / 17)
    assert rf.lsc[0] == pytest.approx(2.114 * 0.342 / 17)
    assert r.nivel == "alerta"          # restam sinais de alerta entre os pontos mantidos
    assert r.capacidade["rcpk"] == pytest.approx((5.0 - 84.341 / 17) / (3 * (0.342 / 17) / 2.326))


def test_pp_e_ppk_do_simulado():
    """Pp e Ppk usam o desvio-padrão total das 85 medições dos subgrupos mantidos."""
    import statistics
    plano = carregar_plano(SIMULADO)
    r = calibrar(plano)
    mantidos = [v for i, s in enumerate(plano.subgrupos) if i not in (1, 8, 16) for v in s]
    s = statistics.stdev(mantidos)
    cap = r.capacidade
    assert cap["n_desempenho"] == 85 and cap["s"] == pytest.approx(s)
    assert cap["pp"] == pytest.approx(1.0 / (6 * s))                       # ≈ 14,91
    assert cap["ppk"] == pytest.approx((5.0 - 84.341 / 17) / (3 * s))      # ≈ 1,16
    assert cap["ppk"] < cap["rcpk"]          # s inclui as mudanças de nível entre subgrupos


def test_individuais_formula_do_livro():
    valores = [10.0, 10.4, 9.8, 10.2, 10.1, 9.7, 10.3]
    carta = criar_carta(plano_de_dicionario({"Type": "IMR", "Goal": "Calibrar", "Data": valores}))
    params = carta.estimar(range(len(valores)))
    ams = [abs(b - a) for a, b in zip(valores, valores[1:])]
    ambar = sum(ams) / len(ams)
    assert params["ambar"] == pytest.approx(ambar)
    i, am = carta.series(params)
    assert i.lsc[0] == pytest.approx(sum(valores) / 7 + 3 * ambar / 1.128)
    assert am.lsc[0] == pytest.approx(3.267 * ambar)
    assert am.ids == list(range(2, 8))


def test_cartas_de_atributos_formulas():
    p = criar_carta(plano_de_dicionario({"Type": "P", "Goal": "Calibrar", "Data": [[4, 100], [6, 100], [5, 50]]}))
    params = p.estimar(range(3))
    assert params["centro"] == pytest.approx(15 / 250)
    serie = p.series(params)[0]
    assert serie.lsc[2] == pytest.approx(0.06 + 3 * (0.06 * 0.94 / 50) ** 0.5)
    assert serie.lic[2] == 0.0
    c = criar_carta(plano_de_dicionario({"Type": "C", "Goal": "Calibrar", "Data": [[4], [9], [5]]}))
    serie = c.series(c.estimar(range(3)))[0]
    assert serie.lc[0] == pytest.approx(6.0) and serie.lsc[0] == pytest.approx(6 + 3 * 6 ** 0.5)
    u = criar_carta(plano_de_dicionario({"Type": "U", "Goal": "Calibrar", "Data": [[4, 2], [9, 3], [5, 1]]}))
    serie = u.series(u.estimar(range(3)))[0]
    assert serie.lc[0] == pytest.approx(3.0) and serie.lsc[1] == pytest.approx(3 + 3 * (3 / 3) ** 0.5)
