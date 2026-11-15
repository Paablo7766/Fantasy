"""El cuaderno añade planes distintos y deja quieto el once después del saque."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from toolbox.consejo_log import consejo_de, registrar, segunda_oferta

ANTES = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
DESPUES = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _plan(cifra: int = 1_000_000) -> dict:
    return {
        "mejora_puntos_jornada": 3.5,
        "once": [{"player_id": "1", "nombre": "Uno", "position": "DEL"}],
        "acciones": [
            {
                "tipo": "PUJA",
                "player_id": "9",
                "nombre": "Nueve",
                "posicion": "DEL",
                "momento": "hoy",
                "euros": cifra,
                "puja_final": cifra,
                "p_ganar_por_valor": 0.42,
            }
        ],
        "reservas": [{"player_id": "8", "nombre": "Ocho", "reserva_de": "Nueve", "euros": 800_000}],
    }


def _once() -> dict:
    return {"xi": [{"player_id": str(i), "nickname": f"J{i}", "position": "MC"} for i in range(11)]}


def _cierre(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table pre_lock_snapshots (season text, jornada integer, kickoff text, stored_at real, payload text)"
    )
    conn.execute(
        "insert into pre_lock_snapshots values ('2026/27', 13, '2026-11-20T20:00:00+00:00', 1, '{}')"
    )
    conn.commit()
    conn.close()


def test_segunda_oferta_no_se_inventa() -> None:
    vacio = segunda_oferta([{"player_id": "1", "bid_count": 3}])
    assert vacio["segundas"] == []
    assert vacio["nota"] is not None
    con_datos = segunda_oferta(
        [{"player_id": "1", "market_id": "m", "bids": [{"amount": 12}, {"amount": 10}, {"amount": 9}]}]
    )
    assert con_datos["segundas"] == [
        {"player_id": "1", "market_id": "m", "primera_eur": 12, "segunda_eur": 10}
    ]


def test_el_plan_guarda_cifra_reserva_y_probabilidad() -> None:
    cuerpo = consejo_de(_plan())
    accion = cuerpo["acciones"][0]
    assert accion["puja_final"] == 1_000_000
    assert accion["p_ganar"] == 0.42
    assert cuerpo["reservas"][0]["euros"] == 800_000


def test_el_mismo_plan_no_pisa_y_otro_del_mismo_dia_se_añade(tmp_path: Path) -> None:
    db = tmp_path / "c.sqlite"
    _cierre(db)
    enviados: list[dict] = []
    primero = registrar("L", _plan(), payload={"saved_lineup": _once()}, now=ANTES, db_path=db, remote=enviados.append)
    segundo = registrar("L", _plan(), payload={"saved_lineup": _once()}, now=ANTES, db_path=db, remote=enviados.append)
    tercero = registrar(
        "L", _plan(1_200_000), payload={"saved_lineup": _once()}, now=ANTES, db_path=db, remote=enviados.append
    )
    assert primero["plan"] is True
    assert segundo["plan"] is False
    assert tercero["plan"] is True
    conn = sqlite3.connect(db)
    filas = conn.execute("select day, payload from consejo_eventos where kind = 'plan' order by id").fetchall()
    assert len(filas) == 2
    assert filas[0][0] == filas[1][0] == "2026-11-15"
    cifras = [json.loads(raw)["acciones"][0]["puja_final"] for _, raw in filas]
    assert cifras == [1_000_000, 1_200_000]
    assert len(enviados) == 2


def test_el_once_se_reescribe_antes_del_saque_y_despues_no(tmp_path: Path) -> None:
    db = tmp_path / "c.sqlite"
    _cierre(db)
    once = _once()
    registrar("L", _plan(), payload={"saved_lineup": once}, now=ANTES, db_path=db, remote=False)
    once["xi"][0]["player_id"] = "cambiado"
    mas_tarde = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    escrito = registrar("L", _plan(), payload={"saved_lineup": once}, now=mas_tarde, db_path=db, remote=False)
    assert escrito["xi"] is True
    tarde = registrar("L", _plan(), payload={"saved_lineup": _once()}, now=DESPUES, db_path=db, remote=False)
    assert tarde["xi"] is False
    conn = sqlite3.connect(db)
    raw = conn.execute("select payload from consejo_eventos where kind = 'xi'").fetchone()[0]
    cuerpo = json.loads(raw)
    assert cuerpo["jornada"] == 13
    assert cuerpo["xi"][0]["player_id"] == "cambiado"
