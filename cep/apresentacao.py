"""Textos de interpretação, resumo no terminal e seções do relatório.

Tudo o que o programa "diz" sobre uma análise sai daqui, a partir do
resultado calculado. Os textos são automáticos e descritivos; a conclusão
técnica sobre as causas continua sendo de quem analisa o processo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from . import config
from .analise import Resultado
from .cartas import Serie
from .leitura import Plano
from .regras import Sinal, descricao_regra
from .util import fmt, fmt_cmc, fmt_mais, fmt_prob, lista_ids, plural, tabela_texto


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def nome_plural(carta) -> str:
    return "observações" if carta.nome_ponto == "observação" else carta.nome_ponto + "s"


def quantos(carta, qtd: int) -> str:
    return plural(qtd, carta.nome_ponto, nome_plural(carta))


def _unidade(plano: Plano) -> str:
    return f" {plano.unidade}" if plano.unidade else ""


def titulo_atividade(resultado: Resultado) -> str:
    acao = "Calibração" if resultado.calibracao else "Acompanhamento"
    return f"{acao} – {resultado.plano.arquivo}"


def pares_do_plano(plano: Plano, carta) -> List[Tuple[str, str]]:
    tipo = f"{plano.tipo_original} → {plano.nome_tipo}"
    objetivo = plano.nome_objetivo if not plano.objetivo_original else f"{plano.objetivo_original} → {plano.nome_objetivo}"
    if plano.lse is None and plano.lie is None:
        especificacao = "não informados"
    else:
        especificacao = f"LIE = {fmt(plano.lie, carta_casas(carta))}; LSE = {fmt(plano.lse, carta_casas(carta))}"
    dados = f"{quantos(carta, carta.num_pontos())}"
    if getattr(carta, "n_const", None) and carta.familia == "variaveis":
        dados += f" de {carta.n_const} medições"
    elif carta.familia == "variaveis":
        dados += f" (n de {min(carta.n)} a {max(carta.n)})"
    if plano.formato_dados:
        dados += f" – {plano.formato_dados}"
    pares = [("Arquivo", plano.arquivo), ("Descrição", plano.rotulo), ("Tipo de carta (Type)", tipo),
             ("Objetivo (Goal)", objetivo), ("Unidade (Unit)", plano.unidade or "não informada"),
             ("Medido em (Measured_at)", plano.medido_em or "não informado"),
             ("Criado por (Created_by)", plano.criado_por or "não informado"),
             ("Limites de especificação", especificacao), ("Dados (Data)", dados)]
    return pares


def carta_casas(carta) -> int:
    return getattr(carta, "casas", 4)


def texto_escolha_da_carta(plano: Plano, carta) -> str:
    tipo = plano.tipo
    if tipo == "XBAR_R":
        n = carta.n_const or f"{min(carta.n)} a {max(carta.n)}"
        return (f"O plano pede a carta '{plano.tipo_original}'. Os dados são medições de uma variável contínua "
                f"em subgrupos de n = {n}: a média de cada subgrupo (X-barra) acompanha o nível do processo e a "
                "amplitude (R) acompanha a variabilidade. Os limites da X-barra são calculados a partir de R-barra, "
                "por isso as duas cartas são analisadas juntas; o Montgomery recomenda conferir a carta R primeiro.")
    if tipo == "R":
        return ("O plano pede a carta R, que acompanha a variabilidade dentro dos subgrupos (amplitude). A carta "
                "X-barra aparece como complemento, porque usa o mesmo R-barra nos seus limites.")
    if tipo in ("I", "IMR"):
        return ("O plano pede a carta de valores individuais. Cada ponto é uma única medição (n = 1), então a "
                "variabilidade é estimada pela amplitude móvel (AM) entre medições consecutivas: σ = AM-barra/1,128. "
                "Pelo Montgomery & Runger, a interpretação deve se concentrar na carta I; a carta AM tem pontos "
                "correlacionados e nela só se verifica a regra 1.")
    if tipo == "MR":
        return ("O plano pede a carta de amplitude móvel (AM), que acompanha a variabilidade entre medições "
                "consecutivas. A carta I aparece como complemento.")
    if tipo == "P":
        return ("O plano pede a carta p: cada amostra tem itens classificados como bons ou defeituosos e o ponto "
                "plotado é a fração defeituosa. Os limites vêm da distribuição binomial, aproximada pela normal "
                "(p-barra ± 3σ), e variam quando o tamanho da amostra varia.")
    if tipo == "NP":
        return ("O plano pede a carta np: número de itens defeituosos em amostras de tamanho constante (binomial).")
    if tipo == "C":
        return ("O plano pede a carta c: número de defeitos (não conformidades) por unidade de inspeção de tamanho "
                "constante. Os limites vêm da distribuição de Poisson (c-barra ± 3√c-barra).")
    return ("O plano pede a carta u: número de defeitos por unidade, para amostras com quantidades de unidades "
            "diferentes (Poisson).")


def tabela_limites(series: Sequence[Serie]) -> Tuple[List[str], List[List[str]]]:
    linhas = []
    for s in series:
        lic, lc, lsc = s.texto_limites()
        linhas.append([s.nome, lic, lc, lsc])
    return ["Carta", "LIC", "LC", "LSC"], linhas


def _lado_texto(sinal: Sinal) -> str:
    return {"acima": "acima", "abaixo": "abaixo", "subindo": "subindo", "descendo": "descendo"}[sinal.lado]


def tabela_sinais(sinais: Dict[str, List[Sinal]], series: Sequence[Serie]) -> Tuple[List[str], List[List[str]]]:
    nomes = {s.chave: s.nome for s in series}
    linhas = []
    for s in series:
        for sinal in sinais.get(s.chave, []):
            trecho = str(sinal.inicio) if sinal.inicio == sinal.fim else f"{sinal.inicio} a {sinal.fim}"
            linhas.append([nomes[s.chave], descricao_regra(sinal.regra), _lado_texto(sinal),
                           lista_ids(sinal.pontos), trecho])
    return ["Carta", "Regra", "Lado", "Pontos", "Trecho"], linhas


def _situacao_pontos(resultado: Resultado) -> Dict[int, str]:
    """Texto curto da situação de cada ponto (número 1-based)."""
    situacao: Dict[int, List[str]] = {}
    nomes = {s.chave: s.nome for s in resultado.series_finais}
    fonte = resultado.sinais_tentativos if resultado.calibracao else resultado.sinais_finais
    for chave, sinais in fonte.items():
        for s in sinais:
            if s.fora_de_controle:
                for p in s.pontos:
                    situacao.setdefault(p, []).append(f"fora em {nomes[chave]} ({s.lado})")
    for chave, sinais in resultado.sinais_finais.items():
        for s in sinais:
            if not s.fora_de_controle:
                for p in s.pontos:
                    rotulo = f"alerta {'T' if s.regra == 'T' else 'R' + s.regra} em {nomes[chave]}"
                    if rotulo not in situacao.get(p, []):
                        situacao.setdefault(p, []).append(rotulo)
    texto = {}
    removidos = {i + 1 for i in resultado.removidos}
    for p in range(1, resultado.carta.num_pontos() + 1):
        partes = situacao.get(p, [])
        if p in removidos:
            partes = ["retirado do cálculo"] + partes
        texto[p] = "; ".join(partes)
    return texto


def tabela_pontos(resultado: Resultado) -> Tuple[List[str], List[List[str]]]:
    cab, linhas = resultado.carta.tabela_pontos()
    situacao = _situacao_pontos(resultado)
    return cab + ["Situação"], [linha + [situacao.get(i + 1, "")] for i, linha in enumerate(linhas)]


def tabela_iteracoes(resultado: Resultado) -> Tuple[List[str], List[List[str]]]:
    linhas = []
    principal = resultado.series_finais[0].chave
    for it in resultado.iteracoes:
        serie = next(s for s in it.series if s.chave == principal)
        lic, lc, lsc = serie.texto_limites()
        fora = []
        for s in it.series:
            pts = [pos + 1 for pos, _ in it.fora.get(s.chave, [])]
            if pts:
                fora.append(f"{s.nome}: {lista_ids(pts)}")
        linhas.append([str(it.numero + 1) if it.numero else "1 (tentativos)", str(len(it.usados)),
                       f"{lic} / {lc} / {lsc}", "; ".join(fora) or "nenhum",
                       lista_ids([p + 1 for p in it.removidos]) if it.removidos else "—"])
    nome = resultado.series_finais[0].nome
    return ["Iteração", f"{nome_plural(resultado.carta).capitalize()} no cálculo",
            f"{nome}: LIC / LC / LSC", "Fora dos limites", "Retirados"], linhas


# ---------------------------------------------------------------------------
# Interpretação
# ---------------------------------------------------------------------------
def _descrever_fora(resultado: Resultado, series: Sequence[Serie], sinais: Dict[str, List[Sinal]]) -> List[str]:
    partes = []
    carta = resultado.carta
    for s in series:
        fora = [x for x in sinais.get(s.chave, []) if x.fora_de_controle]
        if not fora:
            continue
        acima = sorted(p for x in fora if x.lado == "acima" for p in x.pontos)
        abaixo = sorted(p for x in fora if x.lado == "abaixo" for p in x.pontos)
        trechos = []
        if abaixo:
            trechos.append(f"{_rotulo_pontos(carta, abaixo)} abaixo do LIC")
        if acima:
            trechos.append(f"{_rotulo_pontos(carta, acima)} acima do LSC")
        partes.append(f"na carta {s.nome}, {' e '.join(trechos)}")
    return partes


def _rotulo_pontos(carta, ids: Sequence[int]) -> str:
    nome = carta.nome_ponto if len(ids) == 1 else nome_plural(carta)
    return f"{nome} {lista_ids(ids)}"


def _descrever_alertas(series: Sequence[Serie], sinais: Dict[str, List[Sinal]]) -> List[str]:
    partes = []
    for s in series:
        for x in sinais.get(s.chave, []):
            if x.fora_de_controle:
                continue
            if x.regra == "T":
                partes.append(f"tendência ({x.lado}) na carta {s.nome}, pontos {lista_ids(x.pontos)}")
            elif x.regra == "4":
                partes.append(f"regra 4 ({len(x.pontos)} pontos seguidos {x.lado} da linha central) na carta "
                              f"{s.nome}, pontos {lista_ids(x.pontos)}")
            else:
                partes.append(f"regra {x.regra} ({x.lado} da linha central) na carta {s.nome}, "
                              f"pontos {lista_ids(x.pontos)}")
    return partes


def _limites_em_texto(series: Sequence[Serie]) -> str:
    textos = []
    for s in series:
        lic, lc, lsc = s.texto_limites()
        textos.append(f"{s.nome}: LIC = {lic}, LC = {lc}, LSC = {lsc}")
    return "; ".join(textos)


def interpretacao(resultado: Resultado) -> List[str]:
    carta = resultado.carta
    paragrafos: List[str] = []
    m = carta.num_pontos()
    if resultado.calibracao:
        tent = resultado.series_tentativas
        paragrafos.append(f"Com {quantos(carta, m)}, os limites tentativos ficaram em {_limites_em_texto(tent)}.")
        fora = _descrever_fora(resultado, tent, resultado.sinais_tentativos)
        if fora:
            paragrafos.append("Ficaram fora dos limites tentativos: " + "; ".join(fora) + ".")
        else:
            paragrafos.append("Nenhum ponto ficou fora dos limites tentativos.")
        if resultado.removidos:
            paragrafos.append(
                f"Retirados {lista_ids([i + 1 for i in resultado.removidos])} do cálculo, os limites revisados "
                f"({quantos(carta, len(resultado.usados))}) ficaram em {_limites_em_texto(resultado.series_finais)}"
                + (", e nenhum ponto mantido ficou fora." if resultado.nivel != "critico" else ".")
            )
            if carta.familia == "variaveis" and any(x.fora_de_controle for x in resultado.sinais_tentativos.get("r", [])):
                paragrafos.append("A carta R também teve ponto fora: a variabilidade dentro dos subgrupos não "
                                  "esteve estável em toda a coleta. O Montgomery recomenda estabilizar a carta R "
                                  "antes de interpretar a X-barra, porque os limites da X-barra dependem de R-barra.")
        else:
            paragrafos.append("Como nenhum ponto saiu dos limites, os limites tentativos já são os limites calibrados.")
        alertas = _descrever_alertas(resultado.series_finais, resultado.sinais_finais)
        if alertas:
            paragrafos.append(
                "Mesmo dentro dos limites, os pontos mantidos mostram padrões não aleatórios: " + "; ".join(alertas)
                + ". Esses padrões indicam causas atribuíveis (por exemplo, mudança de nível ou desgaste) e devem "
                "ser investigados antes de usar os limites no acompanhamento."
            )
        else:
            paragrafos.append("Os pontos mantidos não apresentam nenhum padrão das regras Western Electric "
                              "nem tendência.")
    else:
        paragrafos.append(f"Os {quantos(carta, m)} foram comparados com limites já calibrados "
                          f"({resultado.origem_limites}): {_limites_em_texto(resultado.series_finais)}.")
        fora = _descrever_fora(resultado, resultado.series_finais, resultado.sinais_finais)
        if fora:
            primeiro = min(p for lista in resultado.sinais_finais.values() for x in lista if x.fora_de_controle
                           for p in x.pontos)
            paragrafos.append("Ficaram fora dos limites calibrados: " + "; ".join(fora) +
                              f". O primeiro sinal aparece no ponto {primeiro}.")
        else:
            paragrafos.append("Nenhum ponto ficou fora dos limites calibrados.")
        alertas = _descrever_alertas(resultado.series_finais, resultado.sinais_finais)
        if alertas:
            paragrafos.append("Sinais de alerta: " + "; ".join(alertas) + ".")
    paragrafos.extend(texto_deslocamento_resumido(resultado))
    return paragrafos


# ---------------------------------------------------------------------------
# Capacidade
# ---------------------------------------------------------------------------
def textos_capacidade(resultado: Resultado) -> Tuple[List[str], List[Tuple[str, str]]]:
    cap = resultado.capacidade
    if not cap:
        return [], []
    carta = resultado.carta
    casas = carta_casas(carta)
    u = _unidade(resultado.plano)
    textos: List[str] = []
    pares: List[Tuple[str, str]] = []
    if cap["tipo"] == "atributos":
        if cap["fora"]:
            textos.append(f"{len(cap['fora'])} de {cap['total']} amostras ficaram fora da especificação "
                          f"(pontos {lista_ids([int(i) for i, _ in cap['fora']])}).")
        else:
            textos.append("Nenhuma amostra ficou fora dos limites de especificação informados.")
        return textos, pares
    fora = cap["fora"]
    if fora:
        exemplos = ", ".join(f"{onde} = {fmt(v, casas)}" for onde, v in fora[:8])
        textos.append(f"{len(fora)} de {cap['total']} medições ficaram fora da especificação ({exemplos}"
                      f"{'…' if len(fora) > 8 else ''}).")
    else:
        textos.append(f"Nenhuma das {cap['total']} medições ficou fora da especificação.")
    if cap.get("aviso"):
        textos.append(cap["aviso"])
        return textos, pares
    pares.append(("Média usada (μ)", f"{fmt(cap['mu'], casas)}{u} ({cap['origem_mu']})"))
    pares.append(("Desvio-padrão do processo (σ)", f"{fmt(cap['sigma'], casas + 1)}{u}"))
    if cap.get("rcp") is not None:
        pares.append(("RCP = (LSE − LIE) / 6σ", fmt(cap["rcp"], 2)))
    if cap.get("rcpk_sup") is not None:
        pares.append(("RCPk superior = (LSE − μ) / 3σ", fmt(cap["rcpk_sup"], 2)))
    if cap.get("rcpk_inf") is not None:
        pares.append(("RCPk inferior = (μ − LIE) / 3σ", fmt(cap["rcpk_inf"], 2)))
    pares.append(("RCPk (o menor dos lados)", f"{fmt(cap['rcpk'], 2)} → {cap['classificacao']}"))
    pares.append(("Fração estimada fora da especificação", f"{fmt_prob(cap['p_fora'])} "
                                                            f"({fmt(cap['ppm'], 1)} ppm)"))
    if cap.get("s"):
        quantas = cap.get("n_desempenho", "")
        origem_s = (f"{quantas} medições dos pontos mantidos" if resultado.calibracao and resultado.removidos
                    else f"todas as {quantas} medições")
        pares.append(("Desvio-padrão total das medições (s)", f"{fmt(cap['s'], casas + 1)}{u} ({origem_s})"))
        if cap.get("pp") is not None:
            pares.append(("Pp = (LSE − LIE) / 6s", fmt(cap["pp"], 2)))
        if cap.get("ppk") is not None:
            pares.append(("Ppk = min(LSE − μ, μ − LIE) / 3s", fmt(cap["ppk"], 2)))
    frase = f"RCPk = {fmt(cap['rcpk'], 2)}: o processo é {cap['classificacao']} "
    frase += f"(critério: RCPk ≥ {fmt(config.RCPK_CAPAZ, 2)} capaz; entre {fmt(config.RCPK_MINIMO, 2)} e " \
             f"{fmt(config.RCPK_CAPAZ, 2)} marginal; abaixo de {fmt(config.RCPK_MINIMO, 2)} não capaz)."
    textos.append(frase)
    if cap.get("ppk") is not None and cap.get("rcpk") and cap["ppk"] < 0.9 * cap["rcpk"]:
        textos.append(f"O Ppk ({fmt(cap['ppk'], 2)}) é menor que o RCPk ({fmt(cap['rcpk'], 2)}). O σ da carta mede "
                      "só a variação dentro dos subgrupos; o desvio-padrão total s inclui também as mudanças de nível "
                      "entre eles. O RCPk mostra o que o processo pode fazer; o Ppk, o que ele fez de fato nesses dados.")
    if cap.get("rcp") is not None and cap.get("rcpk") is not None and cap["rcp"] > 0 and cap["rcpk"] < 0.75 * cap["rcp"]:
        lado = "LSE" if (cap.get("rcpk_sup") or 1e9) < (cap.get("rcpk_inf") or 1e9) else "LIE"
        textos.append(f"O RCP ({fmt(cap['rcp'], 2)}) é bem maior que o RCPk: a dispersão caberia folgada na "
                      f"tolerância, mas a média está descentralizada, perto do {lado}. Centralizar o processo "
                      "aumentaria o RCPk.")
    if resultado.nivel != "ok":
        textos.append("As razões de capacidade só têm validade plena com o processo sob controle estatístico; "
                      "como há sinais na carta, use esses números com cautela.")
    return textos, pares


# ---------------------------------------------------------------------------
# Deslocamento e probabilidades
# ---------------------------------------------------------------------------
def _rotulo_delta(analise: Dict[str, Any], aval: Dict[str, Any]) -> str:
    tipo = analise["tipo"]
    if tipo == "media":
        return f"{fmt_mais(aval['delta'], 2)}σ"
    if tipo == "variabilidade":
        return f"σ1 = {fmt(aval['razao'], 2)}·σ0"
    return f"{analise.get('simbolo', '')}1 = {fmt(aval['novo'], 4 if tipo != 'contagem' else 2)}"


def texto_deslocamento_resumido(resultado: Resultado) -> List[str]:
    d = resultado.deslocamento
    if not d or d.get("aviso"):
        return [d["aviso"]] if d and d.get("aviso") else []
    carta = resultado.carta
    textos = []
    mud = d.get("mudanca")
    ten = d.get("tendencia")
    if mud and mud["significativa"]:
        textos.append(f"Há indício de mudança de nível após o ponto {mud['apos_ponto']}: a estatística passa de "
                      f"{fmt(mud['antes'], d['casas'])} para {fmt(mud['depois'], d['casas'])}"
                      + (f" ({fmt_mais(mud['delta'], 2)}σ)" if d["tipo"] == "media" else "") + ".")
    if ten and ten["significativa"]:
        sentido = "alta" if ten["inclinacao"] > 0 else "baixa"
        textos.append(f"A sequência tem tendência de {sentido} ({fmt_mais(ten['inclinacao'], d['casas'] + 1)}"
                      f"{_unidade(resultado.plano) if d['tipo'] in ('media', 'variabilidade') else ''} por "
                      f"{carta.nome_ponto}; p = {fmt_prob(ten['p_valor'])}).")
    aval = d["avaliado"]
    textos.append(f"Para o deslocamento estimado ({aval['origem']}: {_rotulo_delta(d, aval)}), a probabilidade de "
                  f"sucesso, isto é, de a carta detectá-lo em uma amostra, é {fmt_prob(aval['p_detectar'])}; "
                  f"a de falha (β) é {fmt_prob(aval['beta'])}, e o CMC é {fmt_cmc(aval['cmc'])} amostras.")
    return textos


def textos_deslocamento(resultado: Resultado) -> Tuple[List[str], List[Tuple[List[str], List[List[str]]]]]:
    d = resultado.deslocamento
    if not d:
        return [], []
    if d.get("aviso"):
        return [d["aviso"]], []
    carta = resultado.carta
    u = _unidade(resultado.plano)
    casas = d["casas"]
    textos: List[str] = []
    tabelas: List[Tuple[List[str], List[List[str]]]] = []
    rec = d["recente"]
    if d["tipo"] == "media":
        textos.append(f"Nível atual (média dos últimos {rec['k']} pontos): {fmt(rec['nivel'], casas)}{u}, "
                      f"{fmt_mais(rec['delta'], 2)}σ em relação à linha central ({fmt(d['centro'], casas)}{u}; "
                      f"σ do processo = {fmt(d['sigma'], casas + 1)}{u}).")
    elif d["tipo"] == "variabilidade":
        textos.append(f"Nível atual da amplitude (últimos {rec['k']} pontos): {fmt(rec['nivel'], casas)}{u}, "
                      f"o que corresponde a σ1 ≈ {fmt(rec['razao'], 2)}·σ0.")
    else:
        textos.append(f"Nível atual (últimos {rec['k']} pontos): {fmt(rec['nivel'], casas)}, "
                      f"{fmt(rec['razao'], 2)} vez(es) a linha central ({fmt(d['centro'], casas)}).")
    mud = d.get("mudanca")
    if mud:
        if mud["significativa"]:
            extra = f" ({fmt_mais(mud['delta'], 2)}σ)" if d["tipo"] == "media" else ""
            textos.append(f"Mudança de nível: a divisão que melhor separa a sequência em dois trechos é após o "
                          f"ponto {mud['apos_ponto']}. A estatística passa de {fmt(mud['antes'], casas)} "
                          f"({mud['pontos_antes']} pontos) para {fmt(mud['depois'], casas)} ({mud['pontos_depois']} "
                          f"pontos){extra}; a diferença é significativa (p ajustado = {fmt_prob(mud['p_ajustado'])}).")
        else:
            textos.append(f"Mudança de nível: não há diferença significativa entre trechos da sequência "
                          f"(melhor divisão após o ponto {mud['apos_ponto']}, p ajustado = "
                          f"{fmt_prob(mud['p_ajustado'])}).")
    ten = d.get("tendencia")
    if ten:
        if ten["significativa"]:
            sentido = "alta" if ten["inclinacao"] > 0 else "baixa"
            frase = (f"Tendência: a reta de mínimos quadrados indica {sentido} de "
                     f"{fmt_mais(ten['inclinacao'], casas + 1)}{u if d['tipo'] != 'fracao' else ''} por "
                     f"{carta.nome_ponto} (t = {fmt(ten['t'], 2)}, p = {fmt_prob(ten['p_valor'])}, "
                     f"R² = {fmt(ten['r2'], 2)}).")
            projecoes = []
            if ten.get("pontos_ate_limite"):
                projecoes.append(f"cruzaria o {'LSC' if ten['inclinacao'] > 0 else 'LIC'} em cerca de "
                                 f"{fmt(ten['pontos_ate_limite'], 1)} {nome_plural(carta)}")
            if ten.get("pontos_ate_rcpk1"):
                projecoes.append(f"levaria a média ao ponto de RCPk = 1 em cerca de "
                                 f"{fmt(ten['pontos_ate_rcpk1'], 1)} {nome_plural(carta)}")
            if ten.get("pontos_ate_especificacao"):
                projecoes.append(f"e à própria especificação em cerca de "
                                 f"{fmt(ten['pontos_ate_especificacao'], 1)}")
            if projecoes:
                frase += " Se o ritmo continuar (extrapolação linear, só indicativa), a reta " + ", ".join(projecoes) + "."
            textos.append(frase)
        else:
            textos.append(f"Tendência: a inclinação da reta não é significativa (p = {fmt_prob(ten['p_valor'])}).")
    aval = d["avaliado"]
    textos.append(
        f"Probabilidades para o deslocamento estimado ({aval['origem']}: {_rotulo_delta(d, aval)}): "
        f"sucesso (detectar em uma amostra) = 1 − β = {fmt_prob(aval['p_detectar'])}; falha (não detectar) = "
        f"β = {fmt_prob(aval['beta'])}; número médio de amostras (tentativas) até o primeiro sinal: "
        f"CMC = 1/(1 − β) = {fmt_cmc(aval['cmc'])}."
    )
    alarme = d["alarme_falso"]
    textos.append(f"Sem deslocamento, a chance de alarme falso por amostra é α = {fmt_prob(alarme['alfa'])}, "
                  f"ou seja, em média um alarme falso a cada {fmt_cmc(alarme['cmc0'])} amostras (CMC0).")
    if d["tipo"] == "media":
        textos.append(f"Com n = {d['n']}, esta carta detecta em uma única amostra um deslocamento de "
                      f"{fmt(d['detectavel']['50'], 2)}σ com 50% de chance e de {fmt(d['detectavel']['90'], 2)}σ "
                      "com 90% de chance.")
        esp = d.get("especificacao") or {}
        for lado, nome, sentido in (("superior", "LSE", "subir"), ("inferior", "LIE", "descer")):
            info = esp.get(lado)
            if not info:
                continue
            delta = info["delta_rcpk1"]
            if abs(info["delta_limite"]) > 12:
                textos.append(f"Avaliação fora do calibre ({nome}): a média está a {fmt(abs(info['delta_limite']), 1)}σ "
                              f"do {nome}; um deslocamento desse tamanho seria detectado imediatamente.")
            elif (lado == "superior" and delta > 0) or (lado == "inferior" and delta < 0):
                p = info.get("p_rcpk1")
                textos.append(f"Avaliação fora do calibre ({nome}): a média pode {sentido} "
                              f"{fmt(abs(delta), 2)}σ ({fmt(abs(delta) * d['sigma'], casas)}{u}) antes de o RCPk "
                              f"chegar a 1, quando o processo começa a produzir itens fora da especificação "
                              f"(0,135% desse lado). Um deslocamento desse tamanho seria detectado com "
                              f"probabilidade {fmt_prob(p)} por amostra.")
            else:
                textos.append(f"Avaliação fora do calibre ({nome}): a média já está a menos de 3σ do {nome} "
                              "(RCPk desse lado abaixo de 1).")
    linhas = [[linha["rotulo"], fmt(linha["nivel"], casas), fmt_prob(linha["p_detectar"]), fmt_prob(linha["beta"]),
               fmt_cmc(linha["cmc"])] for linha in d["tabela"]]
    primeira = {"media": "Deslocamento da média", "variabilidade": "Desvio-padrão",
                "fracao": "Fração p1 (× p̄)", "contagem": "Defeitos c1 (× c̄)", "taxa": "u1 (× ū)"}[d["tipo"]]
    tabelas.append(([primeira, "Novo nível", "P(detectar) = 1 − β", "β (não detectar)", "CMC"], linhas))
    tabelas.append((["Amostras (m)", "P(detectar em até m amostras) = 1 − β^m"],
                    [[str(m), fmt_prob(p)] for m, p in aval["ate"]]))
    return textos, tabelas


# ---------------------------------------------------------------------------
# Resumo no terminal
# ---------------------------------------------------------------------------
def resumo_terminal(resultado: Resultado) -> str:
    plano, carta = resultado.plano, resultado.carta
    linhas: List[str] = []
    barra = "=" * 74
    linhas += [barra, titulo_atividade(resultado), f"Carta: {plano.nome_tipo} · {quantos(carta, carta.num_pontos())}"
               + (f" · unidade {plano.unidade}" if plano.unidade else ""), "-" * 74]
    for aviso in plano.avisos:
        linhas.append(f"Aviso: {aviso}")
    if resultado.calibracao:
        cab, tab = tabela_limites(resultado.series_tentativas)
        linhas += [f"Limites tentativos ({quantos(carta, carta.num_pontos())})", tabela_texto(cab, tab)]
        fora = _descrever_fora(resultado, resultado.series_tentativas, resultado.sinais_tentativos)
        linhas.append("Fora dos limites: " + ("; ".join(fora) if fora else "nenhum ponto"))
        if resultado.removidos:
            cab, tab = tabela_limites(resultado.series_finais)
            linhas += ["", f"Limites revisados ({quantos(carta, len(resultado.usados))}; retirados: "
                           f"{lista_ids([i + 1 for i in resultado.removidos])})", tabela_texto(cab, tab)]
    else:
        cab, tab = tabela_limites(resultado.series_finais)
        linhas += [f"Limites calibrados ({resultado.origem_limites})", tabela_texto(cab, tab)]
        fora = _descrever_fora(resultado, resultado.series_finais, resultado.sinais_finais)
        linhas.append("Fora dos limites: " + ("; ".join(fora) if fora else "nenhum ponto"))
    alertas = _descrever_alertas(resultado.series_finais, resultado.sinais_finais)
    if alertas:
        linhas.append("Sinais de alerta" + (" nos pontos mantidos" if resultado.calibracao else "") + ":")
        linhas += [f"  - {a}" for a in alertas]
    cap = resultado.capacidade
    if cap and cap["tipo"] == "variaveis" and cap.get("rcpk") is not None:
        rcp = f"RCP = {fmt(cap['rcp'], 2)} · " if cap.get("rcp") is not None else ""
        ppk = f"Ppk = {fmt(cap['ppk'], 2)} · " if cap.get("ppk") is not None else ""
        linhas.append(f"Capacidade: {rcp}RCPk = {fmt(cap['rcpk'], 2)} ({cap['classificacao']}) · {ppk}"
                      f"medições fora da especificação: {len(cap['fora'])}")
    elif cap:
        linhas.append(f"Especificação: {len(cap['fora'])} ponto(s) fora")
    d = resultado.deslocamento
    if d and not d.get("aviso"):
        mud, ten, aval = d.get("mudanca"), d.get("tendencia"), d["avaliado"]
        if mud and mud["significativa"]:
            linhas.append(f"Mudança de nível após o ponto {mud['apos_ponto']}: {fmt(mud['antes'], d['casas'])} → "
                          f"{fmt(mud['depois'], d['casas'])} (p ajustado = {fmt_prob(mud['p_ajustado'])})")
        if ten and ten["significativa"]:
            linhas.append(f"Tendência de {'alta' if ten['inclinacao'] > 0 else 'baixa'}: "
                          f"{fmt_mais(ten['inclinacao'], d['casas'] + 1)} por {carta.nome_ponto} "
                          f"(p = {fmt_prob(ten['p_valor'])})")
        linhas.append(f"Deslocamento avaliado ({aval['origem']}): {_rotulo_delta(d, aval)} → "
                      f"P(sucesso) = {fmt_prob(aval['p_detectar'])} · β = {fmt_prob(aval['beta'])} · "
                      f"CMC = {fmt_cmc(aval['cmc'])}")
    elif d and d.get("aviso"):
        linhas.append(d["aviso"])
    linhas.append("-" * 74)
    linhas.append(f"SITUAÇÃO: {resultado.status}")
    if resultado.calibracao_salva:
        linhas.append(f"Calibração salva em: {resultado.calibracao_salva}")
    linhas.append(barra)
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Seção do relatório
# ---------------------------------------------------------------------------
def registrar(resultado: Resultado, relatorio, graficos: Dict[str, str]) -> None:
    plano, carta = resultado.plano, resultado.carta
    relatorio.secao(titulo_atividade(resultado))
    relatorio.destaque(resultado.status, resultado.nivel)

    relatorio.subtitulo("Plano lido do arquivo")
    relatorio.pares(pares_do_plano(plano, carta))
    if plano.avisos:
        relatorio.paragrafo("Ajustes e observações da leitura:")
        relatorio.lista(plano.avisos)

    relatorio.subtitulo("Escolha da carta")
    relatorio.paragrafo(texto_escolha_da_carta(plano, carta))

    relatorio.subtitulo("Resumo e interpretação")
    for texto in interpretacao(resultado):
        relatorio.paragrafo(texto)
    if resultado.ressalvas:
        relatorio.paragrafo("**Ressalvas:**")
        relatorio.lista(resultado.ressalvas)

    if resultado.calibracao:
        relatorio.subtitulo("Limites tentativos (todos os pontos)")
        primeira = resultado.iteracoes[0]
        relatorio.pares(carta.descricao_parametros(primeira.params))
        cab, linhas = tabela_limites(resultado.series_tentativas)
        relatorio.tabela(cab, linhas, [3, 3, 3, 3])
        if "tentativos" in graficos:
            relatorio.imagem(graficos["tentativos"])
        if len(resultado.iteracoes) > 1:
            relatorio.subtitulo("Revisão dos limites (retirada dos pontos fora de controle)")
            cab, linhas = tabela_iteracoes(resultado)
            relatorio.tabela(cab, linhas, [2.2, 2.6, 5.5, 4.2, 2.5])
        relatorio.subtitulo("Limites calibrados" + (" (revisados)" if resultado.removidos else ""))
        relatorio.pares(carta.descricao_parametros(resultado.params))
        cab, linhas = tabela_limites(resultado.series_finais)
        relatorio.tabela(cab, linhas, [3, 3, 3, 3])
        if "revisados" in graficos:
            relatorio.imagem(graficos["revisados"])
        if resultado.calibracao_salva:
            relatorio.paragrafo(f"Calibração salva em: {resultado.calibracao_salva}")
    else:
        relatorio.subtitulo("Limites calibrados usados")
        relatorio.paragrafo(f"Origem dos limites: {resultado.origem_limites}.")
        relatorio.pares(carta.descricao_parametros({**resultado.params, "m": resultado.params.get("m") or "—"}))
        cab, linhas = tabela_limites(resultado.series_finais)
        relatorio.tabela(cab, linhas, [3, 3, 3, 3])
        if "carta" in graficos:
            relatorio.imagem(graficos["carta"])

    relatorio.subtitulo("Sinais de alerta (regras Western Electric e tendência)")
    if resultado.calibracao:
        cab, linhas = tabela_sinais(resultado.sinais_tentativos, resultado.series_tentativas)
        relatorio.paragrafo("Com os limites tentativos, considerando todos os pontos:")
        if linhas:
            relatorio.tabela(cab, linhas, [1.8, 7.0, 1.7, 3.6, 1.9])
        else:
            relatorio.paragrafo("nenhum sinal.")
        cab, linhas = tabela_sinais(resultado.sinais_finais, resultado.series_finais)
        relatorio.paragrafo("Com os limites calibrados, considerando só os pontos mantidos no cálculo:")
        if linhas:
            relatorio.tabela(cab, linhas, [1.8, 7.0, 1.7, 3.6, 1.9])
        else:
            relatorio.paragrafo("nenhum sinal.")
    else:
        cab, linhas = tabela_sinais(resultado.sinais_finais, resultado.series_finais)
        if linhas:
            relatorio.tabela(cab, linhas, [1.8, 7.0, 1.7, 3.6, 1.9])
        else:
            relatorio.paragrafo("Nenhum sinal.")

    textos_cap, pares_cap = textos_capacidade(resultado)
    if textos_cap or pares_cap:
        relatorio.subtitulo("Capacidade do processo (limites de especificação)")
        for texto in textos_cap:
            relatorio.paragrafo(texto)
        if pares_cap:
            relatorio.pares(pares_cap)
        if "capacidade" in graficos:
            relatorio.imagem(graficos["capacidade"])

    textos_desl, tabelas_desl = textos_deslocamento(resultado)
    if textos_desl:
        relatorio.subtitulo("Deslocamento, tendência e probabilidades de detecção")
        for texto in textos_desl:
            relatorio.paragrafo(texto)
        for cab, linhas in tabelas_desl:
            relatorio.tabela(cab, linhas)
        if "deteccao" in graficos:
            relatorio.imagem(graficos["deteccao"], 16.0)

    relatorio.subtitulo("Dados e situação de cada ponto")
    cab, linhas = tabela_pontos(resultado)
    relatorio.tabela(cab, linhas)
