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
        self.assertEqual(result["bid_state"], "evidence_gaps_open")
        self.assertEqual(result["compliance_decision"]["label"], "Blocked")
        self.assertFalse(result["compliance_decision"]["can_prepare_packet"])
        self.assertTrue(result["evidence_ledger"])
        self.assertTrue(result["gate_results"])
        self.assertTrue(result["agent_tasks"])
        self.assertIn("pdf_uploaded", [action["action_type"] for action in result["agent_actions"]])

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
        self.assertEqual(updated["bid_state"], "owner_packet_ready")
        self.assertEqual(updated["compliance_decision"]["label"], "Pursue")
        self.assertTrue(updated["compliance_decision"]["can_prepare_packet"])
        self.assertFalse(updated["gate_results"])
        self.assertFalse(updated["agent_tasks"])
        self.assertIn("requirement_resolved", [action["action_type"] for action in updated["agent_actions"]])

    def test_approve_rejects_unresolved_server_analysis_even_with_fake_client_matrix(self) -> None:
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

            with self.assertRaises(ValueError) as context:
                service.approve(
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

        self.assertIn("Resolve all deterministic agent tasks", str(context.exception))

    def test_approve_records_owner_packet_action_after_ready_state(self) -> None:
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
            row = analysis["compliance_matrix"][0]
            service.resolve_requirement(
                {
                    "analysis_id": analysis["analysis_id"],
                    "requirement_id": row["requirement_id"],
                    "resolution_type": "site_visit_attended",
                }
            )

            result = service.approve(
                {
                    "approved": True,
                    "opportunity_id": "RFQ-123",
                    "analysis_id": analysis["analysis_id"],
                }
            )
            stored = service._document_analysis_sessions[analysis["analysis_id"]]

        self.assertEqual(result["packet"]["opportunity_id"], "RFQ-123")
        self.assertEqual(result["packet"]["agent_summary"]["bid_state"], "owner_packet_ready")
        self.assertEqual(result["packet"]["compliance_decision"]["label"], "Pursue")
        self.assertGreater(result["packet"]["agent_summary"]["evidence_fact_count"], 0)
        self.assertTrue(result["packet"]["agent_evidence_ledger"])
        self.assertTrue(result["packet"]["agent_action_trace"])
        self.assertIn("owner_packet_prepared", [action["action_type"] for action in stored["agent_actions"]])

    def test_no_requirement_pdf_is_not_owner_packet_ready(self) -> None:
        pdf_bytes = _pdf_bytes(["This document contains general background information only."])
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ContractRadarService(document_storage_dir=tmpdir).analyze_document(
                {
                    "filename": "background.pdf",
                    "opportunity_id": "RFQ-EMPTY",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        self.assertEqual(result["compliance_summary"]["total"], 0)
        self.assertEqual(result["bid_state"], "requirements_extracted")
        self.assertFalse(result["compliance_summary"]["ready_to_prepare"])

    def test_open_data_acquisition_creates_metadata_only_session(self) -> None:
        service = ContractRadarService()
        service._last_scan = _approval_scan("RFQ-OPEN")

        result = service.acquire_document(
            {
                "opportunity_id": "RFQ-OPEN",
                "profile_id": "road_civil_infrastructure",
            }
        )

        self.assertTrue(result["analysis_id"].startswith("analysis-"))
        self.assertEqual(result["opportunity_id"], "RFQ-OPEN")
        self.assertEqual(result["bid_state"], "metadata_intake")
        self.assertEqual(result["acquisition"]["status"], "metadata_only")
        self.assertTrue(result["acquisition"]["package_required"])
        self.assertEqual(result["gate_results"][0]["rule_id"], "official_package_required")
        self.assertEqual(result["agent_tasks"][0]["task_type"], "acquire_official_package")
        self.assertIn("open_data_metadata", {fact["source_type"] for fact in result["evidence_ledger"]})
        self.assertIn("open_data_metadata_loaded", [action["action_type"] for action in result["agent_actions"]])

    def test_approve_rejects_metadata_only_acquisition_session(self) -> None:
        service = ContractRadarService()
        service._last_scan = _approval_scan("RFQ-OPEN")
        analysis = service.acquire_document(
            {
                "opportunity_id": "RFQ-OPEN",
                "profile_id": "road_civil_infrastructure",
            }
        )

        with self.assertRaises(ValueError) as context:
            service.approve(
                {
                    "approved": True,
                    "opportunity_id": "RFQ-OPEN",
                    "analysis_id": analysis["analysis_id"],
                }
            )

        self.assertIn("Resolve all deterministic agent tasks", str(context.exception))


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
                    "source_links": {
                        "source_label": "Toronto Bids Solicitations",
                        "open_data_record_url": "https://example.test/open-data-record",
                        "toronto_bids_portal_url": "https://example.test/portal",
                        "toronto_bids_search_hint": f"Search {document_number} in TO Bids",
                    },
                },
            }
        ],
        "watchlist": [],
        "skipped": [],
        "all_evaluated": [],
    }


if __name__ == "__main__":
    unittest.main()
