"""Escudo anticipado: cláusulas que se abren antes del próximo bloqueo y posiciones sin recambio."""

from __future__ import annotations

from datetime import datetime, timezone

from toolbox.engine.clause_advisor import auditar_clausulas_plantilla, deja_sin_once, evaluar_clausulas

M = 1_000_000
AHORA = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
INICIO_J13 = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)
CIERRE_CLAUSULAS = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)


def _propio(pid, pos, valor, clausula=None, abre=None, xp=5.0):
    lock = {"present": True, "expires_at": abre, "is_locked": True} if abre else {"present": True, "is_locked": False}
    return {
        "player_id": pid,
        "nombre": pid,
        "position": pos,
        "valor": valor,
        "clausula": clausula if clausula is not None else valor,
        "blindado": False,
        "bloqueo": lock,
        "jornada": xp,
        "p_titular": 0.9,
        "pct": 0.0,
        "en_xi": True,
        "tu_once_pierde_sin_el": xp,
        "elegible": True,
    }


def _plantilla_12():
    """Un solo POR (Radu) y un solo DEL (Cepeda), como la plantilla real del 8-nov."""
    filas = [_propio("radu", "POR", 50 * M, abre="2026-11-15T13:08:46+00:00", xp=6.5)]
    filas += [_propio(f"def{i}", "DEF", 10 * M, clausula=20 * M) for i in range(5)]
    filas += [_propio(f"mc{i}", "MC", 10 * M, clausula=20 * M) for i in range(5)]
    filas.append(_propio("cepeda", "DEL", int(3.6 * M), abre="2026-11-16T13:00:00+00:00", xp=4.5))
    return filas


RIVALES = [{"team_id": "f", "manager": "floren romi", "saldo": int(80.8 * M), "posiciones": []}]
ALTERNATIVAS = [
    {"player_id": "por_libre", "nombre": "Portero libre", "position": "POR", "coste": 2 * M, "xp": 3.0, "via": "puja"},
    {"player_id": "por_rival", "nombre": "Portero rival", "position": "POR", "coste": 1 * M, "xp": 4.0, "via": "clausula"},
    {"player_id": "del_libre", "nombre": "Delantero libre", "position": "DEL", "coste": int(1.5 * M), "xp": 2.5, "via": "puja"},
]


def _informe():
    return evaluar_clausulas(
        propios=_plantilla_12(),
        ajenos=[],
        rivales=RIVALES,
        saldo=250_000,
        ratio=4 * M,
        ahora=AHORA,
        cierre=CIERRE_CLAUSULAS,
        alternativas=ALTERNATIVAS,
        inicio_jornada=INICIO_J13,
    )


def test_unico_portero_y_delantero_dejan_sin_once():
    plantilla = _plantilla_12()
    assert deja_sin_once(plantilla[0], plantilla) is True  # Radu
    assert deja_sin_once(plantilla[-1], plantilla) is True  # Cepeda
    assert deja_sin_once(plantilla[1], plantilla) is False  # un defensa con 4 más


def test_alerta_prioritaria_con_fecha_de_apertura():
    informe = _informe()
    alertas = {a["player_id"]: a for a in informe["resumen"]["alertas_prioritarias"]}
    assert set(alertas) == {"radu", "cepeda"}
    assert alertas["radu"]["abre_el"] == "15-nov"
    assert alertas["cepeda"]["abre_el"] == "16-nov"
    # El recambio sugerido se compra por puja (admite crédito), nunca por cláusula.
    assert alertas["radu"]["recambio_sugerido"]["player_id"] == "por_libre"
    assert "se abre el 15-nov" in alertas["radu"]["accion"]
    radu = next(f for f in informe["proteger"] if f["player_id"] == "radu")
    assert radu["veredicto_codigo"] == "SIN_RECAMBIO" and radu["riesgo"] == "ALTO"
    assert radu["en_candado"] is False  # se abre antes del saque: no se esconde como «candado»
    assert informe["proteger"][0]["alerta_prioritaria"] is True  # las alertas van primero
    assert informe["resumen"]["en_peligro"] >= 2


def test_candado_que_dura_mas_alla_del_saque_no_alerta():
    plantilla = _plantilla_12()
    plantilla[0]["bloqueo"] = {"present": True, "expires_at": "2026-11-25T13:00:00+00:00", "is_locked": True}
    informe = evaluar_clausulas(
        propios=plantilla,
        ajenos=[],
        rivales=RIVALES,
        saldo=250_000,
        ratio=4 * M,
        ahora=AHORA,
        cierre=CIERRE_CLAUSULAS,
        alternativas=ALTERNATIVAS,
        inicio_jornada=INICIO_J13,
    )
    assert "radu" not in {a["player_id"] for a in informe["resumen"]["alertas_prioritarias"]}


def test_radar_mira_hasta_el_bloqueo_y_no_solo_3_dias():
    fila = {
        "player_id": "radu",
        "nombre": "Radu",
        "position": "POR",
        "clausula": 50 * M,
        "valor_mercado": 50 * M,
        "clausulaAbre": {"expires_at": "2026-11-15T13:08:46+00:00"},
        "jornada": 6.5,
    }
    rivales = [{"dineroEstimado": int(80.8 * M), "manager": "floren romi"}]
    assert auditar_clausulas_plantilla([fila], rivales, ahora=AHORA) == []  # 7 días: fuera de la ventana de 3
    filas = auditar_clausulas_plantilla([fila], rivales, ahora=AHORA, hasta=INICIO_J13)
    assert [f["estado"] for f in filas] == ["RIESGO_ALTO"]
