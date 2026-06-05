from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class AgentWorkdirResumeApiTests(unittest.TestCase):
    def test_service_resumes_pipeline_from_agent_workdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            work_dir = directory / "agent-work"
            work_dir.mkdir()
            _write_json(
                work_dir / "owner-approval-report.json",
                {
                    "source": "owner_approval_decision_report",
                    "approval_request_id": "approval-request-api-workdir",
                    "approved": True,
                    "approved_by": "Owner",
                    "note": "Approved through workdir API.",
                    "analysis_id": "fake-browser-analysis",
                    "compliance_rows": [{"requirement_id": "fake"}],
                    "pricing_rows": [{"line_item_id": "fake"}],
                },
            )
            _write_json(
                work_dir / "portal-submission-report.json",
                {
                    "source": "portal_submission_preparation_report",
                    "request_id": "portal-submission-request-api-workdir",
                    "generated_bid_package_id": "generated-package-api-workdir",
                    "opportunity_id": "RFQ-API-WORKDIR",
                    "status": "prepared_not_submitted",
                    "copied_fields": [{"field_id": "company_name", "status": "copied"}],
                    "prepared_attachments": [],
                    "portal_blockers": [],
                    "final_submit_clicked": False,
                },
            )
            service = ContractRadarService(local_state_dir=directory / "state")

            with patch.object(
                service,
                "run_agent_pipeline",
                return_value={
                    "pipeline": {"status": "packets_generated"},
                    "applied_actions": [{"endpoint": "/api/owner-approval/approve"}],
                    "action_application_errors": [],
                    "next_agent_actions": [{"action_id": "download-packet"}],
                    "generated_bid_packages": [{"generated_bid_package_id": "generated-package-api-workdir"}],
                },
            ) as pipeline:
                result = service.resume_agent_workdir(
                    {
                        "agent_work_dir": str(work_dir),
                        "profile_id": "road_civil_infrastructure",
                        "max_steps": 2,
                        "compliance_rows": [{"requirement_id": "fake-browser-row"}],
                    }
                )
            reloaded = ContractRadarService(local_state_dir=directory / "state")

        pipeline_payload = pipeline.call_args.args[0]
        actions = pipeline_payload["completed_actions"]
        self.assertEqual(result["source"], "agent_workdir_resume")
        self.assertEqual(result["artifact_summary"]["completed_action_count"], 1)
        self.assertEqual(result["artifact_summary"]["portal_submission_report_count"], 1)
        self.assertEqual(result["submission_report_application"]["recorded_report_count"], 1)
        self.assertEqual(result["next_agent_actions"][0]["action_id"], "download-packet")
        self.assertEqual(result["generated_bid_packages"][0]["generated_bid_package_id"], "generated-package-api-workdir")
        self.assertEqual(pipeline_payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(pipeline_payload["max_steps"], 2)
        self.assertNotIn("compliance_rows", pipeline_payload)
        self.assertEqual(actions[0]["endpoint"], "/api/owner-approval/approve")
        self.assertNotIn("analysis_id", actions[0]["payload"])
        self.assertNotIn("pricing_rows", actions[0]["payload"])
        self.assertEqual(len(reloaded._portal_submission_reports), 1)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
