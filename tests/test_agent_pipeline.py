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
        self.assertEqual(action["completed_action_template"]["endpoint"], "/api/owner-approval/approve")
        self.assertEqual(action["completed_action_template"]["payload"]["approval_request_id"], action["approval_request_id"])
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
        self.assertEqual(len(result["generated_bid_packages"]), 1)
        generated = result["generated_bid_packages"][0]
        self.assertEqual(generated["source"], "server_owned_generated_bid_package")
        self.assertEqual(generated["status"], "ready_for_human_submission")
        self.assertEqual(generated["opportunity_id"], "RFQ-PIPELINE-GENERATE")
        self.assertEqual(generated["export"]["download_url"], packet["download_url"])
        self.assertEqual(generated["pricing"]["target_bid"], 760000)
        self.assertEqual(generated["submission_manifest_summary"]["required_open"], 0)
        self.assertTrue(generated["form_blueprint_summary"]["ready_for_form_work"])
        self.assertGreaterEqual(len(generated["prefilled_fields"]), 1)
        self.assertGreaterEqual(len(generated["attachment_manifest"]), 1)
        self.assertGreaterEqual(len(generated["portal_steps"]), 1)
        self.assertIn("Human buyer-portal upload", " ".join(generated["guardrails"]))
        self.assertEqual(
            result["next_agent_actions"][0]["generated_bid_package_id"],
            generated["generated_bid_package_id"],
        )
        self.assertTrue(analysis["owner_approved"])
        self.assertEqual(analysis["owner_approval"]["note"], "Approved by pipeline test.")

    def test_pipeline_applies_completed_owner_approval_and_generates_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            snapshot = _ready_snapshot(service, "RFQ-PIPELINE-COMPLETED-OWNER")
            request_id = snapshot["owner_approval_requests"][0]["approval_request_id"]

            with patch.object(service, "run_until_approval", return_value=snapshot):
                result = service.run_agent_pipeline(
                    {
                        "completed_actions": [
                            {
                                "action_id": "completed-owner-approval",
                                "endpoint": "/api/owner-approval/approve",
                                "payload": {
                                    "approval_request_id": request_id,
                                    "approved": True,
                                    "approved_by": "Owner",
                                    "note": "Approved via completed action.",
                                    "analysis_id": "analysis-fake-browser-id",
                                    "opportunity_id": "RFQ-FAKE-BROWSER-ID",
                                },
                            }
                        ]
                    }
                )

            analysis = service._document_analysis_sessions["analysis-ready-rfq-pipeline-completed-owner"]

        self.assertEqual(result["pipeline"]["status"], "packets_generated")
        self.assertEqual(result["pipeline"]["applied_action_count"], 1)
        self.assertEqual(result["pipeline"]["generated_packet_count"], 1)
        self.assertEqual(result["pending_approval_actions"], [])
        self.assertEqual(result["applied_actions"][0]["endpoint"], "/api/owner-approval/approve")
        self.assertTrue(result["applied_actions"][0]["generated_packet_id"])
        self.assertIn(request_id, result["applied_actions"][0]["output_ids"])
        self.assertEqual(result["generated_packets"][0]["approval_request_id"], request_id)
        self.assertEqual(result["generated_bid_packages"][0]["opportunity_id"], "RFQ-PIPELINE-COMPLETED-OWNER")
        self.assertEqual(result["next_agent_actions"][0]["action_type"], "download_packet_and_submit_manually")
        self.assertEqual(analysis["owner_approval"]["note"], "Approved via completed action.")

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
        self.assertEqual(action["completed_action_template"]["endpoint"], "/api/pricing/approve")
        self.assertEqual(action["completed_action_template"]["payload"]["analysis_id"], "analysis-price")
        self.assertIn("Do not invent", " ".join(action["guardrails"]))

    def test_pipeline_returns_package_directory_manifest_for_manual_package_tasks(self) -> None:
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
                    "opportunity_id": "RFQ-PACKAGE",
                    "analysis_id": "analysis-package",
                    "task_type": "acquire_official_package",
                    "status": "get_package",
                    "title": "Get Official Package",
                    "blocker": "Official solicitation package is required.",
                    "acquisition_status": "portal_login_required",
                    "acquisition_guidance": {
                        "portal_url": "https://example.test/portal",
                        "search_hint": "Search RFQ-PACKAGE",
                        "expected_documents": ["RFQ-PACKAGE solicitation package", "addenda"],
                        "instructions": ["Open the buyer portal.", "Download the official package."],
                    },
                }
            ],
            "business_profile": {"profile_id": "road_civil_infrastructure"},
            "scan": {
                "current_agent_tasks": [
                    {
                        "task_id": "agent-task-package",
                        "opportunity_id": "RFQ-PACKAGE",
                        "analysis_id": "analysis-package",
                        "task_type": "acquire_official_package",
                    }
                ]
            },
            "as_of": "2026-06-04",
            "priority_mode": "best_win_chance",
        }

        with patch.object(service, "run_until_approval", return_value=snapshot):
            result = service.run_agent_pipeline({})

        manifest = result["package_directory_manifest"]
        entry = manifest["entries"][0]
        portal_request = result["portal_package_requests"][0]
        self.assertEqual(result["pipeline"]["status"], "waiting_on_human_input")
        self.assertEqual(result["pipeline"]["package_download_count"], 1)
        self.assertEqual(result["pipeline"]["portal_package_request_count"], 1)
        self.assertEqual(manifest["status"], "packages_needed")
        self.assertIn("--package-dir <download-dir>", manifest["package_dir_command"])
        self.assertEqual(entry["opportunity_id"], "RFQ-PACKAGE")
        self.assertEqual(entry["recommended_filename"], "RFQ-PACKAGE__official-package.pdf")
        self.assertEqual(entry["task_id"], "agent-task-package")
        self.assertEqual(entry["portal_url"], "https://example.test/portal")
        self.assertEqual(entry["search_hint"], "Search RFQ-PACKAGE")
        self.assertIn("--package-file RFQ-PACKAGE=<download-dir>\\RFQ-PACKAGE__official-package.pdf", entry["package_file_command"])
        self.assertIn("addenda", entry["expected_documents"])
        self.assertEqual(portal_request["source"], "deterministic_portal_package_request")
        self.assertEqual(portal_request["status"], "download_required")
        self.assertEqual(portal_request["opportunity_id"], "RFQ-PACKAGE")
        self.assertEqual(portal_request["portal_url"], "https://example.test/portal")
        self.assertEqual(portal_request["download_target"]["path"], "<download-dir>\\RFQ-PACKAGE__official-package.pdf")
        self.assertIn("application/pdf", portal_request["download_target"]["accepted_content_types"])
        self.assertEqual(portal_request["completion_report_template"]["source"], "portal_package_download_report")
        self.assertEqual(portal_request["completion_report_template"]["opportunity_id"], "RFQ-PACKAGE")
        self.assertEqual(
            portal_request["completion_report_template"]["downloaded_files"][0]["path"],
            "<download-dir>\\RFQ-PACKAGE__official-package.pdf",
        )
        self.assertEqual(portal_request["resume"]["package_report_endpoint"], "/api/agent/package-report")
        self.assertTrue(portal_request["resume"]["package_report_payload_template"]["resume_pipeline"])
        self.assertEqual(
            portal_request["resume"]["package_report_payload_template"]["portal_package_report"]["request_id"],
            portal_request["request_id"],
        )
        self.assertIn("--portal-package-report-file <report.json>", portal_request["resume"]["package_report_command"])
        self.assertEqual(portal_request["resume"]["completed_action_template"]["endpoint"], "/api/documents/analyze")
        self.assertEqual(
            portal_request["resume"]["completed_action_template"]["payload"]["opportunity_id"],
            "RFQ-PACKAGE",
        )
        self.assertIn(
            "run_resume_command",
            {step["action"] for step in portal_request["browser_agent_steps"]},
        )
        self.assertIn("Do not submit", " ".join(portal_request["guardrails"]))
        self.assertEqual(
            result["human_resolution_actions"][0]["acquisition_guidance"]["portal_url"],
            "https://example.test/portal",
        )

    def test_pipeline_applies_completed_actions_before_resuming_loop(self) -> None:
        service = ContractRadarService()
        events: list[str] = []

        def fake_approve_pricing(payload: dict) -> dict:
            events.append("apply_pricing")
            self.assertEqual(payload["analysis_id"], "analysis-price")
            return {
                "analysis_id": "analysis-price",
                "opportunity_id": "RFQ-PRICE",
                "bid_state": "owner_packet_ready",
                "pricing_approval": {"approval_id": "pricing-approval-1"},
            }

        def fake_loop(payload: dict) -> dict:
            events.append("run_loop")
            self.assertNotIn("completed_actions", payload)
            return {
                "agent_loop": {"status": "no_action_required", "error_count": 0, "errors": []},
                "agent_run": {"status": "no_action_required"},
                "daily_inbox": {},
                "daily_run": {},
                "document_analyses": {},
                "owner_approval_requests": [],
                "human_required_actions": [],
                "business_profile": {"profile_id": "road_civil_infrastructure"},
                "scan": {},
                "as_of": "2026-06-04",
                "priority_mode": "best_win_chance",
            }

        with patch.object(service, "approve_pricing", side_effect=fake_approve_pricing):
            with patch.object(service, "run_until_approval", side_effect=fake_loop):
                result = service.run_agent_pipeline(
                    {
                        "completed_actions": [
                            {
                                "action_id": "completed-price-approval",
                                "endpoint": "/api/pricing/approve",
                                "payload": {
                                    "analysis_id": "analysis-price",
                                    "approved_by": "Estimator",
                                },
                            }
                        ]
                    }
                )

        self.assertEqual(events, ["apply_pricing", "run_loop"])
        self.assertEqual(result["pipeline"]["applied_action_count"], 1)
        self.assertEqual(result["applied_actions"][0]["action_id"], "completed-price-approval")
        self.assertEqual(result["applied_actions"][0]["endpoint"], "/api/pricing/approve")
        self.assertIn("pricing-approval-1", result["applied_actions"][0]["output_ids"])
        self.assertEqual(result["action_application_errors"], [])

    def test_pipeline_rejects_unsupported_completed_action_endpoint(self) -> None:
        service = ContractRadarService()
        with patch.object(
            service,
            "run_until_approval",
            return_value={
                "agent_loop": {"status": "no_action_required", "error_count": 0, "errors": []},
                "agent_run": {"status": "no_action_required"},
                "daily_inbox": {},
                "daily_run": {},
                "document_analyses": {},
                "owner_approval_requests": [],
                "human_required_actions": [],
                "business_profile": {"profile_id": "road_civil_infrastructure"},
                "scan": {},
                "as_of": "2026-06-04",
                "priority_mode": "best_win_chance",
            },
        ):
            result = service.run_agent_pipeline(
                {
                    "completed_actions": [
                        {
                            "action_id": "unsupported",
                            "endpoint": "/api/not-a-pipeline-action",
                            "payload": {},
                        }
                    ]
                }
            )

        self.assertEqual(result["pipeline"]["status"], "error")
        self.assertEqual(result["pipeline"]["applied_action_count"], 0)
        self.assertEqual(result["action_application_errors"][0]["action_id"], "unsupported")
        self.assertIn("Unsupported", result["pipeline"]["next_action"])


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
