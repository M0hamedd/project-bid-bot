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

    def test_daily_runner_task_state_survives_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            scan = service._scan_with_runtime_state(_approval_scan("RFQ-DAILY"))
            service._persist_scan_result(scan)

            reloaded = ContractRadarService(local_state_dir=tmpdir)

        self.assertTrue(scan["daily_run"]["run_id"])
        self.assertTrue(scan["agent_task_state"])
        self.assertTrue(scan["opportunity_snapshots"])
        self.assertTrue(reloaded._daily_runs)
        self.assertTrue(reloaded._agent_task_state)
        self.assertTrue(reloaded._opportunity_snapshots)
        self.assertEqual(
            next(iter(reloaded._agent_task_state.values()))["task_state"],
            "waiting_on_package",
        )

    def test_addendum_change_marks_ready_analysis_stale_and_blocks_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            _attach_ready_analysis(service, "RFQ-STALE")
            first = service._scan_with_runtime_state(_approval_scan("RFQ-STALE"))
            service._opportunity_snapshots = first["opportunity_snapshots"]

            changed_scan = _approval_scan("RFQ-STALE")
            changed_scan["top_opportunities"][0]["solicitation"]["public_note"] = "Addendum 1 has been issued."
            changed_scan["all_evaluated"][0]["solicitation"]["public_note"] = "Addendum 1 has been issued."
            second = service._scan_with_runtime_state(changed_scan)
            service._last_scan = second

            stale = second["document_analyses"]["RFQ-STALE"]
            reloaded = ContractRadarService(local_state_dir=tmpdir)

            with self.assertRaises(ValueError) as context:
                service.approve(
                    {
                        "approved": True,
                        "opportunity_id": "RFQ-STALE",
                        "analysis_id": stale["analysis_id"],
                    }
                )

        self.assertEqual(stale["bid_state"], "evidence_gaps_open")
        self.assertEqual(stale["agent_tasks"][0]["task_type"], "reanalyze_official_package")
        self.assertEqual(stale["gate_results"][0]["rule_id"], "source_change_reanalysis_required")
        self.assertTrue(second["daily_run"]["addenda_alerts"])
        self.assertEqual(second["daily_inbox"]["items"][0]["status"], "resolve_gates")
        self.assertIn("Resolve all deterministic agent tasks", str(context.exception))
        persisted = reloaded._document_analysis_sessions["analysis-ready-rfq-stale"]
        self.assertTrue(persisted["source_change_events"])
        self.assertEqual(persisted["agent_tasks"][0]["task_type"], "reanalyze_official_package")

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
            exports = list(reloaded._packet_exports.values())
            self.assertEqual(result["packet"]["opportunity_id"], "RFQ-READY")
            self.assertTrue(result["packet_export"]["export_id"])
            self.assertIn("not_submitted_by_project_bid_bot", result["packet_export"]["markdown"])
            self.assertEqual(len(packets), 1)
            self.assertEqual(len(exports), 1)
            self.assertEqual(packets[0]["packet"]["opportunity_id"], "RFQ-READY")
            self.assertEqual(packets[0]["packet_export"]["export_id"], result["packet_export"]["export_id"])
            self.assertTrue(reloaded.packet_export_file(result["packet_export"]["export_id"])["markdown"])
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
        "pricing_context": _pricing_context(),
        "pricing_approval": {
            "approval_id": f"pricing-approval-{document_number.lower()}",
            "status": "approved",
            "approved_target_bid": 760000,
            "approved_by": "Estimator",
            "approved_at": "2026-06-02T12:10:00Z",
        },
        "bid_state": "owner_packet_ready",
        "gate_results": [],
        "agent_tasks": [],
        "evidence_ledger": [],
        "agent_actions": [],
    }
    service._document_analysis_sessions[analysis_id] = session
    service._latest_document_analysis_by_opportunity[document_number] = analysis_id


def _pricing_context() -> dict:
    return {
        "pricing_breakdown": {
            "recommended_bid": 760000,
            "market_reference": 720000,
            "direct_cost": 500000,
            "estimated_cost": 620000,
            "win_probability": 0.42,
            "expected_profit": 52000,
            "candidate_bids": [{"bid": 700000}, {"bid": 760000}, {"bid": 820000}],
        },
        "bid_recommendation": {
            "recommended_bid": 760000,
            "low_bid": 650000,
            "high_bid": 880000,
            "confidence": "Moderate",
        },
        "historical": {
            "examples": [
                {"document_number": "A1", "description": "Road repair", "award_value": 690000},
                {"document_number": "A2", "description": "Asphalt paving", "award_value": 735000},
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
