import math

import pytest

from cep import probabilidade as prob
from cep.constantes import TABELA, d2_d3_calculados, fatores, prob_amplitude_entre


def test_tabela_confere_com_calculo_numerico():
    for n, (A2, D3, D4, d2, d3) in TABELA.items():
        d2c, d3c = d2_d3_calculados(n)
        assert d2c == pytest.approx(d2, abs=0.002)
        assert d3c == pytest.approx(d3, abs=0.002)
        assert D4 == pytest.approx(1 + 3 * d3c / d2c, abs=0.003)
        assert D3 == pytest.approx(max(0.0, 1 - 3 * d3c / d2c), abs=0.003)
        assert A2 == pytest.approx(3 / (d2c * math.sqrt(n)), abs=0.002)


def test_fatores_para_n_grande_sao_calculados():
    f = fatores(30)
    assert f.origem == "calculado"
    assert f.d2 == pytest.approx(4.086, abs=0.002)
    assert f.d3 == pytest.approx(0.693, abs=0.002)
    with pytest.raises(ValueError):
        fatores(1)


def test_combinatoria():
    assert prob.combinacoes(5, 2) == 10
    assert prob.arranjos(5, 2) == 20
    assert prob.permutacoes(5) == 120
    assert prob.combinacoes(3, 5) == 0
    with pytest.raises(prob.ErroDeProbabilidade):
        prob.combinacoes(2.5, 1)


def test_binomial():
    assert sum(prob.binomial_pmf(k, 20, 0.3) for k in range(21)) == pytest.approx(1.0)
    assert prob.binomial_pmf(2, 10, 0.1) == pytest.approx(math.comb(10, 2) * 0.1 ** 2 * 0.9 ** 8)
    assert prob.binomial_acumulada(10, 10, 0.4) == 1.0
    assert prob.binomial_intervalo(2, 3, 10, 0.1) == pytest.approx(
        prob.binomial_pmf(2, 10, 0.1) + prob.binomial_pmf(3, 10, 0.1))
    with pytest.raises(prob.ErroDeProbabilidade):
        prob.binomial_pmf(1, 5, 1.5)


def test_geometrica_e_cmc():
    assert prob.prob_primeiro_sucesso_em(3, 0.5) == pytest.approx(0.125)
    assert prob.prob_sucesso_ate(3, 0.5) == pytest.approx(0.875)
    assert prob.tentativas_esperadas(0.25) == pytest.approx(4)
    assert prob.tentativas_para_atingir(0.95, 0.5) == 5


def test_poisson_normal_t():
    assert sum(prob.poisson_pmf(k, 4.0) for k in range(60)) == pytest.approx(1.0)
    assert prob.normal_acumulada(1.96) == pytest.approx(0.975, abs=1e-4)
    assert prob.normal_inversa(0.975) == pytest.approx(1.95996, abs=1e-4)
    assert prob.t_p_valor_bilateral(2.0, 10) == pytest.approx(0.0734, abs=1e-4)


def test_desempenho_da_carta_xbarra_como_no_livro():
    # n = 5, deslocamento de 1σ: β ≈ 0,7775 e CMC ≈ 4,5
    d = prob.desempenho_media(1.0, 5)
    assert d["beta"] == pytest.approx(0.7775, abs=1e-3)
    assert d["cmc"] == pytest.approx(4.5, abs=0.01)
    # sem deslocamento: alarme falso 0,0027 e CMC0 ≈ 370
    zero = prob.desempenho_media(0.0, 5)
    assert zero["p_detectar"] == pytest.approx(0.0027, abs=1e-4)
    assert zero["cmc"] == pytest.approx(370.4, abs=0.5)


def test_desempenho_atributos_e_amplitude():
    # carta p: β calculado pela binomial é a soma direta das probabilidades
    n, lic, lsc, p1 = 100, 0.0, 0.10, 0.08
    esperado = sum(prob.binomial_pmf(k, n, p1) for k in range(0, 11))
    assert prob.desempenho_p(p1, n, lic, lsc)["beta"] == pytest.approx(esperado)
    # carta c
    esperado = sum(prob.poisson_pmf(k, 9.0) for k in range(0, 13))
    assert prob.desempenho_c(9.0, 0.0, 12.5)["beta"] == pytest.approx(esperado)
    # carta R, n = 5: alarme falso ≈ 0,0046 (a distribuição de R é assimétrica)
    alfa = 1 - prob_amplitude_entre(0.0, 2.114 * 2.326, 5)
    assert alfa == pytest.approx(0.0046, abs=3e-4)
