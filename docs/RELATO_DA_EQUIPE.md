# Relato do projeto

**Autor:** Felipe Duque _(matrícula)_
**Disciplina:** Controle Estatístico Remoto de Processos – FGA/UnB, 2º/2026

## 1. O problema

O programa que desenvolvi faz o controle estatístico de processos por meio de medições e cálculos
estatísticos, para que esses processos sejam mais bem aproveitados e mais eficazes. Ele recebe um
arquivo JSON com o plano da análise (tipo de carta, objetivo, limites de especificação e
medições), calcula os limites das cartas de controle X-barra e R, I-AM, p, np, c e u, aponta
pontos fora de controle e sinais de alerta, estima deslocamentos do processo e a chance de a carta
detectá-los, avalia a capacidade em relação à especificação e gera um relatório PDF com tudo o que
foi feito. Pode ser usado pelo menu no terminal, pela linha de comando ou por uma página web.

## 2. Como trabalhei

Realizei o estudo das cartas de controle exigidas e desenvolvi o software junto com um assistente
de IA, fazendo testes e implementações em conjunto e juntando habilidades técnicas e práticas. Os
resultados foram conferidos com o gabarito do simulado calculado à mão e com testes automatizados.

## 3. O que aprendi de CEP

O limite de controle é calculado a partir dos dados do próprio processo e indica se ele está
variando além do natural; o limite de especificação define as características aceitáveis para o
produto final. A calibração retira alguns pontos e recalcula os limites para garantir a precisão
das cartas de controle.

No simulado, a carta tem 0,61 de probabilidade de detectar o deslocamento: em cada amostra, a
chance de sucesso em detectar o problema é de 61%. O CMC de 1,64 significa que, em média, o sistema
leva 1,64 amostra para emitir o primeiro sinal de alarme.

## 4. O simulado da prova

O simulado tem 20 subgrupos de 5 medições, em milímetros. Com os limites tentativos, os subgrupos 2
e 17 ficaram fora da carta X-barra e o subgrupo 9 ficou fora da carta R. Depois de retirados, os
limites revisados da X-barra ficaram em 4,9496 / 4,9612 / 4,9728 mm, sem nenhum ponto restante fora.

Mesmo assim, restaram sinais de alerta: os primeiros subgrupos ficaram seguidamente abaixo da linha
central e os últimos, acima. O programa encontrou uma mudança de nível depois do subgrupo 10, de
4,9543 para 4,9670 mm (cerca de 1,5 desvio-padrão), e uma tendência de alta. Ou seja, o processo
não ficou estável: a média subiu ao longo da coleta.

Quanto à especificação, o processo é capaz (RCPk = 1,49), mas trabalha perto do limite superior:
a média só pode subir mais 1,48 desvio-padrão antes de começar a produzir peças fora.

## 5. Decisões e dificuldades

A decisão que considero mais esperta é a emissão de alertas, porque ela mostra mudanças no
processo antes que as peças saiam da especificação; no acompanhamento, cada novo arquivo de
medições já é comparado com os limites calibrados. A maior dificuldade foi implementar os cálculos
de todos os tipos de carta.

## 6. Próximos passos

Realizar a avaliação em aula com o software.
