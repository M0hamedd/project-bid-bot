from __future__ import annotations

import unittest

from contract_radar.compliance import (
    extract_requirements,
    requirements_to_dicts,
)
from contract_radar.models import BusinessProfile


class ComplianceExtractionTests(unittest.TestCase):
    def test_extracts_cited_compliance_rows_with_stable_statuses(self) -> None:
        profile = BusinessProfile()
        chunks = [
            {
                "text": (
                    "Bidders must provide proof of commercial general liability insurance. "
                    "A mandatory site meeting must be attended by all bidders. "
                    "Bidders shall submit the completed price schedule with unit prices."
                ),
                "source": "municipal-sidewalk.pdf",
                "page_number": 2,
                "chunk_id": "p2",
            },
            {
                "text": "The contractor shall provide professional engineering design services for stamped drawings.",
                "source": "municipal-sidewalk.pdf",
                "page_number": 5,
                "chunk_id": "p5",
            },
        ]

        rows = extract_requirements(chunks, contractor_profile=profile)
        payload = requirements_to_dicts(rows)

        self.assertGreaterEqual(len(rows), 4)
        self.assertTrue(all(row.citation.source == "municipal-sidewalk.pdf" for row in rows))
        self.assertTrue(all(row.citation.page for row in rows))
        self.assertTrue(all(row.citation.snippet for row in rows))

        by_category = {row.category: row for row in rows}
        self.assertEqual(by_category["insurance"].status, "ready")
        self.assertIn("insurance", " ".join(by_category["insurance"].matched_evidence).lower())
        self.assertEqual(by_category["site_visit"].status, "blocker")
        self.assertEqual(by_category["pricing_sheet"].status, "missing")
        self.assertEqual(by_category["scope"].status, "blocker")
        self.assertIn("professional engineering design", " ".join(by_category["scope"].matched_evidence).lower())
        self.assertEqual(payload[0]["citation"]["source"], "municipal-sidewalk.pdf")

    def test_no_profile_context_marks_requirements_for_review(self) -> None:
        rows = extract_requirements(
            [
                {
                    "text": "The successful bidder must provide a bid bond and proof of insurance.",
                    "source": "snow-removal.pdf",
                    "page": 1,
                }
            ]
        )

        self.assertTrue(rows)
        self.assertTrue(all(row.status == "needs_review" for row in rows))

    def test_document_inventory_can_satisfy_required_forms(self) -> None:
        rows = extract_requirements(
            [
                {
                    "text": "Bidders shall submit the addendum acknowledgement form with the proposal.",
                    "source": "parks-maintenance.pdf",
                    "page": 3,
                }
            ],
            document_inventory=["signed addendum acknowledgement"],
        )

        self.assertEqual(rows[0].category, "addendum")
        self.assertEqual(rows[0].status, "ready")


if __name__ == "__main__":
    unittest.main()
