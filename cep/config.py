"""Parâmetros gerais do programa, reunidos em um só lugar."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Limites de controle
# ---------------------------------------------------------------------------
# Distância dos limites até a linha central, em desvios-padrão da estatística
# plotada (limites "3-sigma", como no Montgomery & Runger).
L_SIGMA = 3.0

# ---------------------------------------------------------------------------
# Regras de sinais de alerta (regras Western Electric, Montgomery & Runger)
# ---------------------------------------------------------------------------
REGRA2_JANELA, REGRA2_MINIMO, REGRA2_SIGMAS = 3, 2, 2.0   # 2 de 3 além de 2σ
REGRA3_JANELA, REGRA3_MINIMO, REGRA3_SIGMAS = 5, 4, 1.0   # 4 de 5 além de 1σ
REGRA4_SEQUENCIA = 8          # 8 pontos seguidos do mesmo lado da linha central

# Alerta complementar de tendência: pontos seguidos sempre subindo ou sempre
# descendo. O livro cita corridas de 8 ou mais; 6 é o valor usual em
# programas de CEP (mais sensível). Ajuste aqui se o professor pedir outro.
TENDENCIA_SEQUENCIA = 6

# ---------------------------------------------------------------------------
# Calibração (Fase I)
# ---------------------------------------------------------------------------
MAX_ITERACOES_REVISAO = 10           # rodadas de "retira pontos e recalcula"
SUBGRUPOS_RECOMENDADOS = 20          # o Montgomery recomenda 20 a 25 subgrupos
FRACAO_MAXIMA_REMOVIDA = 0.5         # acima disso a calibração não é confiável

# ---------------------------------------------------------------------------
# Deslocamento e probabilidades
# ---------------------------------------------------------------------------
JANELA_RECENTE = 5                                   # pontos usados no "nível atual"
DESLOCAMENTOS_SIGMA = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]   # deslocamentos da média, em σ
RAZOES_SIGMA = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]       # σ1/σ0 para cartas de amplitude
FATORES_ATRIBUTOS = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]  # múltiplos de p̄, c̄ ou ū
AMOSTRAS_ATE_DETECTAR = [1, 2, 3, 4, 5, 10, 20]      # P(detectar em até m amostras)
NIVEL_SIGNIFICANCIA = 0.05
SEGMENTO_MINIMO = 3            # pontos mínimos de cada lado na mudança de nível

# ---------------------------------------------------------------------------
# Capacidade do processo
# ---------------------------------------------------------------------------
RCPK_CAPAZ = 1.33        # RCPk >= 1,33: processo capaz
RCPK_MINIMO = 1.0        # 1,00 <= RCPk < 1,33: marginal; abaixo de 1: não capaz

# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------
SEPARADOR_DECIMAL = ","  # vírgula no relatório e no terminal (os JSON usam ponto)

# ---------------------------------------------------------------------------
# Pastas
# ---------------------------------------------------------------------------
PASTA_SAIDA = Path("saida")              # relatórios, gráficos e calibrações
PASTA_CALIBRACOES = "calibracoes"        # subpasta de PASTA_SAIDA
PASTAS_DE_DADOS = ["dados", "exemplos", "entradas", "."]   # onde o menu procura JSON
PASTA_ENTRADAS = Path("entradas")        # JSON gerados pelo módulo de entrada

# O menu também mostra os JSON baixados recentemente (por exemplo, o arquivo da
# prova), procurando nestas pastas dentro da pasta do usuário.
PASTAS_DOWNLOADS = ["Downloads", "Transferências"]
DIAS_DOWNLOADS = 7          # só arquivos baixados nos últimos 7 dias
MAX_DOWNLOADS = 10          # no máximo 10, do mais recente para o mais antigo
