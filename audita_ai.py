#!/usr/bin/env python3
"""
Audita Aí;  —  confere os boletins de urna (BU) publicados pelo TSE contra o resultado oficial.
por Garoto do Programa;  (github.com/garotodoprograma404/audita-ai)

O que ele confere, em 5 passos:
  1. baixa os boletins de urna de um estado (portal de dados abertos do TSE);
  2. INTEGRIDADE: o hash SHA-512 do arquivo é igual ao que o TSE publicou?
  3. CONSISTÊNCIA: em cada seção, a soma dos votos bate com quem compareceu?
  4. TOTALIZAÇÃO: a soma de todos os boletins bate com o resultado oficial divulgado?
  5. ESTATÍSTICA: simula pesquisas (Monte Carlo) pra mostrar de onde sai a margem de erro.

Uso:
  python3 audita_ai.py                 # Acre, 1º turno (o menor arquivo, ~17 MB)
  python3 audita_ai.py RR              # qualquer estado (ZZ = eleitores no exterior)
  python3 audita_ai.py SP --turno 2    # 2º turno (quando o TSE publicar)
  python3 -m unittest                  # roda os testes

Precisa só de Python 3.10+. Nenhuma biblioteca pra instalar.
Isto NÃO é pesquisa eleitoral nem previsão: a simulação usa a abstenção, um resultado que já aconteceu,
e o programa não mostra nome de candidato nenhum (só contagens).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import hmac
import io
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ANO = 2026
API_DADOS_ABERTOS = f"https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ANO}-boletim-de-urna"
RESULTADOS = "https://resultados.tse.jus.br/oficial"
PASTA_DADOS = Path(__file__).resolve().parent / "dados"
UFS = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ",   # ZZ = exterior
})

# Quantos votos cada eleitor dá em cada cargo, pela regra da eleição de 2026.
# Senador: 2/3 do Senado são renovados → duas vagas por estado → dois votos por eleitor.
VOTOS_POR_ELEITOR = {"Senador": 2}


# ---------------------------------------------------------------- saída no terminal
COR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def pinta(texto: object, codigo: str) -> str:
    return f"\033[{codigo}m{texto}\033[0m" if COR else str(texto)


def verde(texto: object) -> str:
    return pinta(texto, "1;92")


def rosa(texto: object) -> str:
    return pinta(texto, "1;95")


def amarelo(texto: object) -> str:
    return pinta(texto, "1;93")


def cinza(texto: object) -> str:
    return pinta(texto, "90")


def br(fracao: float, casas: int = 2) -> str:
    """Porcentagem no jeito brasileiro: 0.2044 -> '20,44%'."""
    return f"{fracao * 100:.{casas}f}%".replace(".", ",")


def mil(n: int) -> str:
    """Ponto de milhar: 613742 -> '613.742'."""
    return f"{n:,}".replace(",", ".")


def marca(ok: bool) -> str:
    return verde("✓") if ok else rosa("✗")


# ---------------------------------------------------------------- 1. baixar
def baixar_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as erro:
        raise SystemExit(rosa(f"Não consegui ler {url}\n   ({erro}). Confere a internet e tenta de novo.")) from None


def achar_boletim(uf: str, turno: int) -> str:
    """O nome do arquivo muda com a data em que o TSE gerou; então a gente pergunta pra API do portal."""
    pacote = baixar_json(API_DADOS_ABERTOS)["result"]
    nome_turno = "Primeiro turno" if turno == 1 else "Segundo turno"
    for recurso in pacote["resources"]:
        nome = recurso.get("name", "")
        if nome.startswith(f"{uf} - ") and nome_turno in nome and recurso["url"].endswith(".zip"):
            return recurso["url"]
    raise SystemExit(rosa(f"O TSE ainda não publicou o boletim de {uf} ({nome_turno})."))


def baixar(url: str, destino: Path) -> None:
    if destino.exists():
        print(cinza(f"   já baixado: {destino.name}"))
        return
    print(cinza(f"   baixando {url}"))
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with urllib.request.urlopen(url, timeout=600) as resp, parcial.open("wb") as arquivo:
            while bloco := resp.read(1 << 20):
                arquivo.write(bloco)
    except (urllib.error.URLError, TimeoutError) as erro:
        parcial.unlink(missing_ok=True)
        raise SystemExit(rosa(f"Download falhou ({erro}). Tenta de novo.")) from None
    parcial.replace(destino)       # só vira o arquivo "de verdade" quando terminou inteiro


# ---------------------------------------------------------------- 2. integridade
def sha512_do_arquivo(caminho: Path) -> str:
    h = hashlib.sha512()
    with caminho.open("rb") as arquivo:
        while bloco := arquivo.read(1 << 20):    # em pedaços de 1 MB: não precisa caber na memória
            h.update(bloco)
    return h.hexdigest()


def hash_publicado(caminho_sha: Path) -> str:
    with caminho_sha.open(encoding="ascii") as arquivo:
        return arquivo.read().split()[0].lower()


# ---------------------------------------------------------------- 3. ler os boletins
@dataclass
class Secao:
    municipio: str
    aptos: int
    compareceram: int
    faltaram: int
    votos: int = 0


@dataclass
class Cargo:
    """Tudo que os boletins dizem sobre UM cargo, somado no estado inteiro."""
    nome: str
    eleicao: str                                   # código da eleição (ex.: 6257 = federal, 6259 = estadual)
    secoes: dict = field(default_factory=dict)     # (município, zona, seção) -> Secao
    por_tipo: collections.Counter = field(default_factory=collections.Counter)    # Nominal/Legenda/Branco/Nulo
    por_numero: collections.Counter = field(default_factory=collections.Counter)  # número do votável -> votos


def ler_boletins(caminho_zip: Path) -> dict[str, Cargo]:
    """Lê o CSV de dentro do zip linha por linha (streaming) e soma tudo por cargo e por seção.

    Cada linha do arquivo é UMA seção × UM cargo × UM votável (candidato, legenda, branco ou nulo).
    """
    cargos: dict[str, Cargo] = {}
    with zipfile.ZipFile(caminho_zip) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            raise SystemExit(rosa(f"{caminho_zip.name} não tem CSV dentro."))
        with z.open(csvs[0]) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="latin-1")      # o TSE usa latin-1 e ";"
            for linha in csv.DictReader(texto, delimiter=";"):
                codigo = linha["CD_CARGO_PERGUNTA"]
                cargo = cargos.setdefault(codigo, Cargo(linha["DS_CARGO_PERGUNTA"], linha["CD_ELEICAO"]))
                votos = int(linha["QT_VOTOS"])                       # o CSV entrega texto: converte antes de somar!
                chave = (linha["CD_MUNICIPIO"], linha["NR_ZONA"], linha["NR_SECAO"])
                secao = cargo.secoes.setdefault(chave, Secao(
                    linha["NM_MUNICIPIO"], int(linha["QT_APTOS"]),
                    int(linha["QT_COMPARECIMENTO"]), int(linha["QT_ABSTENCOES"])))
                secao.votos += votos
                cargo.por_tipo[linha["DS_TIPO_VOTAVEL"]] += votos
                if linha["DS_TIPO_VOTAVEL"] == "Nominal":
                    cargo.por_numero[linha["NR_VOTAVEL"]] += votos
    return cargos


# ---------------------------------------------------------------- 3b. consistência de cada seção
@dataclass
class Consistencia:
    cargo: str
    votos_por_eleitor: int
    secoes: int
    soma_bate: int           # seções em que votos == comparecimento × votos por eleitor
    presenca_bate: int       # seções em que aptos == compareceram + faltaram

    @property
    def ok(self) -> bool:
        return self.soma_bate == self.presenca_bate == self.secoes


def conferir_secoes(cargo: Cargo) -> Consistencia:
    n = VOTOS_POR_ELEITOR.get(cargo.nome, 1)
    return Consistencia(
        cargo=cargo.nome,
        votos_por_eleitor=n,
        secoes=len(cargo.secoes),
        soma_bate=sum(1 for s in cargo.secoes.values() if s.votos == n * s.compareceram),
        presenca_bate=sum(1 for s in cargo.secoes.values() if s.aptos == s.compareceram + s.faltaram),
    )


# ---------------------------------------------------------------- 4. totalização oficial
def achar_ciclo(turno: int) -> str:
    """O site de resultados do TSE guarda as eleições num arquivo de configuração."""
    config = baixar_json(f"{RESULTADOS}/comum/config/ele-c.json")
    for pleito in config["pl"]:
        if pleito["c"] == f"ele{ANO}" and any(e["t"] == str(turno) for e in pleito["e"]):
            return pleito["c"]
    raise SystemExit(rosa(f"Resultado oficial do {turno}º turno de {ANO} ainda não está no site do TSE."))


def resultado_oficial(ciclo: str, eleicao: str, cargo: str, uf: str) -> dict:
    """Total oficial divulgado pelo TSE pra um cargo num estado (é o mesmo dado do site de resultados)."""
    arquivo = f"{uf.lower()}-c{int(cargo):04d}-e{int(eleicao):06d}-u.json"
    return baixar_json(f"{RESULTADOS}/{ciclo}/{int(eleicao)}/dados/{uf.lower()}/{arquivo}")


@dataclass
class Totalizacao:
    cargo: str
    linhas: list = field(default_factory=list)     # (o que, soma dos boletins, oficial)
    candidatos: int = 0
    candidatos_batem: int = 0

    @property
    def ok(self) -> bool:
        return self.candidatos == self.candidatos_batem and all(bu == of for _, bu, of in self.linhas)


def conferir_totalizacao(cargo: Cargo, oficial: dict) -> Totalizacao:
    """Soma de TODOS os boletins == resultado oficial divulgado? Campo a campo e candidato a candidato.

    Detalhe que pega muita gente: o boletim conta o voto no número digitado. Se o candidato teve o registro
    barrado, o resultado oficial joga esses votos em "nulos técnicos" (vnt) ou "anulados sub judice".
    Então: votos nominais nos boletins = válidos nominais + sub judice + nulos técnicos.
    """
    e, v = oficial["e"], oficial["v"]
    candidatos = [c for agr in oficial["carg"][0]["agr"] for par in agr["par"] for c in par["cand"]]
    numeros_oficiais = {c["n"] for c in candidatos}
    nulos_tecnicos = sum(n for numero, n in cargo.por_numero.items() if numero not in numeros_oficiais)
    sub_judice = sum(int(c["vap"]) for c in candidatos if c.get("dvt") != "Válido")
    t = Totalizacao(cargo.nome)
    t.linhas = [
        ("eleitores aptos", sum(s.aptos for s in cargo.secoes.values()), int(e["te"])),
        ("compareceram", sum(s.compareceram for s in cargo.secoes.values()), int(e["c"])),
        ("faltaram", sum(s.faltaram for s in cargo.secoes.values()), int(e["a"])),
        ("votos em branco", cargo.por_tipo["Branco"], int(v["vb"])),
        ("votos nulos (digitados + técnicos)", cargo.por_tipo["Nulo"] + nulos_tecnicos, int(v["tvn"])),
        ("nominais (válidos + sub judice + nulos técnicos)", cargo.por_tipo["Nominal"],
         int(v["vnom"]) + sub_judice + int(v.get("vnt") or 0)),
    ]
    if v.get("vl") is not None:            # só deputado tem voto de legenda (voto só no número do partido)
        partidos = [par for agr in oficial["carg"][0]["agr"] for par in agr["par"]]
        t.linhas.append(("votos de legenda", cargo.por_tipo["Legenda"], sum(int(p.get("tvtl") or 0) for p in partidos)))
    t.candidatos = len(candidatos)
    t.candidatos_batem = sum(1 for c in candidatos if cargo.por_numero[c["n"]] == int(c["vap"]))
    return t


# ---------------------------------------------------------------- raio-X (sem candidatos)
def cargo_de_referencia(cargos: dict[str, Cargo]) -> Cargo:
    """Presidente: TODO eleitor vota nele (quem vota em trânsito só pode votar pra presidente,
    então o número de aptos muda de cargo pra cargo). Se não tiver, usa o cargo com mais seções."""
    return next((c for c in cargos.values() if c.nome == "Presidente"),
                max(cargos.values(), key=lambda c: len(c.secoes)))


def abstencao(cargo: Cargo) -> tuple[int, int, float]:
    aptos = sum(s.aptos for s in cargo.secoes.values())
    faltaram = sum(s.faltaram for s in cargo.secoes.values())
    return aptos, faltaram, (faltaram / aptos if aptos else 0.0)


def abstencao_por_municipio(cargo: Cargo) -> list[tuple[str, float]]:
    soma = collections.defaultdict(lambda: [0, 0])
    for s in cargo.secoes.values():
        soma[s.municipio][0] += s.faltaram
        soma[s.municipio][1] += s.aptos
    return sorted(((m, f / a) for m, (f, a) in soma.items() if a), key=lambda x: x[1])


# ---------------------------------------------------------------- 5. simulação de Monte Carlo
def simular_pesquisas(taxa_real: float, amostra: int, rodadas: int, semente: int) -> list[float]:
    """Finge ser um instituto de pesquisa: entrevista `amostra` eleitores sorteados e anota quantos faltaram.
    Repete `rodadas` vezes. Semente fixa = qualquer pessoa roda e tira exatamente o mesmo resultado."""
    sorteio = random.Random(semente)
    resultados = []
    for _ in range(rodadas):
        faltosos = sum(1 for _ in range(amostra) if sorteio.random() < taxa_real)   # um eleitor por vez
        resultados.append(faltosos / amostra)
    return resultados


def margem_de_erro(taxa: float, amostra: int, z: float = 1.96) -> float:
    """A fórmula que os institutos usam (95% de confiança): z × √(p(1−p)/n)."""
    return z * math.sqrt(taxa * (1 - taxa) / amostra)


def fracao_dentro(resultados: list[float], taxa_real: float, margem: float) -> float:
    return sum(1 for r in resultados if abs(r - taxa_real) <= margem) / len(resultados)


def histograma(resultados: list[float], taxa_real: float, margem: float, faixa: float = 0.005) -> list[str]:
    caixas = collections.Counter(round((r - taxa_real) / faixa) for r in resultados)
    maior = max(caixas.values())
    linhas = []
    for c in range(min(caixas), max(caixas) + 1):
        barra = "█" * round(caixas[c] / maior * 40)
        cor = verde if abs(c * faixa) <= margem else rosa
        linhas.append(f"   {br(taxa_real + c * faixa, 1):>6} {cor(barra)}")
    return linhas


# ---------------------------------------------------------------- programa
def argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Audita Aí; confere os boletins de urna do TSE contra o resultado oficial")
    ap.add_argument("uf", nargs="?", default="AC", type=str.upper, help="sigla do estado (padrão: AC; ZZ = exterior)")
    ap.add_argument("--turno", type=int, choices=(1, 2), default=1)
    ap.add_argument("--amostra", type=int, default=2000, help="eleitores por pesquisa simulada")
    ap.add_argument("--rodadas", type=int, default=5000, help="quantas pesquisas simular")
    ap.add_argument("--semente", type=int, default=ANO, help="semente do sorteio (resultado reprodutível)")
    a = ap.parse_args(argv)
    if a.uf not in UFS:
        ap.error(f"'{a.uf}' não é uma UF. Use uma destas: {' '.join(sorted(UFS))}")
    if a.amostra < 1 or a.rodadas < 1:
        ap.error("--amostra e --rodadas precisam ser maiores que zero")
    return a


def titulo(n: int, texto: str) -> None:
    print("\n" + amarelo(f"[{n}/5] {texto}"))


def main(argv: list[str] | None = None) -> int:
    a = argumentos(argv)
    PASTA_DADOS.mkdir(exist_ok=True)
    print(verde("Audita Aí;") + cinza(f"  por Garoto do Programa · dados oficiais do TSE · {a.turno}º turno {ANO}"))

    titulo(1, f"baixando os boletins de urna de {a.uf}")
    url = achar_boletim(a.uf, a.turno)
    zip_local = PASTA_DADOS / Path(url).name
    sha_local = PASTA_DADOS / (Path(url).name + ".sha512")
    baixar(url, zip_local)
    baixar(url + ".sha512", sha_local)

    titulo(2, "integridade: o arquivo é idêntico ao publicado? (SHA-512)")
    oficial_hash, calculado = hash_publicado(sha_local), sha512_do_arquivo(zip_local)
    print(cinza(f"   TSE publicou: {oficial_hash[:32]}…\n   calculei:     {calculado[:32]}…"))
    if not hmac.compare_digest(oficial_hash, calculado):
        print(rosa(f"   ✗ o arquivo NÃO é igual ao publicado. Apaga {zip_local.name} e roda de novo."))
        return 1
    print("   " + verde("✓ idêntico ao publicado pelo TSE"))

    titulo(3, "consistência: em cada seção, a soma dos votos bate com quem compareceu?")
    cargos = ler_boletins(zip_local)
    tudo_ok = True
    for codigo in sorted(cargos, key=int):
        c = conferir_secoes(cargos[codigo])
        tudo_ok &= c.ok
        extra = cinza(f"  (cada eleitor dá {c.votos_por_eleitor} votos)") if c.votos_por_eleitor > 1 else ""
        print(f"   {c.cargo:<18} {mil(c.soma_bate):>7} de {mil(c.secoes):<7} seções  {marca(c.ok)}{extra}")

    titulo(4, "totalização: a soma de TODOS os boletins bate com o resultado oficial?")
    ciclo = achar_ciclo(a.turno)
    for codigo in sorted(cargos, key=int):
        cargo = cargos[codigo]
        t = conferir_totalizacao(cargo, resultado_oficial(ciclo, cargo.eleicao, codigo, a.uf))
        tudo_ok &= t.ok
        print(f"   {amarelo(cargo.nome)}  {marca(t.ok)}")
        for oque, bu, of in t.linhas:
            print(cinza(f"      {oque:<48}") + f" {mil(bu):>10} = {mil(of):<10} {marca(bu == of)}")
        print(cinza(f"      {'votos de cada candidato':<48}") +
              f" {t.candidatos_batem:>10} de {t.candidatos:<7} {marca(t.candidatos_batem == t.candidatos)}")
    print("   " + (verde("✓ tudo bateu") if tudo_ok else rosa("✗ tem diferença pra investigar (veja acima)")))

    referencia = cargo_de_referencia(cargos)
    aptos, faltaram, taxa = abstencao(referencia)
    ranking = abstencao_por_municipio(referencia)
    print(amarelo("\n   raio-X do estado"))
    print(f"   {mil(len(referencia.secoes))} seções · {mil(aptos)} aptos · {mil(faltaram)} faltaram"
          f" → abstenção de {amarelo(br(taxa))}")
    print(cinza("   menos faltosos:"), ", ".join(f"{m.title()} ({br(x, 1)})" for m, x in ranking[:3]))
    print(cinza("   mais faltosos: "), ", ".join(f"{m.title()} ({br(x, 1)})" for m, x in ranking[::-1][:3]))

    titulo(5, f"e se fosse uma pesquisa? {mil(a.rodadas)} sorteios de {mil(a.amostra)} eleitores")
    resultados = simular_pesquisas(taxa, a.amostra, a.rodadas, a.semente)
    margem = margem_de_erro(taxa, a.amostra)
    print("\n".join(histograma(resultados, taxa, margem)))
    print(f"   valor real: {amarelo(br(taxa))}  ·  margem pela fórmula: ±{br(margem, 1).rstrip('%')} pontos")
    print(f"   {verde(br(fracao_dentro(resultados, taxa, margem), 1))} das {mil(a.rodadas)} pesquisas "
          "simuladas caíram dentro da margem")
    print(cinza("\n   não é pesquisa nem previsão: é matemática em cima de um resultado que já aconteceu."))
    print(verde("   confere você também;)  ") + cinza("github.com/garotodoprograma404/audita-ai"))
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
