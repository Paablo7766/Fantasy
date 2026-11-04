"""Blindaje quirúrgico: liquidez sin crédito, willingness to pay, candado y rentabilidad."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from toolbox.engine.clause_shield import (
    TEXTO_CANDADO,
    TEXTO_FUERA,
    blindaje_quirurgico,
    cebo_o_blindaje,
    disposicion_a_pagar,
    liquidez_rival,
    necesidad_rival,
)

JUEVES = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
SAQUE = JUEVES + timedelta(days=2)
ABIERTA = {"is_locked": False}


def _plantilla(n_del: int = 3, xp_del: float = 4.0, banquillo: int = 0) -> list[dict]:
    filas = [{"position": "POR", "sano": True, "jornada": 4.0, "valor": 5_000_000}]
    filas += [{"position": "DEF", "sano": True, "jornada": 4.0, "valor": 5_000_000} for _ in range(4)]
    filas += [{"position": "MC", "sano": True, "jornada": 4.0, "valor": 5_000_000} for _ in range(3)]
    filas += [{"position": "DEL", "sano": True, "jornada": xp_del, "valor": 5_000_000} for _ in range(n_del)]
    filas += [{"position": "DEF", "sano": True, "jornada": 0.5, "valor": 2_000_000} for _ in range(banquillo)]
    return filas


def _rival(saldo: int, **kw: object) -> dict:
    return {"manager": "Luis", "saldo": saldo, "plantilla": _plantilla(**kw)}  # type: ignore[arg-type]


def _mio(clausula: int, valor: int = 10_000_000, abre: object = ABIERTA, perdida: float = 5.0, xp: float = 6.0) -> dict:
    return {
        "player_id": "j",
        "nombre": "Jota",
        "position": "DEL",
        "clausula": clausula,
        "valor_mercado": valor,
        "prevision_7d_pct": 0,
        "clausulaAbre": abre,
        "jornada": xp,
        "tu_once_pierde_sin_el": perdida,
    }


def _una(mio: dict, rival: dict, ahora: datetime = JUEVES, **kw: object) -> dict:
    return blindaje_quirurgico([mio], [rival], ahora=ahora, primer_saque=SAQUE, **kw)[0]  # type: ignore[arg-type]


class LiquidezTests(unittest.TestCase):
    def test_sin_credito_y_con_caja_negativa_no_hay_liquidez(self) -> None:
        self.assertEqual(liquidez_rival({"saldo": -3_000_000, "plantilla": []}, 48), {"inmediata": 0, "en_24h": 0})

    def test_vender_suplentes_suma_el_95_por_ciento(self) -> None:
        liquidez = liquidez_rival(_rival(1_000_000, banquillo=2), 48)
        self.assertEqual(liquidez["inmediata"], 1_000_000)
        self.assertEqual(liquidez["en_24h"], 1_000_000 + int(0.95 * 4_000_000))

    def test_con_menos_de_24h_solo_cuenta_la_caja_de_hoy(self) -> None:
        self.assertEqual(liquidez_rival(_rival(1_000_000, banquillo=2), 23.9)["en_24h"], 1_000_000)


class WillingnessTests(unittest.TestCase):
    def test_hueco_justo_y_cubierto(self) -> None:
        self.assertEqual(necesidad_rival(_rival(0, n_del=2), "DEL", 6.0), ("hueco", 6.0))
        self.assertEqual(necesidad_rival(_rival(0, n_del=3), "DEL", 6.0), ("justo", 2.0))
        rival = {"plantilla": _plantilla(n_del=4)}
        self.assertEqual(necesidad_rival(rival, "DEL", 6.0)[0], "cubierto")

    def test_no_mejora_no_suma_urgencia(self) -> None:
        self.assertEqual(necesidad_rival(_rival(0), "DEL", 3.0), ("justo", 0.0))
        self.assertEqual(disposicion_a_pagar(10_000_000, 500_000, "justo", 0.0), 10_500_000)

    def test_precio_maximo(self) -> None:
        self.assertEqual(disposicion_a_pagar(10_000_000, 0, "hueco", 2.0), 17_000_000)
        self.assertEqual(disposicion_a_pagar(10_000_000, 0, "cubierto", 2.0), 12_400_000)


class VeredictoTests(unittest.TestCase):
    def test_candado_tras_el_saque_es_riesgo_cero(self) -> None:
        abre = (SAQUE + timedelta(hours=1)).isoformat()
        fila = _una(_mio(12_000_000, abre=abre), _rival(99_000_000, n_del=0))
        self.assertEqual(fila["estado"], "CANDADO")
        self.assertEqual(fila["consejo"], TEXTO_CANDADO)

    def test_candado_que_abre_antes_del_saque_sigue_en_juego(self) -> None:
        abre = (SAQUE - timedelta(hours=5)).isoformat()
        self.assertNotEqual(_una(_mio(12_000_000, abre=abre), _rival(99_000_000, n_del=0))["estado"], "CANDADO")

    def test_fuera_de_alcance_si_nadie_llega(self) -> None:
        # Hueco: pagaría como mucho 10 + 3,5 × 6 = 31M.
        fila = _una(_mio(40_000_000), _rival(99_000_000, n_del=0))
        self.assertEqual(fila["estado"], "FUERA_DE_ALCANCE")
        self.assertEqual(fila["consejo"], TEXTO_FUERA)

    def test_la_caja_tambien_limita_la_amenaza(self) -> None:
        fila = _una(_mio(12_000_000), _rival(8_000_000, n_del=0))
        self.assertEqual(fila["estado"], "FUERA_DE_ALCANCE")
        self.assertEqual(fila["amenaza_max"], 8_000_000)

    def test_fuera_de_alcance_si_hay_caja_pero_no_incentivo(self) -> None:
        # Caja de sobra, pero con el puesto cubierto solo pagaría valor + 1,2M por punto.
        fila = _una(_mio(20_000_000, perdida=5.0, xp=4.5), _rival(99_000_000, n_del=4, xp_del=4.0))
        self.assertEqual(fila["estado"], "FUERA_DE_ALCANCE")
        self.assertLess(fila["amenaza_max"], 20_000_000)

    def test_blindar_cuando_el_dano_supera_el_coste(self) -> None:
        # Amenaza 31M → óptima 31,2M, coste (31,2 − 10) / 2 = 10,6M < 8 xP × 2M = 16M.
        fila = _una(_mio(10_000_000, perdida=8.0), _rival(99_000_000, n_del=0))
        self.assertEqual(fila["estado"], "BLINDAR")
        self.assertEqual(fila["clausula_optima"], 31_200_000)
        self.assertEqual(fila["coste_subida"], 10_600_000)
        self.assertIn("BLINDAR A 31,2M (Coste: 10,6M)", fila["consejo"])

    def test_asumir_si_blindar_cuesta_mas_que_perderlo(self) -> None:
        fila = _una(_mio(10_000_000, perdida=2.0), _rival(99_000_000, n_del=0))
        self.assertEqual(fila["estado"], "ASUMIR")

    def test_cebo_si_la_prima_compensa(self) -> None:
        # Cláusula 13M sobre valor 10M: prima 3M. Subir cuesta 9,1M > 1 xP × 2M − 3M.
        fila = _una(_mio(13_000_000, perdida=1.0), _rival(99_000_000, n_del=0))
        self.assertEqual(fila["estado"], "CEBO")
        self.assertIn("Si pagan 13,0M te regalan +3,0M", fila["consejo"])

    def test_cebo_si_apenas_pesa_y_la_clausula_es_alta(self) -> None:
        resultado = cebo_o_blindaje(clausula=13_000_000, valor=10_000_000, amenaza_max=14_000_000, perdida_xp=0.5, ratio_eur_xp=2_000_000)
        self.assertEqual(resultado["codigo"], "CEBO")

    def test_de_lunes_a_miercoles_el_recambio_comprable_baja_la_perdida(self) -> None:
        martes = JUEVES - timedelta(days=2)
        alternativas = [{"player_id": "otro", "position": "DEL", "coste": 9_000_000, "xp": 5.9}]
        sin = _una(_mio(10_000_000, perdida=8.0), _rival(99_000_000, n_del=0), ahora=martes)
        con = _una(_mio(10_000_000, perdida=8.0), _rival(99_000_000, n_del=0), ahora=martes, alternativas=alternativas)
        jueves = _una(_mio(10_000_000, perdida=8.0), _rival(99_000_000, n_del=0), alternativas=alternativas)
        self.assertEqual(sin["estado"], "BLINDAR")
        self.assertEqual(con["estado"], "ASUMIR")
        self.assertEqual(con["perdida_del_once_sin_el"], 0.3)
        self.assertEqual(jueves["estado"], "BLINDAR")

    def test_blindado_no_se_evalua(self) -> None:
        mio = {**_mio(10_000_000), "blindado": True}
        self.assertEqual(blindaje_quirurgico([mio], [_rival(1)], ahora=JUEVES, primer_saque=SAQUE), [])


if __name__ == "__main__":
    unittest.main()
