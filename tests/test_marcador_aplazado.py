"""Un partido aplazado no puede dejar sin puntos al resto de su jornada.

J12 tuvo un aplazado el 22-nov. Las filas sin saque propio tomaban ese saque como
«el último de la jornada»: cada arranque vaciaba sus puntos por «prematuros» y el
evaluador los volvía a poner. Quien leía entre medias veía la mitad de la tabla.
"""

import sqlite3
import time
import unittest

from toolbox.marcador import reparar_historico, ultimo_saque_por_jornada


class UltimoSaque(unittest.TestCase):
    def test_el_aplazado_no_cuenta(self):
        filas = [
            ("12", "2026-11-06T20:00:00+00:00"),
            ("12", "2026-11-08T20:00:00+00:00"),
            ("12", "2026-11-22T17:30:00+00:00"),
            ("12", None),
        ]
        self.assertEqual(ultimo_saque_por_jornada(filas)["12"], "2026-11-08T20:00:00+00:00")


class Reparacion(unittest.TestCase):
    def test_las_filas_sin_saque_conservan_sus_puntos(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """create table matchday_snapshots (jornada_id text, player_id text, kickoff text, stored_at real,
               evaluated_at real, actual_points real, expected_points real, ceiling_points real)"""
        )
        evaluado = time.mktime((2026, 11, 14, 12, 0, 0, 0, 0, -1))
        guardado = time.mktime((2026, 11, 5, 12, 0, 0, 0, 0, -1))
        conn.executemany(
            "insert into matchday_snapshots values (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("12", "a", "2026-11-08T20:00:00+00:00", guardado, evaluado, 5.0, 4.0, 9.0),
                ("12", "aplazado", "2026-11-22T17:30:00+00:00", guardado, None, None, 4.0, 9.0),
                ("12", "sin_saque", None, guardado, evaluado, 6.0, 5.0, 9.0),
            ],
        )
        reparar_historico(conn)
        puntos = conn.execute("select actual_points from matchday_snapshots where player_id = 'sin_saque'").fetchone()[0]
        self.assertEqual(puntos, 6.0)


if __name__ == "__main__":
    unittest.main()
