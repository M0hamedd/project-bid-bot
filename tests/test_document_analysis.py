from __future__ import annotations

import base64
import tempfile
import unittest

import fitz

from contract_radar.service import ContractRadarService


class DocumentAnalysisTests(unittest.TestCase):
    def test_service_analyzes_uploaded_pdf_into_compliance_matrix(self) -> None:
        pdf_bytes = _pdf_bytes(
            [
                "Bidders must provide proof of commercial general liability insurance.",
                "A mandatory site meeting must be attended by all bidders.",
                "Bidders shall submit the completed pricing form with unit prices.",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ContractRadarService(document_storage_dir=tmpdir).analyze_document(
                {
                    "filename": "sidewalk-rfq.pdf",
                    "opportunity_id": "RFQ-123",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        self.assertEqual(result["document"]["filename"], "sidewalk-rfq.pdf")
        self.assertEqual(result["document"]["opportunity_id"], "RFQ-123")
        self.assertTrue(result["analysis_id"].startswith("analysis-"))
        self.assertEqual(result["text"]["page_count"], 3)
        self.assertGreaterEqual(result["compliance_summary"]["total"], 3)
        self.assertGreaterEqual(result["compliance_summary"]["evidence_needed"], 2)
        self.assertGreaterEqual(result["compliance_summary"]["business_has_capability"], 1)
        self.assertFalse(result["compliance_summary"]["ready_to_prepare"])
        self.assertTrue(result["compliance_matrix"][0]["citation"]["source"])
        self.assertTrue(result["compliance_matrix"][0]["citation"]["page"])
        self.assertNotIn("status", result["compliance_matrix"][0])

    def test_service_rejects_invalid_base64_upload(self) -> None:
        with self.assertRaises(ValueError) as context:
            ContractRadarService().analyze_document(
                {
                    "filename": "broken.pdf",
                    "opportunity_id": "RFQ-123",
                    "content_base64": "not base64!!!",
                }
            )

        self.assertIn("base64", str(context.exception))

    def test_service_resolves_requirements_inside_server_session(self) -> None:
        pdf_bytes = _pdf_bytes(
            [
                "A mandatory site meeting must be attended by all bidders.",
                "Bidders shall submit the completed pricing form with unit prices.",
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(document_storage_dir=tmpdir)
            result = service.analyze_document(
                {
                    "filename": "sidewalk-rfq.pdf",
                    "opportunity_id": "RFQ-123",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )
            by_category = {row["category"]: row for row in result["compliance_matrix"]}

            updated = service.resolve_requirement(
                {
                    "analysis_id": result["analysis_id"],
                    "requirement_id": by_category["site_visit"]["requirement_id"],
                    "resolution_type": "site_visit_attended",
                }
            )
            updated = service.resolve_requirement(
                {
                    "analysis_id": result["analysis_id"],
                    "requirement_id": by_category["pricing_sheet"]["requirement_id"],
                    "resolution_type": "pricing_form_assigned",
                }
            )

        self.assertEqual(updated["compliance_summary"]["resolved"], 2)
        self.assertTrue(updated["compliance_summary"]["ready_to_prepare"])

    def test_approve_uses_server_analysis_not_client_matrix(self) -> None:
        pdf_bytes = _pdf_bytes(["A mandatory site meeting must be attended by all bidders."])
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(document_storage_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-123")
            analysis = service.analyze_document(
                {
                    "filename": "sidewalk-rfq.pdf",
                    "opportunity_id": "RFQ-123",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

            result = service.approve(
                {
                    "approved": True,
                    "opportunity_id": "RFQ-123",
                    "analysis_id": analysis["analysis_id"],
                    "compliance_matrix": [
                        {
                            "requirement_id": "fake",
                            "requirement": "fake resolved row",
                            "resolved": True,
                        }
                    ],
                }
            )

        self.assertEqual(result["packet"]["compliance_summary"]["unresolved"], 1)
        self.assertNotEqual(result["packet"]["compliance_matrix"][0]["requirement_id"], "fake")


def _pdf_bytes(pages: list[str]) -> bytes:
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page(width=420, height=160)
            page.insert_text((36, 48), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def _approval_scan(document_number: str) -> dict:
    return {
        "business_profile": {
            "profile_id": "road_civil_infrastructure",
            "name": "Harbourfront Civil Works Ltd.",
        },
        "top_opportunities": [
            {
                "label": "Pursue",
                "matched_terms": ["road repairs"],
                "missing_requirements": [],
                "solicitation": {
                    "document_number": document_number,
                    "description": "Road and sidewalk repair",
                    "submission_deadline": "2026-06-18",
                },
            }
        ],
        "watchlist": [],
        "skipped": [],
        "all_evaluated": [],
    }


if __name__ == "__main__":
    unittest.main()
