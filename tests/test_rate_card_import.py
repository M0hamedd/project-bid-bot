from __future__ import annotations

import unittest

from contract_radar.rate_card_import import import_rate_card


class RateCardImportTests(unittest.TestCase):
    def test_imports_csv_rate_card_rows(self) -> None:
        csv_text = """label,keywords,units,unit_direct_cost,confidence,rate_id
Asphalt paving,"asphalt,paving",m2,$72.50,moderate,custom-asphalt-m2
Curb repair,"curb;gutter",linear m,210,high,
"""

        result = import_rate_card(csv_text, profile_id="road_civil_infrastructure", created_at="2026-06-04T12:00:00Z")

        self.assertEqual(result["source"], "deterministic_rate_card_import")
        self.assertEqual(result["imported_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["rate_card"][0]["rate_id"], "custom-asphalt-m2")
        self.assertEqual(result["rate_card"][0]["keywords"], ["asphalt", "paving"])
        self.assertEqual(result["rate_card"][0]["units"], ["m2"])
        self.assertEqual(result["rate_card"][0]["unit_direct_cost"], 72.5)
        self.assertEqual(result["rate_card"][0]["confidence"], "Moderate")
        self.assertEqual(result["rate_card"][0]["profile_id"], "road_civil_infrastructure")
        self.assertEqual(result["rate_card"][0]["source"], "deterministic_rate_card_import")
        self.assertEqual(result["rate_card"][0]["created_at"], "2026-06-04T12:00:00Z")
        self.assertEqual(result["rate_card"][1]["keywords"], ["curb", "gutter"])

    def test_imports_list_rows_and_aliases(self) -> None:
        rows = [
            {
                "name": "Sod repair",
                "terms": ["Sod", "Turf"],
                "unit": "M2",
                "cost": "18",
                "confidence": "low",
            },
            {
                "item": "Tree planting",
                "keywords": "tree; planting",
                "units": ["Each"],
                "direct_cost": "$650",
            },
        ]

        result = import_rate_card(rows, profile_id="parks_landscape")

        self.assertEqual(result["imported_count"], 2)
        self.assertEqual(result["rate_card"][0]["label"], "Sod repair")
        self.assertEqual(result["rate_card"][0]["keywords"], ["sod", "turf"])
        self.assertEqual(result["rate_card"][0]["units"], ["m2"])
        self.assertEqual(result["rate_card"][0]["unit_direct_cost"], 18.0)
        self.assertEqual(result["rate_card"][0]["confidence"], "Low")
        self.assertEqual(result["rate_card"][1]["label"], "Tree planting")
        self.assertEqual(result["rate_card"][1]["unit_direct_cost"], 650.0)
        self.assertEqual(result["rate_card"][1]["confidence"], "High")

    def test_generates_deterministic_ids_when_missing(self) -> None:
        rows = [{"label": "Sidewalk panel", "keywords": "sidewalk", "units": "m2", "unit_direct_cost": "155"}]

        first = import_rate_card(rows, profile_id="road_civil_infrastructure")
        second = import_rate_card(rows, profile_id="road_civil_infrastructure")
        different_profile = import_rate_card(rows, profile_id="parks_landscape")

        self.assertEqual(first["rate_card"][0]["rate_id"], second["rate_card"][0]["rate_id"])
        self.assertNotEqual(first["rate_card"][0]["rate_id"], different_profile["rate_card"][0]["rate_id"])
        self.assertTrue(first["rate_card"][0]["rate_id"].startswith("rate-card-"))

    def test_skips_bad_rows_with_row_numbers_and_reasons(self) -> None:
        csv_text = """label,unit,cost
Valid item,each,25
,m2,12
Bad cost,m2,0
Missing cost,m2,
"""

        result = import_rate_card(csv_text)

        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["skipped_count"], 3)
        self.assertEqual(result["rate_card"][0]["label"], "Valid item")
        self.assertEqual(
            result["errors"],
            [
                {"row": 3, "reason": "missing label"},
                {"row": 4, "reason": "unit_direct_cost must be positive"},
                {"row": 5, "reason": "unit_direct_cost must be positive"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
