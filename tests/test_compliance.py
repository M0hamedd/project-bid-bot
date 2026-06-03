from __future__ import annotations

import unittest

from contract_radar.compliance import (
    apply_requirement_resolution,
    extract_requirements,
    requirements_to_dicts,
)
from contract_radar.models import BusinessProfile


class ComplianceExtractionTests(unittest.TestCase):
    def test_extracts_cited_compliance_rows_with_evidence_model(self) -> None:
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
        self.assertTrue(by_category["insurance"].requirement_detected)
        self.assertTrue(by_category["insurance"].business_has_capability)
        self.assertIn("insurance certificate", by_category["insurance"].evidence_needed)
        self.assertFalse(by_category["insurance"].resolved)
        self.assertIn("insurance", " ".join(by_category["insurance"].matched_capabilities).lower())
        self.assertIn("site visit attendance", by_category["site_visit"].evidence_needed)
        self.assertFalse(by_category["site_visit"].resolved)
        self.assertIn("pricing form assigned", by_category["pricing_sheet"].evidence_needed)
        self.assertFalse(by_category["pricing_sheet"].resolved)
        self.assertFalse(by_category["scope"].business_has_capability)
        self.assertFalse(by_category["scope"].resolved)
        self.assertIn("professional engineering design", " ".join(by_category["scope"].matched_capabilities).lower())
        self.assertEqual(payload[0]["citation"]["source"], "municipal-sidewalk.pdf")
        self.assertNotIn("status", payload[0])

    def test_no_profile_context_keeps_detected_requirements_unresolved(self) -> None:
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
        self.assertTrue(all(row.requirement_detected for row in rows))
        self.assertTrue(all(row.business_has_capability is None for row in rows))
        self.assertTrue(all(not row.resolved for row in rows))

    def test_document_inventory_can_resolve_required_forms(self) -> None:
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
        self.assertTrue(rows[0].uploaded_evidence)
        self.assertTrue(rows[0].resolved)

    def test_resolution_action_marks_requirement_resolved(self) -> None:
        rows = requirements_to_dicts(
            extract_requirements(
                [
                    {
                        "text": "A mandatory site meeting must be attended by all bidders.",
                        "source": "parks-maintenance.pdf",
                        "page": 1,
                    }
                ],
                contractor_profile=BusinessProfile(),
            )
        )

        updated = apply_requirement_resolution(
            rows,
            rows[0]["requirement_id"],
            "site_visit_attended",
            resolved_at="2026-06-02T12:00:00Z",
        )

        self.assertTrue(updated[0]["resolved"])
        self.assertEqual(updated[0]["evidence_needed"], [])
        self.assertEqual(updated[0]["uploaded_evidence"][0]["type"], "site_visit_attended")


if __name__ == "__main__":
    unittest.main()
