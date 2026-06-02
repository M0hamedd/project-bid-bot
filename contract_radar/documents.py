from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from contract_radar import config


DEFAULT_DOCUMENT_STORAGE_DIR = Path(
    os.getenv("CONTRACT_RADAR_DOCUMENT_STORAGE_DIR", config.ROOT_DIR / "data" / "uploads")
)
INDEX_FILENAME = "documents.json"
PDF_MIME_TYPE = "application/pdf"


class DocumentUploadError(ValueError):
    """Base error for solicitation package upload failures."""


class UnsupportedDocumentError(DocumentUploadError):
    """Raised when an upload is not a supported PDF document."""


@dataclass(frozen=True)
class DocumentMetadata:
    filename: str
    content_hash: str
    size: int
    uploaded_at: str
    opportunity_id: str
    storage_key: str
    mime_type: str = PDF_MIME_TYPE
    deduplicated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, deduplicated: bool = False) -> "DocumentMetadata":
        return cls(
            filename=str(payload["filename"]),
            content_hash=str(payload["content_hash"]),
            size=int(payload["size"]),
            uploaded_at=str(payload["uploaded_at"]),
            opportunity_id=str(payload["opportunity_id"]),
            storage_key=str(payload["storage_key"]),
            mime_type=str(payload.get("mime_type") or PDF_MIME_TYPE),
            deduplicated=deduplicated,
        )


class DocumentStore:
    def __init__(self, storage_dir: Path | str | None = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir is not None else DEFAULT_DOCUMENT_STORAGE_DIR
        self.files_dir = self.storage_dir / "files"
        self.index_path = self.storage_dir / INDEX_FILENAME

    def store_pdf(
        self,
        *,
        filename: str,
        content: bytes,
        opportunity_id: str,
        uploaded_at: datetime | None = None,
    ) -> DocumentMetadata:
        safe_filename = _clean_filename(filename)
        opportunity = _clean_opportunity_id(opportunity_id)
        _validate_pdf_upload(safe_filename, content)

        content_hash = hashlib.sha256(content).hexdigest()
        storage_key = f"files/{content_hash}.pdf"
        document_path = self.storage_dir / storage_key

        self.files_dir.mkdir(parents=True, exist_ok=True)
        index = self._read_index()
        documents = index.setdefault("documents", {})
        existing = documents.get(content_hash)
        if isinstance(existing, dict):
            if not document_path.exists():
                document_path.write_bytes(content)
            return DocumentMetadata.from_dict(existing, deduplicated=True)

        if not document_path.exists():
            document_path.write_bytes(content)

        metadata = DocumentMetadata(
            filename=safe_filename,
            content_hash=content_hash,
            size=len(content),
            uploaded_at=_utc_timestamp(uploaded_at),
            opportunity_id=opportunity,
            storage_key=storage_key,
        )
        documents[content_hash] = _index_payload(metadata)
        self._write_index(index)
        return metadata

    def metadata_for_hash(self, content_hash: str) -> DocumentMetadata | None:
        payload = self._read_index().get("documents", {}).get(content_hash)
        if not isinstance(payload, dict):
            return None
        return DocumentMetadata.from_dict(payload)

    def _read_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"documents": {}}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DocumentUploadError(f"Document metadata index is not valid JSON: {self.index_path}") from exc
        if not isinstance(payload, dict):
            raise DocumentUploadError(f"Document metadata index must be a JSON object: {self.index_path}")
        documents = payload.setdefault("documents", {})
        if not isinstance(documents, dict):
            raise DocumentUploadError(f"Document metadata index has an invalid documents section: {self.index_path}")
        return payload

    def _write_index(self, payload: dict[str, Any]) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.index_path)


def store_solicitation_pdf(
    *,
    filename: str,
    content: bytes,
    opportunity_id: str,
    storage_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Backend helper for future multipart/API wiring."""
    metadata = DocumentStore(storage_dir).store_pdf(
        filename=filename,
        content=content,
        opportunity_id=opportunity_id,
    )
    return metadata.to_dict()


def solicitation_package_upload_api_spec() -> dict[str, Any]:
    return {
        "method": "POST",
        "path": "/api/opportunities/{opportunity_id}/documents",
        "content_type": "multipart/form-data",
        "file_field": "file",
        "accepted_mime_types": [PDF_MIME_TYPE],
        "backend_helper": "contract_radar.documents.store_solicitation_pdf",
        "response_metadata": [
            "filename",
            "content_hash",
            "size",
            "uploaded_at",
            "opportunity_id",
            "storage_key",
            "mime_type",
            "deduplicated",
        ],
    }


def _validate_pdf_upload(filename: str, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise UnsupportedDocumentError("Solicitation package upload must provide PDF bytes.")
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedDocumentError(
            f"Unsupported solicitation package '{filename}': only PDF files are accepted."
        )
    if not content:
        raise UnsupportedDocumentError(f"Unsupported solicitation package '{filename}': PDF content is empty.")
    if not content.startswith(b"%PDF-"):
        raise UnsupportedDocumentError(
            f"Unsupported solicitation package '{filename}': file content is not a PDF."
        )


def _clean_filename(filename: str) -> str:
    text = str(filename or "").replace("\x00", "").strip()
    name = PurePosixPath(PureWindowsPath(text).name).name
    if not name:
        raise DocumentUploadError("A filename is required for solicitation package upload.")
    return name


def _clean_opportunity_id(opportunity_id: str) -> str:
    text = str(opportunity_id or "").strip()
    if not text:
        raise DocumentUploadError("An opportunity_id is required for solicitation package upload.")
    return text


def _utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _index_payload(metadata: DocumentMetadata) -> dict[str, Any]:
    payload = metadata.to_dict()
    payload.pop("deduplicated", None)
    return payload
