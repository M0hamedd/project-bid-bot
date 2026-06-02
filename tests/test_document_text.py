from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from contract_radar.document_text import (
    PAGE_TEXT_SEPARATOR,
    ScannedPDFError,
    extract_pdf_text,
    extract_pdf_text_from_bytes,
    extract_pdf_text_from_path,
)


class DocumentTextTests(unittest.TestCase):
    def test_extracts_pdf_bytes_as_page_chunks_with_citation_metadata(self) -> None:
        pdf_bytes = _text_pdf_bytes(
            [
                "Road repairs tender\nMandatory site meeting",
                "Bid bond and insurance requirements",
            ]
        )

        chunks = extract_pdf_text_from_bytes(
            pdf_bytes,
            source_filename="rfq-road-repairs.pdf",
            source_hash="sha256:testhash",
        )

        self.assertEqual([chunk.page_number for chunk in chunks], [1, 2])
        self.assertIn("Road repairs tender", chunks[0].text)
        self.assertIn("Bid bond", chunks[1].text)
        self.assertEqual(chunks[0].source_filename, "rfq-road-repairs.pdf")
        self.assertEqual(chunks[0].source_hash, "sha256:testhash")
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[0].char_end, len(chunks[0].text))
        self.assertEqual(chunks[1].char_start, chunks[0].char_end + len(PAGE_TEXT_SEPARATOR))
        self.assertEqual(chunks[1].char_end, chunks[1].char_start + len(chunks[1].text))

        repeated = extract_pdf_text(pdf_bytes, source_filename="rfq-road-repairs.pdf", source_hash="sha256:testhash")
        self.assertEqual([chunk.to_dict() for chunk in chunks], [chunk.to_dict() for chunk in repeated])

    def test_extracts_pdf_path_and_uses_filename_when_not_supplied(self) -> None:
        pdf_bytes = _text_pdf_bytes(["Site servicing and sidewalk restoration"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notice.pdf"
            path.write_bytes(pdf_bytes)

            chunks = extract_pdf_text_from_path(path)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].page_number, 1)
        self.assertEqual(chunks[0].source_filename, "notice.pdf")
        self.assertIsNone(chunks[0].source_hash)
        self.assertIn("sidewalk restoration", chunks[0].text)

    def test_image_only_pdf_raises_clear_scanned_pdf_failure(self) -> None:
        with self.assertRaises(ScannedPDFError) as context:
            extract_pdf_text(_image_only_pdf_bytes(), source_filename="scan.pdf")

        message = str(context.exception).lower()
        self.assertIn("no extractable text", message)
        self.assertIn("scanned", message)
        self.assertIn("image-only", message)
        self.assertIn("ocr", message)
        self.assertIn("scan.pdf", message)


def _text_pdf_bytes(pages: list[str]) -> bytes:
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page(width=320, height=160)
            page.insert_text((36, 48), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def _image_only_pdf_bytes() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=160, height=160)
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 16), False)
        pixmap.clear_with(0xDDDDDD)
        page.insert_image(fitz.Rect(32, 32, 128, 128), pixmap=pixmap)
        return document.tobytes()
    finally:
        document.close()


if __name__ == "__main__":
    unittest.main()
