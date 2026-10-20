"""Gera arquivos JSON de exemplo (dados simulados) para todos os tipos de carta.

Os exemplos usam o mesmo formato do arquivo da prova e servem para testar o
programa com cartas que ainda não vieram do professor (R, IMR, P, NP, C, U)
e com acompanhamento. São dados SIMULADOS, gerados com semente fixa.

Uso: python ferramentas/gerar_exemplos.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cep.entrada import montar_json, salvar_json  # noqa: E402

PASTA = RAIZ / "exemplos"
AUTOR = "exemplo simulado (cep-cartas-controle)"


def normal(rng, media, desvio, casas=3):
    return round(rng.gauss(media, desvio), casas)


def salvar(nome, conteudo):
    destino = PASTA / nome
    if destino.exists():
        destino.unlink()
    caminho = salvar_json(conteudo, PASTA, nome)
    print("gerado:", caminho.relative_to(RAIZ))


def main():
    PASTA.mkdir(exist_ok=True)
    rng = random.Random(2026)

    # X-barra/R – acompanhamento do mesmo processo do simulado, com deslocamento a partir do subgrupo 9
    dados = []
    for i in range(15):
        media = 4.961 + (0.013 if i >= 8 else 0.0)
        dados.append([normal(rng, media, 0.0087) for _ in range(5)])
    salvar("exemplo_x_acompanhar.json", montar_json(
        "X", "Acompanhar", dados, "mm", 5.0, 4.0, AUTOR, "Diâmetro – acompanhamento (exemplo)",
        "2026-10-16 09:00:00"))

    # X-barra/R com subgrupos de tamanho variável
    dados = [[normal(rng, 12.0, 0.05) for _ in range(rng.choice([3, 4, 5, 6]))] for _ in range(22)]
    salvar("exemplo_x_tamanho_variavel.json", montar_json(
        "X", "Calibrar", dados, "mm", 12.2, 11.8, AUTOR, "Comprimento – subgrupos de tamanho variável (exemplo)",
        "2026-10-10 14:00:00"))

    # R – variabilidade da tensão de saída de uma fonte
    dados = []
    for i in range(25):
        desvio = 0.10 if i in (7, 18) else 0.04
        dados.append([normal(rng, 5.0, desvio) for _ in range(4)])
    salvar("exemplo_r_calibrar.json", montar_json(
        "R", "Calibrar", dados, "V", 5.25, 4.75, AUTOR, "Tensão de saída da fonte (exemplo)",
        "2026-10-10 10:30:00"))

    # I-AM – temperatura medida por sensor, uma leitura por vez
    valores = [normal(rng, 25.0, 0.4, 2) for _ in range(30)]
    valores[17] = 27.1
    salvar("exemplo_imr_calibrar.json", montar_json(
        "IMR", "Calibrar", [[v] for v in valores], "°C", 27.0, 23.0, AUTOR,
        "Temperatura do dissipador (exemplo)", "2026-10-11 08:00:00"))

    valores = [normal(rng, 25.0 + 0.06 * i, 0.4, 2) for i in range(20)]
    salvar("exemplo_imr_acompanhar.json", montar_json(
        "IMR", "Acompanhar", [[v] for v in valores], "°C", 27.0, 23.0, AUTOR,
        "Temperatura do dissipador – acompanhamento (exemplo)", "2026-10-12 08:00:00"))

    # p – placas reprovadas no teste final, amostras de tamanho variável: pares [defeituosos, n]
    dados = []
    for i in range(25):
        n = rng.choice([80, 90, 100, 110, 120])
        p = 0.13 if i == 11 else 0.05
        dados.append([sum(rng.random() < p for _ in range(n)), n])
    salvar("exemplo_p_calibrar.json", montar_json(
        "P", "Calibrar", dados, "", None, None, AUTOR, "Placas reprovadas no teste final (exemplo)",
        "2026-10-09 16:00:00"))

    # p – acompanhamento com a linha central informada no próprio arquivo
    dados = []
    for i in range(15):
        n = 100
        p = 0.05 if i < 9 else 0.10
        dados.append([sum(rng.random() < p for _ in range(n)), n])
    conteudo = montar_json("P", "Acompanhar", dados, "", None, None, AUTOR,
                           "Placas reprovadas – acompanhamento com limites no arquivo (exemplo)", "2026-10-13 16:00:00")
    conteudo["Limites"] = {"LC": 0.05}
    salvar("exemplo_p_acompanhar_limites_no_arquivo.json", conteudo)

    # np – número de defeituosos com n fixo informado no campo "n"
    dados = [[sum(rng.random() < 0.08 for _ in range(50))] for _ in range(25)]
    salvar("exemplo_np_calibrar.json", montar_json(
        "NP", "Calibrar", dados, "", None, None, AUTOR, "Conectores com defeito em lotes de 50 (exemplo)",
        "2026-10-09 11:00:00", n=50))

    # c – defeitos de solda por placa
    def poisson(lam):
        limite, k, produto = 2.718281828459045 ** (-lam), 0, rng.random()
        while produto > limite:
            k += 1
            produto *= rng.random()
        return k
    contagens = [poisson(6.0) for _ in range(25)]
    contagens[20] = 16
    salvar("exemplo_c_calibrar.json", montar_json(
        "C", "Calibrar", [[c] for c in contagens], "", 15, None, AUTOR, "Defeitos de solda por placa (exemplo)",
        "2026-10-08 15:00:00"))
    contagens = [poisson(6.0 if i < 10 else 9.0) for i in range(20)]
    salvar("exemplo_c_acompanhar.json", montar_json(
        "C", "Acompanhar", [[c] for c in contagens], "", 15, None, AUTOR,
        "Defeitos de solda por placa – acompanhamento (exemplo)", "2026-10-15 15:00:00"))

    # u – defeitos por metro de cabo, comprimento inspecionado variável: pares [defeitos, unidades]
    dados = []
    for _ in range(25):
        unidades = rng.choice([1.0, 1.5, 2.0, 2.5])
        dados.append([poisson(3.0 * unidades), unidades])
    salvar("exemplo_u_calibrar.json", montar_json(
        "U", "Calibrar", dados, "", None, None, AUTOR, "Falhas de isolamento por metro de cabo (exemplo)",
        "2026-10-07 13:00:00"))


if __name__ == "__main__":
    main()
