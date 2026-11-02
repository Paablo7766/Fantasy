import unittest

from toolbox.engine.trading_desk import build_trading_desk, capital_trading, ganancia_esperada


def _cand(pid: str, euros: int, pct: float, valor: int | None = None) -> dict:
    return {"player_id": pid, "nombre": pid, "origen": "bid", "euros": euros, "valor": valor or euros, "pct": pct}


class TradingDeskTests(unittest.TestCase):
    def test_capital_usa_la_mitad_del_margen_de_deuda(self) -> None:
        capital = capital_trading(3_000_000, 100_000_000)
        self.assertEqual(capital["deuda_usable"], 10_000_000)
        self.assertEqual(capital["capital"], 13_000_000)
        self.assertEqual(capital_trading(-2_000_000, 0)["capital"], 0)

    def test_mochila_maximiza_euros_no_porcentaje(self) -> None:
        # 15 M al 5 % (≈429 k€) frente a dos de 2 M al 20 % (≈229 k€ cada uno), con capital para uno grande.
        grande = _cand("grande", 15_000_000, 5.0)
        pequenos = [_cand("p1", 2_000_000, 20.0), _cand("p2", 2_000_000, 20.0)]
        desk = build_trading_desk([grande, *pequenos], saldo_sobrante=15_000_000, valor_equipo=0, dias_para_jornada=4)
        self.assertEqual({op["player_id"] for op in desk["operaciones"]}, {"p1", "p2"})
        self.assertEqual(desk["usa_deuda"], 0)
        # Con más capital caben los tres y el mejor va primero.
        todos = build_trading_desk([grande, *pequenos], saldo_sobrante=19_000_000, valor_equipo=0, dias_para_jornada=4)
        self.assertEqual(len(todos["operaciones"]), 3)

    def test_la_deuda_financia_pero_con_tope(self) -> None:
        desk = build_trading_desk(
            [_cand("caro", 12_000_000, 10.0)], saldo_sobrante=0, valor_equipo=100_000_000, dias_para_jornada=4
        )
        self.assertEqual(desk["operaciones"], [])  # solo 10 M de deuda usable
        desk = build_trading_desk(
            [_cand("medio", 9_000_000, 10.0)], saldo_sobrante=0, valor_equipo=100_000_000, dias_para_jornada=4
        )
        self.assertEqual(desk["usa_deuda"], 9_000_000)

    def test_sin_dos_dias_no_hay_trading(self) -> None:
        desk = build_trading_desk([_cand("a", 1_000_000, 30.0)], saldo_sobrante=5_000_000, valor_equipo=0, dias_para_jornada=1)
        self.assertFalse(desk["activo"])
        self.assertEqual(desk["operaciones"], [])

    def test_la_prima_pagada_se_descuenta(self) -> None:
        self.assertLess(ganancia_esperada(1_000_000, 1_300_000, 20.0), ganancia_esperada(1_000_000, 1_000_000, 20.0))
        desk = build_trading_desk(
            [_cand("sobrepuja", 1_300_000, 15.0, valor=1_000_000)], saldo_sobrante=5_000_000, valor_equipo=0, dias_para_jornada=4
        )
        self.assertEqual(desk["operaciones"], [])


if __name__ == "__main__":
    unittest.main()
