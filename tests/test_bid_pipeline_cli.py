from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from contract_radar.submission_reports import build_portal_submission_reports
from scripts.run_bid_pipeline import run_bid_pipeline_cli


class BidPipelineCliTests(unittest.TestCase):
    def test_cli_builds_agent_pipeline_payload(self) -> None:
        result = run_bid_pipeline_cli(
            [
                "--profile-id",
                "road_civil_infrastructure",
                "--max-steps",
                "3",
                "--approval-request-id",
                "approval-request-1",
                "--approved-by",
                "Owner",
                "--note",
                "Approved.",
                "--state-dir",
                "demo-state",
            ],
            service_factory=FakePipelineService,
        )

        payload = result["payload"]
        self.assertEqual(result["state_dir"], "demo-state")
        self.assertEqual(payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(payload["max_steps"], 3)
        self.assertEqual(payload["approval_request_ids"], ["approval-request-1"])
        self.assertEqual(payload["approved_by"], "Owner")
        self.assertEqual(payload["note"], "Approved.")

    def test_cli_loads_completed_action_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            action_path = Path(tmpdir) / "completed-actions.json"
            action_path.write_text(
                json.dumps(
                    [
                        {
                            "action_id": "completed-price",
                            "endpoint": "/api/pricing/approve",
                            "payload": {
                                "analysis_id": "analysis-price",
                                "approved_by": "Estimator",
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--completed-action-file",
                    str(action_path),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_id"], "completed-price")
        self.assertEqual(actions[0]["payload"]["analysis_id"], "analysis-price")

    def test_cli_loads_completed_action_directory_and_skips_handoff_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            completed_dir = directory / "completed-action-templates"
            completed_dir.mkdir()
            action = {
                "action_id": "completed-price",
                "endpoint": "/api/pricing/approve",
                "payload": {
                    "analysis_id": "analysis-price",
                    "approved_by": "Estimator",
                },
            }
            (directory / "pipeline-summary.json").write_text(json.dumps({"status": "waiting"}), encoding="utf-8")
            (directory / "completed-action-templates.json").write_text(json.dumps([action]), encoding="utf-8")
            (completed_dir / "completed-price.json").write_text(json.dumps(action), encoding="utf-8")

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--completed-action-dir",
                    str(directory),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_id"], "completed-price")
        self.assertEqual(actions[0]["endpoint"], "/api/pricing/approve")

    def test_cli_rejects_completed_action_file_without_action_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            action_path = Path(tmpdir) / "not-an-action.json"
            action_path.write_text(json.dumps({"status": "waiting"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "completed action object"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--completed-action-file",
                        str(action_path),
                    ],
                    service_factory=FakePipelineService,
                )

    def test_cli_builds_package_file_completed_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = Path(tmpdir) / "official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\n%%EOF")

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--package-file",
                    f"RFQ-PACKAGE={package_path}",
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_id"], "completed-package-upload-RFQ-PACKAGE")
        self.assertEqual(actions[0]["endpoint"], "/api/documents/analyze")
        self.assertEqual(actions[0]["payload"]["opportunity_id"], "RFQ-PACKAGE")
        self.assertEqual(actions[0]["payload"]["profile_id"], "road_civil_infrastructure")
        self.assertEqual(actions[0]["payload"]["filename"], "official-package.pdf")
        self.assertEqual(base64.b64decode(actions[0]["payload"]["content_base64"]), b"%PDF-1.4\n%%EOF")

    def test_cli_rejects_malformed_package_file_spec(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPPORTUNITY_ID=PDF_PATH"):
            run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--package-file",
                    "missing-equals.pdf",
                ],
                service_factory=FakePipelineService,
            )

    def test_cli_builds_package_dir_completed_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            first = directory / "RFQ-ONE__official-package.pdf"
            second = directory / "RFQ-TWO__addendum-package.pdf"
            first.write_bytes(b"%PDF-1.4\none\n%%EOF")
            second.write_bytes(b"%PDF-1.4\ntwo\n%%EOF")

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--package-dir",
                    str(directory),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual([action["payload"]["opportunity_id"] for action in actions], ["RFQ-ONE", "RFQ-TWO"])
        self.assertEqual(actions[0]["endpoint"], "/api/documents/analyze")
        self.assertEqual(actions[0]["payload"]["filename"], "RFQ-ONE__official-package.pdf")
        self.assertEqual(base64.b64decode(actions[1]["payload"]["content_base64"]), b"%PDF-1.4\ntwo\n%%EOF")

    def test_cli_builds_completed_action_from_portal_package_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "RFQ-REPORT__official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\nportal report\n%%EOF")
            report_path = directory / "package-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-rfq-report",
                        "opportunity_id": "RFQ-REPORT",
                        "status": "downloaded",
                        "downloaded_files": [
                            {
                                "path": package_path.name,
                                "document_type": "solicitation_package",
                                "is_primary_package": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--portal-package-report-file",
                    str(report_path),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_id"], "completed-portal-package-portal-request-rfq-report")
        self.assertEqual(actions[0]["endpoint"], "/api/documents/analyze")
        self.assertEqual(actions[0]["payload"]["opportunity_id"], "RFQ-REPORT")
        self.assertEqual(actions[0]["payload"]["filename"], "RFQ-REPORT__official-package.pdf")
        self.assertEqual(base64.b64decode(actions[0]["payload"]["content_base64"]), b"%PDF-1.4\nportal report\n%%EOF")

    def test_cli_accepts_utf8_bom_portal_package_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "RFQ-BOM__official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\nbom report\n%%EOF")
            report = json.dumps(
                {
                    "source": "portal_package_download_report",
                    "request_id": "portal-request-bom",
                    "opportunity_id": "RFQ-BOM",
                    "status": "downloaded",
                    "file_path": str(package_path),
                }
            )
            report_path = directory / "package-report.json"
            report_path.write_bytes(b"\xef\xbb\xbf" + report.encode("utf-8"))

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--portal-package-report-file",
                    str(report_path),
                ],
                service_factory=FakePipelineService,
            )

        self.assertEqual(result["payload"]["completed_actions"][0]["payload"]["opportunity_id"], "RFQ-BOM")

    def test_cli_loads_portal_package_report_directory_and_skips_request_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            reports = directory / "reports"
            reports.mkdir()
            package_path = reports / "RFQ-DIR-REPORT__official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\ndir report\n%%EOF")
            (reports / "portal-request-template.json").write_text(
                json.dumps(
                    {
                        "source": "deterministic_portal_package_request",
                        "request_id": "portal-request-template",
                    }
                ),
                encoding="utf-8",
            )
            (reports / "package-report.json").write_text(
                json.dumps(
                    {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-dir-report",
                        "opportunity_id": "RFQ-DIR-REPORT",
                        "status": "downloaded",
                        "file_path": str(package_path),
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--portal-package-report-dir",
                    str(directory),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["payload"]["opportunity_id"], "RFQ-DIR-REPORT")

    def test_cli_records_portal_submission_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "submission-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "portal_submission_preparation_report",
                        "request_id": "portal-submission-request-cli",
                        "generated_bid_package_id": "generated-package-cli",
                        "opportunity_id": "RFQ-SUBMIT-CLI",
                        "status": "prepared_not_submitted",
                        "copied_fields": [{"field_id": "company_name", "status": "copied"}],
                        "prepared_attachments": [{"attachment_id": "insurance", "status": "prepared"}],
                        "portal_blockers": [],
                        "final_submit_clicked": False,
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--portal-submission-report-file",
                    str(report_path),
                ],
                service_factory=FakeSubmissionReportService,
            )

        application = result["portal_submission_report_application"]
        self.assertEqual(application["recorded_report_count"], 1)
        self.assertEqual(application["report"]["request_id"], "portal-submission-request-cli")
        self.assertFalse(application["report"]["final_submit_clicked"])
        self.assertEqual(result["recorded_submission_report_count"], 1)

    def test_cli_loads_portal_submission_report_directory_and_skips_request_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            reports = directory / "reports"
            reports.mkdir()
            (reports / "portal-submission-request-template.json").write_text(
                json.dumps(
                    {
                        "source": "deterministic_portal_submission_request",
                        "request_id": "portal-submission-request-template",
                        "completion_report_template": {
                            "source": "portal_submission_preparation_report",
                            "request_id": "portal-submission-request-template",
                            "status": "prepared_not_submitted",
                            "final_submit_clicked": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (reports / "submission-report.json").write_text(
                json.dumps(
                    {
                        "source": "portal_submission_preparation_report",
                        "request_id": "portal-submission-request-dir",
                        "opportunity_id": "RFQ-SUBMIT-DIR",
                        "status": "ready_for_human_review",
                        "final_submit_clicked": False,
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--portal-submission-report-dir",
                    str(directory),
                ],
                service_factory=FakeSubmissionReportService,
            )

        application = result["portal_submission_report_application"]
        self.assertEqual(application["recorded_report_count"], 1)
        self.assertEqual(application["report"]["request_id"], "portal-submission-request-dir")

    def test_cli_rejects_portal_submission_report_with_final_submit_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "submission-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "portal_submission_preparation_report",
                        "request_id": "portal-submission-request-bad",
                        "final_submit_clicked": True,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot claim final buyer submission"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--portal-submission-report-file",
                        str(report_path),
                    ],
                    service_factory=FakeSubmissionReportService,
                )

    def test_cli_builds_completed_action_from_owner_approval_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "owner-approval-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "owner_approval_decision_report",
                        "approval_request_id": "approval-request-cli",
                        "approved": True,
                        "approved_by": "Casey Owner",
                        "note": "Approved for packet generation.",
                        "analysis_id": "analysis-fake-browser-id",
                        "compliance_rows": [{"requirement_id": "fake"}],
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--owner-approval-report-file",
                    str(report_path),
                ],
                service_factory=FakePipelineService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_id"], "completed-owner-approval-approval-request-cli")
        self.assertEqual(actions[0]["endpoint"], "/api/owner-approval/approve")
        self.assertEqual(
            actions[0]["payload"],
            {
                "approval_request_id": "approval-request-cli",
                "approved": True,
                "approved_by": "Casey Owner",
                "note": "Approved for packet generation.",
            },
        )

    def test_cli_rejects_owner_approval_report_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "owner-approval-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "owner_approval_decision_report",
                        "approval_request_id": "approval-request-cli",
                        "approved": False,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "approved=true"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--owner-approval-report-file",
                        str(report_path),
                    ],
                    service_factory=FakePipelineService,
                )

    def test_cli_resumes_entire_agent_work_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "agent-work"
            completed_dir = work_dir / "completed-action-templates"
            owner_approval_dir = work_dir / "owner-approval-requests"
            package_request_dir = work_dir / "portal-package-requests"
            submission_request_dir = work_dir / "portal-submission-requests"
            downloads_dir = work_dir / "downloads"
            completed_dir.mkdir(parents=True)
            owner_approval_dir.mkdir()
            package_request_dir.mkdir()
            submission_request_dir.mkdir()
            downloads_dir.mkdir()
            package_path = downloads_dir / "RFQ-RESUME__official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\nresume package\n%%EOF")
            completed_action = {
                "action_id": "completed-pricing",
                "endpoint": "/api/pricing/approve",
                "payload": {"analysis_id": "analysis-resume", "approved_by": "Estimator"},
            }
            (completed_dir / "completed-pricing.json").write_text(json.dumps(completed_action), encoding="utf-8")
            (work_dir / "pipeline-summary.json").write_text(json.dumps({"status": "waiting"}), encoding="utf-8")
            (owner_approval_dir / "approval-request-template.json").write_text(
                json.dumps(
                    {
                        "source": "deterministic_owner_approval_request_handoff",
                        "approval_request_id": "approval-request-template",
                        "approval_report_template": {
                            "source": "owner_approval_decision_report",
                            "approval_request_id": "approval-request-template",
                            "approved": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (work_dir / "owner-approval-report.json").write_text(
                json.dumps(
                    {
                        "source": "owner_approval_decision_report",
                        "approval_request_id": "approval-request-resume",
                        "approved": True,
                        "approved_by": "Owner",
                        "note": "Approved from resume dir.",
                    }
                ),
                encoding="utf-8",
            )
            (package_request_dir / "portal-package-request.json").write_text(
                json.dumps(
                    {
                        "source": "deterministic_portal_package_request",
                        "request_id": "portal-request-template",
                        "completion_report_template": {"source": "portal_package_download_report"},
                    }
                ),
                encoding="utf-8",
            )
            (work_dir / "portal-package-report.json").write_text(
                json.dumps(
                    {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-resume",
                        "opportunity_id": "RFQ-RESUME",
                        "status": "downloaded",
                        "file_path": str(package_path),
                    }
                ),
                encoding="utf-8",
            )
            (submission_request_dir / "portal-submission-request.json").write_text(
                json.dumps(
                    {
                        "source": "deterministic_portal_submission_request",
                        "request_id": "portal-submission-request-template",
                        "completion_report_template": {
                            "source": "portal_submission_preparation_report",
                            "request_id": "portal-submission-request-template",
                            "status": "prepared_not_submitted",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (work_dir / "portal-submission-report.json").write_text(
                json.dumps(
                    {
                        "source": "portal_submission_preparation_report",
                        "request_id": "portal-submission-request-resume",
                        "generated_bid_package_id": "generated-package-resume",
                        "opportunity_id": "RFQ-RESUME",
                        "status": "prepared_not_submitted",
                        "final_submit_clicked": False,
                    }
                ),
                encoding="utf-8",
            )

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--resume-agent-work-dir",
                    str(work_dir),
                ],
                service_factory=FakeSubmissionReportService,
            )

        actions = result["payload"]["completed_actions"]
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0]["action_id"], "completed-pricing")
        self.assertEqual(actions[1]["action_id"], "completed-owner-approval-approval-request-resume")
        self.assertEqual(actions[1]["payload"]["approval_request_id"], "approval-request-resume")
        self.assertEqual(actions[2]["endpoint"], "/api/documents/analyze")
        self.assertEqual(actions[2]["payload"]["opportunity_id"], "RFQ-RESUME")
        self.assertEqual(actions[2]["payload"]["filename"], "RFQ-RESUME__official-package.pdf")
        self.assertEqual(result["portal_submission_report_application"]["recorded_report_count"], 1)
        self.assertEqual(result["recorded_submission_report_count"], 1)

    def test_cli_rejects_portal_package_report_without_pdf_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "package-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-missing-path",
                        "opportunity_id": "RFQ-MISSING-PATH",
                        "status": "downloaded",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "downloaded PDF path"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--portal-package-report-file",
                        str(report_path),
                    ],
                    service_factory=FakePipelineService,
                )

    def test_cli_rejects_portal_package_report_with_non_pdf_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = Path(tmpdir) / "RFQ-BAD__official-package.pdf"
            package_path.write_bytes(b"not a pdf")
            report_path = Path(tmpdir) / "package-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-bad-pdf",
                        "opportunity_id": "RFQ-BAD",
                        "status": "downloaded",
                        "file_path": str(package_path),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not look like a PDF"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--portal-package-report-file",
                        str(report_path),
                    ],
                    service_factory=FakePipelineService,
                )

    def test_cli_rejects_package_dir_pdf_without_opportunity_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "official-package.pdf").write_bytes(b"%PDF-1.4\n%%EOF")

            with self.assertRaisesRegex(ValueError, "OPPORTUNITY_ID__anything.pdf"):
                run_bid_pipeline_cli(
                    [
                        "--profile-id",
                        "road_civil_infrastructure",
                        "--package-dir",
                        str(directory),
                    ],
                    service_factory=FakePipelineService,
                )

    def test_cli_writes_agent_handoff_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handoff_dir = Path(tmpdir) / "handoff"

            result = run_bid_pipeline_cli(
                [
                    "--profile-id",
                    "road_civil_infrastructure",
                    "--agent-work-dir",
                    str(handoff_dir),
                ],
                service_factory=FakeHandoffService,
            )

            handoff = result["agent_handoff"]
            pipeline_summary = json.loads((handoff_dir / "pipeline-summary.json").read_text(encoding="utf-8"))
            next_actions = json.loads((handoff_dir / "next-agent-actions.json").read_text(encoding="utf-8"))
            completed_actions = json.loads((handoff_dir / "completed-action-templates.json").read_text(encoding="utf-8"))
            owner_approval_requests = json.loads((handoff_dir / "owner-approval-requests.json").read_text(encoding="utf-8"))
            package_manifest = json.loads((handoff_dir / "package-directory-manifest.json").read_text(encoding="utf-8"))
            portal_requests = json.loads((handoff_dir / "portal-package-requests.json").read_text(encoding="utf-8"))
            submission_requests = json.loads((handoff_dir / "portal-submission-requests.json").read_text(encoding="utf-8"))
            packages = json.loads((handoff_dir / "generated-bid-packages.json").read_text(encoding="utf-8"))
            handoff_file = json.loads((handoff_dir / "agent-handoff.json").read_text(encoding="utf-8"))
            action_file = json.loads(
                (handoff_dir / "completed-action-templates" / "completed-price-approval.json").read_text(encoding="utf-8")
            )
            owner_approval_file = json.loads(
                (handoff_dir / "owner-approval-requests" / "approval-request-rfq-package.json").read_text(encoding="utf-8")
            )
            portal_request_file = json.loads(
                (handoff_dir / "portal-package-requests" / "portal-request-rfq-package.json").read_text(encoding="utf-8")
            )
            submission_request_file = json.loads(
                (handoff_dir / "portal-submission-requests" / "portal-submission-request-rfq-package.json").read_text(encoding="utf-8")
            )

        self.assertEqual(handoff["pipeline_status"], "waiting_on_human_input")
        self.assertEqual(handoff["completed_action_template_count"], 1)
        self.assertEqual(handoff["owner_approval_request_count"], 1)
        self.assertEqual(handoff["package_download_count"], 1)
        self.assertEqual(handoff["portal_package_request_count"], 1)
        self.assertEqual(handoff["portal_submission_request_count"], 1)
        self.assertEqual(handoff["resume_agent_work_dir"], str(handoff_dir))
        self.assertIn("--resume-agent-work-dir", handoff["resume_agent_work_command"])
        self.assertIn("--agent-work-dir", handoff["resume_agent_work_command"])
        self.assertEqual(pipeline_summary["status"], "waiting_on_human_input")
        self.assertEqual(next_actions[0]["action_id"], "next-price")
        self.assertEqual(completed_actions[0]["action_id"], "completed-price-approval")
        self.assertEqual(action_file["endpoint"], "/api/pricing/approve")
        self.assertEqual(owner_approval_requests[0]["approval_request_id"], "approval-request-rfq-package")
        self.assertEqual(owner_approval_file["approval_report_template"]["source"], "owner_approval_decision_report")
        self.assertFalse(owner_approval_file["approval_report_template"]["approved"])
        self.assertEqual(package_manifest["entries"][0]["recommended_filename"], "RFQ-PACKAGE__official-package.pdf")
        self.assertEqual(portal_requests[0]["request_id"], "portal-request-rfq-package")
        self.assertEqual(portal_request_file["download_target"]["filename"], "RFQ-PACKAGE__official-package.pdf")
        self.assertEqual(
            portal_request_file["completion_report_template"]["source"],
            "portal_package_download_report",
        )
        self.assertEqual(submission_requests[0]["request_id"], "portal-submission-request-rfq-package")
        self.assertEqual(submission_request_file["completion_report_template"]["status"], "prepared_not_submitted")
        self.assertEqual(packages[0]["generated_bid_package_id"], "generated-package-1")
        self.assertEqual(handoff_file["files"]["agent_handoff"], str(handoff_dir / "agent-handoff.json"))
        self.assertEqual(handoff_file["files"]["owner_approval_requests"], str(handoff_dir / "owner-approval-requests.json"))
        self.assertEqual(handoff_file["files"]["portal_package_requests"], str(handoff_dir / "portal-package-requests.json"))
        self.assertEqual(handoff_file["files"]["portal_submission_requests"], str(handoff_dir / "portal-submission-requests.json"))
        self.assertEqual(
            handoff_file["owner_approval_request_files"][0]["path"],
            str(handoff_dir / "owner-approval-requests" / "approval-request-rfq-package.json"),
        )
        self.assertEqual(
            handoff_file["portal_package_request_files"][0]["path"],
            str(handoff_dir / "portal-package-requests" / "portal-request-rfq-package.json"),
        )
        self.assertEqual(
            handoff_file["portal_submission_request_files"][0]["path"],
            str(handoff_dir / "portal-submission-requests" / "portal-submission-request-rfq-package.json"),
        )


class FakePipelineService:
    def __init__(self, local_state_dir: str | None = None) -> None:
        self.local_state_dir = local_state_dir

    def run_agent_pipeline(self, payload: dict) -> dict:
        return {
            "payload": payload,
            "state_dir": self.local_state_dir,
        }


class FakeSubmissionReportService(FakePipelineService):
    def __init__(self, local_state_dir: str | None = None) -> None:
        super().__init__(local_state_dir=local_state_dir)
        self.recorded_submission_reports: list[dict] = []

    def record_portal_submission_report(self, payload: dict) -> dict:
        reports = build_portal_submission_reports(
            payload.get("portal_submission_reports"),
            created_at="2026-06-05T00:00:00Z",
        )
        self.recorded_submission_reports.extend(reports)
        return {
            "source": "portal_submission_report_application",
            "recorded_report_count": len(reports),
            "reports": reports,
            "report": reports[-1] if reports else {},
        }

    def run_agent_pipeline(self, payload: dict) -> dict:
        result = super().run_agent_pipeline(payload)
        result["recorded_submission_report_count"] = len(self.recorded_submission_reports)
        return result


class FakeHandoffService:
    def run_agent_pipeline(self, payload: dict) -> dict:
        return {
            "pipeline": {
                "status": "waiting_on_human_input",
                "next_action": "Approve pricing",
            },
            "next_agent_actions": [
                {
                    "action_id": "next-price",
                    "completed_action_template": {
                        "action_id": "completed-price-approval",
                        "endpoint": "/api/pricing/approve",
                        "payload": {"analysis_id": "analysis-price", "approved_by": "Estimator"},
                    },
                }
            ],
            "approval_actions": [
                {
                    "approval_request_id": "approval-request-rfq-package",
                    "opportunity_id": "RFQ-PACKAGE",
                    "analysis_id": "analysis-rfq-package",
                    "title": "RFQ package",
                    "deadline": "2026-06-30",
                    "target_bid": 250000,
                    "approval_endpoint": "/api/owner-approval/approve",
                    "approval_payload": {
                        "approval_request_id": "approval-request-rfq-package",
                        "approved": True,
                    },
                }
            ],
            "package_directory_manifest": {
                "package_dir_command": "python scripts\\run_bid_pipeline.py --package-dir <download-dir>",
                "entries": [
                    {
                        "opportunity_id": "RFQ-PACKAGE",
                        "recommended_filename": "RFQ-PACKAGE__official-package.pdf",
                    }
                ],
            },
            "portal_package_requests": [
                {
                    "request_id": "portal-request-rfq-package",
                    "opportunity_id": "RFQ-PACKAGE",
                    "download_target": {
                        "filename": "RFQ-PACKAGE__official-package.pdf",
                    },
                    "completion_report_template": {
                        "source": "portal_package_download_report",
                    },
                }
            ],
            "generated_bid_packages": [
                {
                    "generated_bid_package_id": "generated-package-1",
                    "opportunity_id": "RFQ-PACKAGE",
                }
            ],
            "portal_submission_requests": [
                {
                    "request_id": "portal-submission-request-rfq-package",
                    "generated_bid_package_id": "generated-package-1",
                    "completion_report_template": {
                        "status": "prepared_not_submitted",
                    },
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
