from __future__ import annotations

import unittest

from contract_radar.profiles import SUPPORTED_PROFILE_IDS, profile_from_payload, supported_profiles
from contract_radar.service import ContractRadarService


class SupportedProfileTests(unittest.TestCase):
    def test_supported_profiles_are_exposed_in_health(self) -> None:
        service = ContractRadarService()

        health = service.health()

        self.assertEqual(
            [profile["profile_id"] for profile in health["supported_profiles"]],
            list(SUPPORTED_PROFILE_IDS),
        )

    def test_profile_from_payload_selects_requested_supported_profile(self) -> None:
        profile = profile_from_payload({"profile_id": "parks_landscape"})

        self.assertEqual(profile.profile_id, "parks_landscape")
        self.assertEqual(profile.name, "Greenline Parks & Landscape Ltd.")
        self.assertIn("topsoil supply", profile.skills)
        self.assertIn("ISA certified arborists", profile.certifications)
        self.assertIn("watering trailers", profile.owned_equipment)
        self.assertEqual(profile.ytd_solicitation_hits, 42)

    def test_supported_profiles_cover_three_distinct_vendor_types(self) -> None:
        profiles = supported_profiles()
        business_types = {profile["business_type"] for profile in profiles}

        self.assertEqual(len(profiles), 3)
        self.assertEqual(len(business_types), 3)
        self.assertEqual(profiles[0]["profile_id"], "road_civil_infrastructure")
        self.assertTrue(any("road" in item for item in business_types))
        self.assertTrue(any("landscaping" in item for item in business_types))
        self.assertTrue(any("engineering" in item for item in business_types))
        self.assertTrue(all("lane_basis" in profile for profile in profiles))
        self.assertTrue(all("exclusive_best_fit_hits" in profile for profile in profiles))
        self.assertTrue(all(profile.get("years_in_business", 0) > 0 for profile in profiles))
        self.assertTrue(all(profile.get("crew_mix") for profile in profiles))
        self.assertTrue(all(profile.get("recent_municipal_work") for profile in profiles))
        self.assertTrue(all(profile.get("bid_constraints") for profile in profiles))
        self.assertTrue(all(profile.get("pricing_rate_card") for profile in profiles))
        self.assertTrue(all(profile.get("pricing_policy") for profile in profiles))

    def test_profile_from_payload_keeps_company_pricing_facts(self) -> None:
        profile = profile_from_payload(
            {
                "profile_id": "road_civil_infrastructure",
                "business_profile": {
                    "profile_id": "road_civil_infrastructure",
                    "name": "Custom Civil",
                    "pricing_rate_card": [
                        {
                            "rate_id": "company_asphalt_m2",
                            "keywords": ["asphalt"],
                            "units": ["m2"],
                            "unit_direct_cost": 44,
                        }
                    ],
                    "pricing_policy": {"overhead_rate": 0.08, "margin_rate": 0.13},
                },
            }
        )

        self.assertEqual(profile.name, "Custom Civil")
        self.assertEqual(profile.pricing_rate_card[0]["rate_id"], "company_asphalt_m2")
        self.assertEqual(profile.pricing_policy["overhead_rate"], 0.08)


if __name__ == "__main__":
    unittest.main()
