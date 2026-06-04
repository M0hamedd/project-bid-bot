from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService
from tests.test_persistence import _approval_scan, _attach_ready_analysis


class AgentPipelineTests(unittest.TestCase):
    def test_pipeline_returns_owner_approval_actions_without_generating_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            snapshot = _ready_snapshot(service, "RFQ-PIPELINE-HANDOFF")

            with patch.object(service, "run_until_approval", return_value=snapshot):
                result = service.run_agent_pipeline({})

        pipeline = result["pipeline"]
        self.assertEqual(pipeline["status"], "awaiting_owner_approval")
        self.assertEqual(pipeline["approval_request_count"], 1)
        self.assertEqual(pipeline["generated_packet_count"], 0)
        self.assertEqual(result["generated_packets"], [])
        self.assertEqual(len(result["approval_actions"]), 1)
        self.assertEqual(result["pipeline"]["next_agent_action_count"], 1)
        self.assertEqual(result["next_agent_actions"][0]["action_type"], "owner_approval_required")
        action = result["approval_actions"][0]
        self.assertEqual(action["opportunity_id"], "RFQ-PIPELINE-HANDOFF")
        self.assertIn("scripts\\approve_owner_request.py", action["cli_command"])
        self.assertIn("scripts\\run_bid_pipeline.py", action["resume_pipeline_command"])
        self.assertEqual(action["endpoint"], "/api/owner-approval/approve")
        self.assertIn("No bid was submitted.", pipeline["guardrails"])

    def test_pipeline_approves_selected_owner_request_and_generates_packet_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            snapshot = _ready_snapshot(service, "RFQ-PIPELINE-GENERATE")
            request_id = snapshot["owner_approval_requests"][0]["approval_request_id"]

            with patch.object(service, "run_until_approval", return_value=snapshot):
                result = service.run_agent_pipeline(
                    {
                        "approval_request_ids": [request_id],
                        "approved_by": "Owner",
                        "note": "Approved by pipeline test.",
                    }
                )

            analysis = service._document_analysis_sessions["analysis-ready-rfq-pipeline-generate"]

        pipeline = result["pipeline"]
        packet = result["generated_packets"][0]
        self.assertEqual(pipeline["status"], "packets_generated")
        self.assertEqual(pipeline["generated_packet_count"], 1)
        self.assertEqual(result["pending_approval_actions"], [])
        self.assertEqual(result["next_agent_actions"][0]["action_type"], "download_packet_and_submit_manually")
        self.assertEqual(packet["approval_request_id"], request_id)
        self.assertEqual(packet["opportunity_id"], "RFQ-PIPELINE-GENERATE")
        self.assertTrue(packet["download_url"])
        self.assertTrue(packet["human_submission_required"])
        self.assertTrue(analysis["owner_approved"])
        self.assertEqual(analysis["owner_approval"]["note"], "Approved by pipeline test.")

    def test_pipeline_rejects_non_current_approval_request_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            snapshot = _ready_snapshot(service, "RFQ-PIPELINE-REJECT")

            with patch.object(service, "run_until_approval", return_value=snapshot):
                with self.assertRaisesRegex(ValueError, "not current or not pending"):
                    service.run_agent_pipeline({"approval_request_ids": ["approval-request-fake"]})

    def test_pipeline_returns_machine_readable_human_resolution_actions(self) -> None:
        service = ContractRadarService()
        snapshot = {
            "agent_loop": {
                "status": "waiting_on_human_input",
                "stop_reason": "human_input_required",
                "error_count": 0,
                "errors": [],
            },
            "agent_run": {"status": "waiting_on_human_input"},
            "daily_inbox": {},
            "daily_run": {},
            "document_analyses": {},
            "owner_approval_requests": [],
            "human_required_actions": [
                {
                    "opportunity_id": "RFQ-PRICE",
                    "analysis_id": "analysis-price",
                    "task_type": "approve_pricing",
                    "status": "resolve_gates",
                    "title": "Approve estimator pricing",
                    "blocker": "Estimator target bid approval is required.",
                }
            ],
            "business_profile": {"profile_id": "road_civil_infrastructure"},
            "scan": {
                "current_agent_tasks": [
                    {
                        "task_id": "agent-task-price",
                        "opportunity_id": "RFQ-PRICE",
                        "analysis_id": "analysis-price",
                        "task_type": "approve_pricing",
                    }
                ]
            },
            "as_of": "2026-06-04",
            "priority_mode": "best_win_chance",
        }

        with patch.object(service, "run_until_approval", return_value=snapshot):
            result = service.run_agent_pipeline({})

        self.assertEqual(result["pipeline"]["status"], "waiting_on_human_input")
        self.assertEqual(len(result["human_resolution_actions"]), 1)
        action = result["human_resolution_actions"][0]
        self.assertEqual(action["task_id"], "agent-task-price")
        self.assertEqual(action["endpoint"], "/api/pricing/approve")
        self.assertEqual(action["payload_template"]["analysis_id"], "analysis-price")
        self.assertEqual(action["payload_template"]["approved_by"], "Estimator")
        self.assertIn("Do not invent", " ".join(action["guardrails"]))


def _ready_snapshot(service: ContractRadarService, opportunity_id: str) -> dict:
    service._last_scan = _approval_scan(opportunity_id)
    _attach_ready_analysis(service, opportunity_id)
    hydrated = service._scan_with_runtime_state(copy.deepcopy(service._last_scan))
    service._last_scan = copy.deepcopy(hydrated)
    return {
        "agent_loop": {
            "status": "awaiting_owner_approval",
            "stop_reason": "owner_approval_required",
            "error_count": 0,
            "errors": [],
        },
        "agent_run": {"status": "awaiting_owner_approval"},
        "daily_inbox": hydrated.get("daily_inbox") or {},
        "daily_run": hydrated.get("daily_run") or {},
        "document_analyses": hydrated.get("document_analyses") or {},
        "owner_approval_requests": hydrated.get("owner_approval_requests") or [],
        "human_required_actions": [],
        "business_profile": hydrated.get("business_profile") or {},
        "scan": hydrated,
        "as_of": hydrated.get("as_of") or "",
        "priority_mode": hydrated.get("priority_mode") or "",
    }


if __name__ == "__main__":
    unittest.main()
