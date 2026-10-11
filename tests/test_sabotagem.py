"""Testes da Sabotagem;  —  o Audita Aí tem que pegar os dois golpes (sem internet).

    python3 -m unittest -v
"""
import tempfile
import unittest
from pathlib import Path

import audita_ai as A
import sabotagem as S
from tests.test_audita_ai import LINHAS, OFICIAL_PRESIDENTE, boletim_falso


class TestSabotagem(unittest.TestCase):
    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)
        self.original = boletim_falso(self.pasta, LINHAS)

    def tearDown(self):
        self._pasta.cleanup()

    def sabotado(self, golpe):
        copia = self.pasta / f"sabotado-{golpe}.zip"
        alvo = S.sabotar(self.original, copia, golpe)
        return alvo, copia, A.ler_boletins(copia)

    def test_original_continua_intacto(self):
        antes = A.sha512_do_arquivo(self.original)
        self.sabotado("troca")
        self.assertEqual(A.sha512_do_arquivo(self.original), antes)

    def test_qualquer_golpe_muda_a_digital(self):
        for golpe in ("troca", "branco"):
            _, copia, _ = self.sabotado(golpe)
            self.assertNotEqual(A.sha512_do_arquivo(copia), A.sha512_do_arquivo(self.original), golpe)

    def test_troca_passa_na_conta_da_urna(self):
        # o golpe esperto: a seção continua fechando, então essa conferência sozinha não pega
        alvo, _, cargos = self.sabotado("troca")
        self.assertEqual(alvo, ("01120", "9", "1"))
        self.assertTrue(A.conferir_secoes(cargos["1"]).ok)

    def test_troca_e_pega_na_soma_contra_o_oficial(self):
        _, _, cargos = self.sabotado("troca")
        t = A.conferir_totalizacao(cargos["1"], OFICIAL_PRESIDENTE)
        self.assertFalse(t.ok)
        self.assertEqual((t.candidatos_batem, t.candidatos), (0, 2))    # um perdeu 1, o outro ganhou 1

    def test_voto_em_branco_a_mais_nao_fecha_a_urna(self):
        _, _, cargos = self.sabotado("branco")
        c = A.conferir_secoes(cargos["1"])
        self.assertFalse(c.ok)
        self.assertEqual(c.soma_bate, 1)                                 # 1 das 2 seções ficou errada

    def test_golpe_sem_onde_aplicar(self):
        so_senador = [l for l in LINHAS if l[6] == "Senador"]
        original = boletim_falso(self.pasta, so_senador)
        with self.assertRaises(SystemExit):
            S.sabotar(original, self.pasta / "x.zip", "branco")
        self.assertFalse((self.pasta / "x.zip").exists())


if __name__ == "__main__":
    unittest.main()
