from __future__ import annotations

from typing import Any


REPORT_SOURCE = "owner_approval_decision_report"


def owner_approval_actions(value: Any, *, skip_templates: bool = False) -> list[dict[str, Any]]:
    reports = owner_approval_reports(value)
    actions: list[dict[str, Any]] = []
    for report in reports:
        if skip_templates and is_unfilled_template(report):
            continue
        actions.append(owner_approval_action_from_report(report))
    return actions


def owner_approval_reports(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if is_owner_approval_report(value):
            return [dict(value)]
        for key in ("owner_approval_report", "approval_report", "report"):
            nested = value.get(key)
            if isinstance(nested, dict) and is_owner_approval_report(nested):
                return [dict(nested)]
        for key in ("owner_approval_reports", "approval_reports", "reports"):
            nested_list = value.get(key)
            if isinstance(nested_list, list):
                reports = [dict(item) for item in nested_list if isinstance(item, dict) and is_owner_approval_report(item)]
                if reports:
                    return reports
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict) and is_owner_approval_report(item)]
    return []


def is_owner_approval_report(value: dict[str, Any]) -> bool:
    if str(value.get("source") or "") == REPORT_SOURCE:
        return True
    return bool(str(value.get("approval_request_id") or "").strip() and "approved" in value)


def owner_approval_action_from_report(report: dict[str, Any]) -> dict[str, Any]:
    approval_request_id = str(report.get("approval_request_id") or "").strip()
    if not approval_request_id:
        raise ValueError("Owner approval report requires an approval_request_id.")
    if report.get("approved") is not True:
        raise ValueError("Owner approval report must have approved=true to generate a packet.")
    return {
        "action_id": f"completed-owner-approval-{approval_request_id}",
        "endpoint": "/api/owner-approval/approve",
        "payload": {
            "approval_request_id": approval_request_id,
            "approved": True,
            "approved_by": str(report.get("approved_by") or "Owner"),
            "note": str(report.get("note") or report.get("approval_note") or ""),
        },
    }


def is_unfilled_template(value: dict[str, Any]) -> bool:
    return value.get("template") is True or value.get("template_only") is True
