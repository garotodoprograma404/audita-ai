#!/usr/bin/env python3
"""
Sabotagem;  —  adultera UMA CÓPIA do boletim de urna e vê se o Audita Aí pega.
por Garoto do Programa;  (github.com/garotodoprograma404/audita-ai)

Nenhuma urna é tocada: o programa copia o arquivo que você baixou do TSE, muda UM voto na cópia
(dentro da pasta dados/) e roda as três conferências do Audita Aí contra ela.

Golpes:
  troca   tira 1 voto de um candidato e dá pra outro, na mesma seção (a conta da seção continua fechando!)
  branco  enfia 1 voto em branco a mais numa seção

Uso:
  python3 sabotagem.py                  # Acre, golpe "troca"
  python3 sabotagem.py --golpe branco
  python3 sabotagem.py RR --golpe troca

Moral da história: uma conferência sozinha tem furo. Auditoria boa é camada em cima de camada.
"""
from __future__ import annotations

import argparse
import csv
import hmac
import io
import sys
import zipfile
from pathlib import Path

import audita_ai as A

CARGO_ALVO = "1"           # Presidente (o programa nunca mostra nome nem número de candidato)


def sabotar(original: Path, destino: Path, golpe: str, cargo: str = CARGO_ALVO) -> tuple[str, str, str]:
    """Copia o boletim mudando UM voto (linha por linha, sem carregar tudo na memória).

    Devolve a seção que foi adulterada: (município, zona, seção).
    """
    alvo, mexidas = None, 0
    with zipfile.ZipFile(original) as z_in:
        nome = next(n for n in z_in.namelist() if n.lower().endswith(".csv"))
        with z_in.open(nome) as bruto, \
                zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z_out, \
                z_out.open(nome, "w") as saida:
            texto = io.TextIOWrapper(saida, encoding="latin-1", newline="")
            escritor = csv.writer(texto, delimiter=";", quoting=csv.QUOTE_ALL)
            leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
            cabecalho = next(leitor)
            escritor.writerow(cabecalho)
            col = {c: i for i, c in enumerate(cabecalho)}
            for linha in leitor:
                if linha[col["CD_CARGO_PERGUNTA"]] == cargo and mexidas < (2 if golpe == "troca" else 1):
                    secao = (linha[col["CD_MUNICIPIO"]], linha[col["NR_ZONA"]], linha[col["NR_SECAO"]])
                    tipo, votos = linha[col["DS_TIPO_VOTAVEL"]], int(linha[col["QT_VOTOS"]])
                    if golpe == "branco" and tipo == "Branco":
                        linha[col["QT_VOTOS"]] = str(votos + 1)              # +1 voto que ninguém deu
                        alvo, mexidas = secao, 1
                    elif golpe == "troca" and tipo == "Nominal":
                        if mexidas == 0 and votos > 0:
                            linha[col["QT_VOTOS"]] = str(votos - 1)          # tira 1 do candidato A…
                            alvo, mexidas = secao, 1
                        elif mexidas == 1 and secao == alvo:
                            linha[col["QT_VOTOS"]] = str(votos + 1)          # …e dá pro candidato B
                            mexidas = 2
                escritor.writerow(linha)
            texto.flush()
            texto.detach()                 # devolve o arquivo pro zip fechar direitinho
    if alvo is None or (golpe == "troca" and mexidas < 2):
        destino.unlink(missing_ok=True)
        raise SystemExit(A.rosa("Não achei onde aplicar o golpe nesse arquivo."))
    return alvo


def argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sabotagem; adultera uma cópia do boletim e vê se o Audita Aí pega")
    ap.add_argument("uf", nargs="?", default="AC", type=str.upper, help="sigla do estado (padrão: AC)")
    ap.add_argument("--golpe", choices=("troca", "branco"), default="troca")
    ap.add_argument("--turno", type=int, choices=(1, 2), default=1)
    a = ap.parse_args(argv)
    if a.uf not in A.UFS:
        ap.error(f"'{a.uf}' não é uma UF. Use uma destas: {' '.join(sorted(A.UFS))}")
    return a


def main(argv: list[str] | None = None) -> int:
    a = argumentos(argv)
    A.PASTA_DADOS.mkdir(exist_ok=True)
    print(A.rosa("Sabotagem;") + A.cinza("  cópia local · nenhuma urna foi ferida neste teste"))

    url = A.achar_boletim(a.uf, a.turno)
    original = A.PASTA_DADOS / Path(url).name
    sha_local = A.PASTA_DADOS / (Path(url).name + ".sha512")
    A.baixar(url, original)
    A.baixar(url + ".sha512", sha_local)

    copia = A.PASTA_DADOS / f"sabotado-{a.golpe}-{original.name}"
    municipio, zona, secao = sabotar(original, copia, a.golpe)
    golpe = ("tirei 1 voto do candidato A e dei pro candidato B" if a.golpe == "troca"
             else "enfiei 1 voto em branco a mais")
    print(A.cinza(f"   golpe: {golpe} (Presidente, zona {zona}, seção {secao})"))
    print(A.cinza(f"   cópia: {copia.name}"))

    pegou = 0
    print("\n" + A.amarelo("[1/3] digital (SHA-512)"))
    publicado, calculado = A.hash_publicado(sha_local), A.sha512_do_arquivo(copia)
    print(A.cinza(f"   TSE publicou: {publicado[:32]}…\n   calculei:     {calculado[:32]}…"))
    digital_ok = hmac.compare_digest(publicado, calculado)
    pegou += not digital_ok
    print("   " + (A.verde("✓ igual") if digital_ok else A.rosa("✗ mudou: pegou!")))

    print("\n" + A.amarelo("[2/3] urna por urna: a soma bate com quem compareceu?"))
    cargos = A.ler_boletins(copia)
    secoes_ok = True
    for codigo in sorted(cargos, key=int):
        c = A.conferir_secoes(cargos[codigo])
        secoes_ok &= c.ok
        print(f"   {c.cargo:<18} {A.mil(c.soma_bate):>7} de {A.mil(c.secoes):<7} seções  {A.marca(c.ok)}")
    pegou += not secoes_ok
    print("   " + (A.rosa("✗ uma urna não fecha a conta: pegou!") if not secoes_ok
                  else A.amarelo("✓ todas fecham… esse golpe passou por aqui")))

    print("\n" + A.amarelo("[3/3] soma de tudo contra o resultado oficial"))
    alvo = cargos[CARGO_ALVO]
    t = A.conferir_totalizacao(alvo, A.resultado_oficial(A.achar_ciclo(a.turno), alvo.eleicao, CARGO_ALVO, a.uf))
    for oque, bu, of in t.linhas:
        sinal = "=" if bu == of else "≠"
        print(A.cinza(f"   {oque:<48}") + f" {A.mil(bu):>10} {sinal} {A.mil(of):<10} {A.marca(bu == of)}")
    print(A.cinza(f"   {'votos de cada candidato':<48}") +
          f" {t.candidatos_batem:>10} de {t.candidatos:<7} {A.marca(t.candidatos_batem == t.candidatos)}")
    pegou += not t.ok
    print("   " + (A.rosa("✗ a soma não bate com o oficial: pegou!") if not t.ok else A.verde("✓ bateu")))

    print("\n   " + (A.verde(f"pego em {pegou} de 3 conferências.") if pegou else A.rosa("passou batido.")) +
          A.cinza(" auditoria boa é camada em cima de camada;)"))
    copia.unlink(missing_ok=True)          # não deixa arquivo adulterado largado por aí
    return 0 if pegou else 1


if __name__ == "__main__":
    sys.exit(main())
