from __future__ import annotations

import base64
import copy
from pathlib import Path
from typing import Any


REPORT_SOURCE = "portal_package_download_report"
READY_STATUSES = {"downloaded", "complete", "completed", "ready"}


def package_report_payloads(
    value: Any,
    *,
    profile_id: str,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    reports = portal_package_reports(value)
    if not reports:
        raise ValueError("Portal package report payload must contain at least one completed package report.")
    base_path = Path(base_dir) if base_dir is not None and str(base_dir).strip() else None
    return [
        package_report_payload(report, profile_id=profile_id, base_dir=base_path)
        for report in reports
    ]


def package_report_payload(
    report: dict[str, Any],
    *,
    profile_id: str,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    status = str(report.get("status") or "").strip().lower()
    if status and status not in READY_STATUSES:
        raise ValueError(f"Portal package report status is not downloadable: {status}")
    opportunity_id = str(report.get("opportunity_id") or "").strip()
    if not opportunity_id:
        raise ValueError("Portal package report requires an opportunity_id.")
    path = report_package_path(report, base_dir=base_dir)
    validate_package_pdf_path(path)
    request_id = str(report.get("request_id") or "").strip()
    return {
        "request_id": request_id,
        "opportunity_id": opportunity_id,
        "path": str(path),
        "payload": {
            "opportunity_id": opportunity_id,
            "profile_id": str(profile_id or "").strip(),
            "filename": path.name,
            "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "portal_package_report": report_summary(report, path=path),
        },
    }


def portal_package_reports(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if is_portal_package_report(value):
            return [copy.deepcopy(value)]
        for key in ("portal_package_report", "package_report", "report"):
            nested = value.get(key)
            if isinstance(nested, dict) and is_portal_package_report(nested):
                return [copy.deepcopy(nested)]
        for key in ("portal_package_reports", "package_reports", "reports"):
            nested_list = value.get(key)
            if isinstance(nested_list, list):
                reports = [
                    copy.deepcopy(item)
                    for item in nested_list
                    if isinstance(item, dict) and is_portal_package_report(item)
                ]
                if reports:
                    return reports
        return []
    if isinstance(value, list):
        return [
            copy.deepcopy(item)
            for item in value
            if isinstance(item, dict) and is_portal_package_report(item)
        ]
    return []


def is_portal_package_report(value: dict[str, Any]) -> bool:
    if str(value.get("source") or "") == REPORT_SOURCE:
        return True
    if str(value.get("status") or "").lower() in READY_STATUSES:
        return bool(str(value.get("opportunity_id") or "").strip() and report_package_path_value(value))
    return False


def report_package_path(report: dict[str, Any], *, base_dir: Path | None = None) -> Path:
    raw = report_package_path_value(report)
    if not raw:
        raise ValueError("Portal package report requires a downloaded PDF path.")
    path = Path(raw)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def report_package_path_value(report: dict[str, Any]) -> str:
    for key in ("file_path", "pdf_path", "downloaded_path", "path"):
        value = str(report.get(key) or "").strip()
        if value:
            return value
    files = report.get("downloaded_files")
    if isinstance(files, list):
        rows = [item for item in files if isinstance(item, dict)]
        primary = [
            item
            for item in rows
            if item.get("is_primary_package") is True
            or str(item.get("document_type") or "").strip() in {"solicitation_package", "official_package", "package"}
        ]
        for item in [*primary, *rows]:
            value = str(item.get("path") or item.get("file_path") or item.get("pdf_path") or "").strip()
            if value:
                return value
    return ""


def validate_package_pdf_path(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise ValueError(f"Package file does not exist: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Package file must be a PDF: {path}")
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        raise ValueError(f"Package file does not look like a PDF: {path}")


def report_summary(report: dict[str, Any], *, path: Path) -> dict[str, Any]:
    return {
        "source": REPORT_SOURCE,
        "request_id": str(report.get("request_id") or ""),
        "opportunity_id": str(report.get("opportunity_id") or ""),
        "status": str(report.get("status") or ""),
        "path": str(path),
        "filename": path.name,
        "notes": str(report.get("notes") or ""),
    }
