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
        self.assertEqual(request["approval_endpoint"], "/api/approve")
        self.assertEqual(request["approval_payload"]["analysis_id"], "analysis-ready")
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
        self.assertEqual(analysis["owner_approval_request"]["approval_request_id"], requests[0]["approval_request_id"])


if __name__ == "__main__":
    unittest.main()
