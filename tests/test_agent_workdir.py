from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contract_radar.agent_workdir import agent_work_dirs, load_agent_workdir_artifacts


class AgentWorkdirTests(unittest.TestCase):
    def test_loader_collects_completed_artifacts_and_skips_unfilled_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            package_path = work_dir / "downloads" / "RFQ-WORKDIR__official-package.pdf"
            package_path.parent.mkdir()
            package_path.write_bytes(b"%PDF-1.4\nworkdir package\n%%EOF")
            completed_dir = work_dir / "completed-action-templates"
            completed_dir.mkdir()
            _write_json(
                completed_dir / "completed-pricing.json",
                {
                    "action_id": "completed-pricing-workdir",
                    "endpoint": "/api/pricing/approve",
                    "payload": {"analysis_id": "analysis-workdir", "approved_by": "Estimator"},
                },
            )
            _write_json(
                work_dir / "owner-approval-report.json",
                {
                    "source": "owner_approval_decision_report",
                    "approval_request_id": "approval-request-workdir",
                    "approved": True,
                    "approved_by": "Owner",
                    "note": "Approved from workdir.",
                    "compliance_rows": [{"requirement_id": "fake-browser-row"}],
                },
            )
            _write_json(
                work_dir / "package-report.json",
                {
                    "source": "portal_package_download_report",
                    "request_id": "portal-request-workdir",
                    "opportunity_id": "RFQ-WORKDIR",
                    "status": "downloaded",
                    "file_path": str(package_path),
                },
            )
            _write_json(
                work_dir / "portal-submission-report.json",
                {
                    "source": "portal_submission_preparation_report",
                    "request_id": "portal-submission-request-workdir",
                    "generated_bid_package_id": "generated-package-workdir",
                    "opportunity_id": "RFQ-WORKDIR",
                    "status": "prepared_not_submitted",
                    "copied_fields": [{"field_id": "company_name", "status": "copied"}],
                    "prepared_attachments": [{"attachment_id": "package", "status": "prepared"}],
                    "portal_blockers": [],
                    "final_submit_clicked": False,
                },
            )
            _write_json(
                work_dir / "report-templates.json",
                {
                    "reports": [
                        {
                            "source": "owner_approval_decision_report",
                            "approval_request_id": "approval-request-template",
                            "template": True,
                        },
                        {
                            "source": "portal_package_download_report",
                            "request_id": "portal-request-template",
                            "opportunity_id": "RFQ-TEMPLATE",
                            "status": "downloaded",
                            "file_path": "<path-to-downloaded-package.pdf>",
                            "template": True,
                        },
                        {
                            "source": "portal_submission_preparation_report",
                            "request_id": "portal-submission-template",
                            "status": "prepared_not_submitted",
                            "template": True,
                        },
                    ]
                },
            )

            result = load_agent_workdir_artifacts(str(work_dir), profile_id="road_civil_infrastructure")

        actions = result["completed_actions"]
        endpoints = [action["endpoint"] for action in actions]
        self.assertEqual(result["summary"]["work_dir_count"], 1)
        self.assertEqual(result["summary"]["completed_action_count"], 3)
        self.assertEqual(result["summary"]["portal_submission_report_count"], 1)
        self.assertEqual(endpoints.count("/api/documents/analyze"), 1)
        self.assertIn("/api/pricing/approve", endpoints)
        self.assertIn("/api/owner-approval/approve", endpoints)
        owner_action = next(action for action in actions if action["endpoint"] == "/api/owner-approval/approve")
        self.assertNotIn("compliance_rows", owner_action["payload"])
        document_action = next(action for action in actions if action["endpoint"] == "/api/documents/analyze")
        self.assertEqual(document_action["action_id"], "completed-portal-package-portal-request-workdir")
        self.assertEqual(document_action["payload"]["opportunity_id"], "RFQ-WORKDIR")
        self.assertEqual(
            result["portal_submission_reports"][0]["request_id"],
            "portal-submission-request-workdir",
        )

    def test_agent_work_dirs_rejects_missing_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            agent_work_dirs("does-not-exist")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
