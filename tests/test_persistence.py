from __future__ import annotations

import tempfile
import unittest

from contract_radar.service import ContractRadarService


class LocalPersistenceTests(unittest.TestCase):
    def test_scan_auto_starts_metadata_intake_for_top_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            scan = _approval_scan("RFQ-AUTO")

            service._auto_start_intake_sessions(scan, scan["business_profile"])
            hydrated = service._scan_with_runtime_state(scan)

            self.assertIn("RFQ-AUTO", hydrated["document_analyses"])
            self.assertEqual(hydrated["document_analyses"]["RFQ-AUTO"]["bid_state"], "metadata_intake")
            self.assertEqual(hydrated["daily_inbox"]["items"][0]["status"], "get_package")
            self.assertEqual(hydrated["auto_started_intake"][0]["opportunity_id"], "RFQ-AUTO")

    def test_acquisition_session_survives_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-OPEN")

            analysis = service.acquire_document(
                {
                    "opportunity_id": "RFQ-OPEN",
                    "profile_id": "road_civil_infrastructure",
                }
            )

            reloaded = ContractRadarService(local_state_dir=tmpdir)
            self.assertEqual(
                reloaded._latest_document_analysis_by_opportunity["RFQ-OPEN"],
                analysis["analysis_id"],
            )
            self.assertEqual(
                reloaded._document_analysis_sessions[analysis["analysis_id"]]["bid_state"],
                "metadata_intake",
            )
            self.assertIn("document_analyses", reloaded._last_scan)
            self.assertEqual(
                reloaded._last_scan["document_analyses"]["RFQ-OPEN"]["analysis_id"],
                analysis["analysis_id"],
            )
            self.assertEqual(
                reloaded._last_scan["daily_inbox"]["items"][0]["acquisition_status"],
                "portal_login_required",
            )

    def test_approval_packet_survives_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-READY")
            _attach_ready_analysis(service, "RFQ-READY")

            result = service.approve(
                {
                    "approved": True,
                    "opportunity_id": "RFQ-READY",
                }
            )

            reloaded = ContractRadarService(local_state_dir=tmpdir)
            packets = list(reloaded._approval_packets.values())
            self.assertEqual(result["packet"]["opportunity_id"], "RFQ-READY")
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0]["packet"]["opportunity_id"], "RFQ-READY")
            self.assertIn("owner_packet_prepared", [
                action["action_type"]
                for action in reloaded._document_analysis_sessions["analysis-ready-rfq-ready"]["agent_actions"]
            ])


def _approval_scan(document_number: str) -> dict:
    return {
        "business_profile": {
            "profile_id": "road_civil_infrastructure",
            "name": "Harbourfront Civil Works Ltd.",
        },
        "as_of": "2026-06-03",
        "priority_mode": "best_win_chance",
        "top_opportunities": [_approval_opportunity(document_number)],
        "watchlist": [],
        "skipped": [],
        "all_evaluated": [_approval_opportunity(document_number)],
    }


def _approval_opportunity(document_number: str) -> dict:
    return {
        "label": "Pursue",
        "matched_terms": ["road repairs"],
        "missing_requirements": [],
        "solicitation": {
            "document_number": document_number,
            "description": "Road and sidewalk repair",
            "submission_deadline": "2026-06-18",
            "buyer_name": "City Buyer",
            "buyer_email": "buyer@toronto.ca",
            "buyer_phone": "416-555-0100",
            "division": "Transportation Services",
            "source_links": {
                "source_label": "Toronto Bids Solicitations",
                "open_data_record_url": "https://example.test/open-data-record",
                "toronto_bids_portal_url": "https://example.test/portal",
                "toronto_bids_search_hint": f"Search {document_number} in TO Bids",
            },
        },
    }


def _attach_ready_analysis(service: ContractRadarService, document_number: str) -> None:
    analysis_id = f"analysis-ready-{document_number.lower()}"
    session = {
        "analysis_id": analysis_id,
        "opportunity_id": document_number,
        "document": {"filename": "rfq.pdf", "content_hash": analysis_id},
        "text": {
            "page_count": 1,
            "character_count": 80,
            "chunks": [{"chunk_id": "1", "text": "Bidders must provide proof of insurance."}],
        },
        "compliance_matrix": [
            {
                "requirement_id": f"REQ-{document_number}",
                "requirement": "Bidders must provide proof of insurance.",
                "category": "insurance",
                "requirement_detected": True,
                "evidence_needed": [],
                "business_has_capability": True,
                "uploaded_evidence": [
                    {
                        "type": "certificate_available",
                        "label": "Certificate available",
                        "note": "",
                        "resolved_at": "2026-06-02T12:00:00Z",
                    }
                ],
                "matched_capabilities": ["Commercial general liability insurance"],
                "resolved": True,
                "citation": {
                    "source": "rfq.pdf",
                    "page": 1,
                    "chunk_id": "1",
                    "snippet": "Bidders must provide proof of insurance.",
                },
            }
        ],
        "compliance_summary": {
            "total": 1,
            "resolved": 1,
            "unresolved": 0,
            "ready_to_prepare": True,
        },
        "created_at": "2026-06-02T12:00:00Z",
        "bid_state": "owner_packet_ready",
        "gate_results": [],
        "agent_tasks": [],
        "evidence_ledger": [],
        "agent_actions": [],
    }
    service._document_analysis_sessions[analysis_id] = session
    service._latest_document_analysis_by_opportunity[document_number] = analysis_id


if __name__ == "__main__":
    unittest.main()
