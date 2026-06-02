from __future__ import annotations

import base64
import tempfile
import unittest

import fitz

from contract_radar.service import ContractRadarService


class DocumentAnalysisTests(unittest.TestCase):
    def test_service_analyzes_uploaded_pdf_into_compliance_matrix(self) -> None:
        pdf_bytes = _pdf_bytes(
            [
                "Bidders must provide proof of commercial general liability insurance.",
                "A mandatory site meeting must be attended by all bidders.",
                "Bidders shall submit the completed pricing form with unit prices.",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ContractRadarService(document_storage_dir=tmpdir).analyze_document(
                {
                    "filename": "sidewalk-rfq.pdf",
                    "opportunity_id": "RFQ-123",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        self.assertEqual(result["document"]["filename"], "sidewalk-rfq.pdf")
        self.assertEqual(result["document"]["opportunity_id"], "RFQ-123")
        self.assertEqual(result["text"]["page_count"], 3)
        self.assertGreaterEqual(result["compliance_summary"]["total"], 3)
        self.assertEqual(result["compliance_summary"]["ready"], 1)
        self.assertGreaterEqual(result["compliance_summary"]["blocker"], 1)
        self.assertTrue(result["compliance_matrix"][0]["citation"]["source"])
        self.assertTrue(result["compliance_matrix"][0]["citation"]["page"])

    def test_service_rejects_invalid_base64_upload(self) -> None:
        with self.assertRaises(ValueError) as context:
            ContractRadarService().analyze_document(
                {
                    "filename": "broken.pdf",
                    "opportunity_id": "RFQ-123",
                    "content_base64": "not base64!!!",
                }
            )

        self.assertIn("base64", str(context.exception))


def _pdf_bytes(pages: list[str]) -> bytes:
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page(width=420, height=160)
            page.insert_text((36, 48), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


if __name__ == "__main__":
    unittest.main()
