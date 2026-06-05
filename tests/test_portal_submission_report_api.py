from __future__ import annotations

import tempfile
import unittest

from contract_radar.service import ContractRadarService


class PortalSubmissionReportApiTests(unittest.TestCase):
    def test_service_records_portal_submission_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)

            result = service.record_portal_submission_report(
                {
                    "portal_submission_report": {
                        "source": "portal_submission_preparation_report",
                        "request_id": "portal-submission-request-api",
                        "generated_bid_package_id": "generated-package-api",
                        "opportunity_id": "RFQ-PORTAL-REPORT",
                        "status": "prepared_not_submitted",
                        "copied_fields": [{"field_id": "company_name", "status": "copied"}],
                        "prepared_attachments": [{"attachment_id": "insurance", "status": "prepared"}],
                        "portal_blockers": [],
                        "final_submit_clicked": False,
                    }
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)

        report = result["report"]
        self.assertEqual(result["source"], "portal_submission_report_application")
        self.assertEqual(result["recorded_report_count"], 1)
        self.assertEqual(report["request_id"], "portal-submission-request-api")
        self.assertFalse(report["final_submit_clicked"])
        self.assertTrue(report["summary"]["ready_for_human_review"])
        self.assertIn("No bid was submitted.", result["guardrails"])
        self.assertIn(report["report_id"], reloaded._portal_submission_reports)

    def test_service_rejects_submission_report_that_claims_final_submit(self) -> None:
        service = ContractRadarService()

        with self.assertRaisesRegex(ValueError, "cannot claim final buyer submission"):
            service.record_portal_submission_report(
                {
                    "source": "portal_submission_preparation_report",
                    "request_id": "portal-submission-request-api",
                    "final_submit_clicked": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
