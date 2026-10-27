"""Pruebas de la Fase 2. No salen a la red."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

import cli
from toolbox import net
from toolbox.cache import EntityStore, ResponseCache
from toolbox.matching import (
    MATCH_THRESHOLD,
    CanonicalPlayer,
    EntityResolver,
    ExternalRecord,
    jaro_winkler,
    levenshtein,
    normalize_name,
    phonetic_key,
)
from toolbox.net import (
    TRANSFERMARKT_MAX_REQUESTS,
    TRANSFERMARKT_WINDOW_SECONDS,
    ExternalClient,
    SlidingWindowLimiter,
    shared_transfermarkt_limiter,
)
from toolbox.scrapers import (
    FF_FITNESS_URL,
    FF_MARKET_URL,
    FF_SANCTIONS_URL,
    FF_WARNINGS_URL,
    parse_fitness_board,
    parse_market_board,
    parse_money,
    parse_warning_board,
)

MARKET_HTML = """
<table>
<tr class="elemento_jugador" data-id="1" data-nombre="b mendez" data-posicion="Centrocampista"
    data-valor="10000000" data-diferencia1="120000" data-diferencia2="250000"
    data-diferencia3="310000" data-aceleracion="500000">
  <td>
    <a class="player-name"><span class="d-none d-md-inline">B. Méndez</span><span>Méndez</span></a>
    <div class="player-equipo"><img alt="Real Sociedad"><span>Real Sociedad</span></div>
  </td>
  <td><span class="probabilidad-widget"><span class="prob-4">80%</span></span></td>
</tr>
<tr class="elemento_jugador" data-id="2" data-nombre="iago aspas" data-posicion="Delantero"
    data-valor="20000000" data-diferencia1="-80000" data-aceleracion="-400000">
  <td>
    <a class="player-name"><span class="d-none d-md-inline">Iago Aspas</span></a>
    <div class="player-equipo"><span>Celta</span></div>
  </td>
  <td><span class="probabilidad-widget"><span class="prob-5">90%</span></span></td>
</tr>
<tr class="elemento_jugador" data-id="1972" data-nombre="yeray alvarez" data-posicion="Defensa"
    data-valor="15000000" data-diferencia1="-18966" data-aceleracion="18966">
  <td>
    <a class="player-name"><span class="d-none d-md-inline">Yeray Álvarez</span></a>
    <div class="player-equipo"><span>Athletic</span></div>
  </td>
  <td>
    <span class="columna_diferencia columna_diferencia1"><span class="analytics-down">-1,42%</span></span>
    <span class="porcentaje-perfil"><span class="probabilidad-widget"><span class="prob-3">70%</span></span></span>
  </td>
</tr>
</table>
"""

FITNESS_HTML = """
<a href="https://www.futbolfantasy.com/laliga/equipos/real-sociedad">Real Sociedad</a>
<div class="elemento lesionado col-12">
  <a class="jugador" href="https://www.futbolfantasy.com/jugadores/brais-mendez">B. Méndez</a>
  <span class="lesion">Sobrecarga</span>
  <span class="rounded-card__status gravedad-1">Duda para la jornada 9</span>
</div>
"""

WARNINGS_HTML = """
<a href="https://www.futbolfantasy.com/laliga/equipos/real-sociedad">Real Sociedad</a>
<div class="elemento sancionado col-12">
  <a class="jugador" href="https://www.futbolfantasy.com/jugadores/brais-mendez">B. Méndez</a>
  <span class="tarjetasA"></span><span class="tarjetasA"></span><span class="tarjetasA"></span><span class="tarjetasA"></span>
</div>
"""

FBREF_HTML = """
<table><tr>
  <th data-stat="player"><a>B. Méndez</a></th>
  <td data-stat="team"><a>Real Sociedad</a></td>
  <td data-stat="pos">MF</td>
  <td data-stat="xg">3.2</td>
  <td data-stat="xg_assist">1.4</td>
  <td data-stat="assisted_shots">18</td>
  <td data-stat="challenges_won">22</td>
  <td data-stat="clearances">4</td>
  <td data-stat="minutes">720</td>
  <td data-stat="games_starts">8</td>
  <td data-stat="minutes_pct">85.0</td>
</tr></table>
"""

SOFA = {
    "results": [
        {
            "player": {"id": 9, "name": "B. Méndez", "position": "M"},
            "team": {"name": "Real Sociedad"},
            "statistics": {
                "rating": 7.4,
                "expectedGoals": 3.2,
                "saves": 1,
                "minutesPlayed": 720,
                "appearances": 8,
                "started": 8,
            },
        }
    ]
}

UNDERSTAT_PAYLOAD = {
    "teams": {
        "1": {
            "id": "1",
            "title": "Real Sociedad",
            "history": [{"xG": 1.2, "xGA": 0.8}, {"xG": 1.0, "xGA": 1.1}],
        },
        "2": {
            "id": "2",
            "title": "Celta Vigo",
            "history": [{"xG": 0.9, "xGA": 1.5}, {"xG": 1.1, "xGA": 1.4}],
        },
    },
    "players": [
        {
            "id": "99",
            "player_name": "Brais Méndez",
            "games": "8",
            "time": "720",
            "xG": "4.0",
            "xA": "2.0",
            "key_passes": "20",
            "position": "M S",
            "team_title": "Real Sociedad",
        }
    ],
    "dates": [
        {
            "id": "1",
            "isResult": False,
            "h": {"id": "1", "title": "Real Sociedad"},
            "a": {"id": "2", "title": "Celta Vigo"},
            "datetime": "2099-01-01 18:00:00",
        }
    ],
}

JP_HTML = """
<html><script>
const marketCaching=[{"playerId":"1","playerUrl":"brais","name":"B. Méndez","real_name":"Brais Méndez","position":"centrocampista","altPositions":[],"remote_player":"1","price":"10000000","max_price":"1","min_price":"1","lastMarkets":{},"url":"brais","teamId":"1","team":"Real Sociedad","teamUrl":"real-sociedad","remote_team":"1","available":"1","penalized":"0","injured":"0","warned":"0","doubt":"0","other":"0","tip":"recomendable","tip_desc":"ok","status":"check","icon":"tick","desc":"Disponible","racha":"3"}];
</script></html>
"""

BRAIS_TM = {
    "results": [
        {
            "id": "10",
            "name": "Brais Méndez",
            "position": "AM",
            "club": {"id": "681", "name": "Real Sociedad"},
            "marketValue": 18000000,
        },
        {
            "id": "11",
            "name": "Otro Méndez",
            "position": "GK",
            "club": {"name": "Getafe"},
            "marketValue": 1000000,
        },
    ]
}

ASPAS_TM = {
    "results": [
        {
            "id": "20",
            "name": "Iago Aspas",
            "position": "ST",
            "club": {"name": "Celta"},
            "marketValue": 8000000,
        }
    ]
}


def _player(player_id: str, name: str, club: str, position: str, *, nickname: str | None = None) -> CanonicalPlayer:
    return CanonicalPlayer(
        player_id=player_id,
        name=name,
        nickname=nickname,
        club=club,
        position=position,
        fantasy_price=10_000_000,
    )


class Phase2Test(unittest.TestCase):
    def test_normalizes_complex_names_and_phonetics(self) -> None:
        self.assertEqual(normalize_name("José María Giménez"), "jose maria gimenez")
        self.assertEqual(normalize_name("B. Méndez Jr."), "b mendez")
        self.assertEqual(phonetic_key("Ibañez"), phonetic_key("Iváñez"))
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.961, places=3)

    def test_matches_initial_and_splits_homonyms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EntityStore(Path(directory))
            resolver = EntityResolver(store)
            brais = _player("1", "Brais Méndez", "Real Sociedad", "MC")
            miguel = _player("2", "Miguel Méndez", "Barcelona", "MC")
            decisions = resolver.link_source(
                [brais, miguel],
                [
                    ExternalRecord(
                        source="futbolfantasy",
                        name="B. Méndez",
                        external_id="ff-1",
                        club="Real Sociedad",
                        position="Centrocampista",
                    )
                ],
                "futbolfantasy",
            )
            linked = {item.player_id: item for item in decisions if item.linked}
            self.assertIn("1", linked)
            self.assertNotIn("2", linked)
            self.assertGreaterEqual(linked["1"].confidence, MATCH_THRESHOLD)
            self.assertEqual(MATCH_THRESHOLD, 0.85)

            low = resolver.link_source(
                [brais, miguel],
                [ExternalRecord(source="futbolfantasy", name="Méndez", club="Real Sociedad", position="MC")],
                "futbolfantasy",
            )
            self.assertTrue(all(not item.linked for item in low))
            audits = resolver.audit()
            self.assertTrue(audits)
            self.assertTrue(all(row["confidence"] < MATCH_THRESHOLD or row["reason"] == "ambiguous" for row in audits))

            ambiguous = resolver.link_source(
                [brais],
                [
                    ExternalRecord(source="fbref", name="Brais Méndez", external_id="a", club="Real Sociedad", position="MC"),
                    ExternalRecord(source="fbref", name="Brais Mendez", external_id="b", club="Real Sociedad", position="MC"),
                ],
                "fbref",
            )
            self.assertTrue(all(not item.linked for item in ambiguous))
            self.assertTrue(any(row["reason"] == "ambiguous" for row in resolver.audit()))

            forced = resolver.force_manual(
                player_id="2",
                source="futbolfantasy",
                external_name="Miguel Méndez",
                external_id="manual-2",
                club="Barcelona",
                position="centrocampista",
            )
            self.assertTrue(forced["manual"])
            self.assertEqual(forced["confidence"], 1.0)
            again = resolver.link_source(
                [brais, miguel],
                [ExternalRecord(source="futbolfantasy", name="Alguien", club="Celta", position="DEL")],
                "futbolfantasy",
            )
            manual = next(item for item in again if item.player_id == "2")
            self.assertTrue(manual.manual)
            self.assertEqual(manual.external_id, "manual-2")
            store.close()

    def test_transfermarkt_rate_limit_is_two_per_three_seconds_per_ip(self) -> None:
        """Presupuesto por IP y ventana. El espaciado por dominio se apaga aquí:
        esta prueba mide exactamente ``slept`` y el controlador de tráfico
        añadiría sus propias esperas, que tienen sus propias pruebas."""
        pacing = patch.dict(os.environ, {"FANTASY_NET_PACING": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)
        from toolbox import net as net_module

        net_module.reset_rate_limits()
        self.addCleanup(net_module.reset_rate_limits)
        now = [0.0]
        slept: list[float] = []

        def clock() -> float:
            return now[0]

        def sleeper(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        limiter = SlidingWindowLimiter(
            max_calls=TRANSFERMARKT_MAX_REQUESTS,
            window_seconds=TRANSFERMARKT_WINDOW_SECONDS,
            sleeper=sleeper,
            clock=clock,
        )
        self.assertEqual(limiter.acquire("10.0.0.1"), 0.0)
        self.assertEqual(limiter.acquire("10.0.0.1"), 0.0)
        self.assertEqual(limiter.acquire("10.0.0.2"), 0.0)
        self.assertEqual(limiter.acquire("10.0.0.2"), 0.0)
        self.assertEqual(limiter.acquire("10.0.0.1"), 3.0)
        self.assertEqual(slept, [3.0])

        shared = shared_transfermarkt_limiter("phase2-budget", sleeper=lambda _seconds: None, clock=clock)
        self.assertEqual((shared.max_calls, shared.window_seconds), (2, 3.0))

        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"results": []})

        with tempfile.TemporaryDirectory() as directory:
            cache = ResponseCache(Path(directory))
            http = httpx.Client(transport=httpx.MockTransport(handler))
            isolated = SlidingWindowLimiter(
                max_calls=2,
                window_seconds=3.0,
                sleeper=sleeper,
                clock=clock,
            )
            client = ExternalClient(
                cache=cache,
                http=http,
                sleeper=sleeper,
                clock=clock,
                transfermarkt_limiter=isolated,
                client_ip="10.0.0.8",
            )
            url = "https://transfermarkt-api.fly.dev/players/search/cache?page_number=1"
            client.get_json(url, ttl=60, fresh=False)
            client.get_json(url, ttl=60, fresh=False)
            self.assertEqual(calls["n"], 1)
            self.assertEqual(cache.get_json(url), {"results": []})
            slept.clear()
            now[0] = 100.0
            for index in range(3):
                client.get_json(
                    f"https://tmapi.transfermarkt.technology/players/search/n{index}?page_number=1",
                    ttl=0,
                    fresh=True,
                )
            self.assertEqual(calls["n"], 4)
            self.assertEqual(slept, [3.0])
            self.assertEqual(client.transfermarkt_budget, (2, 3.0))
            client.close()
            http.close()
            cache.close()

    def test_parsers_read_probability_acceleration_and_cards(self) -> None:
        board = parse_market_board(MARKET_HTML)
        self.assertEqual(board[0].name, "B. Méndez")
        self.assertEqual(board[0].p_titular, 0.8)
        self.assertEqual(board[0].acceleration, 500000)
        self.assertEqual(board[0].price_delta, 120000)
        # Los acumulados de 2 y 3 días se leían y se tiraban: la app oficial a
        # veces enseña ese tramo y parecía que el panel se había quedado corto.
        self.assertEqual(board[0].price_delta_2, 250000)
        self.assertEqual(board[0].price_delta_3, 310000)
        self.assertEqual(board[0].position, "MC")
        self.assertEqual(board[1].acceleration, -400000)
        yeray = next(row for row in board if row.external_id == "1972")
        self.assertEqual(yeray.p_titular, 0.7)
        fitness = parse_fitness_board(FITNESS_HTML)
        self.assertEqual(fitness[0].fitness, "duda")
        self.assertEqual(fitness[0].club, "Real Sociedad")
        warnings = parse_warning_board(WARNINGS_HTML)
        self.assertEqual(warnings[0].yellow_cards, 4)
        self.assertTrue(warnings[0].on_verge)
        self.assertEqual(parse_money("€18.00m"), 18_000_000)
        self.assertEqual(parse_money(0), None)

    def test_trends_json_schema(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith(FF_MARKET_URL):
                return httpx.Response(200, text=MARKET_HTML)
            if url.startswith(FF_FITNESS_URL):
                return httpx.Response(200, text=FITNESS_HTML)
            if url.startswith(FF_SANCTIONS_URL):
                return httpx.Response(200, text="<div></div>")
            if url.startswith(FF_WARNINGS_URL):
                return httpx.Response(200, text=WARNINGS_HTML)
            if "posibles-alineaciones" in url or "alineaciones-probables" in url:
                return httpx.Response(200, text="<html></html>")
            if "fbref.com" in url:
                return httpx.Response(200, text=FBREF_HTML)
            if "sofascore.com" in url:
                return httpx.Response(200, json=SOFA)
            if "understat.com" in url and "getLeagueData" in url:
                return httpx.Response(200, json=UNDERSTAT_PAYLOAD)
            if "jornadaperfecta.com" in url:
                return httpx.Response(200, text=JP_HTML)
            if "players/search" in url and ("Aspas" in url or "Iago" in url):
                return httpx.Response(200, json=ASPAS_TM)
            if "players/search" in url:
                return httpx.Response(200, json=BRAIS_TM)
            if "analiticafantasy.com" in url:
                # Enrichment AF vacío pero OK: no fuerza partial ni inventa filas.
                return httpx.Response(200, text="<html></html>")
            return httpx.Response(404, text="no")

        transport = httpx.MockTransport(handler)

        class FakeLeague:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                return None

            def __enter__(self) -> FakeLeague:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def market_document(self, _league: str | None, *, fresh: bool) -> dict:
                return {
                    "ok": True,
                    "league_id": "7",
                    "league_name": "Liga",
                    "listings": [
                        {
                            "player_id": "1001",
                            "name": "Brais Méndez",
                            "nickname": "B. Méndez",
                            "position": "MC",
                            "club": "Real Sociedad",
                            "market_value": 10_000_000,
                            "sale_price": 9_500_000,
                        }
                    ],
                }

            def squads_document(self, _league: str | None, *, fresh: bool) -> dict:
                return {
                    "ok": True,
                    "league_id": "7",
                    "league_name": "Liga",
                    "partial": False,
                    "squads": [
                        {
                            "team_id": "9",
                            "players": [
                                {
                                    "player_id": "1001",
                                    "name": "Brais Méndez",
                                    "nickname": "B. Méndez",
                                    "position": "MC",
                                    "club": "Real Sociedad",
                                    "market_value": 10_000_000,
                                },
                                {
                                    "player_id": "1002",
                                    "name": "Iago Aspas",
                                    "nickname": "Aspas",
                                    "position": "DEL",
                                    "club": "Celta",
                                    "market_value": 20_000_000,
                                },
                            ],
                        }
                    ],
                }

        real_client = httpx.Client

        def client_factory() -> httpx.Client:
            # Transporte simulado para el ``ExternalClient()`` que construyen
            # los scrapers por su cuenta. Es el punto de inyección oficial del
            # air-gap: fuera de producción solo se acepta un MockTransport.
            return real_client(transport=transport)

        stdout = StringIO()
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            env = {
                "FANTASY_CACHE_DIR": directory,
                "FANTASY_CLIENT_IP": "phase2-schema",
                "SOFASCORE_STATS_URL": "https://api.sofascore.com/api/v1/unique-tournament/8/statistics",
            }
            with patch.dict(os.environ, env, clear=False):
                with (
                    patch("cli.LaligaClient", FakeLeague),
                    patch.object(net, "TRANSPORT_FACTORY", client_factory),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.main(["trends", "--json", "--league", "7"])
            payload = json.loads(stdout.getvalue())
            cache = ResponseCache(Path(directory))
            cached_page = cache.get_page(FF_MARKET_URL)
            store = EntityStore(Path(directory))
            link = store.get_link("1001", "futbolfantasy")
            cache.close()
            store.close()

        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["command"], "trends")
        self.assertEqual(payload["league_id"], "7")
        self.assertEqual(payload["matching"]["threshold"], 0.85)
        self.assertIn("form_note", payload)
        self.assertFalse(payload["partial"])
        self.assertIsNotNone(cached_page)
        self.assertIn("elemento_jugador", cached_page or "")
        self.assertIsNotNone(link)
        self.assertGreaterEqual(float((link or {})["confidence"]), 0.85)

        for key in ("rising", "falling", "undervalued", "availability", "players", "sources"):
            self.assertIn(key, payload)
        rising = payload["rising"][0]
        self.assertEqual(rising["player_id"], "1001")
        self.assertTrue(rising["flip_candidate"])
        self.assertEqual(rising["acceleration"], 500000)
        self.assertEqual(rising["p_titular"], 0.8)
        self.assertEqual(rising["fitness"], "duda")
        self.assertEqual(rising["sanction"]["yellow_cards"], 4)
        self.assertTrue(rising["sanction"]["on_verge"])
        self.assertFalse(rising["sanction"]["suspended"])
        self.assertGreaterEqual(rising["matching_confidence"], 0.85)
        self.assertEqual(rising["transfermarkt_value_eur"], 18_000_000)
        self.assertEqual(rising["gap_eur"], 8_000_000)
        # Understat manda en xG/xA; FBref/Sofascore rellenan el resto.
        self.assertEqual(rising["form"]["xg"], 4.0)
        self.assertEqual(rising["form"]["xa"], 2.0)
        self.assertEqual(rising["form"]["key_passes"], 20)
        self.assertEqual(rising["form"]["duels_won"], 22)
        self.assertEqual(rising["form"]["clearances"], 4)
        self.assertEqual(rising["form"]["average_rating"], 7.4)
        self.assertEqual(rising["form"]["minutes"], 720)
        self.assertEqual(rising["form"]["minutes_pct"], 1.0)
        self.assertEqual(rising["form"]["jp_tip"], "recomendable")
        self.assertEqual(rising["form"]["jp_projected_points"], 6.5)
        self.assertIsNotNone(rising.get("fixture"))
        self.assertEqual(rising["fixture"]["opponent"], "Celta Vigo")
        self.assertTrue(rising["fixture"]["home"])
        self.assertIn(rising["fixture"]["fdr"], {1, 2, 3, 4, 5})
        self.assertTrue(payload["sources"]["understat"]["ok"])
        self.assertTrue(payload["sources"]["jornadaperfecta"]["ok"])
        self.assertEqual(payload["falling"][0]["player_id"], "1002")
        self.assertLess(payload["falling"][0]["acceleration"], 0)
        self.assertEqual(payload["undervalued"][0]["player_id"], "1001")
        self.assertTrue(any(player["player_id"] == "1001" for player in payload["availability"]))
        for source in payload["sources"].values():
            self.assertIn("ok", source)
            self.assertIn("from_cache", source)


if __name__ == "__main__":
    unittest.main()
