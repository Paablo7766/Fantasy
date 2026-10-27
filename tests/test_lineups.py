"""Parsers de alineaciones probables. No salen a la red."""

from __future__ import annotations

import unittest

from toolbox.fantasy_scraper import (
    DOUBT_BELOW,
    LineupPlayer,
    enrich_player_list,
    match_catalog,
    normalize_name,
    parse_af_fixture_urls,
    parse_af_match,
    parse_ff_fixture_urls,
    parse_ff_match,
)
from toolbox.matching import CanonicalPlayer, MATCH_THRESHOLD

FF_INDEX = """
<section>
  <a href="https://www.futbolfantasy.com/partidos/22505-espanyol-atletico">Espanyol</a>
  <a href="https://www.futbolfantasy.com/partidos/22505-espanyol-atletico">duplicado</a>
</section>
<aside>
  <a href="https://www.futbolfantasy.com/partidos/1-ya-jugado">resultado</a>
</aside>
"""

FF_MATCH = """
<div class="nombre">Espanyol</div>
<div class="nombre">Atlético</div>
<div class="row-local">
  <div class="jugador_3738 campo camiseta-wrapper" data-onceFF="titular">
    <a class="camiseta" data-probabilidad="80%" data-lesion="-1"
       href="https://www.futbolfantasy.com/jugadores/edu-exposito/laliga-26-27"></a>
    <div class="juggadores"><span class="truncate-name">Edu Expósito</span></div>
  </div>
</div>
<div class="row-visitante">
  <div class="jugador_99 campo camiseta-wrapper" data-onceFF="titular">
    <a class="camiseta" data-probabilidad="50%" data-lesion="-1"
       href="https://www.futbolfantasy.com/jugadores/eder-militao"></a>
    <span class="truncate-name">Éder Militão</span>
  </div>
  <div class="jugador_99 campo camiseta-wrapper" data-onceFF="suplente">
    <a data-probabilidad="20%" href="https://www.futbolfantasy.com/jugadores/eder-militao"></a>
    <span class="truncate-name">Éder Militão</span>
  </div>
</div>
<div class="alineacion_superwrapper local">
  <div class="jugador_10 campo camiseta-wrapper" data-onceFF="suplente">
    <a data-probabilidad="40%" href="https://www.futbolfantasy.com/jugadores/brais-mendez"></a>
    <span class="truncate-name">B. Méndez</span>
  </div>
</div>
"""

AF_INDEX = """
<a href="https://www.analiticafantasy.com/partido/100012018-deportivo-la-coruna-levante">Depor</a>
<a href="/partido/100012019-espanyol-atletico">otro</a>
"""

AF_MATCH = r"""
<script>
\"homeTeamId\":544,\"awayTeamId\":539,\"homeTeamName\":\"Deportivo\",\"awayTeamName\":\"Atlético\",
\"lineupBlock\":{\"home\":{\"teamId\":544,\"players\":[
  {\"playerId\":31,\"chance\":80,\"esTitular\":true,\"name\":\"J. M. Giménez\",\"positionId\":1,\"playerExtras\":null}
]},\"away\":{\"teamId\":539,\"players\":[
  {\"playerId\":7,\"chance\":40,\"esTitular\":true,\"name\":\"Álvaro Rodríguez\",\"positionId\":3,
   \"playerExtras\":{\"status\":\"doubt\",\"report\":\"Duda para el once\"}},
  {\"playerId\":8,\"chance\":0,\"esTitular\":false,\"name\":\"Lesionado X\",\"positionId\":1,
   \"playerExtras\":{\"status\":\"injured\",\"report\":\"Baja para la jornada 9\"}}
]}}
</script>
"""


class LineupParserTest(unittest.TestCase):
    def test_normalizes_names(self) -> None:
        self.assertEqual(normalize_name("Éder Militão"), "eder militao")
        self.assertEqual(MATCH_THRESHOLD, 0.85)
        self.assertEqual(DOUBT_BELOW, 0.70)

    def test_ff_index_ignores_played_matches(self) -> None:
        urls = parse_ff_fixture_urls(FF_INDEX)
        self.assertEqual(urls, ["https://www.futbolfantasy.com/partidos/22505-espanyol-atletico"])

    def test_ff_match_reads_role_probability_and_club(self) -> None:
        rows = {row.external_id: row for row in parse_ff_match(FF_MATCH)}
        self.assertEqual(rows["3738"].name, "Edu Expósito")
        self.assertEqual(rows["3738"].club, "Espanyol")
        self.assertEqual(rows["3738"].status, "titular")
        self.assertEqual(rows["3738"].start_probability, 0.8)
        self.assertEqual(rows["99"].club, "Atlético")
        self.assertEqual(rows["99"].status, "duda")
        self.assertEqual(rows["99"].start_probability, 0.5)
        self.assertEqual(rows["10"].club, "Espanyol")
        self.assertEqual(rows["10"].status, "suplente")
        self.assertEqual(rows["10"].start_probability, 0.4)

    def test_af_index_and_escaped_lineup_block(self) -> None:
        urls = parse_af_fixture_urls(AF_INDEX)
        self.assertEqual(
            urls,
            [
                "https://www.analiticafantasy.com/partido/100012018-deportivo-la-coruna-levante",
                "https://www.analiticafantasy.com/partido/100012019-espanyol-atletico",
            ],
        )
        rows = {row.external_id: row for row in parse_af_match(AF_MATCH)}
        self.assertEqual(rows["31"].club, "Deportivo")
        self.assertEqual(rows["31"].position, "DEF")
        self.assertEqual(rows["31"].status, "titular")
        self.assertEqual(rows["31"].start_probability, 0.8)
        self.assertEqual(rows["7"].club, "Atlético")
        self.assertEqual(rows["7"].status, "duda")
        self.assertEqual(rows["7"].start_probability, 0.4)
        self.assertEqual(rows["8"].status, "baja")
        self.assertEqual(rows["8"].start_probability, 0.0)

    def test_enrich_matches_initials_and_skips_unknown(self) -> None:
        sightings = parse_ff_match(FF_MATCH) + parse_af_match(AF_MATCH)
        local = [
            {
                "player_id": "m",
                "name": "E. Militão",
                "nickname": "Militão",
                "club": "Atlético",
                "position": "DEF",
            },
            {
                "player_id": "b",
                "name": "Brais Méndez",
                "nickname": "B. Méndez",
                "club": "Espanyol",
                "position": "MC",
            },
            {"player_id": "x", "name": "Alguien Distinto", "club": "Getafe", "position": "DEL"},
        ]
        enriched = {row["player_id"]: row for row in enrich_player_list(local, sightings)}
        self.assertGreaterEqual(enriched["m"]["matchingConfidence"], 0.85)
        self.assertEqual(enriched["m"]["lineupStatus"], "duda")
        self.assertEqual(enriched["m"]["p_titular"], 0.5)
        self.assertEqual(enriched["m"]["startProbability"], 0.5)
        self.assertEqual(enriched["b"]["lineupStatus"], "suplente")
        self.assertEqual(enriched["b"]["p_titular"], 0.4)
        self.assertNotIn("p_titular", enriched["x"])
        self.assertNotIn("externalSource", enriched["x"])
        self.assertEqual(local[0].get("p_titular"), None)

    def test_merge_prefers_high_titular_over_stale_baja(self) -> None:
        catalog = [
            CanonicalPlayer(
                player_id="ji",
                name="Juan Iglesias",
                nickname="Juan Iglesias",
                club="Getafe",
                position="DEF",
                fantasy_price=1_000_000,
                on_market=False,
                week_points=[],
            )
        ]
        sightings = [
            LineupPlayer(
                name="Juan Iglesias",
                source="futbolfantasy",
                club="Getafe",
                position="DEF",
                start_probability=0.01,
                status="baja",
            ),
            LineupPlayer(
                name="Juan Iglesias",
                source="analiticafantasy",
                club="Getafe",
                position="DEF",
                start_probability=0.9,
                status="titular",
            ),
        ]
        hit = match_catalog(catalog, sightings)["ji"]
        self.assertEqual(hit.status, "titular")
        self.assertEqual(hit.start_probability, 0.9)
        self.assertIsNone(hit.fitness)

    def test_long_club_name_matches_short_squad_club(self) -> None:
        from toolbox.fantasy_scraper import LineupPlayer

        sightings = [
            LineupPlayer(
                name="Leo Román",
                source="analiticafantasy",
                club="Deportivo La Coruna",
                position="POR",
                start_probability=0.9,
                status="titular",
            )
        ]
        enriched = enrich_player_list(
            [{"player_id": "1", "name": "Leo Román", "club": "Deportivo", "position": "POR"}],
            sightings,
        )
        self.assertEqual(enriched[0]["p_titular"], 0.9)
        self.assertEqual(enriched[0]["lineupStatus"], "titular")
        self.assertEqual(enriched[0]["externalSource"], "analiticafantasy")


if __name__ == "__main__":
    unittest.main()
