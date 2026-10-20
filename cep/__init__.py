"""CEP – Controle Estatístico de Processos com cartas de controle.

Pacote do trabalho da disciplina Controle Estatístico Remoto de Processos
(Engenharia Eletrônica – FGA/UnB). Referência principal: Montgomery & Runger,
"Estatística Aplicada e Probabilidade para Engenheiros" (LTC), capítulo de
Controle Estatístico da Qualidade.

Organização:
    leitura        lê e valida o JSON (o "plano" da análise)
    cartas         estatísticas e limites de cada carta (X-barra/R, I/AM, p, np, c, u)
    regras         regras Western Electric e tendência (sinais de alerta)
    analise        calibração (Fase I) e acompanhamento (Fase II)
    deslocamento   deslocamento, mudança de nível, tendência, curva CO e CMC
    capacidade     razões de capacidade RCP e RCPk
    probabilidade  binomial, arranjos, combinações, geométrica, Poisson, normal
    calibracoes    salvar e carregar calibrações em JSON
    graficos       figuras das cartas (matplotlib)
    relatorio      relatório PDF cumulativo da sessão
    apresentacao   textos de interpretação e saída no terminal
    entrada        módulo de entrada de medições (teclado, CSV, porta serial)
    menu           menu interativo
"""

__version__ = "1.1.0"
