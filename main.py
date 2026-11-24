#!/usr/bin/env python3
"""CEP – Cartas de Controle.

Uso:
    python main.py                         abre o menu interativo
    python main.py arquivo.json [...]      processa os arquivos e gera o relatório
    python main.py dados/*.json --abrir    processa vários e abre o PDF no fim

Opções:
    --calibracao ARQUIVO   calibração a usar nos arquivos de acompanhamento
    --saida PASTA          pasta de saída (padrão: saida)
    --abrir                abre o relatório PDF ao terminar
    --continuar            acrescenta ao último relatório em vez de começar outro
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path


def _configurar_terminal() -> None:
    """Evita erro de acentuação/símbolos em terminais antigos do Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")
        except Exception:
            pass


def _expandir(padroes):
    """No Windows o terminal não expande *.json; fazemos isso aqui."""
    arquivos = []
    for padrao in padroes:
        if any(c in padrao for c in "*?["):
            encontrados = sorted(glob.glob(padrao))
            arquivos.extend(encontrados or [padrao])
        else:
            arquivos.append(padrao)
    return arquivos


def _dependencias_ok() -> bool:
    """Confere os pacotes no MESMO Python que está rodando o programa."""
    import importlib
    faltando = []
    for modulo in ("numpy", "matplotlib", "reportlab"):
        try:
            importlib.import_module(modulo)
        except ImportError:
            faltando.append(modulo)
    if not faltando:
        return True
    print(f"Faltam pacotes no Python que está rodando o programa: {', '.join(faltando)}.")
    print(f"Python em uso: {sys.executable}")
    if "msys" in sys.executable.lower() or "mingw" in sys.executable.lower():
        print("Este é o Python do MSYS2, que não instala esses pacotes pelo pip.")
        print("Rode o programa com o Python da Microsoft Store ou do python.org, por exemplo:")
        print("  python3.13 main.py      ou      py main.py")
        print("e, se ainda faltar algo:  python3.13 -m pip install -r requirements.txt")
        return False
    print("Instale com este mesmo Python (copie e cole o comando abaixo):")
    if sys.platform.startswith("win"):
        print(f'  PowerShell:         & "{sys.executable}" -m pip install -r requirements.txt')
        print(f'  Prompt de Comando:  "{sys.executable}" -m pip install -r requirements.txt')
    else:
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
    return False


def main(argv=None) -> int:
    _configurar_terminal()
    if not _dependencias_ok():
        return 1
    from cep import __version__, apresentacao, config
    from cep.leitura import CALIBRAR, ErroDeLeitura, carregar_plano
    from cep.menu import Menu, abrir_arquivo, registrar_erro
    from cep.processamento import Sessao

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Cartas de controle (CEP): calibração e acompanhamento a partir de arquivos JSON.",
    )
    parser.add_argument("arquivos", nargs="*", help="arquivos JSON a processar (sem arquivos, abre o menu)")
    parser.add_argument("--calibracao", help="arquivo de calibração a usar nos acompanhamentos")
    parser.add_argument("--saida", default=str(config.PASTA_SAIDA), help="pasta de saída (padrão: saida)")
    parser.add_argument("--abrir", action="store_true", help="abre o relatório PDF ao terminar")
    parser.add_argument("--continuar", action="store_true",
                        help="acrescenta ao último relatório (no menu: opção 9)")
    parser.add_argument("--versao", action="version", version=f"cep-cartas-controle {__version__}")
    args = parser.parse_args(argv)

    if not args.arquivos:
        try:
            menu = Menu(Path(args.saida))
            if args.continuar:
                menu.continuar_relatorio()
            return menu.executar()
        except KeyboardInterrupt:
            print("\nAté logo.")
            return 0

    sessao = Sessao(Path(args.saida))
    if args.continuar and sessao.continuar_ultimo_relatorio() is None:
        print("Não há relatório anterior; começando um novo.")
    erros = 0
    planos = []
    for arquivo in _expandir(args.arquivos):
        try:
            planos.append((arquivo, carregar_plano(arquivo)))
        except ErroDeLeitura as erro:
            erros += 1
            print(f"\nERRO em {arquivo}: {erro}", file=sys.stderr)
            registrar_erro(sessao.relatorio, Path(arquivo).name, str(erro))
    # Calibrações primeiro, para os acompanhamentos já encontrarem os limites.
    ordenados = sorted(planos, key=lambda item: item[1].objetivo != CALIBRAR)
    if [a for a, _ in ordenados] != [a for a, _ in planos]:
        print("Os arquivos de calibração serão processados antes dos de acompanhamento.")
    for arquivo, plano in ordenados:
        try:
            resultado = sessao.processar_plano(plano, calibracao_forcada=args.calibracao)
            print(apresentacao.resumo_terminal(resultado))
        except ErroDeLeitura as erro:
            erros += 1
            print(f"\nERRO em {arquivo}: {erro}", file=sys.stderr)
            registrar_erro(sessao.relatorio, Path(arquivo).name, str(erro))
    pdf = sessao.relatorio.ultimo_pdf
    print(f"\nRelatório: {pdf}")
    if pdf and pdf.name != "relatorio.pdf":
        print("(o relatorio.pdf estava aberto em outro programa; esta versão foi salva com outro nome)")
    if args.abrir and pdf:
        abrir_arquivo(pdf)
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
