// cep_embarcado.h – CEP (carta X-barra e R) em malha fechada, para rodar no próprio microcontrolador.
//
// É a mesma lógica do servidor Python (cep/malha.py), em C++ simples, sem alocação dinâmica e
// sem depender do Arduino: por isso dá para testar no computador (veja firmware/testes/).
//
//   Aquecimento: controlador PI incremental leva a média dos subgrupos ao alvo.
//   Calibração:  com o PWM fixo, N subgrupos viram a calibração (Fase I), com retirada dos
//                pontos fora dos limites e recálculo, como no software do PC.
//   Acompanhamento: regras 1 a 4 e tendência na X-barra e regra 1 na R. O PWM só muda quando
//                a carta dá um sinal; depois de um ajuste, espera o processo responder.
#pragma once

#include <math.h>
#include <stdint.h>
#include <string.h>

namespace cep {

const int N_MAX = 10;              // medições por subgrupo (2 a 10)
const int CAL_MAX = 40;            // subgrupos guardados para a calibração
const int JANELA = 30;             // subgrupos avaliados no acompanhamento

enum Fase { AQUECIMENTO = 0, CALIBRACAO = 1, ACOMPANHAMENTO = 2 };
enum Acao { MANTER = 0, AUMENTAR, REDUZIR, DESLIGAR, VERIFICAR };

inline const char* nomeFase(Fase f) {
  switch (f) {
    case AQUECIMENTO: return "aquecimento";
    case CALIBRACAO: return "calibracao";
    default: return "acompanhamento";
  }
}

inline const char* nomeAcao(Acao a) {
  switch (a) {
    case AUMENTAR: return "aumentar";
    case REDUZIR: return "reduzir";
    case DESLIGAR: return "desligar";
    case VERIFICAR: return "verificar";
    default: return "manter";
  }
}

// Fatores A2, D3, D4 para n = 2..10 (mesma tabela de cep/constantes.py).
inline void fatores(int n, float& A2, float& D3, float& D4) {
  static const float T[9][3] = {
      {1.880f, 0.000f, 3.267f}, {1.023f, 0.000f, 2.574f}, {0.729f, 0.000f, 2.282f},
      {0.577f, 0.000f, 2.114f}, {0.483f, 0.000f, 2.004f}, {0.419f, 0.076f, 1.924f},
      {0.373f, 0.136f, 1.864f}, {0.337f, 0.184f, 1.816f}, {0.308f, 0.223f, 1.777f}};
  int i = n < 2 ? 0 : (n > 10 ? 8 : n - 2);
  A2 = T[i][0]; D3 = T[i][1]; D4 = T[i][2];
}

struct Configuracao {
  float alvo = 35.0f;
  float lse = 38.0f;
  float lie = 32.0f;
  int n = 5;
  int subgruposCalibracao = 20;
  float ganho = 10.0f;           // ajuste: PWM por grau de desvio
  float kp = 20.0f;              // PI do aquecimento
  float ki = 5.0f;
  int pwmInicial = 128;
  int pwmMin = 0;
  int pwmMax = 255;
  float toleranciaAquecimento = 0.3f;
  int subgruposEstaveis = 5;
  int esperaAposAjuste = 8;
};

struct Limites {
  float lic = 0, lc = 0, lsc = 0;     // X-barra
  float rlc = 0, rlsc = 0, rlic = 0;  // R
  float sigmaMedia = 0;               // (LSC − LC) / 3, para as zonas das regras 2 e 3
  int usados = 0, retirados = 0;
  bool confiavel = false;             // nenhum ponto restante fora depois da revisão
};

struct Decisao {
  int numero = 0;
  Fase fase = AQUECIMENTO;
  Acao acao = MANTER;
  int pwm = 0;
  bool alarme = false;
  char regra = '-';                   // '1', '2', '3', '4', 'T', 'R' (amplitude) ou '-'
  float media = 0, amplitude = 0;
};

class MalhaCEP {
 public:
  Configuracao cfg;
  Fase fase = AQUECIMENTO;
  int pwm = 128;
  int recebidos = 0;
  int ajustes = 0;
  Limites lim;
  Decisao ultima;

  explicit MalhaCEP(const Configuracao& c = Configuracao()) { reiniciar(c); }

  void reiniciar(const Configuracao& c) {
    cfg = c;
    if (cfg.n < 2) cfg.n = 2;
    if (cfg.n > N_MAX) cfg.n = N_MAX;
    if (cfg.subgruposCalibracao > CAL_MAX) cfg.subgruposCalibracao = CAL_MAX;
    if (cfg.subgruposCalibracao < 5) cfg.subgruposCalibracao = 5;
    fase = AQUECIMENTO;
    pwm = limitar((float)cfg.pwmInicial);
    recebidos = ajustes = 0;
    nCal = nJan = nAquec = estaveis = espera = 0;
    temErroAnterior = false;
    lim = Limites();
    ultima = Decisao();
  }

  // Recalibra sem refazer o aquecimento (botão "recalibrar" da página).
  void recalibrar() {
    fase = CALIBRACAO;
    nCal = nJan = espera = 0;
    lim = Limites();
  }

  // Recebe um subgrupo de cfg.n medições e decide o PWM. Devolve false se o subgrupo for inválido.
  bool receber(const float* valores, Decisao& d) {
    float soma = 0, menor = valores[0], maior = valores[0];
    for (int i = 0; i < cfg.n; i++) {
      float v = valores[i];
      if (isnan(v) || isinf(v)) return false;
      soma += v;
      if (v < menor) menor = v;
      if (v > maior) maior = v;
    }
    recebidos++;
    float media = soma / cfg.n, amplitude = maior - menor;
    d = Decisao();
    d.numero = recebidos;
    d.media = media;
    d.amplitude = amplitude;
    d.fase = fase;
    if (fase == AQUECIMENTO) aquecer(media, d);
    else if (fase == CALIBRACAO) calibrar(media, amplitude, d);
    else acompanhar(media, amplitude, d);
    pwm = d.pwm;
    ultima = d;
    return true;
  }

  // Médias recentes, da mais antiga para a mais nova (para o gráfico da página).
  int historico(float* destino, int maximo) const {
    int quantos = nHist < maximo ? nHist : maximo;
    for (int i = 0; i < quantos; i++) {
      int idx = (inicioHist + nHist - quantos + i) % HIST;
      destino[i] = hist[idx];
    }
    return quantos;
  }

 private:
  static const int HIST = 120;
  float calMedias[CAL_MAX], calAmplitudes[CAL_MAX];
  float janMedias[JANELA];
  float hist[HIST];
  int nCal = 0, nJan = 0, nAquec = 0, estaveis = 0, espera = 0;
  int nHist = 0, inicioHist = 0;
  float recentes[16];
  float erroAnterior = 0;
  bool temErroAnterior = false;

  int limitar(float v) const {
    if (v < cfg.pwmMin) v = (float)cfg.pwmMin;
    if (v > cfg.pwmMax) v = (float)cfg.pwmMax;
    return (int)lroundf(v);
  }

  void guardarHistorico(float media) {
    if (nHist < HIST) hist[(inicioHist + nHist++) % HIST] = media;
    else { hist[inicioHist] = media; inicioHist = (inicioHist + 1) % HIST; }
  }

  void ajustarPara(float nivel, Decisao& d) {
    float novo = pwm + cfg.ganho * (lim.lc - nivel);
    d.pwm = limitar(novo);
    d.acao = d.pwm > pwm ? AUMENTAR : (d.pwm < pwm ? REDUZIR : MANTER);
  }

  // --- Fase 0 -----------------------------------------------------------------
  void aquecer(float media, Decisao& d) {
    guardarHistorico(media);
    float erro = cfg.alvo - media;
    int k = cfg.subgruposEstaveis < 16 ? cfg.subgruposEstaveis : 16;
    // guarda as últimas k médias para checar se o processo parou de derivar
    if (nAquec < k) recentes[nAquec++] = media;
    else { memmove(recentes, recentes + 1, sizeof(float) * (k - 1)); recentes[k - 1] = media; }
    float mn = recentes[0], mx = recentes[0];
    for (int i = 1; i < nAquec; i++) { if (recentes[i] < mn) mn = recentes[i]; if (recentes[i] > mx) mx = recentes[i]; }
    bool parado = nAquec < 2 || (mx - mn) <= cfg.toleranciaAquecimento;
    if (fabsf(erro) <= cfg.toleranciaAquecimento && parado) {
      estaveis++;
      d.pwm = pwm;
      d.acao = MANTER;
      if (estaveis >= cfg.subgruposEstaveis) { fase = CALIBRACAO; nCal = 0; }
      return;
    }
    estaveis = 0;
    float delta = cfg.ki * erro + (temErroAnterior ? cfg.kp * (erro - erroAnterior) : 0.0f);
    erroAnterior = erro;
    temErroAnterior = true;
    d.pwm = limitar(pwm + delta);
    d.acao = d.pwm > pwm ? AUMENTAR : (d.pwm < pwm ? REDUZIR : MANTER);
  }

  // --- Fase I -------------------------------------------------------------------
  void calibrar(float media, float amplitude, Decisao& d) {
    guardarHistorico(media);
    d.pwm = pwm;
    d.acao = MANTER;
    calMedias[nCal] = media;
    calAmplitudes[nCal] = amplitude;
    nCal++;
    if (nCal < cfg.subgruposCalibracao) return;
    calcularLimites();
    d.alarme = !lim.confiavel;
    fase = ACOMPANHAMENTO;
    nJan = espera = 0;
  }

 public:
  // Limites com revisão: retira os subgrupos fora (X-barra ou R) e recalcula, até não sobrar nenhum.
  // Público para os testes compararem com o software do PC.
  void calcularLimitesDe(const float* medias, const float* amplitudes, int m) {
    for (int i = 0; i < m && i < CAL_MAX; i++) { calMedias[i] = medias[i]; calAmplitudes[i] = amplitudes[i]; }
    nCal = m < CAL_MAX ? m : CAL_MAX;
    calcularLimites();
  }

 private:
  void calcularLimites() {
    float A2, D3, D4;
    fatores(cfg.n, A2, D3, D4);
    bool usado[CAL_MAX];
    for (int i = 0; i < nCal; i++) usado[i] = true;
    int usados = nCal;
    lim.confiavel = false;
    for (int rodada = 0; rodada <= 10; rodada++) {
      float sx = 0, sr = 0;
      for (int i = 0; i < nCal; i++) if (usado[i]) { sx += calMedias[i]; sr += calAmplitudes[i]; }
      float xbb = sx / usados, rbar = sr / usados;
      lim.lc = xbb; lim.lsc = xbb + A2 * rbar; lim.lic = xbb - A2 * rbar;
      lim.rlc = rbar; lim.rlsc = D4 * rbar; lim.rlic = D3 * rbar;
      lim.sigmaMedia = A2 * rbar / 3.0f;
      bool remover[CAL_MAX];
      int fora = 0;
      for (int i = 0; i < nCal; i++) {
        remover[i] = usado[i] && (calMedias[i] > lim.lsc || calMedias[i] < lim.lic ||
                                  calAmplitudes[i] > lim.rlsc || calAmplitudes[i] < lim.rlic);
        if (remover[i]) fora++;
      }
      if (fora == 0) { lim.confiavel = true; break; }
      if (usados - fora < 2) break;        // retiraria quase tudo: fica na última rodada possível
      for (int i = 0; i < nCal; i++) if (remover[i]) { usado[i] = false; usados--; }
    }
    lim.usados = usados;
    lim.retirados = nCal - usados;
  }

  // --- Fase II ------------------------------------------------------------------
  void acompanhar(float media, float amplitude, Decisao& d) {
    guardarHistorico(media);
    d.pwm = pwm;
    d.acao = MANTER;
    if (media > cfg.lse) {                         // segurança: passou da especificação
      d.pwm = cfg.pwmMin; d.acao = DESLIGAR; d.alarme = true; d.regra = '1';
      nJan = 0; espera = cfg.esperaAposAjuste; ajustes++;
      return;
    }
    if (espera > 0) {
      espera--;
      if (espera == 0) nJan = 0;                   // o transitório não entra nas regras
      return;
    }
    if (nJan < JANELA) janMedias[nJan++] = media;
    else { memmove(janMedias, janMedias + 1, sizeof(float) * (JANELA - 1)); janMedias[JANELA - 1] = media; }

    char regra = '-';
    float nivel = media;
    avaliar(regra, nivel);
    if (regra != '-') {
      ajustarPara(nivel, d);
      d.regra = regra;
      d.alarme = (regra == '1');
      nJan = 0;
      espera = cfg.esperaAposAjuste;
      ajustes++;
      return;
    }
    if (amplitude > lim.rlsc) { d.acao = VERIFICAR; d.alarme = true; d.regra = 'R'; }
  }

  // Avalia as regras sobre a janela, considerando só os sinais que incluem o ponto mais novo.
  void avaliar(char& regra, float& nivel) {
    int m = nJan;
    const float* x = janMedias;
    float s = lim.sigmaMedia;
    float z = s > 0 ? (x[m - 1] - lim.lc) / s : 0;
    // Regra 1
    if (x[m - 1] > lim.lsc || x[m - 1] < lim.lic) { regra = '1'; nivel = x[m - 1]; return; }
    if (s <= 0) return;
    // Regras 2 (2 de 3 além de 2σ) e 3 (4 de 5 além de 1σ), do mesmo lado do ponto novo
    const int janelas[2] = {3, 5}, minimos[2] = {2, 4};
    const float zonas[2] = {2.0f, 1.0f};
    const char nomes[2] = {'2', '3'};
    for (int r = 0; r < 2; r++) {
      int jan = janelas[r];
      if (m < jan) continue;
      float lado = z > 0 ? 1.0f : -1.0f;
      if (fabsf(z) <= zonas[r]) continue;          // o ponto novo precisa fazer parte do sinal
      int conta = 0; float soma = 0;
      for (int i = m - jan; i < m; i++) {
        float zi = (x[i] - lim.lc) / s;
        if (zi * lado > zonas[r]) { conta++; soma += x[i]; }
      }
      if (conta >= minimos[r]) { regra = nomes[r]; nivel = soma / conta; return; }
    }
    // Regra 4: 8 seguidos do mesmo lado
    if (m >= 8 && z != 0) {
      float lado = z > 0 ? 1.0f : -1.0f, soma = 0;
      bool todos = true;
      for (int i = m - 8; i < m; i++) { if ((x[i] - lim.lc) * lado <= 0) { todos = false; break; } soma += x[i]; }
      if (todos) { regra = '4'; nivel = soma / 8; return; }
    }
    // Tendência: 6 pontos sempre subindo ou sempre descendo
    if (m >= 6) {
      bool sobe = true, desce = true;
      for (int i = m - 5; i < m; i++) { if (!(x[i] > x[i - 1])) sobe = false; if (!(x[i] < x[i - 1])) desce = false; }
      if (sobe || desce) {
        float soma = 0;
        for (int i = m - 6; i < m; i++) soma += x[i];   // nível: média dos 6 pontos da tendência
        regra = 'T'; nivel = soma / 6; return;
      }
    }
  }
};

}  // namespace cep
