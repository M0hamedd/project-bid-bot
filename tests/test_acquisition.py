from __future__ import annotations

import unittest

from contract_radar.acquisition import (
    CANDIDATE_URLS_FOUND_STATUS,
    MANUAL_DOWNLOAD_REQUIRED_STATUS,
    PACKAGE_UPLOADED_STATUS,
    PORTAL_REQUIRED_STATUS,
    acquisition_report,
    acquisition_status_for_opportunity,
    build_metadata_only_session,
    discover_public_package_candidates,
    expected_document_names,
)


class AcquisitionTests(unittest.TestCase):
    def test_direct_pdf_candidate_is_classified_for_automatic_fetch(self) -> None:
        opportunity = _opportunity(
            source_links={
                "source_label": "Test Portal",
                "open_data_record_url": "https://example.test/record",
                "package_pdf_url": "https://example.test/packages/rfq-1.pdf",
            }
        )

        status = acquisition_status_for_opportunity(opportunity)
        report = acquisition_report(opportunity=opportunity, status=status, now="2026-06-03T12:00:00Z")

        self.assertEqual(status, CANDIDATE_URLS_FOUND_STATUS)
        self.assertEqual(report["guidance"]["next_step"], "Fetch direct PDF candidate")
        self.assertEqual(report["guidance"]["candidate_public_package_urls"], ["https://example.test/packages/rfq-1.pdf"])
        self.assertTrue(report["package_required"])

    def test_portal_link_is_classified_as_login_required(self) -> None:
        opportunity = _opportunity(
            source_links={
                "source_label": "Toronto Bids",
                "open_data_record_url": "https://example.test/record",
                "toronto_bids_portal_url": "https://example.test/portal",
                "toronto_bids_search_hint": "Search RFQ-1 in TO Bids",
            }
        )

        session = build_metadata_only_session(
            opportunity=opportunity,
            business_profile={"profile_id": "road_civil_infrastructure"},
            now="2026-06-03T12:00:00Z",
        )

        self.assertEqual(session["acquisition"]["status"], PORTAL_REQUIRED_STATUS)
        self.assertIn("Open the buyer portal.", session["acquisition"]["guidance"]["instructions"])
        self.assertEqual(session["acquisition"]["guidance"]["portal_url"], "https://example.test/portal")

    def test_open_data_without_portal_requires_manual_download(self) -> None:
        opportunity = _opportunity(
            source_links={
                "source_label": "Open Data",
                "open_data_record_url": "https://example.test/record",
                "toronto_bids_search_hint": "Search RFQ-1 in buyer records",
            }
        )

        status = acquisition_status_for_opportunity(opportunity)
        report = acquisition_report(opportunity=opportunity, status=status, now="2026-06-03T12:00:00Z")

        self.assertEqual(status, MANUAL_DOWNLOAD_REQUIRED_STATUS)
        self.assertEqual(report["guidance"]["next_step"], "Manually download and upload package")
        self.assertTrue(report["package_required"])

    def test_uploaded_package_report_is_not_package_required(self) -> None:
        report = acquisition_report(
            opportunity=_opportunity(),
            status=PACKAGE_UPLOADED_STATUS,
            now="2026-06-03T12:00:00Z",
        )

        self.assertFalse(report["package_required"])
        self.assertEqual(report["guidance"]["next_step"], "Analyze uploaded package")

    def test_expected_document_names_include_construction_artifacts(self) -> None:
        names = expected_document_names(_opportunity(description="Road and sidewalk construction"))

        self.assertIn("RFQ-1 solicitation package", names)
        self.assertIn("pricing form", names)
        self.assertIn("drawings", names)
        self.assertIn("specifications", names)

    def test_discovers_ranked_public_pdf_candidates_from_source_page(self) -> None:
        opportunity = _opportunity(
            source_links={
                "source_label": "Buyer Source",
                "open_data_record_url": "https://example.test/bids/rfq-1",
            }
        )
        html = """
        <html>
          <body>
            <a href="/docs/rfq-1-award-summary.pdf">Award summary</a>
            <a href="/docs/rfq-1-solicitation-package.pdf">RFQ-1 solicitation package</a>
            <a href="/docs/rfq-1-addendum-1.pdf">Addendum 1</a>
          </body>
        </html>
        """

        discovery = discover_public_package_candidates(opportunity, fetcher=lambda url: html)

        self.assertEqual(discovery["source_page_urls"], ["https://example.test/bids/rfq-1"])
        self.assertEqual(discovery["attempts"][0]["status"], "fetched")
        self.assertEqual(discovery["attempts"][0]["candidate_count"], 3)
        self.assertEqual(
            discovery["candidate_public_package_urls"][:2],
            [
                "https://example.test/docs/rfq-1-solicitation-package.pdf",
                "https://example.test/docs/rfq-1-addendum-1.pdf",
            ],
        )
        self.assertNotIn("https://example.test/docs/rfq-1-award-summary.pdf", discovery["candidate_public_package_urls"])
        self.assertIn("https://example.test/docs/rfq-1-award-summary.pdf", discovery["excluded_public_pdf_urls"])
        document_types = [item["document_type"] for item in discovery["package_documents"]]
        self.assertEqual(document_types[:2], ["solicitation_package", "addendum"])
        self.assertIn("award_summary", document_types)
        self.assertEqual(discovery["package_documents"][0]["role"], "primary")
        self.assertTrue(discovery["package_document_summary"]["has_addenda"])

    def test_public_page_discovery_records_fetch_failure_without_candidates(self) -> None:
        opportunity = _opportunity(
            source_links={
                "source_label": "Buyer Source",
                "open_data_record_url": "https://example.test/bids/rfq-1",
            }
        )

        def fail(_url: str) -> str:
            raise ValueError("offline")

        discovery = discover_public_package_candidates(opportunity, fetcher=fail)

        self.assertFalse(discovery["candidate_public_package_urls"])
        self.assertEqual(discovery["attempts"][0]["status"], "fetch_failed")
        self.assertEqual(discovery["attempts"][0]["error"], "offline")


def _opportunity(
    *,
    description: str = "Road repair solicitation",
    source_links: dict | None = None,
) -> dict:
    return {
        "solicitation": {
            "document_number": "RFQ-1",
            "description": description,
            "source_links": source_links or {"source_label": "Open Data"},
        }
    }


if __name__ == "__main__":
    unittest.main()
