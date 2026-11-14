"""La curva de ganar es de cada jugador, y completar un once vacío vale la jornada.

* Tramo de valor, si su valor sube hoy y si ya tiene pujas: cada segmento se
  mezcla con el de arriba según su muestra.
* Con 10 jugadores, la puja que pone al n.º 11 rescata el resto del once.
"""

import unittest

from toolbox.engine.auction_intel import (
    CURVA_PRIMAS_PRIOR,
    PENDIENTE_XP_BACKTEST,
    curva_para_jugador,
    prob_ganar_prima,
)
from toolbox.engine.strategy_layer import PESO_JORNADA_UNICA, _sellar_pujas_plan


def _p(curva, prima):
    return prob_ganar_prima(prima, curva)


class CurvaPorJugador(unittest.TestCase):
    def test_sin_base_usa_el_tramo_medido(self):
        media, info = curva_para_jugador(None, valor=3_000_000)
        cara, _ = curva_para_jugador(None, valor=20_000_000)
        self.assertEqual(info["segmento"], "1-5M")
        # Entre 1 y 5 M€ se paga más prima que en la liga; por encima de 5 M€, menos.
        self.assertLess(_p(media, 0.30), _p(CURVA_PRIMAS_PRIOR, 0.30))
        self.assertGreater(_p(cara, 0.30), _p(CURVA_PRIMAS_PRIOR, 0.30))

    def _muestras(self):
        # 40 compras: las que suben hoy se pagaron a +40 %, las demás a +5 %.
        return (
            [{"prima": 0.05, "valor": 8_000_000, "subiendo": False, "pujas": 0} for _ in range(30)]
            + [{"prima": 0.40, "valor": 8_000_000, "subiendo": True, "pujas": 2} for _ in range(10)]
        )

    def test_un_jugador_que_sube_hoy_es_mas_dificil_de_ganar(self):
        quieto, _ = curva_para_jugador(self._muestras(), valor=8_000_000, subiendo=False)
        sube, info = curva_para_jugador(self._muestras(), valor=8_000_000, subiendo=True)
        self.assertEqual(info["segmento"], ">=5M · sube hoy")
        self.assertEqual(info["muestra"], 10)
        self.assertLess(_p(sube, 0.10), _p(quieto, 0.10))

    def test_las_pujas_vistas_separan_a_quien_nadie_quiere(self):
        sin, info = curva_para_jugador(self._muestras(), valor=8_000_000, pujas=0)
        con, _ = curva_para_jugador(self._muestras(), valor=8_000_000, pujas=3)
        self.assertEqual(info["segmento"], ">=5M · sin pujas")
        self.assertGreater(_p(sin, 0.10), _p(con, 0.10))

    def test_curvas_monotonas(self):
        curva, _ = curva_para_jugador(self._muestras(), valor=8_000_000, subiendo=True, pujas=2)
        ps = [p for _, p in curva]
        self.assertEqual(ps, sorted(ps))


class MuestrasDeLaBase(unittest.TestCase):
    def test_valor_del_dia_o_del_anterior_y_registro_de_respaldo(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from toolbox.engine_calibration import muestras_primas_de_liga

        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "r.sqlite"
            conn = sqlite3.connect(ruta)
            conn.executescript(
                """
                create table activity_buys (player_id text, amount_eur int, at text);
                create table price_snapshots (player_id text, day text, market_value int, market_value_change int);
                create table market_listing_log (player_id text, day text, market_value int, bid_count int);
                insert into activity_buys values ('a', 1100000, '2026-11-05T14:08:00+01:00');
                insert into activity_buys values ('viejo', 2000000, '2026-11-12T14:08:00+01:00');
                insert into activity_buys values ('log', 1500000, '2026-11-12T14:08:00+01:00');
                insert into price_snapshots values ('a', '2026-11-04', 1000000, 20000);
                insert into price_snapshots values ('viejo', '2026-11-01', 1000000, 0);
                insert into market_listing_log values ('log', '2026-11-12', 1000000, 2);
                """
            )
            conn.commit()
            conn.close()
            muestras = {round(m["prima"], 2): m for m in muestras_primas_de_liga(ruta)}
        self.assertEqual(set(muestras), {0.10, 0.50})
        self.assertTrue(muestras[0.10]["subiendo"])
        self.assertEqual(muestras[0.50]["pujas"], 2)


RATIO = 3_800_000
DIEZ = {"POR": 1, "DEF": 4, "MC": 3, "DEL": 2}


class RescateDelOnce(unittest.TestCase):
    def _plan(self, pujas_plan, plantilla, holgura=200_000_000):
        plan = {
            "ratio_mercado": RATIO,
            "puntos_once_referencia": 40.0,
            "presupuesto": {"holgura": holgura},
            "acciones": [
                {"tipo": "PUJA", "player_id": pid, "nombre": pid, "posicion": pos, "euros": valor,
                 "mejora_neta": mejora, "momento": "hoy"}
                for pid, pos, valor, mejora in pujas_plan
            ],
        }
        pujas = {pid: {"valor_mercado": valor} for pid, _pos, valor, _m in pujas_plan}
        _sellar_pujas_plan(plan, pujas, None, plantilla_por_puesto=plantilla)
        return {a["player_id"]: a for a in plan["acciones"]}

    def test_la_unica_puja_que_completa_rescata_la_jornada(self):
        sin_hueco = self._plan([("del", "DEL", 8_000_000, 2.0)], {**DIEZ, "DEL": 3})["del"]
        con_hueco = self._plan([("del", "DEL", 8_000_000, 2.0)], DIEZ)["del"]
        self.assertEqual(sin_hueco["rescate_once_eur"], 0)
        self.assertEqual(con_hueco["rescate_once_eur"], int(round(40.0 * RATIO * PESO_JORNADA_UNICA * PENDIENTE_XP_BACKTEST)))
        self.assertGreater(con_hueco["puja_final"], sin_hueco["puja_final"])
        self.assertGreater(con_hueco["p_ganar_por_valor"], sin_hueco["p_ganar_por_valor"])

    def test_un_portero_no_completa_y_no_rescata(self):
        acciones = self._plan([("por", "POR", 8_000_000, 2.0), ("del", "DEL", 8_000_000, 2.0)], DIEZ)
        self.assertEqual(acciones["por"]["rescate_once_eur"], 0)
        self.assertGreater(acciones["del"]["rescate_once_eur"], 0)

    def test_con_dos_que_completan_cada_una_vale_menos_que_sola(self):
        sola = self._plan([("a", "DEL", 8_000_000, 2.0)], DIEZ)["a"]
        dos = self._plan([("a", "DEL", 8_000_000, 2.0), ("b", "MC", 8_000_000, 2.0)], DIEZ)
        self.assertLess(dos["a"]["rescate_once_eur"], sola["rescate_once_eur"])
        self.assertGreater(dos["a"]["rescate_once_eur"], 0)

    def test_sin_holgura_no_pasa_de_lo_que_el_plan_puede_poner(self):
        a = self._plan([("del", "DEL", 8_000_000, 2.0)], DIEZ, holgura=0)["del"]
        self.assertLessEqual(a["puja_final"], 8_000_000)


if __name__ == "__main__":
    unittest.main()
