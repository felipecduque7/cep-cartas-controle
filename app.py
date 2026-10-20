"""Interface web opcional (Streamlit) sobre o mesmo motor de cálculo do menu.

Uso:
    python -m pip install -r requirements-web.txt
    python -m streamlit run app.py

O menu do terminal (python main.py) continua sendo a interface principal; esta
página só reaproveita a sessão, a análise, os gráficos e o relatório do pacote cep.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

import streamlit as st

from cep import __version__, apresentacao
from cep.deslocamento import desempenho_personalizado
from cep.leitura import ErroDeLeitura
from cep.processamento import Sessao
from cep.relatorio import Relatorio, nova_pasta_sessao
from cep.util import fmt, fmt_cmc, fmt_prob

RAIZ = Path(__file__).resolve().parent
PASTA_SAIDA = Path(os.environ.get("CEP_SAIDA", RAIZ / "saida"))
PASTA_ENVIADOS = PASTA_SAIDA / "enviados_web"
PASTAS_EXEMPLO = [RAIZ / "dados", RAIZ / "exemplos"]
NIVEL = {"ok": st.success, "alerta": st.warning, "critico": st.error}


# ---------------------------------------------------------------------------
# Estado da página
# ---------------------------------------------------------------------------
def sessao() -> Sessao:
    if "sessao" not in st.session_state:
        st.session_state.sessao = Sessao(PASTA_SAIDA)
        st.session_state.resultados = []
    return st.session_state.sessao


def guardar_envio(nome: str, conteudo: bytes) -> Path:
    """Salva o arquivo enviado pelo navegador para o motor ler do disco, como no menu."""
    PASTA_ENVIADOS.mkdir(parents=True, exist_ok=True)
    seguro = re.sub(r"[^\w.\-]", "_", Path(nome).name) or "arquivo.json"
    resumo = hashlib.sha1(conteudo).hexdigest()[:8]
    caminho = PASTA_ENVIADOS / f"{Path(seguro).stem}_{resumo}{Path(seguro).suffix or '.json'}"
    caminho.write_bytes(conteudo)
    return caminho


def processar(caminho: Path, calibracao: Optional[Path]) -> None:
    try:
        resultado = sessao().processar_arquivo(caminho, calibracao_forcada=str(calibracao) if calibracao else None,
                                               avisar=lambda _texto: None)
    except ErroDeLeitura as erro:
        st.session_state.erro = f"{caminho.name}: {erro}"
        return
    st.session_state.erro = None
    st.session_state.resultados.append(resultado)


def exemplos() -> List[Path]:
    return [a for pasta in PASTAS_EXEMPLO if pasta.is_dir() for a in sorted(pasta.glob("*.json"))]


# ---------------------------------------------------------------------------
# Pedaços da página
# ---------------------------------------------------------------------------
def tabela(cabecalho: Sequence[str], linhas: Sequence[Sequence[str]]) -> None:
    if linhas:
        st.dataframe([dict(zip(cabecalho, linha)) for linha in linhas], hide_index=True, width="stretch")


def pares(itens) -> None:
    tabela(["Item", "Valor"], [[a, b] for a, b in itens])


def figura(resultado, sufixo: str, legenda: str = "") -> None:
    for caminho in resultado.graficos:
        if Path(caminho).stem.endswith(sufixo) and Path(caminho).exists():
            st.image(str(caminho), caption=legenda or None, width="stretch")


def metrica(coluna, rotulo: str, valor: str, detalhe: str) -> None:
    try:
        coluna.metric(rotulo, valor, detalhe, delta_color="off", delta_arrow="off")
    except TypeError:            # Streamlit mais antigo, sem delta_arrow
        coluna.metric(rotulo, valor, detalhe, delta_color="off")


def metricas(r) -> None:
    """Os números que respondem à prova, de relance."""
    serie = r.serie_principal
    lic, lc, lsc = serie.texto_limites()
    fora = sorted({p for sinais in r.sinais_finais.values() for s in sinais if s.fora_de_controle for p in s.pontos})
    if r.calibracao:
        fora_texto = "retirados: " + (", ".join(str(i + 1) for i in r.removidos) or "nenhum")
    else:
        fora_texto = ", ".join(map(str, fora)) or "nenhum"
    colunas = st.columns(4)
    metrica(colunas[0], f"Linha central da {serie.nome}", lc, f"LIC {lic} · LSC {lsc}")
    metrica(colunas[1], "Pontos fora (regra 1)", str(len(r.removidos) if r.calibracao else len(fora)), fora_texto)
    cap = r.capacidade or {}
    if cap.get("rcpk") is not None:
        metrica(colunas[2], "RCPk", fmt(cap["rcpk"], 2), cap["classificacao"])
    d = r.deslocamento or {}
    if d.get("avaliado"):
        metrica(colunas[3], "Sucesso (1 − β)", fmt_prob(d["avaliado"]["p_detectar"]),
                f"CMC = {fmt_cmc(d['avaliado']['cmc'])}")


def aba_cartas(r) -> None:
    st.subheader("Limites de controle")
    cab, linhas = apresentacao.tabela_limites(r.series_finais)
    tabela(cab, linhas)
    if r.calibracao:
        if r.removidos:
            st.markdown("**Limites tentativos** (todos os pontos)")
            figura(r, "limites_tentativos")
            cab, linhas = apresentacao.tabela_iteracoes(r)
            tabela(cab, linhas)
        st.markdown("**Limites " + ("revisados" if r.removidos else "calibrados") + "**")
        figura(r, "limites_calibrados")
    else:
        st.caption(f"Origem dos limites: {r.origem_limites}.")
        figura(r, "acompanhamento")


def aba_sinais(r) -> None:
    if r.calibracao:
        st.markdown("**Com os limites tentativos, todos os pontos**")
        cab, linhas = apresentacao.tabela_sinais(r.sinais_tentativos, r.series_tentativas)
        tabela(cab, linhas) if linhas else st.write("Nenhum sinal.")
        st.markdown("**Com os limites calibrados, só os pontos mantidos**")
    cab, linhas = apresentacao.tabela_sinais(r.sinais_finais, r.series_finais)
    tabela(cab, linhas) if linhas else st.write("Nenhum sinal.")
    st.subheader("Situação de cada ponto")
    cab, linhas = apresentacao.tabela_pontos(r)
    tabela(cab, linhas)


def aba_capacidade(r) -> None:
    textos, itens = apresentacao.textos_capacidade(r)
    if not textos and not itens:
        st.info("O arquivo não traz LSE nem LIE: não há capacidade para calcular.")
        return
    for texto in textos:
        st.write(texto)
    pares(itens)
    figura(r, "capacidade")


def aba_deslocamento(r) -> None:
    d = r.deslocamento
    if not d or d.get("aviso"):
        st.info(d.get("aviso") if d else "Sem análise de deslocamento para estes dados.")
        return
    textos, tabelas = apresentacao.textos_deslocamento(r)
    for texto in textos:
        st.write(texto)
    for cab, linhas in tabelas:
        tabela(cab, linhas)
    figura(r, "deteccao")
    st.subheader("Teste outro deslocamento")
    pergunta, padrao, passo = {
        "media": ("Deslocamento da média, em σ do processo", 1.0, 0.25),
        "variabilidade": ("Razão σ1/σ0", 1.5, 0.25),
        "fracao": ("Nova fração defeituosa p1", round(2 * d["centro"], 4), 0.01),
        "contagem": ("Nova média de defeitos c1", round(2 * d["centro"], 2), 0.5),
        "taxa": ("Novo número de defeitos por unidade u1", round(2 * d["centro"], 4), 0.05),
    }[d["tipo"]]
    valor = st.number_input(pergunta, value=float(padrao), step=passo, key=f"desl_{id(r)}")
    resposta = desempenho_personalizado(d, valor)
    c1, c2, c3 = st.columns(3)
    c1.metric("Sucesso (1 − β)", fmt_prob(resposta["p_detectar"]))
    c2.metric("Falha (β)", fmt_prob(resposta["beta"]))
    c3.metric("CMC (amostras)", fmt_cmc(resposta["cmc"]))


def aba_relatorio(r) -> None:
    relatorio = sessao().relatorio
    st.write(f"O relatório tem {relatorio.num_secoes} atividade(s) desta sessão, sempre acumuladas no mesmo PDF.")
    if relatorio.ultimo_pdf and Path(relatorio.ultimo_pdf).exists():
        st.download_button("Baixar relatório PDF", Path(relatorio.ultimo_pdf).read_bytes(),
                           file_name="relatorio_cep.pdf", mime="application/pdf")
    if r.calibracao_salva and Path(r.calibracao_salva).exists():
        st.download_button("Baixar calibração (JSON)", Path(r.calibracao_salva).read_bytes(),
                           file_name=Path(r.calibracao_salva).name, mime="application/json")
    st.subheader("Plano lido do arquivo")
    pares(apresentacao.pares_do_plano(r.plano, r.carta))
    if r.plano.avisos:
        st.markdown("**Ajustes da leitura**")
        for aviso in r.plano.avisos:
            st.write(f"- {aviso}")


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="CEP – Cartas de Controle", layout="wide")
    sessao()
    with st.sidebar:
        st.header("Arquivo JSON")
        enviado = st.file_uploader("Plano da análise", type=["json"])
        calibracao = st.file_uploader("Calibração para acompanhamento (opcional)", type=["json"])
        if st.button("Processar arquivo enviado", disabled=enviado is None, type="primary"):
            cal = guardar_envio(calibracao.name, calibracao.getvalue()) if calibracao else None
            processar(guardar_envio(enviado.name, enviado.getvalue()), cal)
        st.divider()
        lista = exemplos()
        escolhido = st.selectbox("Ou use um arquivo de exemplo", lista, format_func=lambda p: p.name,
                                 index=None, placeholder="Escolha um exemplo")
        if st.button("Processar exemplo", disabled=escolhido is None):
            processar(escolhido, None)
        st.divider()
        if st.button("Começar um novo relatório"):
            sessao().usar_relatorio(Relatorio(nova_pasta_sessao(PASTA_SAIDA)))
            st.session_state.resultados = []
        st.caption(f"cep-cartas-controle {__version__} · o menu do terminal (python main.py) faz o mesmo.")

    st.title("CEP – Cartas de Controle")
    if st.session_state.get("erro"):
        st.error(f"Não foi possível processar {st.session_state.erro}")
    resultados = st.session_state.resultados
    if not resultados:
        st.info("Envie um JSON ou escolha um exemplo na barra lateral. Calibre antes de acompanhar: "
                "o acompanhamento usa a calibração feita nesta sessão ou salva em saida/calibracoes/.")
        return
    atual = resultados[-1]
    if len(resultados) > 1:
        atual = st.selectbox("Atividade", resultados[::-1], format_func=apresentacao.titulo_atividade)
    st.subheader(apresentacao.titulo_atividade(atual))
    NIVEL[atual.nivel](atual.status)
    metricas(atual)
    abas = st.tabs(["Resumo", "Cartas", "Sinais e pontos", "Capacidade", "Deslocamento e probabilidades",
                    "Relatório"])
    with abas[0]:
        for texto in apresentacao.interpretacao(atual):
            st.write(texto)
        if atual.ressalvas:
            st.markdown("**Ressalvas**")
            for ressalva in atual.ressalvas:
                st.write(f"- {ressalva}")
    with abas[1]:
        aba_cartas(atual)
    with abas[2]:
        aba_sinais(atual)
    with abas[3]:
        aba_capacidade(atual)
    with abas[4]:
        aba_deslocamento(atual)
    with abas[5]:
        aba_relatorio(atual)


main()
