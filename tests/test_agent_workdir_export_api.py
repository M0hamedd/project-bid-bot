from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class AgentWorkdirExportApiTests(unittest.TestCase):
    def test_service_exports_pipeline_handoff_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            work_dir = directory / "agent-work"
            service = ContractRadarService(local_state_dir=directory / "state")
            pipeline_result = _pipeline_result()

            with patch.object(service, "run_agent_pipeline", return_value=pipeline_result) as pipeline:
                result = service.export_agent_workdir(
                    {
                        "agent_work_dir": str(work_dir),
                        "profile_id": "road_civil_infrastructure",
                        "max_steps": 0,
                        "compliance_rows": [{"requirement_id": "fake-browser-row"}],
                        "pricing_rows": [{"line_item_id": "fake-browser-row"}],
                    }
                )

            handoff_file = json.loads((work_dir / "agent-handoff.json").read_text(encoding="utf-8"))
            completed_file = json.loads(
                (work_dir / "completed-action-templates" / "completed-pricing-approval.json").read_text(
                    encoding="utf-8"
                )
            )
            owner_report_template = json.loads(
                (work_dir / "reports" / "owner-approval-report-approval-request-export.json").read_text(
                    encoding="utf-8"
                )
            )

        pipeline_payload = pipeline.call_args.args[0]
        self.assertEqual(result["source"], "agent_workdir_export")
        self.assertEqual(result["agent_handoff"]["source"], "agent_workdir_api_export")
        self.assertEqual(result["agent_handoff"]["pipeline_status"], "waiting_on_human_input")
        self.assertEqual(result["agent_handoff"]["completed_action_template_count"], 1)
        self.assertEqual(result["agent_handoff"]["owner_approval_request_count"], 1)
        self.assertEqual(result["agent_handoff"]["portal_package_request_count"], 1)
        self.assertEqual(result["agent_handoff"]["portal_submission_request_count"], 1)
        self.assertEqual(handoff_file["files"]["agent_handoff"], str(work_dir / "agent-handoff.json"))
        self.assertEqual(completed_file["endpoint"], "/api/pricing/approve")
        self.assertEqual(owner_report_template["source"], "owner_approval_decision_report")
        self.assertTrue(owner_report_template["template"])
        self.assertEqual(pipeline_payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(pipeline_payload["max_steps"], 0)
        self.assertNotIn("agent_work_dir", pipeline_payload)
        self.assertNotIn("compliance_rows", pipeline_payload)
        self.assertNotIn("pricing_rows", pipeline_payload)

    def test_service_rejects_workdir_export_without_directory(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "agent_work_dir"):
            service.export_agent_workdir({"profile_id": "road_civil_infrastructure"})


def _pipeline_result() -> dict:
    return {
        "pipeline": {
            "status": "waiting_on_human_input",
            "next_action": "Complete handoff actions",
        },
        "next_agent_actions": [
            {
                "action_id": "next-pricing",
                "completed_action_template": {
                    "action_id": "completed-pricing-approval",
                    "endpoint": "/api/pricing/approve",
                    "payload": {"analysis_id": "analysis-export", "approved_by": "Estimator"},
                },
            }
        ],
        "approval_actions": [
            {
                "approval_request_id": "approval-request-export",
                "opportunity_id": "RFQ-EXPORT",
                "analysis_id": "analysis-export",
                "title": "Export handoff test",
                "target_bid": 123000,
                "approval_endpoint": "/api/owner-approval/approve",
                "approval_payload": {"approval_request_id": "approval-request-export", "approved": True},
            }
        ],
        "package_directory_manifest": {
            "entries": [{"opportunity_id": "RFQ-EXPORT", "recommended_filename": "RFQ-EXPORT__official-package.pdf"}],
            "package_dir_command": "python scripts\\run_bid_pipeline.py --package-dir downloads",
        },
        "portal_package_requests": [
            {
                "request_id": "portal-package-export",
                "download_target": {"filename": "RFQ-EXPORT__official-package.pdf"},
                "completion_report_template": {
                    "source": "portal_package_download_report",
                    "request_id": "portal-package-export",
                    "opportunity_id": "RFQ-EXPORT",
                    "status": "downloaded",
                    "file_path": "<path-to-downloaded-package.pdf>",
                },
            }
        ],
        "portal_submission_requests": [
            {
                "request_id": "portal-submission-export",
                "completion_report_template": {
                    "source": "portal_submission_preparation_report",
                    "request_id": "portal-submission-export",
                    "status": "prepared_not_submitted",
                },
            }
        ],
        "generated_bid_packages": [],
    }


if __name__ == "__main__":
    unittest.main()
