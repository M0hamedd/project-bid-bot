from __future__ import annotations

import copy
import hashlib
from typing import Any


REPORT_SOURCE = "portal_submission_preparation_report"
ALLOWED_STATUSES = {
    "prepared_not_submitted",
    "blocked",
    "needs_human",
    "ready_for_human_review",
}


def build_portal_submission_reports(value: Any, *, created_at: str) -> list[dict[str, Any]]:
    reports = portal_submission_reports(value)
    if not reports:
        raise ValueError("Portal submission report payload must contain at least one preparation report.")
    return [build_portal_submission_report(report, created_at=created_at) for report in reports]


def build_portal_submission_report(report: dict[str, Any], *, created_at: str) -> dict[str, Any]:
    status = str(report.get("status") or "prepared_not_submitted").strip() or "prepared_not_submitted"
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported portal submission report status: {status}")
    if bool(report.get("final_submit_clicked")):
        raise ValueError("Portal submission reports cannot claim final buyer submission.")
    request_id = str(report.get("request_id") or "").strip()
    package_id = str(report.get("generated_bid_package_id") or "").strip()
    opportunity_id = str(report.get("opportunity_id") or "").strip()
    if not request_id and not package_id and not opportunity_id:
        raise ValueError("Portal submission report requires a request_id, generated_bid_package_id, or opportunity_id.")
    copied_fields = _rows(report.get("copied_fields"))
    prepared_attachments = _rows(report.get("prepared_attachments"))
    blockers = _string_rows(report.get("portal_blockers"))
    report_id = str(report.get("report_id") or "").strip() or _report_id(
        request_id,
        package_id,
        opportunity_id,
        copied_fields,
        prepared_attachments,
        blockers,
    )
    return {
        "report_id": report_id,
        "source": REPORT_SOURCE,
        "request_id": request_id,
        "generated_bid_package_id": package_id,
        "opportunity_id": opportunity_id,
        "status": status,
        "copied_fields": copied_fields,
        "prepared_attachments": prepared_attachments,
        "portal_blockers": blockers,
        "final_submit_clicked": False,
        "notes": str(report.get("notes") or "").strip(),
        "created_at": str(report.get("created_at") or created_at),
        "updated_at": created_at,
        "summary": {
            "copied_field_count": len(copied_fields),
            "prepared_attachment_count": len(prepared_attachments),
            "blocker_count": len(blockers),
            "ready_for_human_review": status in {"prepared_not_submitted", "ready_for_human_review"} and not blockers,
        },
        "guardrails": [
            "No bid was submitted.",
            "Final buyer portal submit/certify controls were not clicked.",
            "A human must perform final review and submission.",
        ],
    }


def portal_submission_reports(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if is_portal_submission_report(value):
            return [copy.deepcopy(value)]
        for key in ("portal_submission_report", "submission_report", "report"):
            nested = value.get(key)
            if isinstance(nested, dict) and is_portal_submission_report(nested):
                return [copy.deepcopy(nested)]
        for key in ("portal_submission_reports", "submission_reports", "reports"):
            nested_list = value.get(key)
            if isinstance(nested_list, list):
                reports = [
                    copy.deepcopy(item)
                    for item in nested_list
                    if isinstance(item, dict) and is_portal_submission_report(item)
                ]
                if reports:
                    return reports
        return []
    if isinstance(value, list):
        return [
            copy.deepcopy(item)
            for item in value
            if isinstance(item, dict) and is_portal_submission_report(item)
        ]
    return []


def is_portal_submission_report(value: dict[str, Any]) -> bool:
    if str(value.get("source") or "") == REPORT_SOURCE:
        return True
    identity = str(value.get("request_id") or value.get("generated_bid_package_id") or value.get("opportunity_id") or "").strip()
    if str(value.get("status") or "") in ALLOWED_STATUSES and identity:
        return True
    return bool(value.get("final_submit_clicked") is not None and identity)


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(item) for item in value if isinstance(item, dict)]


def _string_rows(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _report_id(*parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"portal-submission-report-{digest}"
