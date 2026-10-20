"""Menu interativo do programa."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import __version__, apresentacao, calibracoes, config, probabilidade as prob
from .deslocamento import desempenho_personalizado
from .entrada import interpretar_linha, registrar_medicoes
from .leitura import ALIASES, ErroDeLeitura, Plano, limpar_caminho, normalizar
from .processamento import Sessao
from .relatorio import Relatorio, nova_pasta_sessao
from .util import fmt, fmt_cmc, fmt_prob, tabela_texto


class Voltar(Exception):
    """Volta ao menu principal."""


def _curto(valor: float) -> str:
    """3.0 -> '3'; 0.95 -> '0,95'."""
    texto = fmt(valor, 4)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def abrir_arquivo(caminho: Path) -> bool:
    """Abre o arquivo no programa padrão do sistema (leitor de PDF, visualizador...)."""
    caminho = Path(caminho)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(caminho))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def pastas_de_downloads() -> List[Path]:
    """Pastas de download do usuário (Downloads no Windows, Transferências em alguns Linux)."""
    casa = Path.home()
    return [casa / nome for nome in config.PASTAS_DOWNLOADS if (casa / nome).is_dir()]


def parece_plano(arquivo: Path) -> bool:
    """O JSON tem cara de plano de análise (campos de tipo e de dados)?

    JSON inválido também entra na lista, para o usuário ver a mensagem de erro
    ao tentar processar; JSON válido de outros programas fica de fora.
    """
    try:
        if arquivo.stat().st_size > 5_000_000:
            return False
        conteudo = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    except OSError:
        return False
    except ValueError:
        return True
    if not isinstance(conteudo, dict):
        return False
    chaves = {normalizar(k) for k in conteudo}
    return bool(chaves & set(ALIASES["tipo"])) and bool(chaves & set(ALIASES["dados"]))


def registrar_erro(relatorio: Relatorio, origem: str, mensagem: str) -> None:
    relatorio.secao(f"Arquivo não processado – {origem}")
    relatorio.destaque(mensagem, "critico")
    relatorio.salvar()


class Menu:
    def __init__(self, pasta_saida: Path = config.PASTA_SAIDA, perguntar: Callable[[str], str] = input,
                 mostrar: Callable[[str], None] = print):
        self.sessao = Sessao(pasta_saida)
        self.perguntar_bruto = perguntar
        self.mostrar = mostrar
        self._secao_calculadora = False

    # --- entrada do usuário ---------------------------------------------------
    def perguntar(self, texto: str) -> str:
        try:
            return self.perguntar_bruto(texto)
        except EOFError:
            raise SystemExit(0)

    def perguntar_numero(self, texto: str, inteiro: bool = False, minimo: Optional[float] = None,
                         maximo: Optional[float] = None, padrao: Optional[float] = None) -> float:
        sufixo = f" [{_curto(padrao)}]" if padrao is not None else ""
        while True:
            resposta = self.perguntar(f"{texto}{sufixo}: ").strip()
            if not resposta and padrao is not None:
                return padrao
            if resposta.lower() in ("v", "voltar", "cancelar"):
                raise Voltar()
            try:
                valores = interpretar_linha(resposta)
                if len(valores) != 1:
                    raise ValueError("informe um único número")
                valor = valores[0]
            except ValueError as erro:
                self.mostrar(f"  Valor inválido: {erro}. (digite 'v' para voltar)")
                continue
            if inteiro and not float(valor).is_integer():
                self.mostrar("  Informe um número inteiro.")
                continue
            if minimo is not None and valor < minimo:
                self.mostrar(f"  O valor deve ser pelo menos {_curto(minimo)}.")
                continue
            if maximo is not None and valor > maximo:
                self.mostrar(f"  O valor deve ser no máximo {_curto(maximo)}.")
                continue
            return int(valor) if inteiro else valor

    def pausar(self) -> None:
        self.perguntar("\nPressione Enter para voltar ao menu...")

    # --- laço principal -------------------------------------------------------------
    def executar(self) -> int:
        self.mostrar(f"\nCEP – Cartas de Controle · versão {__version__}")
        self.mostrar(f"Relatório desta sessão: {self.sessao.relatorio.caminho_pdf}")
        opcoes: List[Tuple[str, str, Callable[[], None]]] = [
            ("1", "Processar arquivo JSON (calibração ou acompanhamento, conforme o arquivo)", self.processar_json),
            ("2", "Registrar medições (módulo de entrada) e gerar JSON", self.registrar),
            ("3", "Calculadora de probabilidades (binomial, arranjos, tentativas, Poisson, desempenho)", self.calculadora),
            ("4", "Deslocamentos possíveis da última análise (probabilidade de detecção e CMC)", self.deslocamentos),
            ("5", "Guia: qual carta de controle escolher?", self.guia_escolha),
            ("6", "Ver calibrações salvas", self.ver_calibracoes),
            ("7", "Abrir o relatório PDF", self.abrir_relatorio),
            ("8", "Começar um novo relatório", self.novo_relatorio),
            ("9", "Continuar o último relatório (depois de fechar o programa)", self.continuar_relatorio),
            ("0", "Sair", None),
        ]
        while True:
            self.mostrar("\n" + "=" * 74)
            self.mostrar("MENU PRINCIPAL")
            for chave, texto, _ in opcoes:
                self.mostrar(f"  {chave}) {texto}")
            try:
                escolha = self.perguntar("Opção: ").strip()
            except KeyboardInterrupt:
                escolha = "0"
            if escolha == "0":
                self.mostrar(f"\nRelatório salvo em: {self.sessao.relatorio.ultimo_pdf or self.sessao.relatorio.caminho_pdf}")
                return 0
            acao = next((a for c, _, a in opcoes if c == escolha), None)
            if acao is None:
                self.mostrar("Opção inválida.")
                continue
            try:
                acao()
            except (Voltar, KeyboardInterrupt):
                self.mostrar("\n(voltando ao menu)")
            except SystemExit:
                raise
            except Exception as erro:  # nenhum erro inesperado derruba o programa durante o uso
                registro = self.sessao.pasta_saida / "erros.log"
                with open(registro, "a", encoding="utf-8") as arquivo:
                    arquivo.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{traceback.format_exc()}")
                self.mostrar(f"\nErro inesperado: {erro}\nDetalhes técnicos gravados em {registro}.")

    # --- 1. processar JSON -----------------------------------------------------------
    def _arquivos_candidatos(self) -> List[Tuple[Path, str]]:
        """JSON baixados recentemente (mais novos primeiro) e depois os das pastas do projeto."""
        vistos, lista = set(), []
        limite = datetime.now().timestamp() - config.DIAS_DOWNLOADS * 86400
        recentes = []
        for pasta in pastas_de_downloads():
            for arquivo in pasta.glob("*.json"):
                try:
                    momento = arquivo.stat().st_mtime
                except OSError:
                    continue
                if momento >= limite and parece_plano(arquivo):
                    recentes.append((momento, arquivo))
        recentes.sort(key=lambda item: item[0], reverse=True)
        for momento, arquivo in recentes[:config.MAX_DOWNLOADS]:
            vistos.add(arquivo.resolve())
            lista.append((arquivo, f"baixado em {datetime.fromtimestamp(momento):%d/%m %H:%M}"))
        for nome in config.PASTAS_DE_DADOS:
            pasta = Path(nome)
            if not pasta.is_dir():
                continue
            for arquivo in sorted(pasta.glob("*.json")):
                real = arquivo.resolve()
                if real in vistos or arquivo.name.startswith("calibracao_") or arquivo.name == "registro.json":
                    continue
                vistos.add(real)
                lista.append((arquivo, ""))
        return lista

    def processar_json(self) -> None:
        arquivos = self._arquivos_candidatos()
        if arquivos:
            self.mostrar("\nArquivos JSON encontrados (os baixados recentemente aparecem primeiro):")
            for i, (arquivo, extra) in enumerate(arquivos, 1):
                self.mostrar(f"  {i:2d}) {arquivo}" + (f"   [{extra}]" if extra else ""))
        self.mostrar("Digite o número da lista ou o caminho do arquivo (pode arrastar o arquivo para cá). "
                     "Enter volta.")
        resposta = self.perguntar("Arquivo: ").strip()
        if not resposta:
            raise Voltar()
        if resposta.isdigit() and arquivos and 1 <= int(resposta) <= len(arquivos):
            caminho = arquivos[int(resposta) - 1][0]
        else:
            caminho = limpar_caminho(resposta)
        self._processar(caminho)

    def _processar(self, caminho: Path) -> None:
        self._secao_calculadora = False
        try:
            resultado = self.sessao.processar_arquivo(caminho, escolher=self._escolher_calibracao,
                                                      avisar=self.mostrar)
        except ErroDeLeitura as erro:
            self.mostrar(f"\nNão foi possível processar {Path(caminho).name}:\n  {erro}")
            registrar_erro(self.sessao.relatorio, Path(caminho).name, str(erro))
            self.pausar()
            return
        self.mostrar("\n" + apresentacao.resumo_terminal(resultado))
        self.mostrar(f"Relatório atualizado: {self.sessao.relatorio.ultimo_pdf}")
        if self.sessao.relatorio.ultimo_pdf and self.sessao.relatorio.ultimo_pdf.name != "relatorio.pdf":
            self.mostrar("(o relatorio.pdf estava aberto em outro programa; esta versão foi salva com outro nome)")
        self.mostrar(f"Gráficos: {self.sessao.relatorio.pasta_graficos}")
        self.pausar()

    def _escolher_calibracao(self, plano: Plano, salvas: List[Tuple[Path, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        self.mostrar(f"\nO arquivo pede acompanhamento ({plano.nome_tipo}). Calibrações compatíveis:")
        for i, (caminho, registro) in enumerate(salvas[:15], 1):
            distancia = registro.get("_distancia")
            perto = "" if distancia is None else (f" · nível dos dados a {fmt(distancia, 1)}σ da LC"
                                                  + (" (outro processo?)" if distancia > calibracoes.DISTANCIA_PLAUSIVEL else ""))
            self.mostrar(f"  {i:2d}) {caminho.name}\n      {registro.get('Label', '')} · {registro.get('Unit', '')} · "
                         f"calibrada em {registro.get('Calibrado_em', '?')}{perto}")
        resposta = self.perguntar("Escolha o número [1], digite o caminho de outro arquivo ou 'v' para voltar: ").strip()
        if resposta.lower() in ("v", "voltar"):
            return None
        if not resposta:
            return salvas[0][1]
        if resposta.isdigit() and 1 <= int(resposta) <= min(15, len(salvas)):
            return salvas[int(resposta) - 1][1]
        return calibracoes.carregar(resposta)

    # --- 2. módulo de entrada ------------------------------------------------------
    def registrar(self) -> None:
        self._secao_calculadora = False
        caminho = registrar_medicoes(self.perguntar, self.mostrar)
        if caminho is None:
            return
        relatorio = self.sessao.relatorio
        relatorio.secao(f"Registro de medições – {caminho.name}")
        relatorio.paragrafo(f"Medições registradas pelo módulo de entrada e salvas em {caminho}.")
        relatorio.salvar()
        if self.perguntar("Processar este arquivo agora? [S/n]: ").strip().lower() in ("", "s", "sim"):
            self._processar(caminho)

    # --- 3. calculadora -------------------------------------------------------------
    def _registrar_calculo(self, titulo: str, pares: Sequence[Tuple[str, str]], explicacao: str = "") -> None:
        relatorio = self.sessao.relatorio
        if not self._secao_calculadora:
            relatorio.secao("Calculadora de probabilidades")
            self._secao_calculadora = True
        relatorio.subtitulo(titulo)
        if explicacao:
            relatorio.paragrafo(explicacao)
        relatorio.pares(pares)
        relatorio.salvar()

    def _mostrar_pares(self, pares: Sequence[Tuple[str, str]]) -> None:
        self.mostrar(tabela_texto(["Item", "Valor"], pares))

    def calculadora(self) -> None:
        opcoes = [
            ("1", "Combinações C(n, k), arranjos A(n, k) e permutações n!", self._calc_combinatoria),
            ("2", "Binomial: k sucessos em n tentativas com probabilidade p", self._calc_binomial),
            ("3", "Tentativas até o primeiro sucesso (geométrica)", self._calc_geometrica),
            ("4", "Poisson: número de defeitos com média λ", self._calc_poisson),
            ("5", "Desempenho da carta X-barra ou I para um deslocamento δ (β, 1 − β, CMC)", self._calc_desempenho_media),
            ("6", "Desempenho da carta p (binomial) ou c (Poisson) para um novo nível", self._calc_desempenho_atributo),
            ("0", "Voltar", None),
        ]
        while True:
            self.mostrar("\n--- Calculadora de probabilidades ---")
            for chave, texto, _ in opcoes:
                self.mostrar(f"  {chave}) {texto}")
            escolha = self.perguntar("Opção: ").strip()
            if escolha in ("0", "", "v"):
                return
            acao = next((a for c, _, a in opcoes if c == escolha), None)
            if acao is None:
                self.mostrar("Opção inválida.")
                continue
            try:
                acao()
            except Voltar:
                continue
            except prob.ErroDeProbabilidade as erro:
                self.mostrar(f"  {erro}")

    def _calc_combinatoria(self) -> None:
        n = self.perguntar_numero("n (total de elementos)", inteiro=True, minimo=0)
        k = self.perguntar_numero("k (elementos escolhidos)", inteiro=True, minimo=0)
        pares = [("n, k", f"{n}, {k}"), ("Combinações C(n, k) = n! / (k!(n − k)!)", f"{prob.combinacoes(n, k):,}".replace(",", ".")),
                 ("Arranjos A(n, k) = n! / (n − k)!", f"{prob.arranjos(n, k):,}".replace(",", ".")),
                 ("Permutações n!", f"{prob.permutacoes(n):,}".replace(",", ".") if n <= 170 else "muito grande")]
        self._mostrar_pares(pares)
        self._registrar_calculo("Combinações e arranjos", pares,
                                "Combinação: a ordem não importa (ex.: quais k itens de uma amostra de n são defeituosos). "
                                "Arranjo: a ordem importa (sequências).")

    def _calc_binomial(self) -> None:
        n = self.perguntar_numero("n (número de tentativas, ex.: itens inspecionados)", inteiro=True, minimo=1)
        p = self.perguntar_numero("p (probabilidade de sucesso em cada tentativa)", minimo=0, maximo=1)
        k = self.perguntar_numero("k (número de sucessos de interesse)", inteiro=True, minimo=0, maximo=n)
        exato = prob.binomial_pmf(k, n, p)
        ate = prob.binomial_acumulada(k, n, p)
        pelo_menos = 1 - prob.binomial_acumulada(k - 1, n, p)
        resumo = prob.binomial_resumo(n, p)
        pares = [("n, p, k", f"{n}; {fmt(p, 4)}; {k}"),
                 (f"P(X = {k}) = C(n,k)·p^k·(1 − p)^(n − k)", fmt_prob(exato)),
                 (f"P(X ≤ {k})", fmt_prob(ate)), (f"P(X ≥ {k})", fmt_prob(pelo_menos)),
                 ("P(X = 0) – nenhum sucesso (todas falham)", fmt_prob(prob.binomial_pmf(0, n, p))),
                 ("Média n·p e desvio-padrão √(n·p·(1 − p))", f"{fmt(resumo['media'], 3)} e {fmt(resumo['desvio'], 3)}")]
        self._mostrar_pares(pares)
        self._registrar_calculo("Distribuição binomial", pares,
                                "X = número de sucessos em n tentativas independentes, cada uma com probabilidade p. "
                                "Na carta p, X é o número de itens defeituosos na amostra.")

    def _calc_geometrica(self) -> None:
        p = self.perguntar_numero("p (probabilidade de sucesso em cada tentativa, ex.: 1 − β)", minimo=0, maximo=1)
        m = self.perguntar_numero("m (número de tentativas de interesse)", inteiro=True, minimo=1, padrao=3)
        alvo = self.perguntar_numero("Probabilidade-alvo de já ter tido sucesso", minimo=0, maximo=0.9999, padrao=0.95)
        necessario = prob.tentativas_para_atingir(alvo, p)
        pares = [("p", fmt(p, 4)), (f"P(1º sucesso exatamente na tentativa {m}) = (1 − p)^(m − 1)·p",
                                     fmt_prob(prob.prob_primeiro_sucesso_em(m, p))),
                 (f"P(pelo menos um sucesso em até {m} tentativas) = 1 − (1 − p)^m", fmt_prob(prob.prob_sucesso_ate(m, p))),
                 ("Tentativas esperadas até o 1º sucesso = 1/p (CMC)", fmt_cmc(prob.tentativas_esperadas(p))),
                 (f"Tentativas para chegar a {fmt(100 * alvo, 1)}% de chance", "não atinge" if necessario is None else str(necessario))]
        self._mostrar_pares(pares)
        self._registrar_calculo("Tentativas até o primeiro sucesso (geométrica)", pares,
                                "Nas cartas de controle, cada amostra é uma tentativa e 'sucesso' é a carta detectar o "
                                "deslocamento; o número médio de amostras até detectar é o CMC.")

    def _calc_poisson(self) -> None:
        lam = self.perguntar_numero("λ (média de defeitos, ex.: c-barra)", minimo=0)
        k = self.perguntar_numero("k (número de defeitos de interesse)", inteiro=True, minimo=0)
        pares = [("λ, k", f"{fmt(lam, 4)}; {k}"), (f"P(X = {k}) = e^(−λ)·λ^k / k!", fmt_prob(prob.poisson_pmf(k, lam))),
                 (f"P(X ≤ {k})", fmt_prob(prob.poisson_acumulada(k, lam))),
                 (f"P(X ≥ {k})", fmt_prob(1 - prob.poisson_acumulada(k - 1, lam)))]
        self._mostrar_pares(pares)
        self._registrar_calculo("Distribuição de Poisson", pares, "Modelo da carta c: número de defeitos por unidade de inspeção.")

    def _calc_desempenho_media(self) -> None:
        n = self.perguntar_numero("n (tamanho do subgrupo; 1 para a carta I)", inteiro=True, minimo=1)
        delta = self.perguntar_numero("δ (deslocamento da média, em desvios-padrão do processo)")
        L = self.perguntar_numero("L (distância dos limites, em σ da média)", minimo=0.1, padrao=3.0)
        d = prob.desempenho_media(delta, n, L, L)
        pares = [("n, δ, L", f"{n}; {fmt(delta, 3)}σ; {fmt(L, 2)}"),
                 ("β = Φ(L − δ√n) − Φ(−L − δ√n)  (falha: não detectar)", fmt_prob(d["beta"])),
                 ("1 − β  (sucesso: detectar em uma amostra)", fmt_prob(d["p_detectar"])),
                 ("CMC = 1/(1 − β)  (amostras até detectar)", fmt_cmc(d["cmc"]))]
        pares += [(f"P(detectar em até {m} amostra{'s' if m > 1 else ''}) = 1 − β^m", fmt_prob(p)) for m, p in
                  prob.detectar_ate(d["p_detectar"], [1, 2, 3, 5, 10])]
        self._mostrar_pares(pares)
        self._registrar_calculo("Desempenho da carta X-barra / I", pares,
                                "Probabilidade de a carta detectar um deslocamento δ·σ na média (Montgomery & Runger).")

    def _calc_desempenho_atributo(self) -> None:
        tipo = self.perguntar("Carta p ou c? ").strip().lower()
        if tipo.startswith("p"):
            pbar = self.perguntar_numero("p-barra (fração defeituosa calibrada)", minimo=0, maximo=1)
            n = self.perguntar_numero("n (tamanho da amostra)", inteiro=True, minimo=1)
            p1 = self.perguntar_numero("p1 (nova fração defeituosa)", minimo=0, maximo=1)
            s = (pbar * (1 - pbar) / n) ** 0.5
            lsc, lic = min(1.0, pbar + 3 * s), max(0.0, pbar - 3 * s)
            d = prob.desempenho_p(p1, n, lic, lsc)
            pares = [("p-barra, n, p1", f"{fmt(pbar, 4)}; {n}; {fmt(p1, 4)}"),
                     ("LIC e LSC da carta p", f"{fmt(lic, 4)} e {fmt(lsc, 4)}"),
                     ("β = P(LIC ≤ D/n ≤ LSC | p1) (binomial)", fmt_prob(d["beta"])),
                     ("1 − β (detectar em uma amostra)", fmt_prob(d["p_detectar"])), ("CMC", fmt_cmc(d["cmc"]))]
            titulo = "Desempenho da carta p (binomial)"
        else:
            cbar = self.perguntar_numero("c-barra (média de defeitos calibrada)", minimo=0)
            c1 = self.perguntar_numero("c1 (nova média de defeitos)", minimo=0)
            s = cbar ** 0.5
            lsc, lic = cbar + 3 * s, max(0.0, cbar - 3 * s)
            d = prob.desempenho_c(c1, lic, lsc)
            pares = [("c-barra, c1", f"{fmt(cbar, 3)}; {fmt(c1, 3)}"), ("LIC e LSC da carta c", f"{fmt(lic, 3)} e {fmt(lsc, 3)}"),
                     ("β = P(LIC ≤ c ≤ LSC | c1) (Poisson)", fmt_prob(d["beta"])),
                     ("1 − β (detectar em uma amostra)", fmt_prob(d["p_detectar"])), ("CMC", fmt_cmc(d["cmc"]))]
            titulo = "Desempenho da carta c (Poisson)"
        self._mostrar_pares(pares)
        self._registrar_calculo(titulo, pares)

    # --- 4. deslocamentos possíveis ------------------------------------------------
    def deslocamentos(self) -> None:
        resultado = self.sessao.ultimo
        if resultado is None or not resultado.deslocamento or resultado.deslocamento.get("aviso"):
            self.mostrar("Processe antes um arquivo JSON (opção 1); esta opção usa a última análise feita.")
            self.pausar()
            return
        d = resultado.deslocamento
        self._secao_calculadora = False
        self.mostrar(f"\nÚltima análise: {apresentacao.titulo_atividade(resultado)}")
        textos, tabelas = apresentacao.textos_deslocamento(resultado)
        cab, linhas = tabelas[0]
        self.mostrar(tabela_texto(cab, linhas))
        pergunta = {"media": "Deslocamento δ da média, em σ do processo (ex.: 1,5)",
                    "variabilidade": "Razão σ1/σ0 (ex.: 1,5)",
                    "fracao": "Nova fração defeituosa p1", "contagem": "Nova média de defeitos c1",
                    "taxa": "Novo número de defeitos por unidade u1"}[d["tipo"]]
        relatorio = self.sessao.relatorio
        relatorio.secao(f"Deslocamentos possíveis – {resultado.plano.arquivo}")
        relatorio.paragrafo("Probabilidade de a carta calibrada detectar deslocamentos possíveis do processo.")
        relatorio.tabela(cab, linhas)
        while True:
            texto = self.perguntar(f"{pergunta} (Enter para terminar): ").strip()
            if not texto:
                break
            try:
                valor = interpretar_linha(texto)[0]
            except (ValueError, IndexError):
                self.mostrar("  Valor inválido.")
                continue
            r = desempenho_personalizado(d, valor)
            pares = [("Deslocamento informado", texto), ("1 − β (sucesso: detectar em uma amostra)", fmt_prob(r["p_detectar"])),
                     ("β (falha: não detectar)", fmt_prob(r["beta"])), ("CMC (amostras até detectar)", fmt_cmc(r["cmc"]))]
            pares += [(f"P(detectar em até {m} amostras)", fmt_prob(p)) for m, p in prob.detectar_ate(r["p_detectar"], [2, 3, 5, 10])]
            self._mostrar_pares(pares)
            relatorio.pares(pares)
        relatorio.salvar()

    # --- 5. guia de escolha ---------------------------------------------------------
    def guia_escolha(self) -> None:
        self._secao_calculadora = False

        def sim(pergunta: str) -> bool:
            while True:
                r = self.perguntar(pergunta + " [s/n]: ").strip().lower()
                if r in ("s", "sim"):
                    return True
                if r in ("n", "nao", "não"):
                    return False
                if r in ("v", "voltar"):
                    raise Voltar()

        respostas = []
        if sim("A característica é MEDIDA numa escala contínua (comprimento, tensão, temperatura...)?"):
            respostas.append("característica medida (variável)")
            if sim("Você mede vários itens de cada vez (subgrupos com n >= 2)?"):
                respostas.append("subgrupos com n >= 2")
                carta = ("X-barra e R (Type X). Com subgrupos grandes (n > 10), o Montgomery prefere X-barra e S.")
            else:
                respostas.append("uma medição por vez")
                carta = "I-AM, valores individuais e amplitude móvel (Type IMR)."
        else:
            respostas.append("característica contada (atributo)")
            if sim("Você conta ITENS DEFEITUOSOS (cada item é bom ou ruim)?"):
                respostas.append("itens defeituosos")
                if sim("O tamanho da amostra é sempre o mesmo?"):
                    respostas.append("tamanho de amostra constante")
                    carta = "p (fração defeituosa) ou np (número de defeituosos) – Type P ou NP."
                else:
                    respostas.append("tamanho de amostra variável")
                    carta = "p (fração defeituosa), com limites variando com n – Type P."
            else:
                respostas.append("defeitos (podem existir vários por item)")
                if sim("A unidade de inspeção tem sempre o mesmo tamanho?"):
                    respostas.append("unidade de inspeção constante")
                    carta = "c (número de defeitos) – Type C."
                else:
                    respostas.append("tamanho da unidade variável")
                    carta = "u (defeitos por unidade) – Type U."
        self.mostrar(f"\nCarta recomendada: {carta}")
        relatorio = self.sessao.relatorio
        relatorio.secao("Guia de escolha da carta")
        relatorio.lista(respostas)
        relatorio.paragrafo(f"Carta recomendada: {carta}")
        relatorio.salvar()
        self.pausar()

    # --- 6, 7, 8 -------------------------------------------------------------------
    def ver_calibracoes(self) -> None:
        itens = calibracoes.listar(self.sessao.pasta_saida)
        if not itens:
            self.mostrar("Nenhuma calibração salva ainda.")
        else:
            linhas = [[c.name, r.get("Type", ""), r.get("Label", ""), r.get("Calibrado_em", ""),
                       r.get("Status", "")[:60]] for c, r in itens]
            self.mostrar(tabela_texto(["Arquivo", "Tipo", "Descrição", "Calibrada em", "Situação"], linhas))
        self.pausar()

    def abrir_relatorio(self) -> None:
        caminho = self.sessao.relatorio.ultimo_pdf
        if caminho is None or not Path(caminho).exists():
            self.sessao.relatorio.salvar()
            caminho = self.sessao.relatorio.ultimo_pdf
        if not abrir_arquivo(caminho):
            self.mostrar(f"Não consegui abrir automaticamente. Abra este arquivo: {caminho}")
        else:
            self.mostrar(f"Abrindo {caminho}")

    def novo_relatorio(self) -> None:
        anterior = self.sessao.relatorio.ultimo_pdf
        self.sessao.usar_relatorio(Relatorio(nova_pasta_sessao(self.sessao.pasta_saida)))
        self._secao_calculadora = False
        if anterior:
            self.mostrar(f"Relatório anterior mantido em {anterior}.")
        self.mostrar(f"Novo relatório: {self.sessao.relatorio.caminho_pdf}")

    def continuar_relatorio(self) -> None:
        self._secao_calculadora = False
        pasta = self.sessao.continuar_ultimo_relatorio()
        if pasta is None:
            self.mostrar("Não há relatório anterior para continuar.")
            return
        secoes = self.sessao.relatorio.num_secoes
        self.mostrar(f"Continuando o relatório de {pasta.name} ({secoes} atividade{'s' if secoes != 1 else ''} até agora).")
        self.mostrar(f"As próximas atividades entram no mesmo PDF: {self.sessao.relatorio.ultimo_pdf}")
