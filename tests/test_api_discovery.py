"""El inventario offline no publica identificadores de mánager y clasifica la forma."""

from __future__ import annotations

import unittest

from tools.api_discovery import classify, redact_example, unwrap


class ApiDiscoveryTests(unittest.TestCase):
    def test_redacts_manager_identity_and_keeps_public_player_fields(self) -> None:
        self.assertEqual(redact_example(("manager", "managerName"), "alguien"), "[redactado]")
        self.assertEqual(redact_example(("user1Id",), 2481395), "[redactado]")
        self.assertEqual(redact_example(("playerMaster", "marketValue"), 567959), 567959)
        self.assertEqual(redact_example(("playerMaster", "name"), "Laporte"), "Laporte")

    def test_classifies_the_shapes_we_already_store(self) -> None:
        self.assertEqual(
            classify({"players": [], "teamMoney": None, "teamValue": 1, "loanedPlayers": []}),
            "team",
        )
        self.assertEqual(classify([{"activityTypeId": 31, "amount": 10}]), "activity")
        self.assertEqual(classify([{"id": "1", "salePrice": 10, "expirationDate": "2026-11-01T14:08:00+01:00"}]), "market")
        self.assertEqual(classify({"formation": {"goalkeeper": []}}), "lineup")
        self.assertEqual(classify([{"id": "68", "teamId": "3", "weekPoints": [], "marketValue": "1"}]), "catalog")

    def test_unwraps_cache_envelope_without_keeping_the_query(self) -> None:
        payload, source = unwrap(
            {
                "kind": "json",
                "source_url": "https://fantasy-api.llt-services.com/api/v1/competition/1/players?x-lang=es",
                "body": '{"players":[]}',
            }
        )
        self.assertEqual(payload, {"players": []})
        self.assertEqual(source, "https://fantasy-api.llt-services.com/api/v1/competition/1/players")


if __name__ == "__main__":
    unittest.main()
