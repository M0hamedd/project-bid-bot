from __future__ import annotations

import unittest

from contract_radar.pricing_extraction import extract_pricing_structure, merge_pricing_extraction


class PricingExtractionTests(unittest.TestCase):
    def test_extracts_cited_pricing_line_items_from_schedule(self) -> None:
        result = extract_pricing_structure(
            [
                {
                    "source": "road-rfq.pdf",
                    "page_number": 7,
                    "chunk_id": "p7",
                    "text": (
                        "Schedule of Prices\n"
                        "Item 1 Asphalt milling 1,200 m2 Unit Price ____ Total ____\n"
                        "Item 2 Concrete curb replacement 350 linear m Unit Price ____ Total ____\n"
                    ),
                }
            ]
        )

        self.assertTrue(result["pricing_form_detected"])
        self.assertFalse(result["required_pricing_inputs"])
        self.assertEqual(len(result["pricing_line_items"]), 2)
        self.assertEqual(result["pricing_line_items"][0]["quantity"], 1200)
        self.assertEqual(result["pricing_line_items"][0]["unit"], "m2")
        self.assertEqual(result["pricing_line_items"][0]["citation"]["source"], "road-rfq.pdf")
        self.assertEqual(result["quantity_summary"]["units"]["m2"], 1200)

    def test_pricing_form_without_quantities_requires_quantity_input(self) -> None:
        result = extract_pricing_structure(
            [
                {
                    "source": "parks-rfq.pdf",
                    "page": 4,
                    "chunk_id": "p4",
                    "text": "Bidders shall submit the pricing form with unit prices for all work items.",
                }
            ]
        )

        self.assertTrue(result["pricing_form_detected"])
        self.assertEqual(result["required_pricing_inputs"], ["quantity"])
        self.assertFalse(result["quantity_summary"]["has_quantities"])

    def test_merge_pricing_extraction_preserves_existing_required_inputs(self) -> None:
        merged = merge_pricing_extraction(
            {"required_pricing_inputs": ["direct_cost"]},
            {
                "pricing_form_detected": True,
                "pricing_form_citations": [],
                "pricing_line_items": [],
                "required_pricing_inputs": ["quantity"],
                "quantity_summary": {"line_item_count": 0, "units": {}, "has_quantities": False},
                "summary": "Pricing form language was detected.",
            },
        )

        self.assertEqual(merged["required_pricing_inputs"], ["direct_cost", "quantity"])
        self.assertTrue(merged["pricing_form_detected"])
        self.assertIn("pricing_extraction", merged)


if __name__ == "__main__":
    unittest.main()
