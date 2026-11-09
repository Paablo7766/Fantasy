"""xP 2.0 fase 3: cambio cronico, produccion pura, suelo muro, 0,50 fantasma y localia unica."""

from __future__ import annotations

import inspect
import unittest

from toolbox.analitica_fantasy import filtrar_af_fantasma
from toolbox.engine import xp2
from toolbox.rival_huella import (
    ETIQUETA_OFERTA_HUMANA,
    estilo_de_cola,
    huella_de_rival,
    ventanas_clausulazo,
)
from tests.test_xp2 import acta, jugador, xp


class CambioCronicoTests(unittest.TestCase):
    def test_sustituido_en_el_45_baja_su_xp_frente_al_que_juega_entero(self) -> None:
        entero = jugador("MC", [acta(j, minutos=90) for j in range(8, 12)])
        cronico = jugador("MC", [acta(j, minutos=45) for j in range(8, 12)])
        self.assertIsNone(xp2.cambio_cronico([]))
        self.assertLess(xp(cronico)["xp_condicional"], xp(entero)["xp_condicional"])
        info = xp(cronico)["cambio_cronico"]
        self.assertTrue(info["activo"])
        self.assertEqual(info["n_cambios_antes_60"], 4)
        self.assertEqual(info["minutos_techo"], 45.0)
        self.assertEqual(info["llega_60"], 0.0)
        self.assertIsNone(xp(entero)["cambio_cronico"])

    def test_un_solo_cambio_no_es_cronico(self) -> None:
        mixto = jugador("DF", [acta(8), acta(9), acta(10, minutos=50), acta(11)])
        self.assertIsNone(xp(mixto)["cambio_cronico"])

    def test_portero_cronico_pierde_la_porteria_a_cero(self) -> None:
        entero = jugador("PT", [acta(j, minutos=90) for j in range(8, 12)])
        cronico = jugador("PT", [acta(j, minutos=50) for j in range(8, 12)])
        self.assertLess(xp(cronico)["porteria"], xp(entero)["porteria"])


class ProduccionYMuroTests(unittest.TestCase):
    def test_produccion_pura_por_90(self) -> None:
        # rating = suelo - 2 = 3 por partido de 90 minutos, sin acciones.
        player = jugador("MC", [acta(j, suelo=5) for j in range(8, 12)])
        self.assertEqual(xp(player)["produccion_pura_90"], 3.0)

    def test_suelo_muro(self) -> None:
        muro = jugador("PT", [acta(j, suelo=6, pts_gol=0.0) for j in range(8, 12)])
        # puntos de acta = min 2 + rating 4 = 6 en todos.
        self.assertTrue(xp(muro)["suelo_muro"]["activo"])
        con_bache = jugador("PT", [acta(8, suelo=6), acta(9, suelo=6), acta(10, suelo=3), acta(11, suelo=6)])
        self.assertFalse(xp(con_bache)["suelo_muro"]["activo"])
        poco = jugador("PT", [acta(8, suelo=6), acta(9, suelo=6)])
        self.assertIsNone(xp(poco)["suelo_muro"])


class FantasmaAfTests(unittest.TestCase):
    def test_af_050_se_ignora_si_ff_es_definida(self) -> None:
        for ff in (0.9, 0.75, 0.2, 0.0):
            jug = {"p_titular_source": "scraper", "p_titular": ff, "af_p_titular": 0.5}
            self.assertTrue(filtrar_af_fantasma(jug))
            self.assertIsNone(jug["af_p_titular"])
            self.assertTrue(jug["af_p_titular_fantasma"])
            self.assertEqual(jug["p_titular"], ff)

    def test_no_filtra_cuando_ff_es_dudosa_o_af_opina(self) -> None:
        dudosa = {"p_titular_source": "scraper", "p_titular": 0.5, "af_p_titular": 0.5}
        self.assertFalse(filtrar_af_fantasma(dudosa))
        opina = {"p_titular_source": "scraper", "p_titular": 0.9, "af_p_titular": 0.55}
        self.assertFalse(filtrar_af_fantasma(opina))
        self.assertEqual(opina["af_p_titular"], 0.55)
        otra = {"p_titular_source": "alineacion", "p_titular": 0.9, "af_p_titular": 0.5}
        self.assertFalse(filtrar_af_fantasma(otra))


class LocaliaUnicaTests(unittest.TestCase):
    def test_xp2_no_recibe_bonus_de_local(self) -> None:
        # La localia ya esta en los lambdas del calendario: xP 2.0 no tiene parametro de local
        # y, con los mismos lambdas, el resultado es identico.
        params = inspect.signature(xp2.prediccion_xp2).parameters
        self.assertFalse([name for name in params if "local" in name or "home" in name or "casa" in name])
        player = jugador("MC", [acta(j) for j in range(8, 12)], is_home=True)
        otro = jugador("MC", [acta(j) for j in range(8, 12)], is_home=False)
        self.assertEqual(xp(player), xp(otro))


class HuellaRivalTests(unittest.TestCase):
    def test_estilos_de_cola(self) -> None:
        self.assertEqual(estilo_de_cola([10_000_004, 12_500_005, 9_000_001])["estilo"], "pica")
        self.assertEqual(estilo_de_cola([10_000_000, 12_500_000, 9_100_000])["estilo"], "redondea_100k")
        self.assertEqual(estilo_de_cola([10_010_000, 12_520_000, 9_130_000])["estilo"], "redondea_10k")
        self.assertIsNone(estilo_de_cola([10_000_004]))

    def test_ventanas_de_clausulazo(self) -> None:
        eventos = [
            {"kind": "clause", "at": "2026-11-02T09:30:00+01:00"},
            {"kind": "clause", "at": "2026-11-05T09:31:00+01:00"},
            {"kind": "clause", "at": "2026-11-04T14:15:00+01:00"},
            {"kind": "buy", "at": "2026-11-04T20:00:00+01:00"},
        ]
        self.assertEqual(ventanas_clausulazo(eventos), ["09:30", "14:15"])
        rango = [
            {"kind": "clause", "at": "2026-11-02T10:15:00+01:00"},
            {"kind": "clause", "at": "2026-11-05T11:20:00+01:00"},
        ]
        self.assertEqual(ventanas_clausulazo(rango), ["10:15-11:20"])

    def test_oferta_humana(self) -> None:
        listings = [
            {"seller_team_id": "9", "offer_count": 2, "nickname": "Dituro", "market_id": "m1", "sale_price": 5},
            {"seller_team_id": "9", "offer_count": 1, "nickname": "X", "market_id": "m2"},
            {"seller_team_id": "8", "offer_count": 3, "nickname": "Y", "market_id": "m3"},
        ]
        huella = huella_de_rival("9", compras=[], eventos=[], listings=listings)
        self.assertEqual([o["nombre"] for o in huella["ofertas_humanas"]], ["Dituro"])
        self.assertEqual(huella["ofertas_humanas"][0]["etiqueta"], ETIQUETA_OFERTA_HUMANA)


if __name__ == "__main__":
    unittest.main()
