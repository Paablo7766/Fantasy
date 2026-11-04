"""Anti-Pizarra: puja asimétrica con demanda alta y golpe al rival en viernes."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.auction_intel import (
    DIFERENCIALES_EUR,
    alta_demanda,
    puja_anti_pizarra,
    puja_pizarra,
)
from toolbox.engine.clause_advisor import bono_rosco_rival, evaluar_clausulas

AHORA = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
CIERRE = AHORA + timedelta(hours=12)


class PujaAntiPizarraTests(unittest.TestCase):
    def test_pizarra_redondea_a_cien_mil(self) -> None:
        # 10 M€ × 1,047 = 10,47 M€ → 10,5 M€
        self.assertEqual(puja_pizarra(10_000_000, 0), 10_500_000)
        # La subida de hoy se suma antes de redondear.
        self.assertEqual(puja_pizarra(10_000_000, 120_000), 10_600_000)
        self.assertIsNone(puja_pizarra(0, 0))

    def test_diferenciales_no_son_redondos(self) -> None:
        self.assertTrue(DIFERENCIALES_EUR)
        for valor in DIFERENCIALES_EUR:
            self.assertTrue(140_000 <= valor <= 220_000)
            self.assertNotEqual(valor % 50_000, 0)

    def test_sin_demanda_no_toca_la_puja(self) -> None:
        info = puja_anti_pizarra(10_000_000, 0, nota_mercado=6.5, prevision_7d_pct=4, clave="p1")
        self.assertFalse(info["alta_demanda"])
        self.assertIsNone(info["puja_anti_pizarra"])
        self.assertEqual(info["diferencial_anti_pizarra_eur"], 0)

    def test_demanda_por_nota_o_por_prevision(self) -> None:
        self.assertTrue(alta_demanda(8.0, None))
        self.assertTrue(alta_demanda(None, "+15,5%"))
        self.assertFalse(alta_demanda(7.9, 15))

    def test_con_demanda_supera_la_pizarra_con_cifra_no_redonda(self) -> None:
        info = puja_anti_pizarra(
            10_000_000, 0, nota_mercado=8.4, prevision_7d_pct=2, clave="p1", maxima=13_000_000, saldo=50_000_000
        )
        self.assertEqual(info["puja_pizarra"], 10_500_000)
        self.assertIn(info["diferencial_anti_pizarra_eur"], DIFERENCIALES_EUR)
        self.assertEqual(info["puja_anti_pizarra"], 10_500_000 + info["diferencial_anti_pizarra_eur"])
        self.assertNotEqual(info["puja_anti_pizarra"] % 100_000, 0)
        # Estable entre refrescos.
        otra = puja_anti_pizarra(10_000_000, 0, nota_mercado=8.4, clave="p1", maxima=13_000_000, saldo=50_000_000)
        self.assertEqual(otra["puja_anti_pizarra"], info["puja_anti_pizarra"])

    def test_respeta_techo_y_caja(self) -> None:
        # El techo coincide con la pizarra: no hay hueco por encima.
        tope = puja_anti_pizarra(10_000_000, 0, nota_mercado=9, clave="p1", maxima=10_500_000)
        self.assertIsNone(tope["puja_anti_pizarra"])
        # La caja recorta el diferencial pero aún queda por encima de la pizarra.
        corta = puja_anti_pizarra(10_000_000, 0, nota_mercado=9, clave="p1", maxima=13_000_000, saldo=10_600_000)
        self.assertEqual(corta["puja_anti_pizarra"], 10_600_000)
        # Sin caja para pasar la pizarra, no se activa.
        pobre = puja_anti_pizarra(10_000_000, 0, nota_mercado=9, clave="p1", maxima=13_000_000, saldo=10_500_000)
        self.assertIsNone(pobre["puja_anti_pizarra"])


def _plantilla_rival(team: str, *, con_recambio_portero: bool, sanos_extra: int) -> list[dict]:
    filas = [{"player_id": f"{team}-POR", "position": "POR", "sano": True, "jornada": 4.0}]
    if con_recambio_portero:
        filas.append({"player_id": f"{team}-POR2", "position": "POR", "sano": True, "jornada": 1.0})
    for indice in range(sanos_extra):
        filas.append({"player_id": f"{team}-X{indice}", "position": "DEF", "sano": True, "jornada": 3.0})
    return filas


class GolpeAlRivalTests(unittest.TestCase):
    def _rival(self, *, puesto: int = 2, recambio: bool = False, extra: int = 12) -> dict:
        return {
            "team_id": "t1",
            "manager": "Marta",
            "saldo": 1_000_000,
            "posiciones": [],
            "puesto_liga": puesto,
            "plantilla": _plantilla_rival("t1", con_recambio_portero=recambio, sanos_extra=extra),
        }

    def _jugador(self) -> dict:
        return {"player_id": "t1-POR", "position": "POR", "jornada": 4.0}

    def test_activo_sin_recambio_en_viernes(self) -> None:
        golpe = bono_rosco_rival(self._jugador(), self._rival(), dias_al_cierre=0.5)
        self.assertIsNotNone(golpe)
        self.assertTrue(golpe["sin_recambio"])
        self.assertEqual(golpe["impacto_pts"], 4.0)
        self.assertIn("Golpe al rival", golpe["mensaje"])

    def test_activo_si_queda_con_menos_de_once(self) -> None:
        # Tiene recambio de portero, pero solo 10 sanos tras quitarle al titular.
        rival = self._rival(recambio=True, extra=9)
        golpe = bono_rosco_rival(self._jugador(), rival, dias_al_cierre=1.0)
        self.assertIsNotNone(golpe)
        self.assertFalse(golpe["sin_recambio"])
        self.assertEqual(golpe["sanos_tras"], 10)

    def test_no_activo_con_recambio_y_plantilla_cubierta(self) -> None:
        rival = self._rival(recambio=True, extra=12)
        self.assertIsNone(bono_rosco_rival(self._jugador(), rival, dias_al_cierre=0.5))

    def test_solo_jueves_y_viernes(self) -> None:
        self.assertIsNone(bono_rosco_rival(self._jugador(), self._rival(), dias_al_cierre=2.5))
        self.assertIsNone(bono_rosco_rival(self._jugador(), self._rival(), dias_al_cierre=None))

    def test_solo_top_cinco(self) -> None:
        self.assertIsNone(bono_rosco_rival(self._jugador(), self._rival(puesto=6), dias_al_cierre=0.5))
        self.assertIsNone(bono_rosco_rival(self._jugador(), self._rival(puesto=None), dias_al_cierre=0.5))

    def test_lesionado_no_duele(self) -> None:
        rival = self._rival()
        rival["plantilla"][0]["sano"] = False
        self.assertIsNone(bono_rosco_rival(self._jugador(), rival, dias_al_cierre=0.5))

    def test_el_clausulazo_sube_a_prioridad_y_lleva_el_mensaje(self) -> None:
        propios = [
            {
                "player_id": f"mio-{i}",
                "nombre": f"Mio{i}",
                "position": pos,
                "valor": 5_000_000,
                "clausula": 20_000_000,
                "blindado": False,
                "bloqueo": {"is_locked": False},
                "jornada": 4.0,
                "en_xi": True,
                "elegible": True,
            }
            for i, pos in enumerate(["POR"] + ["DEF"] * 4 + ["MC"] * 3 + ["DEL"] * 3)
        ]
        ajenos = [
            {
                "player_id": "t1-POR",
                "nombre": "Portero Rival",
                "position": "POR",
                "valor": 3_000_000,
                "clausula": 4_000_000,
                "blindado": False,
                "bloqueo": {"is_locked": False},
                "jornada": 2.0,
                "manager": "Marta",
                "team_id": "t1",
            }
        ]
        informe = evaluar_clausulas(
            propios=propios,
            ajenos=ajenos,
            rivales=[self._rival()],
            saldo=30_000_000,
            ratio=2_000_000,
            ahora=AHORA,
            cierre=CIERRE,
        )
        fila = informe["clausulazos"][0]
        self.assertEqual(fila["veredicto_codigo"], "GOLPE_RIVAL")
        self.assertTrue(fila["bono_rosco_rival"]["activo"])
        self.assertGreater(fila["prioridad_estrategica"], fila["mejora_once"])
        self.assertIn("Golpe al rival", fila["motivo_detallado"])
        self.assertEqual(informe["resumen"]["golpes_al_rival"], 1)


if __name__ == "__main__":
    unittest.main()
