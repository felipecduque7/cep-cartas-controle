#!/usr/bin/env python3
"""Servidor do CEP remoto em malha fechada.

O ESP32 (ou o simulador) envia cada subgrupo medido por HTTP; o servidor roda o CEP do
pacote cep (calibração da X-barra e R, regras de alerta) e responde com o PWM que o
microcontrolador deve aplicar. Usa só a biblioteca padrão do Python, sem pacotes extras.

Uso:
    python servidor.py                         alvo 35 °C, especificação 32 a 38 °C, porta 8000
    python servidor.py --alvo 40 --lse 43 --lie 37 --porta 8080

Rotas:
    POST /medicoes   {"subgrupo": [35.1, 35.0, 34.9, 35.2, 35.0], "pwm": 120}  -> decisão em JSON
    GET  /estado     estado da malha em JSON
    GET  /           painel que se atualiza sozinho (abra no navegador)
    GET  /relatorio  acrescenta o acompanhamento e os ajustes ao relatório PDF
"""

from __future__ import annotations

import argparse
import html
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from cep.malha import Configuracao, MalhaCEP, registrar_no_relatorio  # noqa: E402
from cep.processamento import Sessao  # noqa: E402
from cep.util import fmt  # noqa: E402

TAMANHO_MAXIMO = 64 * 1024


class Manipulador(BaseHTTPRequestHandler):
    server: "ServidorCEP"
    protocol_version = "HTTP/1.1"

    # --- respostas ----------------------------------------------------------------
    def _enviar(self, codigo: int, corpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, codigo: int, dados: Dict[str, Any]) -> None:
        self._enviar(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8")

    def log_message(self, formato: str, *args) -> None:      # o servidor já imprime cada decisão
        if self.server.verboso:
            super().log_message(formato, *args)

    # --- rotas ---------------------------------------------------------------------
    def do_GET(self) -> None:
        rota = self.path.split("?")[0].rstrip("/") or "/"
        if rota == "/estado":
            self._json(200, self.server.malha.estado())
        elif rota == "/relatorio":
            pdf = self.server.gerar_relatorio()
            self._json(200, {"pdf": pdf})
        elif rota == "/":
            self._enviar(200, painel(self.server.malha.estado()).encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._json(404, {"erro": f"Rota {rota} não existe. Use /, /estado, /relatorio ou POST /medicoes."})

    def do_POST(self) -> None:
        rota = self.path.split("?")[0].rstrip("/")
        if rota != "/medicoes":
            self._json(404, {"erro": "Envie as medições para POST /medicoes."})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tamanho = -1
        if not 0 < tamanho <= TAMANHO_MAXIMO:
            self._json(400, {"erro": "Corpo vazio ou grande demais."})
            return
        try:
            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("O corpo precisa ser um objeto JSON.")
            subgrupo = dados.get("subgrupo", dados.get("Data"))
            if not isinstance(subgrupo, list):
                raise ValueError('Campo "subgrupo" ausente: envie {"subgrupo": [medições], "pwm": valor}.')
            decisao = self.server.malha.receber(subgrupo, dados.get("pwm"))
        except (ValueError, UnicodeDecodeError) as erro:
            self._json(400, {"erro": str(erro)})
            return
        except Exception as erro:  # o servidor não pode cair no meio da demonstração
            self._json(500, {"erro": f"Falha ao processar o subgrupo: {erro}"})
            return
        self.server.mostrar(decisao)
        self._json(200, decisao.resposta(self.server.malha.limites()))


class ServidorCEP(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, endereco, malha: MalhaCEP, sessao: Sessao, verboso: bool = False):
        super().__init__(endereco, Manipulador)
        self.malha = malha
        self.sessao = sessao
        self.verboso = verboso
        self.silencioso = False

    def mostrar(self, d) -> None:
        if self.silencioso:
            return
        marca = "!!" if d.alarme else "  "
        print(f"{marca} #{d.numero:<4} {d.fase:<14} média {fmt(d.media, 2):>7}  PWM {d.pwm:>3}  {d.acao:<9} "
              f"{d.motivo}", flush=True)

    def gerar_relatorio(self) -> Optional[str]:
        with self.malha._trava:
            return registrar_no_relatorio(self.malha, self.sessao)


def criar_servidor(host: str, porta: int, config: Configuracao, pasta_saida, verboso: bool = False,
                   silencioso: bool = True) -> ServidorCEP:
    sessao = Sessao(Path(pasta_saida))
    servidor = ServidorCEP((host, porta), MalhaCEP(config, sessao=sessao), sessao, verboso)
    servidor.silencioso = silencioso
    return servidor


# ----------------------------------------------------------------------
# Painel web
# ----------------------------------------------------------------------
def _svg(decisoes, limites, alvo) -> str:
    if len(decisoes) < 2:
        return "<p class='vazio'>O gráfico aparece quando chegarem os primeiros subgrupos.</p>"
    medias = [d["media"] for d in decisoes]
    valores = medias + [alvo] + ([limites["lic"], limites["lsc"]] if limites else [])
    menor, maior = min(valores), max(valores)
    folga = (maior - menor) * 0.12 or 0.5
    menor, maior = menor - folga, maior + folga
    largura, altura, margem = 640, 220, 34

    def px(i):
        return margem + i * (largura - 2 * margem) / (len(medias) - 1)

    def py(v):
        return altura - margem / 2 - (v - menor) * (altura - margem) / (maior - menor)

    linhas = []
    if limites:
        for chave, classe in (("lsc", "lim"), ("lc", "lc"), ("lic", "lim")):
            y = py(limites[chave])
            linhas.append(f"<line class='{classe}' x1='{margem}' x2='{largura - margem}' y1='{y:.1f}' y2='{y:.1f}'/>"
                          f"<text x='{largura - margem + 4}' y='{y + 4:.1f}'>{chave.upper()}</text>")
    pontos = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(medias))
    marcas = "".join(
        f"<circle class='{'alarme' if d['alarme'] else 'ajuste' if d['acao'] != 'manter' else 'ponto'}' "
        f"cx='{px(i):.1f}' cy='{py(d['media']):.1f}' r='{4 if d['acao'] != 'manter' or d['alarme'] else 2.5}'/>"
        for i, d in enumerate(decisoes))
    return (f"<svg viewBox='0 0 {largura} {altura}' role='img' aria-label='Médias recentes'>{''.join(linhas)}"
            f"<polyline points='{pontos}'/>{marcas}</svg>")


def painel(estado: Dict[str, Any]) -> str:
    lim = estado["limites"]
    decisoes = estado["ultimas_decisoes"]
    unidade = html.escape(estado["unidade"])
    ultima = decisoes[-1] if decisoes else None
    linhas = "".join(
        f"<tr class='{'alarme' if d['alarme'] else ''}'><td>{d['numero']}</td><td>{d['quando']}</td>"
        f"<td>{fmt(d['media'], 2)}</td><td>{d['pwm']}</td><td>{html.escape(d['acao'])}</td>"
        f"<td>{html.escape(d['motivo'])}</td></tr>" for d in reversed(decisoes[-15:]))
    limites = (f"{fmt(lim['lic'], 2)} / {fmt(lim['lc'], 2)} / {fmt(lim['lsc'], 2)} {unidade}"
               if lim else "ainda não calibrado")
    estado_txt = html.escape(ultima["motivo"]) if ultima else "Aguardando o primeiro subgrupo do ESP32."
    classe = "alarme" if ultima and ultima["alarme"] else "ok"
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="3">
<title>CEP remoto – {html.escape(estado['dispositivo'])}</title>
<style>
:root {{ --fundo:#f6f6f3; --cartao:#fff; --tinta:#111; --muda:#666; --borda:#ddd; --azul:#2a78d6;
        --verm:#d03b3b; --lar:#ec835a; --verde:#0ca30c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fundo:#141414; --cartao:#1e1e1e; --tinta:#eee;
        --muda:#aaa; --borda:#333; }} }}
body {{ margin:0; padding:16px; background:var(--fundo); color:var(--tinta);
       font:15px/1.4 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width:980px; margin:auto; }} h1 {{ font-size:20px; margin:0 0 12px; }}
.grade {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }}
.cartao {{ background:var(--cartao); border:1px solid var(--borda); border-radius:10px; padding:12px; }}
.rot {{ color:var(--muda); font-size:12px; }} .val {{ font-size:20px; font-weight:600; overflow-wrap:break-word; hyphens:auto; }}
.estado {{ margin:12px 0; padding:10px 12px; border-radius:8px; border-left:5px solid var(--verde);
          background:var(--cartao); }} .estado.alarme {{ border-color:var(--verm); }}
svg {{ width:100%; height:auto; }} polyline {{ fill:none; stroke:var(--azul); stroke-width:1.8; }}
line.lim {{ stroke:var(--verm); stroke-dasharray:6 4; }} line.lc {{ stroke:var(--muda); }}
svg text {{ fill:var(--muda); font-size:11px; }} circle.ponto {{ fill:var(--azul); }}
circle.ajuste {{ fill:var(--lar); }} circle.alarme {{ fill:var(--verm); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }} td, th {{ padding:5px 6px;
        border-bottom:1px solid var(--borda); text-align:left; vertical-align:top; }}
tr.alarme td {{ color:var(--verm); }} .tabela {{ overflow-x:auto; }} .vazio {{ color:var(--muda); }}
</style></head><body><main>
<h1>CEP remoto em malha fechada · {html.escape(estado['dispositivo'])}</h1>
<div class="grade">
 <div class="cartao"><div class="rot">Fase</div><div class="val">{html.escape(estado['nome_fase'])}</div></div>
 <div class="cartao"><div class="rot">Última média</div>
   <div class="val">{fmt(ultima['media'], 2) + ' ' + unidade if ultima else '–'}</div></div>
 <div class="cartao"><div class="rot">PWM do aquecedor</div><div class="val">{estado['pwm']}</div></div>
 <div class="cartao"><div class="rot">Subgrupos recebidos</div>
   <div class="val">{estado['subgrupos_recebidos']}</div></div>
 <div class="cartao"><div class="rot">Ajustes no acompanhamento</div>
   <div class="val">{estado['ajustes_no_acompanhamento']}</div></div>
</div>
<div class="estado {classe}">{estado_txt}</div>
<div class="cartao"><div class="rot">X-barra: LIC / LC / LSC = {limites} · alvo {fmt(estado['alvo'], 2)} {unidade}</div>
{_svg(decisoes, lim, estado['alvo'])}</div>
<h2 style="font-size:16px">Últimas decisões</h2>
<div class="cartao tabela"><table><tr><th>#</th><th>Hora</th><th>Média</th><th>PWM</th><th>Ação</th>
<th>Motivo</th></tr>{linhas}</table></div>
<p class="rot">Esta página se atualiza a cada 3 s. Relatório PDF: abra <a href="/relatorio">/relatorio</a>
 no fim da demonstração.</p>
</main></body></html>"""


# ----------------------------------------------------------------------
def ip_local() -> str:
    """IP desta máquina na rede local, para configurar o ESP32 (não envia nada pela rede)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(argv=None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")
        except Exception:
            pass
    padrao = Configuracao()
    p = argparse.ArgumentParser(description="Servidor do CEP remoto em malha fechada (ESP32 + estufa).")
    p.add_argument("--host", default="0.0.0.0", help="endereço de escuta (padrão: todas as interfaces)")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--alvo", type=float, default=padrao.alvo, help="temperatura desejada")
    p.add_argument("--lse", type=float, default=padrao.lse)
    p.add_argument("--lie", type=float, default=padrao.lie)
    p.add_argument("--n", type=int, default=padrao.n, help="medições por subgrupo (igual ao firmware)")
    p.add_argument("--calibracao", type=int, default=padrao.subgrupos_calibracao,
                   help="subgrupos usados na calibração")
    p.add_argument("--ganho", type=float, default=padrao.ganho, help="PWM por grau de desvio no ajuste")
    p.add_argument("--espera", type=int, default=padrao.espera_apos_ajuste,
                   help="subgrupos de espera depois de cada ajuste")
    p.add_argument("--pwm-inicial", type=int, default=padrao.pwm_inicial)
    p.add_argument("--unidade", default=padrao.unidade)
    p.add_argument("--saida", default="saida_malha", help="pasta do relatório e das calibrações")
    p.add_argument("--verboso", action="store_true", help="mostra também cada requisição HTTP")
    a = p.parse_args(argv)
    if a.lse is not None and a.lie is not None and not a.lie < a.alvo < a.lse:
        p.error("o alvo precisa ficar entre o LIE e o LSE")
    config = Configuracao(alvo=a.alvo, lse=a.lse, lie=a.lie, n=a.n, subgrupos_calibracao=a.calibracao,
                          ganho=a.ganho, espera_apos_ajuste=a.espera, pwm_inicial=a.pwm_inicial,
                          unidade=a.unidade)
    try:
        servidor = criar_servidor(a.host, a.porta, config, a.saida, verboso=a.verboso, silencioso=False)
    except OSError as erro:
        print(f"Não foi possível abrir a porta {a.porta}: {erro}. Tente outra com --porta.")
        return 1
    ip = ip_local()
    print("Servidor do CEP remoto em execução.")
    print(f"  Painel:              http://{ip}:{a.porta}/   (ou http://localhost:{a.porta}/)")
    print(f"  No firmware do ESP32: SERVIDOR = \"http://{ip}:{a.porta}/medicoes\"")
    print(f"  Alvo {fmt(a.alvo, 1)} {a.unidade}, especificação {fmt(a.lie, 1)} a {fmt(a.lse, 1)} {a.unidade}, "
          f"subgrupos de {a.n}. Ctrl+C encerra e gera o relatório PDF.\n")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        servidor.server_close()
        pdf = servidor.gerar_relatorio()
        if pdf:
            print(f"Relatório: {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
