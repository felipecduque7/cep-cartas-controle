#!/usr/bin/env python3
"""Simula o ESP32 da estufa: mede, envia o subgrupo ao servidor e aplica o PWM devolvido.

Serve para testar e demonstrar a malha fechada antes de montar o hardware.

Uso (com o servidor rodando em outro terminal):
    python ferramentas/simulador_esp32.py
    python ferramentas/simulador_esp32.py --url http://192.168.0.10:8000 --perturbacao 80 --intervalo 0.2

A perturbação simula a porta da estufa aberta: a partir do subgrupo indicado, o ambiente
fica 4 °C mais frio e a carta deve sinalizar a queda, levando o servidor a aumentar o PWM.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cep.simulacao import Estufa  # noqa: E402


def enviar(url: str, subgrupo: List[float], pwm: int, timeout: float = 5.0) -> Dict[str, Any]:
    corpo = json.dumps({"dispositivo": "simulador", "subgrupo": subgrupo, "pwm": pwm}).encode("utf-8")
    pedido = urllib.request.Request(url.rstrip("/") + "/medicoes", data=corpo,
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def simular(url: str, subgrupos: int = 150, perturbacao: Optional[int] = 100, queda: float = 4.0,
            n: int = 5, intervalo: float = 0.1, semente: Optional[int] = None, pwm: int = 128,
            mostrar: Callable[[str], None] = print) -> List[Dict[str, Any]]:
    estufa = Estufa(semente=semente)
    respostas = []
    for k in range(1, subgrupos + 1):
        if perturbacao and k == perturbacao:
            estufa.ambiente -= queda
            mostrar(f"--- subgrupo {k}: porta aberta, ambiente {queda:g} °C mais frio ---")
        subgrupo = estufa.subgrupo(pwm, n)
        resposta = enviar(url, subgrupo, pwm)
        pwm = int(resposta["pwm"])
        respostas.append(resposta)
        alarme = " ALARME" if resposta.get("alarme") else ""
        mostrar(f"#{k:<4} {resposta['fase']:<14} média {sum(subgrupo) / n:6.2f}  PWM {pwm:>3}{alarme}  "
                f"{resposta['motivo']}")
        if intervalo:
            time.sleep(intervalo)
    return respostas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Simulador do ESP32 da estufa (malha fechada com o servidor CEP).")
    p.add_argument("--url", default="http://localhost:8000", help="endereço do servidor")
    p.add_argument("--subgrupos", type=int, default=150)
    p.add_argument("--perturbacao", type=int, default=100, help="subgrupo em que a porta abre (0 = nunca)")
    p.add_argument("--queda", type=float, default=4.0, help="quantos °C o ambiente esfria na perturbação")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--intervalo", type=float, default=0.1, help="segundos entre subgrupos")
    p.add_argument("--semente", type=int, default=None)
    a = p.parse_args(argv)
    try:
        simular(a.url, a.subgrupos, a.perturbacao, a.queda, a.n, a.intervalo, a.semente)
    except urllib.error.HTTPError as erro:
        print(f"O servidor recusou o subgrupo: {erro.read().decode('utf-8', 'replace')}")
        return 1
    except (urllib.error.URLError, OSError) as erro:
        print(f"Não foi possível falar com o servidor em {a.url}: {erro}. Ele está rodando?")
        return 1
    except KeyboardInterrupt:
        print("\nSimulação interrompida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
