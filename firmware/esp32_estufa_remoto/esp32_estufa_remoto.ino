// =====================================================================================
// CEP REMOTO em malha fechada – estufa com ESP32
//
// O ESP32 mede a temperatura (DS18B20), junta N leituras num subgrupo e envia ao
// servidor (servidor.py) por WiFi/HTTP. O servidor roda o CEP (carta X-barra e R) e
// responde com o PWM do aquecedor e se há alarme. O ESP32 aplica a resposta: malha fechada.
//
// Segurança local: se a temperatura passar de TEMP_MAXIMA, ou o sensor falhar, o
// aquecedor desliga na hora, sem esperar o servidor. Se o servidor ficar fora do ar,
// o ESP32 segura a estufa perto do alvo com um liga/desliga simples até ele voltar.
//
// Bibliotecas (Arduino IDE > Gerenciador de Bibliotecas):
//   OneWire (Paul Stoffregen), DallasTemperature (Miles Burton), ArduinoJson 7 (Benoit Blanchon)
// Placa: "ESP32 Dev Module" (pacote esp32 da Espressif, versão 2.x ou 3.x).
// =====================================================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#if __has_include(<esp_arduino_version.h>)
#include <esp_arduino_version.h>
#endif
#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 2
#endif

// ---------------- CONFIGURE AQUI ----------------
const char* WIFI_SSID = "NOME_DA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";
// O servidor.py mostra este endereço quando é iniciado ("No firmware do ESP32: ...").
const char* SERVIDOR = "http://192.168.0.10:8000/medicoes";
const char* DISPOSITIVO = "esp32-estufa";

const int N = 5;                         // medições por subgrupo (igual ao --n do servidor)
const unsigned long INTERVALO_MS = 1000; // uma leitura por segundo
const float TEMP_MAXIMA = 45.0;          // corte de segurança local, em °C
const float ALVO_LOCAL = 35.0;           // usado só se o servidor ficar fora do ar
const int FALHAS_PARA_MODO_LOCAL = 3;

const int PINO_SENSOR = 4;               // DS18B20 (dados), com resistor de 4,7 kΩ para 3,3 V
const int PINO_AQUECEDOR = 25;           // gate do MOSFET do aquecedor
const int PINO_COOLER = 26;              // transistor do cooler (opcional)
const int PINO_ALARME = 2;               // LED da placa (ou LED/buzzer externo)
const int PWM_COOLER = 0;                // 0 = desligado; ~120 deixa o ar circulando
const int PWM_FREQ = 1000;               // Hz
const int PWM_BITS = 8;                  // PWM de 0 a 255 (igual ao servidor)
const int CANAL_AQUECEDOR = 0, CANAL_COOLER = 1;   // usados só no pacote esp32 2.x
// -------------------------------------------------

OneWire barramento(PINO_SENSOR);
DallasTemperature sensores(&barramento);

float subgrupo[N];
int lidas = 0;
int pwmAtual = 128;
bool alarme = false;
int falhas = 0;
bool conversaoPendente = false;
unsigned long ultimoTick = 0;

void configurarPwm(int pino, int canal) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  (void)canal;
  ledcAttach(pino, PWM_FREQ, PWM_BITS);
#else
  ledcSetup(canal, PWM_FREQ, PWM_BITS);
  ledcAttachPin(pino, canal);
#endif
}

void escreverPwm(int pino, int canal, int valor) {
  valor = constrain(valor, 0, 255);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  (void)canal;
  ledcWrite(pino, valor);
#else
  (void)pino;
  ledcWrite(canal, valor);
#endif
}

void aplicarAquecedor(int pwm) {
  pwmAtual = constrain(pwm, 0, 255);
  escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, pwmAtual);
}

void conectarWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Conectando ao WiFi %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 15000) {
    delay(300);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nConectado. IP do ESP32: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nSem WiFi por enquanto; tento de novo no próximo subgrupo.");
  }
}

// Envia o subgrupo e lê a decisão do servidor. Devolve false se algo falhar.
bool enviarSubgrupo() {
  conectarWiFi();
  if (WiFi.status() != WL_CONNECTED) return false;

  JsonDocument pedido;
  pedido["dispositivo"] = DISPOSITIVO;
  pedido["pwm"] = pwmAtual;
  JsonArray valores = pedido["subgrupo"].to<JsonArray>();
  for (int i = 0; i < N; i++) valores.add(roundf(subgrupo[i] * 100.0f) / 100.0f);
  String corpo;
  serializeJson(pedido, corpo);

  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(SERVIDOR)) return false;
  http.addHeader("Content-Type", "application/json");
  int codigo = http.POST(corpo);
  String texto = codigo > 0 ? http.getString() : String();
  http.end();
  if (codigo != 200) {
    Serial.printf("Servidor respondeu %d %s\n", codigo, texto.c_str());
    return false;
  }

  JsonDocument resposta;
  if (deserializeJson(resposta, texto)) {
    Serial.println("Resposta do servidor não é um JSON válido.");
    return false;
  }
  int pwm = resposta["pwm"] | pwmAtual;
  alarme = resposta["alarme"] | false;
  const char* fase = resposta["fase"] | "?";
  const char* acao = resposta["acao"] | "?";
  const char* motivo = resposta["motivo"] | "";
  aplicarAquecedor(pwm);
  Serial.printf("[%s] %s -> PWM %d%s | %s\n", fase, acao, pwmAtual, alarme ? " ALARME" : "", motivo);
  return true;
}

// Liga/desliga simples, só enquanto o servidor estiver fora do ar.
void controleLocal(float media) {
  if (media < ALVO_LOCAL - 0.5f) aplicarAquecedor(200);
  else if (media > ALVO_LOCAL + 0.5f) aplicarAquecedor(0);
  Serial.printf("Modo local (servidor fora do ar): média %.2f -> PWM %d\n", media, pwmAtual);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PINO_ALARME, OUTPUT);
  configurarPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR);
  configurarPwm(PINO_COOLER, CANAL_COOLER);
  escreverPwm(PINO_COOLER, CANAL_COOLER, PWM_COOLER);
  aplicarAquecedor(pwmAtual);

  sensores.begin();
  if (sensores.getDeviceCount() == 0) Serial.println("ATENÇÃO: nenhum DS18B20 encontrado. Confira as ligações.");
  sensores.setResolution(12);
  sensores.setWaitForConversion(false);   // não trava o loop durante a conversão (~750 ms)
  conectarWiFi();
}

void loop() {
  unsigned long agora = millis();
  if (agora - ultimoTick < INTERVALO_MS) return;
  ultimoTick = agora;

  if (!conversaoPendente) {               // primeira passada: só pede a conversão
    sensores.requestTemperatures();
    conversaoPendente = true;
    return;
  }
  float t = sensores.getTempCByIndex(0);
  sensores.requestTemperatures();          // já pede a próxima

  if (t == DEVICE_DISCONNECTED_C || t < -50 || t > 125) {
    aplicarAquecedor(0);                   // sem leitura confiável, nada de aquecer
    alarme = true;
    Serial.println("Falha no sensor: aquecedor desligado.");
  } else if (t > TEMP_MAXIMA) {
    aplicarAquecedor(0);
    alarme = true;
    Serial.printf("%.2f °C acima de TEMP_MAXIMA: aquecedor desligado.\n", t);
    lidas = 0;
  } else {
    subgrupo[lidas++] = t;
    Serial.printf("Leitura %d/%d: %.2f °C\n", lidas, N, t);
    if (lidas == N) {
      lidas = 0;
      if (enviarSubgrupo()) {
        falhas = 0;
      } else if (++falhas >= FALHAS_PARA_MODO_LOCAL) {
        float soma = 0;
        for (int i = 0; i < N; i++) soma += subgrupo[i];
        controleLocal(soma / N);
      }
    }
  }
  // LED: aceso com alarme; piscando (1 s aceso, 1 s apagado) no modo local
  static bool fase = false;
  fase = !fase;
  bool piscar = falhas >= FALHAS_PARA_MODO_LOCAL && fase;
  digitalWrite(PINO_ALARME, (alarme || piscar) ? HIGH : LOW);
}
