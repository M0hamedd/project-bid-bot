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


if __name__ == "__main__":
    unittest.main()
