from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService
from tests.test_persistence import _approval_scan, _attach_ready_analysis


class AgentTaskExecutionTests(unittest.TestCase):
    def test_execute_current_package_task_runs_acquisition_from_server_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            scan = _approval_scan("RFQ-TASK-ACQUIRE")
            hydrated = service._scan_with_runtime_state(scan)
            service._last_scan = copy.deepcopy(hydrated)
            task_id = hydrated["current_agent_tasks"][0]["task_id"]
            acquired_payloads: list[dict] = []

            def fake_acquire(payload: dict) -> dict:
                acquired_payloads.append(copy.deepcopy(payload))
                return {
                    "analysis_id": "analysis-task-acquire",
                    "opportunity_id": payload["opportunity_id"],
                    "bid_state": "evidence_gaps_open",
                    "acquisition": {
                        "status": "package_fetched",
                        "message": "Fetched public official package.",
                    },
                }

            with patch.object(service, "acquire_document", side_effect=fake_acquire):
                result = service.execute_agent_task(
                    {
                        "task_id": task_id,
                        "opportunity_id": "RFQ-FAKE-CLIENT-ID",
                    }
                )

        execution = result["agent_task_execution"]
        self.assertEqual(len(acquired_payloads), 1)
        self.assertEqual(acquired_payloads[0]["opportunity_id"], "RFQ-TASK-ACQUIRE")
        self.assertEqual(execution["task_id"], task_id)
        self.assertEqual(execution["action_type"], "official_package_acquisition_checked")
        self.assertEqual(execution["status"], "completed")
        self.assertIn("No bid was submitted.", result["guardrails"])

    def test_execute_current_recheck_task_runs_reanalysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._document_analysis_sessions["analysis-task-recheck"] = {
                "analysis_id": "analysis-task-recheck",
                "opportunity_id": "RFQ-TASK-RECHECK",
                "bid_state": "evidence_gaps_open",
                "source_stale": True,
                "source_change_events": [{"event_id": "evt-1"}],
                "agent_tasks": [
                    {
                        "task_id": "source-task-recheck",
                        "task_type": "reanalyze_official_package",
                        "title": "Recheck changed source",
                        "detail": "Addendum changed.",
                    }
                ],
                "acquisition": {"status": "package_uploaded"},
                "compliance_decision": {"label": "Pursue", "next_action": "Recheck changed source"},
            }
            service._latest_document_analysis_by_opportunity["RFQ-TASK-RECHECK"] = "analysis-task-recheck"
            hydrated = service._scan_with_runtime_state(_approval_scan("RFQ-TASK-RECHECK"))
            service._last_scan = copy.deepcopy(hydrated)
            task_id = hydrated["current_agent_tasks"][0]["task_id"]
            rechecked_payloads: list[dict] = []

            def fake_recheck(payload: dict) -> dict:
                rechecked_payloads.append(copy.deepcopy(payload))
                return {
                    "analysis_id": payload["analysis_id"],
                    "opportunity_id": payload["opportunity_id"],
                    "bid_state": "evidence_gaps_open",
                    "acquisition": {
                        "status": "portal_login_required",
                        "message": "Portal credentials are required.",
                    },
                }

            with patch.object(service, "recheck_document", side_effect=fake_recheck):
                result = service.execute_agent_task({"task_id": task_id})

        execution = result["agent_task_execution"]
        self.assertEqual(len(rechecked_payloads), 1)
        self.assertEqual(rechecked_payloads[0]["analysis_id"], "analysis-task-recheck")
        self.assertEqual(rechecked_payloads[0]["opportunity_id"], "RFQ-TASK-RECHECK")
        self.assertEqual(execution["action_type"], "changed_source_rechecked")
        self.assertEqual(execution["status"], "requires_input")

    def test_execute_owner_packet_task_returns_approval_request_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _approval_scan("RFQ-TASK-OWNER")
            _attach_ready_analysis(service, "RFQ-TASK-OWNER")
            hydrated = service._scan_with_runtime_state(service._last_scan)
            service._last_scan = copy.deepcopy(hydrated)
            task_id = hydrated["current_agent_tasks"][0]["task_id"]

            result = service.execute_agent_task({"task_id": task_id})

        execution = result["agent_task_execution"]
        analysis = service._document_analysis_sessions["analysis-ready-rfq-task-owner"]
        self.assertEqual(execution["status"], "requires_owner_approval")
        self.assertEqual(result["owner_approval_request"]["opportunity_id"], "RFQ-TASK-OWNER")
        self.assertFalse(analysis.get("owner_approved", False))
        self.assertIn("This endpoint does not approve owner requests.", result["guardrails"])

    def test_execute_agent_task_rejects_fake_or_stale_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            hydrated = service._scan_with_runtime_state(_approval_scan("RFQ-TASK-STALE"))
            service._last_scan = copy.deepcopy(hydrated)

            with self.assertRaisesRegex(ValueError, "not current"):
                service.execute_agent_task({"task_id": "agent-task-fake"})


if __name__ == "__main__":
    unittest.main()
