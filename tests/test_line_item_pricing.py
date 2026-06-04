from __future__ import annotations

import unittest

from contract_radar.line_item_pricing import build_line_item_cost_rollup


class LineItemPricingTests(unittest.TestCase):
    def test_builds_profile_rate_card_rollup_for_civil_quantities(self) -> None:
        rollup = build_line_item_cost_rollup(
            [
                {
                    "line_item_id": "line-asphalt",
                    "description": "Asphalt milling",
                    "quantity": 1200,
                    "unit": "m2",
                    "citation": {"source": "road-rfq.pdf", "page": 7, "snippet": "Asphalt milling 1,200 m2"},
                },
                {
                    "line_item_id": "line-curb",
                    "description": "Concrete curb replacement",
                    "quantity": 350,
                    "unit": "linear m",
                    "citation": {"source": "road-rfq.pdf", "page": 7, "snippet": "Concrete curb 350 linear m"},
                },
            ],
            {
                "business_profile": {
                    "profile_id": "road_civil_infrastructure",
                    "business_type": "civil infrastructure contractor",
                },
                "solicitation": {"description": "Road repairs with traffic staging"},
            },
        )

        self.assertEqual(rollup["source"], "deterministic_profile_rate_card")
        self.assertEqual(rollup["coverage"], 1)
        self.assertEqual(rollup["priced_line_item_count"], 2)
        self.assertGreater(rollup["direct_cost"], 0)
        self.assertGreater(rollup["target_bid"], rollup["estimated_cost"])
        self.assertEqual(rollup["priced_line_items"][0]["rate_source"], "civil_milling_m2")
        self.assertEqual(rollup["priced_line_items"][1]["rate_source"], "civil_curb_linear_m")

    def test_unmatched_units_reduce_rollup_coverage(self) -> None:
        rollup = build_line_item_cost_rollup(
            [
                {
                    "line_item_id": "line-unknown",
                    "description": "Special allowance",
                    "quantity": 1,
                    "unit": "allowance",
                }
            ],
            {"business_profile": {"profile_id": "road_civil_infrastructure"}},
        )

        self.assertEqual(rollup["coverage"], 0)
        self.assertEqual(rollup["unpriced_line_item_count"], 1)
        self.assertEqual(rollup["confidence"], "Low")
        self.assertTrue(rollup["risks"])

    def test_business_profile_rate_card_overrides_supported_profile_default(self) -> None:
        rollup = build_line_item_cost_rollup(
            [
                {
                    "line_item_id": "line-asphalt",
                    "description": "Asphalt paving",
                    "quantity": 1000,
                    "unit": "m2",
                    "citation": {"source": "road-rfq.pdf", "page": 8, "snippet": "Asphalt paving 1,000 m2"},
                }
            ],
            {
                "business_profile": {
                    "profile_id": "road_civil_infrastructure",
                    "business_type": "civil infrastructure contractor",
                    "pricing_rate_card": [
                        {
                            "rate_id": "company_asphalt_m2",
                            "label": "Company asphalt paving",
                            "keywords": ["asphalt", "paving"],
                            "units": ["m2"],
                            "unit_direct_cost": 42,
                            "confidence": "High",
                        }
                    ],
                    "pricing_policy": {
                        "contingency_rate": 0.1,
                        "overhead_rate": 0.09,
                        "margin_rate": 0.11,
                    },
                },
                "solicitation": {"description": "Asphalt resurfacing"},
            },
        )

        item = rollup["priced_line_items"][0]
        self.assertEqual(item["unit_direct_cost"], 42)
        self.assertEqual(item["rate_source"], "profile_rate_card:company_asphalt_m2")
        self.assertEqual(item["rate_source_type"], "business_profile")
        self.assertEqual(rollup["rate_card_source"], "business_profile")
        self.assertEqual(rollup["business_rate_count"], 1)
        self.assertEqual(rollup["rates"]["overhead_rate"], 0.09)
        self.assertEqual(rollup["rates"]["margin_rate"], 0.11)
        self.assertTrue(any(rate["source_type"] == "business_profile" for rate in rollup["rate_card_facts"]))

    def test_business_profile_rate_card_falls_back_with_risk_when_partial(self) -> None:
        rollup = build_line_item_cost_rollup(
            [
                {
                    "line_item_id": "line-asphalt",
                    "description": "Asphalt paving",
                    "quantity": 100,
                    "unit": "m2",
                },
                {
                    "line_item_id": "line-curb",
                    "description": "Concrete curb",
                    "quantity": 25,
                    "unit": "linear m",
                },
            ],
            {
                "business_profile": {
                    "profile_id": "road_civil_infrastructure",
                    "pricing_rate_card": [
                        {
                            "rate_id": "company_asphalt_m2",
                            "keywords": ["asphalt"],
                            "units": ["m2"],
                            "unit_direct_cost": 42,
                        }
                    ],
                }
            },
        )

        self.assertEqual(rollup["rate_card_source"], "business_profile_with_fallbacks")
        self.assertTrue(any("fallback" in risk.lower() for risk in rollup["risks"]))


if __name__ == "__main__":
    unittest.main()
