// Testa a lógica de cep_embarcado.h no computador (sem ESP32).
//   g++ -std=c++11 -O2 -o teste_cep teste_cep.cpp
//
// Modos (pela entrada padrão):
//   cal <n> <m>  seguido de m linhas com n medições  -> imprime os limites calibrados
//   sim <subgrupos> <perturbacao> <queda>            -> malha fechada com uma estufa simulada
#include <cstdio>
#include <cmath>
#include <random>
#include "../esp32_cep_embarcado/cep_embarcado.h"

int main() {
  char modo[8];
  if (scanf("%7s", modo) != 1) return 2;
  if (modo[0] == 'c') {
    int n, m;
    if (scanf("%d %d", &n, &m) != 2) return 2;
    cep::Configuracao c; c.n = n;
    cep::MalhaCEP malha(c);
    float medias[cep::CAL_MAX], amplitudes[cep::CAL_MAX];
    for (int i = 0; i < m; i++) {
      float s = 0, mn = 1e30f, mx = -1e30f;
      for (int j = 0; j < n; j++) { float v; if (scanf("%f", &v) != 1) return 2; s += v; mn = fminf(mn, v); mx = fmaxf(mx, v); }
      medias[i] = s / n; amplitudes[i] = mx - mn;
    }
    malha.calcularLimitesDe(medias, amplitudes, m);
    const cep::Limites& L = malha.lim;
    printf("%.6f %.6f %.6f %.6f %.6f %d %d\n", L.lic, L.lc, L.lsc, L.rlc, L.rlsc, L.retirados, L.confiavel ? 1 : 0);
    return 0;
  }
  int total, perturbacao; float queda;
  if (scanf("%d %d %f", &total, &perturbacao, &queda) != 3) return 2;
  // Mesma estufa de cep/simulacao.py: T += (ambiente + 0,08·PWM − T)/30, ruído 0,15 °C
  std::mt19937 gerador(7);
  std::normal_distribution<float> ruido(0.0f, 0.15f);
  float T = 25, ambiente = 25;
  cep::MalhaCEP malha;
  float sub[5];
  int pwmAntes = 0, ajustesAntes = 0;
  for (int k = 1; k <= total; k++) {
    if (k == perturbacao) { ambiente -= queda; pwmAntes = malha.pwm; ajustesAntes = malha.ajustes; }
    for (int i = 0; i < 5; i++) { T += (ambiente + 0.08f * malha.pwm - T) / 30.0f; sub[i] = T + ruido(gerador); }
    cep::Decisao d;
    malha.receber(sub, d);
    if (d.acao != cep::MANTER || k == total)
      printf("#%d %s %s pwm=%d media=%.2f regra=%c\n", d.numero, cep::nomeFase(d.fase), cep::nomeAcao(d.acao),
             d.pwm, d.media, d.regra);
  }
  float h[20];
  int q = malha.historico(h, 15);
  float s = 0; for (int i = 0; i < q; i++) s += h[i];
  printf("FIM fase=%s lc=%.3f lsc=%.3f lic=%.3f pwm_antes=%d pwm=%d ajustes_depois=%d media_final=%.3f\n",
         cep::nomeFase(malha.fase), malha.lim.lc, malha.lim.lsc, malha.lim.lic, pwmAntes, malha.pwm,
         malha.ajustes - ajustesAntes, s / q);
  return 0;
}
