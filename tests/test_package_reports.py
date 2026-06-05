from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from contract_radar.package_reports import package_report_payloads, portal_package_reports


class PackageReportTests(unittest.TestCase):
    def test_package_report_payloads_resolve_relative_primary_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "RFQ-REPORT__official-package.pdf"
            package_path.write_bytes(b"%PDF-1.4\nreport\n%%EOF")

            payloads = package_report_payloads(
                {
                    "source": "portal_package_download_report",
                    "request_id": "portal-request-1",
                    "opportunity_id": "RFQ-REPORT",
                    "status": "downloaded",
                    "downloaded_files": [
                        {
                            "path": package_path.name,
                            "document_type": "solicitation_package",
                            "is_primary_package": True,
                        }
                    ],
                },
                profile_id="road_civil_infrastructure",
                base_dir=directory,
            )

        payload = payloads[0]["payload"]
        self.assertEqual(payloads[0]["request_id"], "portal-request-1")
        self.assertEqual(payload["opportunity_id"], "RFQ-REPORT")
        self.assertEqual(payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(payload["filename"], "RFQ-REPORT__official-package.pdf")
        self.assertEqual(base64.b64decode(payload["content_base64"]), b"%PDF-1.4\nreport\n%%EOF")
        self.assertEqual(payload["portal_package_report"]["source"], "portal_package_download_report")

    def test_portal_package_reports_accept_wrapped_reports(self) -> None:
        reports = portal_package_reports(
            {
                "portal_package_reports": [
                    {
                        "source": "portal_package_download_report",
                        "opportunity_id": "RFQ-ONE",
                        "status": "downloaded",
                        "file_path": "one.pdf",
                    },
                    {"source": "deterministic_portal_package_request"},
                ]
            }
        )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["opportunity_id"], "RFQ-ONE")

    def test_package_report_rejects_non_pdf_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            package_path = directory / "not-package.pdf"
            package_path.write_bytes(b"not a pdf")

            with self.assertRaisesRegex(ValueError, "does not look like a PDF"):
                package_report_payloads(
                    {
                        "source": "portal_package_download_report",
                        "opportunity_id": "RFQ-BAD",
                        "status": "downloaded",
                        "file_path": str(package_path),
                    },
                    profile_id="road_civil_infrastructure",
                )


if __name__ == "__main__":
    unittest.main()
