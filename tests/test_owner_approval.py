from __future__ import annotations

import tempfile
import unittest

from contract_radar.owner_approval import PENDING_STATUS, build_owner_approval_request
from contract_radar.service import ContractRadarService
from tests.test_persistence import _approval_scan, _attach_ready_analysis


class OwnerApprovalRequestTests(unittest.TestCase):
    def test_ready_analysis_builds_deterministic_owner_approval_request(self) -> None:
        request = build_owner_approval_request(
            {
                "analysis_id": "analysis-ready",
                "opportunity_id": "RFQ-READY",
                "bid_state": "owner_packet_ready",
                "business_profile": {"profile_id": "road_civil_infrastructure", "name": "Harbourfront Civil"},
                "opportunity_metadata": {
                    "document_number": "RFQ-READY",
                    "title": "Road repair",
                    "submission_deadline": "2026-06-18",
                    "buyer_name": "City Buyer",
                },
                "compliance_decision": {"label": "Pursue", "reason": "All gates clear."},
                "submission_manifest_summary": {"total": 4, "required_open": 1},
                "agent_tasks": [],
                "gate_results": [],
                "pricing_worksheet": {
                    "target_bid": 760000,
                    "low_bid": 720000,
                    "high_bid": 810000,
                    "confidence": "Moderate",
                    "estimator_approval_status": "approved",
                    "pricing_line_items": [
                        {
                            "line_item_id": "line-1",
                            "citation": {
                                "source": "pricing.pdf",
                                "page": 1,
                                "chunk_id": "chunk-1",
                                "snippet": "Asphalt repair 10 m2",
                            },
                        }
                    ],
                },
                "document": {"filename": "rfq.pdf"},
                "acquisition": {"status": "package_fetched", "message": "Fetched package."},
            }
        )

        self.assertEqual(request["status"], PENDING_STATUS)
        self.assertTrue(request["ready_for_owner"])
        self.assertEqual(request["approval_endpoint"], "/api/owner-approval/approve")
        self.assertEqual(request["approval_payload"]["approval_request_id"], request["approval_request_id"])
        self.assertEqual(request["server_approval_payload"]["analysis_id"], "analysis-ready")
        self.assertEqual(request["pricing"]["target_bid"], 760000)
        self.assertTrue(any(item["citation_type"] == "pricing_line_item" for item in request["citations"]))
        self.assertIn("This request does not submit the bid.", request["guardrails"])

    def test_scan_exposes_owner_approval_requests_for_ready_analyses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            scan = _approval_scan("RFQ-OWNER-REQ")
            _attach_ready_analysis(service, "RFQ-OWNER-REQ")

            hydrated = service._scan_with_runtime_state(scan)

        requests = hydrated["owner_approval_requests"]
        analysis = hydrated["document_analyses"]["RFQ-OWNER-REQ"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["opportunity_id"], "RFQ-OWNER-REQ")
        self.assertEqual(requests[0]["approval_payload"]["approved"], True)
        self.assertEqual(requests[0]["server_approval_payload"]["opportunity_id"], "RFQ-OWNER-REQ")
        self.assertEqual(analysis["owner_approval_request"]["approval_request_id"], requests[0]["approval_request_id"])

    def test_owner_approval_request_id_prepares_packet_from_server_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-OWNER-APPROVE")
            _attach_ready_analysis(service, "RFQ-OWNER-APPROVE")
            hydrated = service._scan_with_runtime_state(service._last_scan)
            service._last_scan = hydrated
            request = hydrated["owner_approval_requests"][0]

            result = service.approve_owner_request(
                {
                    "approval_request_id": request["approval_request_id"],
                    "approved": True,
                    "approved_by": "Owner",
                    "approval_note": "Approved the target bid.",
                    "analysis_id": "analysis-fake-client-id",
                    "opportunity_id": "RFQ-FAKE-CLIENT-ID",
                }
            )

        analysis = service._document_analysis_sessions["analysis-ready-rfq-owner-approve"]
        action_types = [action["action_type"] for action in analysis["agent_actions"]]
        self.assertEqual(result["packet"]["opportunity_id"], "RFQ-OWNER-APPROVE")
        self.assertEqual(result["owner_approval_request"]["previous_status"], PENDING_STATUS)
        self.assertEqual(result["owner_approval_request"]["approval_request_id"], request["approval_request_id"])
        self.assertEqual(result["owner_approval"]["approved_by"], "Owner")
        self.assertEqual(result["owner_approval"]["note"], "Approved the target bid.")
        self.assertEqual(result["packet"]["form_blueprint"]["source"], "deterministic_form_blueprint")
        self.assertIn("no_submission", " ".join(result["packet"]["form_blueprint"]["guardrails"]))
        self.assertTrue(analysis["owner_approved"])
        self.assertEqual(analysis["owner_approval"]["approval_request_id"], request["approval_request_id"])
        self.assertIn("owner_packet_prepared", action_types)

    def test_owner_approval_request_rejects_fake_or_stale_request_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-OWNER-STALE")
            _attach_ready_analysis(service, "RFQ-OWNER-STALE")
            hydrated = service._scan_with_runtime_state(service._last_scan)
            service._last_scan = hydrated
            request = hydrated["owner_approval_requests"][0]

            with self.assertRaisesRegex(ValueError, "not pending"):
                service.approve_owner_request({"approval_request_id": "approval-request-fake"})
            with self.assertRaisesRegex(ValueError, "approved=true"):
                service.approve_owner_request(
                    {
                        "approval_request_id": request["approval_request_id"],
                        "approved": "false",
                    }
                )

            service.approve_owner_request({"approval_request_id": request["approval_request_id"]})
            with self.assertRaisesRegex(ValueError, "not pending"):
                service.approve_owner_request({"approval_request_id": request["approval_request_id"]})


if __name__ == "__main__":
    unittest.main()
