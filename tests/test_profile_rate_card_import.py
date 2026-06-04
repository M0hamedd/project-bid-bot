from __future__ import annotations

import tempfile
import unittest

from contract_radar.service import ContractRadarService


class ProfileRateCardImportServiceTests(unittest.TestCase):
    def test_import_rate_card_persists_saved_business_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            result = service.import_profile_rate_card(
                {
                    "profile_id": "road_civil_infrastructure",
                    "rate_card_csv": "label,unit,cost\nCustom asphalt,m2,44\n",
                    "replace": True,
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)
            profile = next(
                item
                for item in reloaded.health()["supported_profiles"]
                if item["profile_id"] == "road_civil_infrastructure"
            )

        self.assertEqual(result["rate_card_import"]["imported_count"], 1)
        self.assertEqual(result["business_profile"]["pricing_rate_card"][0]["label"], "Custom asphalt")
        self.assertEqual(profile["pricing_rate_card"][0]["unit_direct_cost"], 44.0)
        self.assertTrue(profile["locally_saved"])

    def test_import_rate_card_merges_by_rate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service.save_profile(
                {
                    "profile_id": "road_civil_infrastructure",
                    "business_profile": {
                        "profile_id": "road_civil_infrastructure",
                        "pricing_rate_card": [
                            {
                                "rate_id": "company_asphalt",
                                "label": "Old asphalt",
                                "keywords": ["asphalt"],
                                "units": ["m2"],
                                "unit_direct_cost": 40,
                            }
                        ],
                    },
                }
            )

            result = service.import_profile_rate_card(
                {
                    "profile_id": "road_civil_infrastructure",
                    "rate_card": [
                        {
                            "rate_id": "company_asphalt",
                            "label": "Updated asphalt",
                            "unit": "m2",
                            "cost": 45,
                        },
                        {
                            "label": "Curb repair",
                            "unit": "linear m",
                            "cost": 210,
                        },
                    ],
                }
            )

        by_id = {
            item["rate_id"]: item
            for item in result["business_profile"]["pricing_rate_card"]
        }
        self.assertEqual(by_id["company_asphalt"]["label"], "Updated asphalt")
        self.assertEqual(by_id["company_asphalt"]["unit_direct_cost"], 45.0)
        self.assertEqual(result["rate_card_import"]["imported_count"], 2)
        self.assertGreaterEqual(len(result["business_profile"]["pricing_rate_card"]), 2)

    def test_import_rate_card_rejects_missing_source(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "Rate-card"):
            service.import_profile_rate_card({"profile_id": "road_civil_infrastructure"})


if __name__ == "__main__":
    unittest.main()
