from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAGE_TEXT_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class PageTextChunk:
    page_number: int
    text: str
    char_start: int
    char_end: int
    source_filename: str | None = None
    source_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "source_filename": self.source_filename,
            "source_hash": self.source_hash,
        }


class PDFTextExtractionError(RuntimeError):
    pass


class ScannedPDFError(PDFTextExtractionError):
    pass


PdfSource = bytes | bytearray | memoryview | str | Path


def extract_pdf_text(
    source: PdfSource,
    *,
    source_filename: str | None = None,
    source_hash: str | None = None,
) -> list[PageTextChunk]:
    """Extract deterministic page text chunks from PDF bytes or a local PDF path."""
    fitz = _load_pymupdf()
    path = _source_path(source)
    effective_filename = source_filename or (path.name if path else None)

    try:
        if path is not None:
            document = fitz.open(str(path))
        else:
            document = fitz.open(stream=bytes(source), filetype="pdf")
    except Exception as exc:
        raise PDFTextExtractionError(f"Could not open PDF for text extraction: {exc}") from exc

    try:
        chunks = _extract_page_chunks(
            document,
            source_filename=effective_filename,
            source_hash=source_hash,
        )
    finally:
        document.close()

    if not chunks:
        label = f" {effective_filename}" if effective_filename else ""
        raise ScannedPDFError(
            f"No extractable text found in PDF{label}; it may be scanned or image-only and requires OCR."
        )

    return chunks


def extract_pdf_text_from_bytes(
    pdf_bytes: bytes | bytearray | memoryview,
    *,
    source_filename: str | None = None,
    source_hash: str | None = None,
) -> list[PageTextChunk]:
    return extract_pdf_text(pdf_bytes, source_filename=source_filename, source_hash=source_hash)


def extract_pdf_text_from_path(
    path: str | Path,
    *,
    source_filename: str | None = None,
    source_hash: str | None = None,
) -> list[PageTextChunk]:
    return extract_pdf_text(path, source_filename=source_filename, source_hash=source_hash)


def _extract_page_chunks(
    document: Any,
    *,
    source_filename: str | None,
    source_hash: str | None,
) -> list[PageTextChunk]:
    chunks: list[PageTextChunk] = []
    offset = 0

    for index, page in enumerate(document, start=1):
        text = _normalize_page_text(page.get_text("text", sort=True))
        if not text:
            continue

        char_start = offset
        char_end = char_start + len(text)
        chunks.append(
            PageTextChunk(
                page_number=index,
                text=text,
                char_start=char_start,
                char_end=char_end,
                source_filename=source_filename,
                source_hash=source_hash,
            )
        )
        offset = char_end + len(PAGE_TEXT_SEPARATOR)

    return chunks


def _normalize_page_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def _source_path(source: PdfSource) -> Path | None:
    if isinstance(source, (str, Path)):
        return Path(source)
    return None


def _load_pymupdf() -> Any:
    try:
        import fitz
    except ImportError as exc:
        raise PDFTextExtractionError("PyMuPDF is required for PDF text extraction.") from exc
    return fitz
