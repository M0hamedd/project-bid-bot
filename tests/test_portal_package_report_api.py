from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contract_radar.service import ContractRadarService


class PortalPackageReportApiTests(unittest.TestCase):
    def test_service_applies_portal_package_report_to_analysis_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "RFQ-API-REPORT__official-package.pdf"
            _write_pdf(
                package_path,
                [
                    "Bidders must submit the completed pricing form with unit prices.",
                    "Bidders must provide proof of commercial general liability insurance.",
                ],
            )
            service = ContractRadarService(local_state_dir=directory / "state", document_storage_dir=directory / "docs")

            result = service.apply_portal_package_report(
                {
                    "profile_id": "road_civil_infrastructure",
                    "portal_package_report": {
                        "source": "portal_package_download_report",
                        "request_id": "portal-request-api",
                        "opportunity_id": "RFQ-API-REPORT",
                        "status": "downloaded",
                        "downloaded_files": [
                            {
                                "path": package_path.name,
                                "document_type": "solicitation_package",
                                "is_primary_package": True,
                            }
                        ],
                    },
                    "base_dir": str(directory),
                }
            )

            reloaded = ContractRadarService(local_state_dir=directory / "state", document_storage_dir=directory / "docs")

        analysis = result["analysis"]
        applied = result["applied_reports"][0]
        self.assertEqual(result["source"], "portal_package_report_application")
        self.assertEqual(result["applied_report_count"], 1)
        self.assertEqual(applied["request_id"], "portal-request-api")
        self.assertEqual(applied["endpoint"], "/api/documents/analyze")
        self.assertEqual(analysis["opportunity_id"], "RFQ-API-REPORT")
        self.assertEqual(analysis["portal_package_report"]["request_id"], "portal-request-api")
        self.assertGreaterEqual(len(analysis["compliance_matrix"]), 1)
        self.assertIn("No bid was submitted.", result["guardrails"])
        persisted = reloaded._document_analysis_sessions[analysis["analysis_id"]]
        self.assertEqual(persisted["portal_package_report"]["request_id"], "portal-request-api")

    def test_service_can_resume_pipeline_after_package_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "RFQ-RESUME-REPORT__official-package.pdf"
            _write_pdf(package_path, ["Bidders must submit the completed pricing form with unit prices."])
            service = ContractRadarService(local_state_dir=directory / "state", document_storage_dir=directory / "docs")

            with patch.object(
                service,
                "run_agent_pipeline",
                return_value={
                    "pipeline": {"status": "waiting_on_human_input"},
                    "next_agent_actions": [{"action_id": "next-action-pricing"}],
                    "generated_bid_packages": [],
                },
            ) as pipeline:
                result = service.apply_portal_package_report(
                    {
                        "profile_id": "road_civil_infrastructure",
                        "priority_mode": "best_win_chance",
                        "max_steps": 3,
                        "resume_pipeline": True,
                        "portal_package_report": {
                            "source": "portal_package_download_report",
                            "request_id": "portal-request-resume",
                            "opportunity_id": "RFQ-RESUME-REPORT",
                            "status": "downloaded",
                            "file_path": str(package_path),
                        },
                    }
                )

        self.assertTrue(result["pipeline_resumed"])
        self.assertEqual(result["pipeline_result"]["pipeline"]["status"], "waiting_on_human_input")
        self.assertEqual(result["next_agent_actions"][0]["action_id"], "next-action-pricing")
        pipeline_payload = pipeline.call_args.args[0]
        self.assertEqual(pipeline_payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(pipeline_payload["max_steps"], 3)
        self.assertNotIn("portal_package_report", pipeline_payload)
        self.assertNotIn("resume_pipeline", pipeline_payload)

    def test_service_rejects_empty_portal_package_report_payload(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "at least one completed package report"):
            service.apply_portal_package_report({"profile_id": "road_civil_infrastructure", "reports": []})


def _write_pdf(path: Path, lines: list[str]) -> None:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - test environment should install requirements.
        raise RuntimeError("PyMuPDF is required for PDF tests.") from exc

    document = fitz.open()
    try:
        page = document.new_page(width=480, height=240)
        y = 48
        for line in lines:
            page.insert_text((36, y), line, fontsize=11)
            y += 24
        document.save(path)
    finally:
        document.close()


if __name__ == "__main__":
    unittest.main()
