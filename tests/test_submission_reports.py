from __future__ import annotations

import unittest

from contract_radar.submission_reports import build_portal_submission_reports


class PortalSubmissionReportTests(unittest.TestCase):
    def test_builds_preparation_report_without_submission(self) -> None:
        reports = build_portal_submission_reports(
            {
                "source": "portal_submission_preparation_report",
                "request_id": "portal-submission-request-1",
                "generated_bid_package_id": "generated-package-1",
                "opportunity_id": "RFQ-SUBMIT",
                "status": "prepared_not_submitted",
                "copied_fields": [{"field_id": "company_name", "status": "copied"}],
                "prepared_attachments": [{"attachment_id": "insurance", "status": "prepared"}],
                "portal_blockers": [],
                "final_submit_clicked": False,
            },
            created_at="2026-06-05T00:00:00Z",
        )

        report = reports[0]
        self.assertEqual(report["source"], "portal_submission_preparation_report")
        self.assertEqual(report["status"], "prepared_not_submitted")
        self.assertFalse(report["final_submit_clicked"])
        self.assertTrue(report["summary"]["ready_for_human_review"])
        self.assertEqual(report["summary"]["copied_field_count"], 1)

    def test_rejects_final_submit_claim(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot claim final buyer submission"):
            build_portal_submission_reports(
                {
                    "source": "portal_submission_preparation_report",
                    "request_id": "portal-submission-request-1",
                    "final_submit_clicked": True,
                },
                created_at="2026-06-05T00:00:00Z",
            )

    def test_requires_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a request_id"):
            build_portal_submission_reports(
                {
                    "source": "portal_submission_preparation_report",
                    "status": "prepared_not_submitted",
                },
                created_at="2026-06-05T00:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
