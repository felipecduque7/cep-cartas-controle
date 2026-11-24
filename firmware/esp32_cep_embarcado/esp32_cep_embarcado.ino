// =====================================================================================
// CEP EMBARCADO em malha fechada – o próprio ESP32 é o servidor
//
// O ESP32 mede a temperatura (DS18B20), roda a carta X-barra e R (cep_embarcado.h:
// aquecimento com PI, calibração com revisão dos limites, regras 1 a 4 e tendência) e
// ajusta o PWM do aquecedor sozinho. Ele também serve uma página web com o estado e o
// gráfico: conecte o celular na rede "CEP-Estufa" e abra http://192.168.4.1
//
// Bibliotecas (Arduino IDE > Gerenciador de Bibliotecas):
//   OneWire (Paul Stoffregen), DallasTemperature (Miles Burton), ArduinoJson 7 (Benoit Blanchon)
// Placa: "ESP32 Dev Module" (pacote esp32 da Espressif, versão 2.x ou 3.x).
// O arquivo cep_embarcado.h precisa ficar nesta mesma pasta.
// =====================================================================================

#include <WiFi.h>
#include <WebServer.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#if __has_include(<esp_arduino_version.h>)
#include <esp_arduino_version.h>
#endif
#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 2
#endif
#include "cep_embarcado.h"

// ---------------- CONFIGURE AQUI ----------------
// Por padrão o ESP32 cria a própria rede (ponto de acesso) e a página fica em http://192.168.4.1
const char* AP_NOME = "CEP-Estufa";
const char* AP_SENHA = "cep12345";       // mínimo de 8 caracteres
// Para usar a rede da sala, troque para true e preencha: o IP aparece no Monitor Serial.
const bool USAR_REDE_EXISTENTE = false;
const char* REDE = "NOME_DA_REDE";
const char* SENHA = "SENHA_DA_REDE";

const unsigned long INTERVALO_MS = 1000; // uma leitura por segundo
const float TEMP_MAXIMA = 45.0;          // corte de segurança, em °C

const int PINO_SENSOR = 4;
const int PINO_AQUECEDOR = 25;
const int PINO_COOLER = 26;
const int PINO_ALARME = 2;
const int PWM_COOLER = 0;
const int PWM_FREQ = 1000;
const int PWM_BITS = 8;
const int CANAL_AQUECEDOR = 0, CANAL_COOLER = 1;   // usados só no pacote esp32 2.x
// -------------------------------------------------

OneWire barramento(PINO_SENSOR);
DallasTemperature sensores(&barramento);
WebServer servidor(80);

cep::Configuracao configuracao;          // alvo 35 °C, LIE 32, LSE 38, n = 5, 20 subgrupos (veja cep_embarcado.h)
cep::MalhaCEP malha(configuracao);
float subgrupo[cep::N_MAX];
int lidas = 0;
float ultimaLeitura = NAN;
bool falhaSensor = false;
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

// ---------------- Página web ----------------
const char PAGINA[] PROGMEM = R"html(<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>CEP embarcado</title>
<style>
:root{--f:#f6f6f3;--c:#fff;--t:#111;--m:#666;--b:#ddd;--a:#2a78d6;--v:#d03b3b;--l:#ec835a;--g:#0ca30c}
@media(prefers-color-scheme:dark){:root{--f:#141414;--c:#1e1e1e;--t:#eee;--m:#aaa;--b:#333}}
body{margin:0;padding:16px;background:var(--f);color:var(--t);font:15px/1.4 system-ui,sans-serif}
main{max-width:900px;margin:auto}h1{font-size:19px;margin:0 0 12px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.k{background:var(--c);border:1px solid var(--b);border-radius:10px;padding:10px}
.r{color:var(--m);font-size:12px}.v{font-size:20px;font-weight:600}
#e{margin:12px 0;padding:10px;border-radius:8px;background:var(--c);border-left:5px solid var(--g)}
#e.al{border-color:var(--v)}svg{width:100%;height:auto}polyline{fill:none;stroke:var(--a);stroke-width:2}
.lim{stroke:var(--v);stroke-dasharray:6 4}.lc{stroke:var(--m)}text{fill:var(--m);font-size:11px}
button{margin-top:12px;padding:8px 14px;border-radius:8px;border:1px solid var(--b);background:var(--c);color:var(--t)}
</style></head><body><main><h1>CEP embarcado no ESP32 · estufa</h1>
<div class="g">
<div class="k"><div class="r">Fase</div><div class="v" id="fase">–</div></div>
<div class="k"><div class="r">Temperatura</div><div class="v" id="temp">–</div></div>
<div class="k"><div class="r">Última média</div><div class="v" id="media">–</div></div>
<div class="k"><div class="r">PWM</div><div class="v" id="pwm">–</div></div>
<div class="k"><div class="r">Subgrupos / ajustes</div><div class="v" id="cont">–</div></div></div>
<div id="e">Carregando...</div>
<div class="k"><div class="r" id="lim">Limites ainda não calibrados</div><svg id="graf" viewBox="0 0 640 220"></svg></div>
<button onclick="fetch('/recalibrar',{method:'POST'}).then(atualizar)">Recalibrar (mantém o aquecimento)</button>
<p class="r">Atualiza a cada 2 s · JSON em <a href="/dados">/dados</a></p></main>
<script>
const F={aquecimento:'Aquecimento',calibracao:'Calibração',acompanhamento:'Acompanhamento'};
const fx=(v,c=2)=>v==null?'–':Number(v).toFixed(c).replace('.',',');
function desenhar(d){const h=d.historico,L=d.limites,s=document.getElementById('graf');
 if(h.length<2){s.innerHTML='';return}
 let vs=h.concat([d.alvo]);if(L.calibrado)vs=vs.concat([L.lic,L.lsc]);
 let a=Math.min(...vs),b=Math.max(...vs),f=(b-a)*.12||.5;a-=f;b+=f;
 const W=640,H=220,M=34,px=i=>M+i*(W-2*M)/(h.length-1),py=v=>H-M/2-(v-a)*(H-M)/(b-a);
 let o='';if(L.calibrado)for(const[k,c]of[['lsc','lim'],['lc','lc'],['lic','lim']]){const y=py(L[k]);
 o+=`<line class="${c}" x1="${M}" x2="${W-M}" y1="${y}" y2="${y}"/><text x="${W-M+4}" y="${y+4}">${k.toUpperCase()}</text>`}
 o+=`<polyline points="${h.map((v,i)=>px(i)+','+py(v)).join(' ')}"/>`;s.innerHTML=o}
function atualizar(){fetch('/dados').then(r=>r.json()).then(d=>{
 document.getElementById('fase').textContent=F[d.fase]||d.fase;
 document.getElementById('temp').textContent=fx(d.temperatura)+' °C';
 document.getElementById('media').textContent=fx(d.ultima.media)+' °C';
 document.getElementById('pwm').textContent=d.pwm;
 document.getElementById('cont').textContent=d.recebidos+' / '+d.ajustes;
 const L=d.limites;document.getElementById('lim').textContent=L.calibrado?
  `X-barra: LIC ${fx(L.lic)} · LC ${fx(L.lc)} · LSC ${fx(L.lsc)} °C · R: LSC ${fx(L.rlsc)} · retirados ${L.retirados}`:
  'Limites ainda não calibrados';
 const e=document.getElementById('e');e.className=d.ultima.alarme?'al':'';e.textContent=d.mensagem;desenhar(d)})
 .catch(()=>{document.getElementById('e').textContent='Sem resposta do ESP32...'})}
atualizar();setInterval(atualizar,2000);
</script></body></html>)html";

String mensagem() {
  const cep::Decisao& d = malha.ultima;
  if (falhaSensor) return "Falha no sensor: aquecedor desligado. Confira o DS18B20.";
  if (d.numero == 0) return "Aguardando o primeiro subgrupo...";
  if (malha.fase == cep::ACOMPANHAMENTO && d.fase == cep::CALIBRACAO)
    return d.alarme ? "Calibração concluída, mas ainda restam pontos fora: confira o processo."
                    : "Calibração concluída: acompanhando com os limites calibrados.";
  char texto[200];
  switch (malha.fase) {
    case cep::AQUECIMENTO:
      snprintf(texto, sizeof texto, "Aquecimento até %.1f °C (controlador PI).", configuracao.alvo);
      break;
    case cep::CALIBRACAO:
      snprintf(texto, sizeof texto, "Calibrando com PWM fixo em %d.", malha.pwm);
      break;
    default:
      if (d.acao == cep::DESLIGAR)
        snprintf(texto, sizeof texto, "Média acima do LSE: aquecedor desligado.");
      else if (d.acao == cep::VERIFICAR)
        snprintf(texto, sizeof texto, "Amplitude acima do LSC da carta R: variação anormal. PWM mantido.");
      else if (d.regra == '1')
        snprintf(texto, sizeof texto, "Subgrupo %d fora dos limites da X-barra: PWM ajustado para %d.",
                 d.numero, d.pwm);
      else if (d.regra == 'T')
        snprintf(texto, sizeof texto, "Subgrupo %d: tendência na X-barra. PWM ajustado para %d.", d.numero, d.pwm);
      else if (d.regra != '-')
        snprintf(texto, sizeof texto, "Subgrupo %d: regra %c na X-barra. PWM ajustado para %d.", d.numero,
                 d.regra, d.pwm);
      else
        snprintf(texto, sizeof texto, "Sem sinais: processo sob controle, PWM mantido em %d.", d.pwm);
  }
  return String(texto);
}

void enviarDados() {
  JsonDocument doc;
  doc["fase"] = cep::nomeFase(malha.fase);
  doc["temperatura"] = isnan(ultimaLeitura) ? 0.0f : ultimaLeitura;
  doc["pwm"] = malha.pwm;
  doc["recebidos"] = malha.recebidos;
  doc["ajustes"] = malha.ajustes;
  doc["alvo"] = configuracao.alvo;
  doc["lse"] = configuracao.lse;
  doc["lie"] = configuracao.lie;
  doc["mensagem"] = mensagem();
  JsonObject u = doc["ultima"].to<JsonObject>();
  u["numero"] = malha.ultima.numero;
  u["media"] = malha.ultima.media;
  u["amplitude"] = malha.ultima.amplitude;
  u["acao"] = cep::nomeAcao(malha.ultima.acao);
  u["alarme"] = malha.ultima.alarme || falhaSensor;
  char regra[2] = {malha.ultima.regra, 0};
  u["regra"] = regra;
  JsonObject l = doc["limites"].to<JsonObject>();
  l["calibrado"] = malha.fase == cep::ACOMPANHAMENTO;
  l["lic"] = malha.lim.lic;
  l["lc"] = malha.lim.lc;
  l["lsc"] = malha.lim.lsc;
  l["rlsc"] = malha.lim.rlsc;
  l["retirados"] = malha.lim.retirados;
  l["confiavel"] = malha.lim.confiavel;
  float historico[60];
  int q = malha.historico(historico, 60);
  JsonArray h = doc["historico"].to<JsonArray>();
  for (int i = 0; i < q; i++) h.add(roundf(historico[i] * 100.0f) / 100.0f);
  String corpo;
  serializeJson(doc, corpo);
  servidor.send(200, "application/json", corpo);
}

void iniciarRede() {
  if (USAR_REDE_EXISTENTE) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(REDE, SENHA);
    Serial.printf("Conectando a %s", REDE);
    unsigned long inicio = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) { delay(300); Serial.print("."); }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\nPágina: http://%s\n", WiFi.localIP().toString().c_str());
      return;
    }
    Serial.println("\nNão conectou; criando a rede própria do ESP32.");
  }
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_NOME, AP_SENHA);
  Serial.printf("Rede %s (senha %s). Página: http://%s\n", AP_NOME, AP_SENHA, WiFi.softAPIP().toString().c_str());
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PINO_ALARME, OUTPUT);
  configurarPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR);
  configurarPwm(PINO_COOLER, CANAL_COOLER);
  escreverPwm(PINO_COOLER, CANAL_COOLER, PWM_COOLER);
  escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, malha.pwm);

  sensores.begin();
  if (sensores.getDeviceCount() == 0) Serial.println("ATENÇÃO: nenhum DS18B20 encontrado. Confira as ligações.");
  sensores.setResolution(12);
  sensores.setWaitForConversion(false);

  iniciarRede();
  servidor.on("/", HTTP_GET, []() { servidor.send_P(200, "text/html; charset=utf-8", PAGINA); });
  servidor.on("/dados", HTTP_GET, enviarDados);
  servidor.on("/recalibrar", HTTP_POST, []() {
    malha.recalibrar();
    lidas = 0;
    servidor.send(200, "application/json", "{\"ok\":true}");
  });
  servidor.onNotFound([]() { servidor.send(404, "text/plain", "Use / ou /dados"); });
  servidor.begin();
}

void loop() {
  servidor.handleClient();
  unsigned long agora = millis();
  if (agora - ultimoTick < INTERVALO_MS) return;
  ultimoTick = agora;

  if (!conversaoPendente) {
    sensores.requestTemperatures();
    conversaoPendente = true;
    return;
  }
  float t = sensores.getTempCByIndex(0);
  sensores.requestTemperatures();

  if (t == DEVICE_DISCONNECTED_C || t < -50 || t > 125) {
    falhaSensor = true;
    escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, 0);
    digitalWrite(PINO_ALARME, HIGH);
    return;
  }
  falhaSensor = false;
  ultimaLeitura = t;
  if (t > TEMP_MAXIMA) {                    // segurança independente do CEP
    escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, 0);
    digitalWrite(PINO_ALARME, HIGH);
    lidas = 0;
    return;
  }
  subgrupo[lidas++] = t;
  if (lidas < configuracao.n) {
    escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, malha.pwm);
    return;
  }
  lidas = 0;
  cep::Decisao d;
  if (malha.receber(subgrupo, d)) {
    escreverPwm(PINO_AQUECEDOR, CANAL_AQUECEDOR, d.pwm);
    digitalWrite(PINO_ALARME, d.alarme ? HIGH : LOW);
    Serial.printf("#%d %s média %.2f PWM %d %s regra %c\n", d.numero, cep::nomeFase(d.fase), d.media, d.pwm,
                  cep::nomeAcao(d.acao), d.regra);
  }
}
