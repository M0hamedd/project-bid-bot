from __future__ import annotations

import tempfile
import unittest

from contract_radar.company_intake import build_company_intake_profile
from contract_radar.service import ContractRadarService


class CompanyIntakeTests(unittest.TestCase):
    def test_company_intake_normalizes_profile_without_demo_evidence(self) -> None:
        profile = build_company_intake_profile(
            {
                "company": {
                    "name": "Northline Grounds",
                    "services": ["park landscaping", "sod repair", "tree planting"],
                    "documents_on_hand": ["WSIB clearance", "insurance certificate"],
                    "equipment": ["watering trailer", "skid steer"],
                    "rate_card": [
                        {
                            "label": "Sod repair",
                            "keywords": ["sod", "turf"],
                            "unit": "m2",
                            "rate": "18",
                        }
                    ],
                    "pricing_policy": {"overhead_rate": "12", "margin_rate": 0.15},
                }
            },
            now="2026-06-04T12:00:00Z",
        )

        self.assertEqual(profile["profile_id"], "parks_landscape")
        self.assertEqual(profile["profile_source"], "company_intake")
        self.assertEqual(profile["name"], "Northline Grounds")
        self.assertEqual(profile["ready_documents"], ["WSIB clearance", "insurance certificate"])
        self.assertNotIn("playground installer references", profile["ready_documents"])
        self.assertEqual(profile["pricing_rate_card"][0]["label"], "Sod repair")
        self.assertEqual(profile["pricing_policy"]["overhead_rate"], 0.12)
        self.assertIn("max_contract_value", profile["missing_profile_facts"])
        self.assertGreater(profile["profile_completeness"], 0)

    def test_company_intake_service_persists_profile_and_evidence_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            result = service.intake_company(
                {
                    "profile_id": "road_civil_infrastructure",
                    "company": {
                        "name": "Custom Road Co",
                        "services": ["asphalt paving", "curb repair"],
                        "documents_on_hand": ["WSIB clearance"],
                        "insurance": "$5M CGL",
                        "bonding_limit": 500000,
                        "equipment": ["roller"],
                        "past_projects": ["municipal curb repair"],
                    },
                }
            )

            reloaded = ContractRadarService(local_state_dir=tmpdir)
            health_profile = next(
                profile
                for profile in reloaded.health()["supported_profiles"]
                if profile["profile_id"] == "road_civil_infrastructure"
            )

        evidence_types = {record["evidence_type"] for record in result["evidence_vault"]["records"]}
        self.assertEqual(result["business_profile"]["name"], "Custom Road Co")
        self.assertIn("insurance_certificate", evidence_types)
        self.assertIn("bonding_capacity", evidence_types)
        self.assertIn("safety_document", evidence_types)
        self.assertEqual(health_profile["name"], "Custom Road Co")
        self.assertTrue(health_profile["locally_saved"])


if __name__ == "__main__":
    unittest.main()
