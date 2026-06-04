from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class AgentRunUntilApprovalTests(unittest.TestCase):
    def test_loop_executes_safe_task_until_owner_approval_request(self) -> None:
        service = ContractRadarService()
        snapshots = [
            _snapshot(
                status="waiting_on_human_input",
                tasks=[
                    {
                        "task_id": "agent-task-acquire",
                        "task_type": "acquire_official_package",
                        "opportunity_id": "RFQ-LOOP",
                    }
                ],
            ),
            _snapshot(
                status="awaiting_owner_approval",
                owner_requests=[
                    {
                        "approval_request_id": "approval-request-loop",
                        "opportunity_id": "RFQ-LOOP",
                    }
                ],
            ),
        ]
        executed_payloads: list[dict] = []

        def fake_execute(payload: dict) -> dict:
            executed_payloads.append(copy.deepcopy(payload))
            return {
                "agent_task_execution": {
                    "execution_id": "agent-task-execution-loop",
                    "task_id": payload["task_id"],
                    "task_type": "acquire_official_package",
                    "opportunity_id": "RFQ-LOOP",
                    "analysis_id": "analysis-loop",
                    "action_type": "official_package_acquisition_checked",
                    "status": "completed",
                    "detail": "Fetched package.",
                    "output_ids": ["analysis-loop"],
                }
            }

        with patch.object(service, "run_agent", side_effect=snapshots):
            with patch.object(service, "execute_agent_task", side_effect=fake_execute):
                result = service.run_until_approval({"profile_id": "road_civil_infrastructure"})

        loop = result["agent_loop"]
        self.assertEqual(len(executed_payloads), 1)
        self.assertEqual(executed_payloads[0]["task_id"], "agent-task-acquire")
        self.assertEqual(loop["status"], "awaiting_owner_approval")
        self.assertEqual(loop["stop_reason"], "owner_approval_required")
        self.assertEqual(loop["automatic_execution_count"], 1)
        self.assertEqual(result["owner_approval_requests"][0]["approval_request_id"], "approval-request-loop")
        self.assertIn("The loop stops before owner approval.", loop["guardrails"])

    def test_loop_stops_on_human_only_task(self) -> None:
        service = ContractRadarService()
        with patch.object(
            service,
            "run_agent",
            return_value=_snapshot(
                status="waiting_on_human_input",
                tasks=[
                    {
                        "task_id": "agent-task-pricing",
                        "task_type": "approve_pricing",
                        "opportunity_id": "RFQ-HUMAN",
                        "analysis_id": "analysis-human",
                    }
                ],
                human_actions=[
                    {
                        "opportunity_id": "RFQ-HUMAN",
                        "analysis_id": "analysis-human",
                        "task_type": "approve_pricing",
                        "status": "resolve_gates",
                    }
                ],
            ),
        ):
            with patch.object(service, "execute_agent_task") as execute:
                result = service.run_until_approval({"profile_id": "road_civil_infrastructure"})

        execute.assert_not_called()
        self.assertEqual(result["agent_loop"]["status"], "waiting_on_human_input")
        self.assertEqual(result["agent_loop"]["stop_reason"], "human_input_required")
        self.assertEqual(result["human_required_actions"][0]["task_type"], "approve_pricing")

    def test_loop_stops_when_safe_task_execution_requires_input(self) -> None:
        service = ContractRadarService()
        snapshots = [
            _snapshot(
                status="waiting_on_human_input",
                tasks=[
                    {
                        "task_id": "agent-task-acquire",
                        "task_type": "acquire_official_package",
                        "opportunity_id": "RFQ-PORTAL",
                    }
                ],
            ),
            _snapshot(
                status="waiting_on_human_input",
                human_actions=[
                    {
                        "opportunity_id": "RFQ-PORTAL",
                        "task_type": "acquire_official_package",
                        "status": "get_package",
                    }
                ],
            ),
        ]
        with patch.object(service, "run_agent", side_effect=snapshots):
            with patch.object(
                service,
                "execute_agent_task",
                return_value={
                    "agent_task_execution": {
                        "execution_id": "agent-task-execution-portal",
                        "task_id": "agent-task-acquire",
                        "task_type": "acquire_official_package",
                        "opportunity_id": "RFQ-PORTAL",
                        "action_type": "official_package_acquisition_checked",
                        "status": "requires_input",
                        "detail": "Portal login required.",
                    }
                },
            ):
                result = service.run_until_approval({"profile_id": "road_civil_infrastructure"})

        self.assertEqual(result["agent_loop"]["status"], "waiting_on_human_input")
        self.assertEqual(result["agent_loop"]["stop_reason"], "human_input_required")
        self.assertEqual(result["agent_loop"]["automatic_executions"][0]["status"], "requires_input")

    def test_loop_respects_zero_max_steps_without_executing_safe_task(self) -> None:
        service = ContractRadarService()
        with patch.object(
            service,
            "run_agent",
            return_value=_snapshot(
                status="waiting_on_human_input",
                tasks=[
                    {
                        "task_id": "agent-task-acquire",
                        "task_type": "acquire_official_package",
                        "opportunity_id": "RFQ-ZERO",
                    }
                ],
            ),
        ):
            with patch.object(service, "execute_agent_task") as execute:
                result = service.run_until_approval({"max_steps": 0})

        execute.assert_not_called()
        self.assertEqual(result["agent_loop"]["status"], "max_steps_reached")
        self.assertEqual(result["agent_loop"]["automatic_execution_count"], 0)


def _snapshot(
    *,
    status: str,
    tasks: list[dict] | None = None,
    owner_requests: list[dict] | None = None,
    human_actions: list[dict] | None = None,
) -> dict:
    tasks = [dict(item) for item in tasks or []]
    owner_requests = [dict(item) for item in owner_requests or []]
    human_actions = [dict(item) for item in human_actions or []]
    return {
        "agent_run": {
            "status": status,
            "approval_required_count": len(owner_requests),
            "human_action_count": len(human_actions),
            "human_required_actions": human_actions,
        },
        "daily_inbox": {
            "summary": {
                "top_action": "Resolve next task",
                "top_opportunity_id": "RFQ-LOOP",
            },
            "items": [
                {
                    "agent_task_id": task.get("task_id"),
                    "task_type": task.get("task_type"),
                    "opportunity_id": task.get("opportunity_id"),
                    "analysis_id": task.get("analysis_id", ""),
                    "status": "resolve_gates",
                    "next_action": "Resolve next task",
                }
                for task in tasks
            ],
        },
        "daily_run": {},
        "document_analyses": {},
        "owner_approval_requests": owner_requests,
        "business_profile": {"profile_id": "road_civil_infrastructure"},
        "scan": {"current_agent_tasks": tasks},
        "as_of": "2026-06-04",
        "priority_mode": "best_win_chance",
    }


if __name__ == "__main__":
    unittest.main()
