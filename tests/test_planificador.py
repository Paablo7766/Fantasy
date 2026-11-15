from datetime import datetime, timezone

from toolbox.planificador import build_planificador

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _board():
    calendario = [{"opponent": f"Club {i}", "is_home": i % 2 == 0, "difficulty": "media", "win_prob": 0.4} for i in range(4)]
    return {
        "trends": {
            "players": [
                {"player_id": "1", "nickname": "Mío", "position": "MC", "club": "Betis", "own_expected_points": 6.0, "own_xp_siguientes": [5.0, 4.0, 3.0], "own_calendar": calendario, "p_titular": 90},
                {"player_id": "2", "nickname": "Rival abierta", "position": "DEL", "club": "Sevilla", "own_expected_points": 8.0, "own_xp_siguientes": [1.0], "own_calendar": calendario, "lineup_status": "duda"},
                {"player_id": "3", "nickname": "Rival bloqueada", "position": "DEF", "club": "Getafe", "own_expected_points": 2.0, "own_xp_siguientes": [], "own_calendar": [], "fitness": "lesionado"},
                {"player_id": "4", "nickname": "Mercado", "position": "PT", "club": "Elche", "own_expected_points": 3.0, "own_xp_siguientes": [3.0, 3.0, 3.0], "own_calendar": calendario},
                {"player_id": "5", "nickname": "Sin xP", "position": "MC", "club": "Elche"},
            ]
        },
        "squads": {
            "squads": [
                {"team_id": "a", "manager_name": "Yo", "is_self": True, "players": [{"player_id": "1", "club": "Betis", "week_points_by_round": {"11": 3, "12": 4}}]},
                {
                    "team_id": "b",
                    "manager_name": "Pepe",
                    "players": [
                        {"player_id": "2", "club": "Sevilla", "buyout_clause": 20_000_000, "market_value": 10_000_000, "clause_lock": {"expires_at": "2026-11-10T10:00:00+00:00"}, "week_points_by_round": {"12": 5}},
                        {"player_id": "3", "club": "Getafe", "buyout_clause": 5_000_000, "market_value": 5_000_000, "clause_lock": {"expires_at": "2026-11-20T10:00:00+00:00"}},
                    ],
                },
            ]
        },
        "market": {"listings": [{"player_id": "4", "sale_price": 1_500_000, "listing_expires_at": "2026-11-16T10:00:00+00:00"}]},
    }


def test_universo_orden_y_horizonte():
    out = build_planificador(_board(), now=NOW)
    ids = [fila["player_id"] for fila in out["jugadores"]]
    assert ids == ["2", "1", "4", "3"]  # ordenado por xP de la próxima; sin xP queda fuera
    assert out["jornada"] == 13 and out["jornadas"] == [13, 14, 15, 16]
    mio = next(f for f in out["jugadores"] if f["player_id"] == "1")
    assert mio["xp"] == [6.0, 5.0, 4.0, 3.0] and mio["xp_total"] == 18.0
    assert mio["p_titular"] == 0.9 and mio["dueno"]["tipo"] == "mio"
    corto = next(f for f in out["jugadores"] if f["player_id"] == "2")
    assert corto["xp"] == [8.0, 1.0, None, None] and corto["xp_total"] == 9.0


def test_duenos_clausulas_y_estado():
    out = build_planificador(_board(), now=NOW)
    por_id = {f["player_id"]: f for f in out["jugadores"]}
    assert por_id["2"]["dueno"] == {"tipo": "rival", "nombre": "Pepe", "team_id": "b"}
    assert por_id["2"]["clausula"]["estado"] == "abierta" and por_id["2"]["clausula"]["multiplo"] == 2.0
    assert por_id["2"]["estado"] == "duda"
    assert por_id["3"]["clausula"]["estado"] == "bloqueada" and por_id["3"]["clausula"]["abre_at"].startswith("2026-11-20")
    assert por_id["3"]["estado"] == "baja"
    assert por_id["4"]["dueno"]["tipo"] == "mercado" and por_id["4"]["mercado"]["precio"] == 1_500_000
    assert por_id["4"]["posicion"] == "POR" and por_id["4"]["clausula"] is None
    assert por_id["1"]["clausula"] is None


def test_clausula_cara_con_la_regla_del_asesor():
    out = build_planificador(_board(), now=NOW)
    por_id = {f["player_id"]: f for f in out["jugadores"]}
    # 2× el valor pasa del tope de 1,25×: quema patrimonio, no compensa.
    assert por_id["2"]["clausula"]["cara"] is True
    assert por_id["2"]["clausula"]["prima_eur"] == 10_000_000
    # Cláusula igual al valor: precio justo.
    assert por_id["3"]["clausula"]["cara"] is False
    assert por_id["3"]["clausula"]["prima_eur"] == 0


def test_rentabilidad_por_jugador():
    out = build_planificador(_board(), now=NOW)
    por_id = {f["player_id"]: f for f in out["jugadores"]}
    # Tuyo: sin veredicto.
    assert por_id["1"]["rentabilidad"] is None
    # Cláusula que quema patrimonio: cara aunque su xP la cubra.
    assert por_id["2"]["rentabilidad"]["veredicto"] == "caro"
    # Mercado: precio frente al valor justo de su xP.
    mercado = por_id["4"]["rentabilidad"]
    assert mercado["precio"] == 1_500_000 and mercado["valor_justo"] > 0
    assert mercado["veredicto"] in {"rentable", "justo", "caro"}
    esperado = round((mercado["valor_justo"] / mercado["precio"] - 1) * 100, 1)
    assert mercado["margen_pct"] == esperado


def test_rentabilidad_umbral():
    from toolbox.planificador import _rentabilidad

    fila = {
        "dueno": {"tipo": "mercado"},
        "mercado": {"precio": 10_000_000},
        "clausula": None,
        "xp": [5.0, None, None, None],
        "valor": 10_000_000,
    }
    # Sin curva: recta de 2 M€ por punto → 10 M€ de valor justo = precio justo.
    assert _rentabilidad(fila, 2_000_000.0, None)["veredicto"] == "justo"
    assert _rentabilidad(fila, 2_400_000.0, None)["veredicto"] == "rentable"
    assert _rentabilidad(fila, 1_600_000.0, None)["veredicto"] == "caro"
    # Valor justo inflado: se recorta a 2,5× el valor de mercado.
    assert _rentabilidad(fila, 20_000_000.0, None)["valor_justo"] == 25_000_000


def test_blindado():
    board = _board()
    board["squads"]["squads"][1]["players"][0]["is_shielded"] = True
    out = build_planificador(board, now=NOW)
    fila = next(f for f in out["jugadores"] if f["player_id"] == "2")
    assert fila["clausula"]["estado"] == "blindado"


def test_libres_fuera_de_la_liga():
    catalogo = [
        {"player_id": "1", "nickname": "Mío", "position": "MC", "club": "Betis", "average_points": 9, "week_points": [9, 9, 9]},
        {"player_id": "9", "nickname": "Libre bueno", "position": "DEL", "club": "Betis", "average_points": 10, "week_points": [8, 12, 4, 14], "player_status": "ok"},
        {"player_id": "8", "nickname": "Libre lesionado", "position": "DEF", "club": "Elche", "average_points": 12, "week_points": [10, 12, 14], "player_status": "injured"},
        {"player_id": "7", "nickname": "Pocas jornadas", "position": "MC", "club": "Elche", "average_points": 20, "week_points": [20]},
    ]
    out = build_planificador(_board(), now=NOW, catalogo=catalogo)
    libres = out["libres"]
    assert [fila["player_id"] for fila in libres] == ["9", "8"]  # los de la liga y los de <3 jornadas fuera; las bajas al final
    bueno = libres[0]
    assert bueno["forma"] == 10.0 and bueno["ultimos"] == [12.0, 4.0, 14.0]
    assert bueno["proximo"]["rival"] == "Club 0"  # rival del club sacado de quien sí tiene calendario
    assert libres[1]["estado"] == "baja"
