from __future__ import annotations

import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class CompletedAgentActionsApiTests(unittest.TestCase):
    def test_service_applies_completed_actions_through_pipeline(self) -> None:
        service = ContractRadarService()
        with patch.object(
            service,
            "run_agent_pipeline",
            return_value={
                "pipeline": {"status": "packets_generated"},
                "applied_actions": [{"action_id": "completed-owner", "status": "applied"}],
                "action_application_errors": [],
                "next_agent_actions": [{"action_id": "download-packet"}],
                "generated_bid_packages": [{"generated_bid_package_id": "generated-package-1"}],
            },
        ) as pipeline:
            result = service.apply_completed_agent_actions(
                {
                    "profile_id": "road_civil_infrastructure",
                    "max_steps": 2,
                    "resume_pipeline": True,
                    "completed_actions": [
                        {
                            "action_id": "completed-owner",
                            "endpoint": "/api/owner-approval/approve",
                            "payload": {"approval_request_id": "approval-request-1", "approved": True},
                        }
                    ],
                }
            )

        pipeline_payload = pipeline.call_args.args[0]
        self.assertEqual(result["source"], "completed_agent_action_application")
        self.assertEqual(result["completed_action_count"], 1)
        self.assertEqual(result["applied_actions"][0]["action_id"], "completed-owner")
        self.assertEqual(result["next_agent_actions"][0]["action_id"], "download-packet")
        self.assertEqual(result["generated_bid_packages"][0]["generated_bid_package_id"], "generated-package-1")
        self.assertEqual(pipeline_payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(pipeline_payload["max_steps"], 2)
        self.assertEqual(pipeline_payload["completed_actions"][0]["endpoint"], "/api/owner-approval/approve")
        self.assertNotIn("resume_pipeline", pipeline_payload)

    def test_service_accepts_single_completed_action_object(self) -> None:
        service = ContractRadarService()
        with patch.object(
            service,
            "run_agent_pipeline",
            return_value={
                "pipeline": {"status": "waiting_on_human_input"},
                "applied_actions": [],
                "action_application_errors": [],
                "next_agent_actions": [],
                "generated_bid_packages": [],
            },
        ) as pipeline:
            service.apply_completed_agent_actions(
                {
                    "profile_id": "road_civil_infrastructure",
                    "endpoint": "/api/pricing/approve",
                    "payload": {"analysis_id": "analysis-price", "approved_by": "Estimator"},
                }
            )

        self.assertEqual(pipeline.call_args.args[0]["completed_actions"][0]["endpoint"], "/api/pricing/approve")

    def test_service_rejects_empty_completed_actions(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "At least one completed action"):
            service.apply_completed_agent_actions({"profile_id": "road_civil_infrastructure", "completed_actions": []})


if __name__ == "__main__":
    unittest.main()
