"""Testes do Audita Aí;  —  rodam sem internet, com um boletim de urna de mentirinha.

    python3 -m unittest -v
"""
import csv
import hashlib
import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path

import audita_ai as A

COLUNAS = ["CD_ELEICAO", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA",
           "DS_CARGO_PERGUNTA", "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "DS_TIPO_VOTAVEL",
           "NR_VOTAVEL", "QT_VOTOS"]


def linha(secao, cargo, codigo, tipo, numero, votos, *, aptos=10, compareceram=8, eleicao="6257"):
    return [eleicao, "01120", "RIO BRANCO", "9", str(secao), codigo, cargo,
            str(aptos), str(compareceram), str(aptos - compareceram), tipo, numero, str(votos)]


def boletim_falso(pasta: Path, linhas: list) -> Path:
    """Monta um zip igual ao do TSE: CSV em latin-1, separado por ';', tudo entre aspas."""
    texto = io.StringIO()
    escritor = csv.writer(texto, delimiter=";", quoting=csv.QUOTE_ALL)
    escritor.writerow(COLUNAS)
    escritor.writerows(linhas)
    caminho = pasta / "bweb_1t_XX_teste.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("bweb_1t_XX_teste.csv", texto.getvalue().encode("latin-1"))
    return caminho


# Seção 1: 8 compareceram. Presidente: 5 + 2 + 1 branco = 8.  Senador (2 votos cada): 9 + 6 + 1 nulo = 16.
# Seção 2: 8 compareceram. Presidente: 4 + 3 + 1 voto num número que foi barrado (99) = 8.
LINHAS = [
    linha(1, "Presidente", "1", "Nominal", "11", 5),
    linha(1, "Presidente", "1", "Nominal", "22", 2),
    linha(1, "Presidente", "1", "Branco", "95", 1),
    linha(2, "Presidente", "1", "Nominal", "11", 4),
    linha(2, "Presidente", "1", "Nominal", "22", 3),
    linha(2, "Presidente", "1", "Nominal", "99", 1),
    linha(1, "Senador", "5", "Nominal", "111", 9, eleicao="6259"),
    linha(1, "Senador", "5", "Nominal", "222", 6, eleicao="6259"),
    linha(1, "Senador", "5", "Nulo", "96", 1, eleicao="6259"),
]

# Do jeito que o site de resultados do TSE entrega (tudo texto). O 99 não está na lista: virou nulo técnico.
OFICIAL_PRESIDENTE = {
    "e": {"te": "20", "c": "16", "a": "4"},
    "v": {"vb": "1", "tvn": "1", "vn": "0", "vnt": "1", "vnom": "14"},
    "carg": [{"agr": [{"par": [{"cand": [{"n": "11", "vap": "9", "dvt": "Válido"},
                                         {"n": "22", "vap": "5", "dvt": "Válido"}]}]}]}],
}


class TestLeitura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._pasta = tempfile.TemporaryDirectory()
        cls.cargos = A.ler_boletins(boletim_falso(Path(cls._pasta.name), LINHAS))

    @classmethod
    def tearDownClass(cls):
        cls._pasta.cleanup()

    def test_separa_por_cargo_e_secao(self):
        self.assertEqual({c.nome for c in self.cargos.values()}, {"Presidente", "Senador"})
        self.assertEqual(len(self.cargos["1"].secoes), 2)
        self.assertEqual(self.cargos["1"].eleicao, "6257")

    def test_soma_numeros_e_nao_texto(self):
        # o bug clássico: "5" + "2" = "52". Aqui tem que dar 7.
        self.assertEqual(self.cargos["1"].secoes[("01120", "9", "1")].votos, 8)
        self.assertEqual(self.cargos["1"].por_numero["11"], 9)

    def test_conta_por_tipo(self):
        p = self.cargos["1"].por_tipo
        self.assertEqual((p["Nominal"], p["Branco"], p["Nulo"]), (15, 1, 0))

    def test_senador_sao_dois_votos_por_eleitor(self):
        c = A.conferir_secoes(self.cargos["5"])
        self.assertEqual(c.votos_por_eleitor, 2)
        self.assertTrue(c.ok)

    def test_presidente_bate_em_todas_as_secoes(self):
        self.assertTrue(A.conferir_secoes(self.cargos["1"]).ok)

    def test_pega_secao_com_voto_sobrando(self):
        cargo = A.Cargo("Presidente", "6257")
        cargo.secoes["x"] = A.Secao("TESTE", aptos=10, compareceram=8, faltaram=2, votos=9)
        c = A.conferir_secoes(cargo)
        self.assertFalse(c.ok)
        self.assertEqual(c.soma_bate, 0)

    def test_totalizacao_bate_com_o_oficial(self):
        t = A.conferir_totalizacao(self.cargos["1"], OFICIAL_PRESIDENTE)
        self.assertTrue(t.ok, t.linhas)
        self.assertEqual((t.candidatos, t.candidatos_batem), (2, 2))

    def test_totalizacao_acusa_diferenca(self):
        adulterado = {**OFICIAL_PRESIDENTE, "e": {"te": "20", "c": "16", "a": "5"}}
        self.assertFalse(A.conferir_totalizacao(self.cargos["1"], adulterado).ok)

    def test_legenda_de_partido_sub_judice(self):
        # Pará 2026: o boletim conta a legenda do partido 33; o oficial zera os válidos (tvtl) e guarda em tval.
        cargo = A.Cargo("Deputado Federal", "6258")
        cargo.secoes["x"] = A.Secao("TESTE", aptos=10, compareceram=8, faltaram=2, votos=8)
        cargo.por_tipo.update({"Nominal": 5, "Legenda": 3})
        cargo.por_numero["1010"] = 5
        oficial = {
            "e": {"te": "10", "c": "8", "a": "2"},
            "v": {"vb": "0", "tvn": "0", "vnom": "5", "vl": "1"},
            "carg": [{"agr": [{"par": [
                {"n": "10", "tvtl": "1", "tval": "1", "cand": [{"n": "1010", "vap": "5", "dvt": "Válido"}]},
                {"n": "33", "tvtl": "0", "tval": "2", "dvt": "Anulado sub judice", "cand": []},
            ]}]}],
        }
        self.assertTrue(A.conferir_totalizacao(cargo, oficial).ok)

    def test_legenda_de_partido_barrado_vira_nulo_tecnico(self):
        # SP 2026: a urna aceitou a legenda do partido 29, que não está na lista oficial: vira nulo técnico.
        cargo = A.Cargo("Deputado Federal", "6258")
        cargo.secoes["x"] = A.Secao("TESTE", aptos=10, compareceram=8, faltaram=2, votos=8)
        cargo.por_tipo.update({"Nominal": 5, "Legenda": 3})
        cargo.por_numero["1010"] = 5
        cargo.por_legenda.update({"10": 1, "29": 2})
        oficial = {
            "e": {"te": "10", "c": "8", "a": "2"},
            "v": {"vb": "0", "tvn": "2", "vnom": "5", "vnt": "2", "vl": "1"},
            "carg": [{"agr": [{"par": [
                {"n": "10", "tvtl": "1", "tval": "1", "cand": [{"n": "1010", "vap": "5", "dvt": "Válido"}]},
            ]}]}],
        }
        self.assertTrue(A.conferir_totalizacao(cargo, oficial).ok, A.conferir_totalizacao(cargo, oficial).linhas)

    def test_abstencao(self):
        aptos, faltaram, taxa = A.abstencao(A.cargo_de_referencia(self.cargos))
        self.assertEqual((aptos, faltaram), (20, 4))
        self.assertAlmostEqual(taxa, 0.2)

    def test_zip_sem_csv(self):
        with tempfile.TemporaryDirectory() as pasta:
            vazio = Path(pasta) / "vazio.zip"
            with zipfile.ZipFile(vazio, "w") as z:
                z.writestr("leia.txt", "nada aqui")
            with self.assertRaises(SystemExit):
                A.ler_boletins(vazio)


class TestIntegridade(unittest.TestCase):
    def test_sha512_em_blocos_igual_ao_de_uma_vez(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "a.bin"
            conteudo = b"confere;)" * 300_000       # ~2,7 MB: passa de um bloco
            arquivo.write_bytes(conteudo)
            self.assertEqual(A.sha512_do_arquivo(arquivo), hashlib.sha512(conteudo).hexdigest())

    def test_le_hash_publicado(self):
        with tempfile.TemporaryDirectory() as pasta:
            sha = Path(pasta) / "a.zip.sha512"
            sha.write_text("ABC123  a.zip\n", encoding="ascii")
            self.assertEqual(A.hash_publicado(sha), "abc123")


class TestEstatistica(unittest.TestCase):
    def test_mesma_semente_mesmo_resultado(self):
        self.assertEqual(A.simular_pesquisas(0.2, 100, 50, 7), A.simular_pesquisas(0.2, 100, 50, 7))

    def test_margem_de_erro_classica(self):
        # a conta que todo instituto usa: 1000 entrevistas, p = 50% → ±3,1 pontos
        self.assertAlmostEqual(A.margem_de_erro(0.5, 1000), 0.031, places=3)

    def test_uns_95_por_cento_caem_na_margem(self):
        taxa, n = 0.2, 2000
        dentro = A.fracao_dentro(A.simular_pesquisas(taxa, n, 2000, 2026), taxa, A.margem_de_erro(taxa, n))
        self.assertGreater(dentro, 0.93)
        self.assertLess(dentro, 0.97)


class TestFormatoEArgumentos(unittest.TestCase):
    def test_formato_brasileiro(self):
        self.assertEqual(A.br(0.20434), "20,43%")
        self.assertEqual(A.mil(613742), "613.742")

    def test_uf_minuscula_vira_maiuscula(self):
        self.assertEqual(A.argumentos(["rr"]).uf, "RR")

    def test_recusa_uf_que_nao_existe(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            A.argumentos(["XY"])

    def test_recusa_amostra_zero(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            A.argumentos(["AC", "--amostra", "0"])


if __name__ == "__main__":
    unittest.main()
