from __future__ import annotations

import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class OwnerApprovalReportApiTests(unittest.TestCase):
    def test_service_applies_owner_approval_report_through_pipeline(self) -> None:
        service = ContractRadarService()

        with patch.object(
            service,
            "run_agent_pipeline",
            return_value={
                "pipeline": {"status": "packets_generated"},
                "applied_actions": [{"endpoint": "/api/owner-approval/approve"}],
                "action_application_errors": [],
                "next_agent_actions": [{"action_id": "download-packet"}],
                "generated_bid_packages": [{"generated_bid_package_id": "generated-package-api"}],
            },
        ) as pipeline:
            result = service.apply_owner_approval_report(
                {
                    "profile_id": "road_civil_infrastructure",
                    "owner_approval_report": {
                        "source": "owner_approval_decision_report",
                        "approval_request_id": "approval-request-api",
                        "approved": True,
                        "approved_by": "Casey Owner",
                        "note": "Approved by API report.",
                        "analysis_id": "fake-browser-analysis",
                        "opportunity_id": "fake-browser-opportunity",
                        "compliance_rows": [{"requirement_id": "fake"}],
                        "pricing_rows": [{"line_item_id": "fake"}],
                    },
                }
            )

        pipeline_payload = pipeline.call_args.args[0]
        action = pipeline_payload["completed_actions"][0]
        self.assertEqual(result["source"], "owner_approval_report_application")
        self.assertEqual(result["owner_approval_report_count"], 1)
        self.assertEqual(action["endpoint"], "/api/owner-approval/approve")
        self.assertEqual(
            action["payload"],
            {
                "approval_request_id": "approval-request-api",
                "approved": True,
                "approved_by": "Casey Owner",
                "note": "Approved by API report.",
            },
        )
        self.assertNotIn("analysis_id", action["payload"])
        self.assertNotIn("compliance_rows", action["payload"])
        self.assertEqual(result["generated_bid_packages"][0]["generated_bid_package_id"], "generated-package-api")

    def test_service_rejects_owner_approval_report_without_approval(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "approved=true"):
            service.apply_owner_approval_report(
                {
                    "owner_approval_report": {
                        "source": "owner_approval_decision_report",
                        "approval_request_id": "approval-request-api",
                        "approved": False,
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
