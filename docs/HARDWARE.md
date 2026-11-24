# Estufa com ESP32: CEP em malha fechada

Este guia leva o software de cartas de controle para um processo físico. Uma pequena estufa
precisa ficar em **35 °C**. O ESP32 mede a temperatura, a carta X-barra e R decide quando
o processo saiu do estado calibrado, e o PWM do aquecedor é corrigido. Isso fecha a malha.

As duas apresentações da disciplina saem do mesmo hardware:

| Avaliação | Quem faz o CEP | Firmware | No PC |
|---|---|---|---|
| Servidor embarcado em MCU, malha fechada | o próprio ESP32 | `firmware/esp32_cep_embarcado` | nada (a página abre no celular) |
| CEP remoto com servidor externo, malha fechada | o `servidor.py` no PC | `firmware/esp32_estufa_remoto` | `python servidor.py` |

## 1. Como a malha funciona

```
 DS18B20 ──► ESP32 ──(subgrupo de 5 leituras)──► CEP (ESP32 ou servidor.py)
   ▲            │                                     │
   │            ◄──────────(PWM e alarme)─────────────┘
   └── estufa ◄── aquecedor (MOSFET + resistor de potência)
```

1. **Aquecimento.** Um controlador PI leva a média dos subgrupos até o alvo. A próxima
   fase só começa quando 5 subgrupos seguidos ficam a até 0,3 °C do alvo, sem derivar.
2. **Calibração (Fase I).** Com o PWM **fixo**, 20 subgrupos formam a calibração da carta
   X-barra e R. Os pontos fora dos limites saem e os limites são recalculados, como no menu.
3. **Acompanhamento (Fase II).** Cada subgrupo novo é avaliado com as regras 1 a 4 e a
   tendência. **Sem sinal, o PWM não muda**: mexer no processo a cada pequena variação só
   aumenta a variabilidade (o experimento do funil de Deming). Com sinal, a correção é
   proporcional ao deslocamento estimado:

   `PWM novo = PWM + ganho × (LC − nível do sinal)`

   Depois de corrigir, o controlador espera 8 subgrupos para a estufa responder, e a
   contagem das regras recomeça.
4. **Segurança.** Se a média passar do LSE, o aquecedor desliga. Independente do CEP, o
   firmware também corta o aquecedor acima de 45 °C ou se o sensor falhar.

## 2. Componentes

| Item | Sugestão | Observação |
|---|---|---|
| Microcontrolador | ESP32 DevKit (30 ou 38 pinos) | só WiFi de 2,4 GHz |
| Sensor | DS18B20 com ponta à prova d'água + resistor de 4,7 kΩ | digital (1-Wire), resolução de 0,0625 °C |
| Aquecedor | resistor de potência de 10 Ω / 20 W (tipo cimento) | a 12 V dissipa cerca de 14 W |
| Chave do aquecedor | MOSFET de nível lógico: IRLZ44N ou módulo D4184 | o IRF520 **não** serve: não satura com 3,3 V |
| Resistores do MOSFET | 220 Ω (gate) e 10 kΩ (gate ao GND) | o de 10 kΩ mantém o aquecedor desligado no boot |
| Fonte | 12 V / 2 A | o GND da fonte precisa ser **o mesmo** do ESP32 |
| Ventoinha (opcional) | cooler 12 V 80 mm + 2º MOSFET + diodo 1N4007 | serve para circular o ar e para provocar perturbações |
| Caixa | isopor ou MDF pequeno (cerca de 20 × 15 × 15 cm) | o resistor fica numa chapa de alumínio, sem encostar no isopor |
| Alarme | LED da própria placa (GPIO 2) ou LED + 330 Ω / buzzer | |

## 3. Ligações

| ESP32 | Liga em |
|---|---|
| 3V3 | VDD do DS18B20 e um lado do resistor de 4,7 kΩ |
| GPIO 4 | DADOS do DS18B20 e o outro lado do 4,7 kΩ |
| GND | GND do DS18B20, source dos MOSFETs e GND da fonte de 12 V |
| GPIO 25 | resistor de 220 Ω → gate do MOSFET do aquecedor (10 kΩ do gate ao GND) |
| GPIO 26 | (opcional) 220 Ω → gate do MOSFET da ventoinha |
| GPIO 2 | LED de alarme (já existe na placa) |

Do lado da potência: **+12 V → resistor de potência → dreno do MOSFET**, e o source do MOSFET
vai ao GND. A ventoinha segue o mesmo esquema, com o diodo 1N4007 em paralelo com ela
(catodo no +12 V).

> Cuidado: o resistor de potência passa de 100 °C na superfície. Prenda-o numa chapa de
> metal, longe do isopor e dos fios, e nunca deixe a estufa ligada sem ninguém por perto.

## 4. Gravar o ESP32

1. **Arduino IDE → Preferências → URLs adicionais:**
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. **Gerenciador de Placas:** instale "esp32" (Espressif). As versões 2.x e 3.x funcionam.
3. **Gerenciador de Bibliotecas:** instale OneWire, DallasTemperature e ArduinoJson (versão 7).
4. Abra o sketch, escolha a placa **ESP32 Dev Module** e a porta COM, e clique em Carregar.
5. Abra o **Monitor Serial a 115200**. Ele mostra cada leitura e cada decisão.

### Versão embarcada (`esp32_cep_embarcado`)
Não precisa configurar nada. O ESP32 cria a rede **CEP-Estufa** (senha `cep12345`): conecte
o celular nela e abra **http://192.168.4.1**. Na página estão a fase, a temperatura, o PWM,
os limites calibrados, o gráfico das médias e o botão **Recalibrar**.

### Versão remota (`esp32_estufa_remoto`)
1. No PC, na pasta do projeto: `python servidor.py`. Ele mostra o endereço que vai no firmware:
   `No firmware do ESP32: SERVIDOR = "http://192.168.x.x:8000/medicoes"`.
2. No sketch, preencha `WIFI_SSID`, `WIFI_SENHA` e `SERVIDOR`. **O PC e o ESP32 precisam
   estar na mesma rede de 2,4 GHz.** A rede da UnB (eduroam) não serve para o ESP32; use o
   roteador do celular.
3. Grave o ESP32 e abra o painel no navegador: `http://localhost:8000`.
4. Se o Windows perguntar, permita o Python em **redes privadas** no firewall.
5. No fim, use **Ctrl+C** no servidor (ou abra `/relatorio`) para gerar o relatório PDF.
   O PDF traz a calibração, o acompanhamento com a carta, o gráfico da malha (média e PWM)
   e a tabela de cada ajuste.

## 5. Testar sem o hardware

O simulador faz o papel do ESP32, com uma estufa virtual (modelo de 1ª ordem com ruído):

```
python servidor.py                          (terminal 1)
python ferramentas/simulador_esp32.py       (terminal 2)
```

No subgrupo 100, a "porta abre": o ambiente esfria 4 °C, a carta sinaliza e o servidor aumenta
o PWM até a estufa voltar ao nível calibrado. Acompanhe tudo pelo painel em `http://localhost:8000`.

## 6. Ajustar ao seu hardware

Os padrões (`ganho` 10 e `espera` 8) foram ajustados para a estufa simulada. Numa caixa real,
meça uma vez:

1. **Ganho do processo.** Com PWM fixo em 128, espere estabilizar e anote a temperatura. Depois
   use PWM 178 (+50) e anote de novo. Se subiu ΔT graus, K = ΔT / 50 °C por unidade de PWM.
   Use `--ganho` ≈ 0,8 / K: um pouco menos que a correção completa, para não passar do ponto.
2. **Tempo de resposta.** Conte quanto tempo a temperatura leva para fazer 2/3 da subida (τ).
   Use `--espera` ≈ 2τ dividido por 5 s, que é a duração de um subgrupo.

Exemplo: `python servidor.py --ganho 15 --espera 24`. Na versão embarcada, os mesmos valores
ficam na `Configuracao`, em `cep_embarcado.h`.

## 7. Roteiro da demonstração (cerca de 10 min)

1. Mostrar o hardware e o painel (o do servidor ou o do ESP32 no celular).
2. **Aquecimento:** o PI leva a estufa a 35 °C. Explicar por que a calibração espera o processo parar.
3. **Calibração:** os limites aparecem no painel. Relacionar com a Fase I do software (pontos retirados, limites revisados).
4. **Acompanhamento sem perturbação:** o PWM não muda. Explicar que não se ajusta sem sinal.
5. **Perturbação:** abrir a tampa, ligar a ventoinha ou encostar um gelo perto do sensor. A
   carta sinaliza (regra 1, 2, 3, 4 ou tendência), o painel registra o ajuste e a temperatura volta.
6. **Relatório:** gerar o PDF e mostrar a carta do acompanhamento e o gráfico da malha.
7. Comparar as duas versões: no MCU tudo é local e rápido; no servidor externo o histórico fica
   guardado, há relatório completo e vários ESP32 poderiam mandar dados para o mesmo servidor.

## 8. Limitações para comentar

- Temperatura é um processo lento e **autocorrelacionado**: leituras seguidas são parecidas, então a
  amplitude dentro do subgrupo subestima a variação entre subgrupos e os limites ficam estreitos.
  Espaçar as leituras (por exemplo, `INTERVALO_MS` de 2 a 5 s) ajuda.
- O CEP detecta a mudança e o ajuste a corrige. A correção não é um controle contínuo: perturbações
  rápidas e pequenas são absorvidas pela variação natural, de propósito.
- A versão remota depende da rede. Se o servidor cair, o ESP32 entra num liga/desliga local
  (o LED pisca) até a conexão voltar.
