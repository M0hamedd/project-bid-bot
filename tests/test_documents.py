from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from contract_radar.documents import (
    DocumentStore,
    UnsupportedDocumentError,
    solicitation_package_upload_api_spec,
    store_solicitation_pdf,
)


class DocumentStorageTests(unittest.TestCase):
    def test_pdf_upload_stores_file_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = Path(tmpdir)
            content = _pdf_bytes("solicitation package")
            uploaded_at = datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc)

            metadata = DocumentStore(storage_dir).store_pdf(
                filename="RFQ-123.pdf",
                content=content,
                opportunity_id="RFQ-123",
                uploaded_at=uploaded_at,
            )

            content_hash = hashlib.sha256(content).hexdigest()
            stored_file = storage_dir / "files" / f"{content_hash}.pdf"
            index_payload = json.loads((storage_dir / "documents.json").read_text(encoding="utf-8"))

            self.assertEqual(metadata.filename, "RFQ-123.pdf")
            self.assertEqual(metadata.content_hash, content_hash)
            self.assertEqual(metadata.size, len(content))
            self.assertEqual(metadata.uploaded_at, "2026-06-02T18:00:00Z")
            self.assertEqual(metadata.opportunity_id, "RFQ-123")
            self.assertEqual(metadata.storage_key, f"files/{content_hash}.pdf")
            self.assertFalse(metadata.deduplicated)
            self.assertEqual(stored_file.read_bytes(), content)
            self.assertEqual(index_payload["documents"][content_hash]["filename"], "RFQ-123.pdf")
            self.assertEqual(index_payload["documents"][content_hash]["opportunity_id"], "RFQ-123")

    def test_repeated_pdf_upload_is_deduplicated_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = Path(tmpdir)
            store = DocumentStore(storage_dir)
            content = _pdf_bytes("duplicate package")
            first = store.store_pdf(
                filename="original.pdf",
                content=content,
                opportunity_id="RFQ-123",
                uploaded_at=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
            )
            second = store.store_pdf(
                filename="renamed.pdf",
                content=content,
                opportunity_id="RFQ-999",
                uploaded_at=datetime(2026, 6, 2, 19, 0, tzinfo=timezone.utc),
            )
            stored_files = list((storage_dir / "files").glob("*.pdf"))

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertTrue(second.deduplicated)
        self.assertEqual(second.filename, "original.pdf")
        self.assertEqual(second.opportunity_id, "RFQ-123")
        self.assertEqual(second.uploaded_at, "2026-06-02T18:00:00Z")
        self.assertEqual(len(stored_files), 1)

    def test_helper_accepts_pdf_bytes_for_api_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = store_solicitation_pdf(
                filename="package.pdf",
                content=_pdf_bytes("api helper"),
                opportunity_id="RFQ-API",
                storage_dir=tmpdir,
            )

        self.assertEqual(metadata["filename"], "package.pdf")
        self.assertEqual(metadata["opportunity_id"], "RFQ-API")
        self.assertEqual(metadata["mime_type"], "application/pdf")
        self.assertIn("content_hash", metadata)

    def test_rejects_non_pdf_filename_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(UnsupportedDocumentError) as context:
                DocumentStore(tmpdir).store_pdf(
                    filename="scope.txt",
                    content=_pdf_bytes("wrong extension"),
                    opportunity_id="RFQ-123",
                )

        self.assertIn("only PDF files are accepted", str(context.exception))

    def test_rejects_non_pdf_content_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(UnsupportedDocumentError) as context:
                DocumentStore(tmpdir).store_pdf(
                    filename="scope.pdf",
                    content=b"This is not a PDF",
                    opportunity_id="RFQ-123",
                )

        self.assertIn("file content is not a PDF", str(context.exception))

    def test_api_spec_documents_future_multipart_route(self) -> None:
        spec = solicitation_package_upload_api_spec()

        self.assertEqual(spec["method"], "POST")
        self.assertEqual(spec["path"], "/api/opportunities/{opportunity_id}/documents")
        self.assertEqual(spec["content_type"], "multipart/form-data")
        self.assertEqual(spec["accepted_mime_types"], ["application/pdf"])
        self.assertIn("content_hash", spec["response_metadata"])


def _pdf_bytes(label: str) -> bytes:
    return f"%PDF-1.4\n1 0 obj\n<< /Title ({label}) >>\nendobj\n%%EOF\n".encode("utf-8")


if __name__ == "__main__":
    unittest.main()
