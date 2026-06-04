from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


INBOX_LIMIT = 12

STATUS_LABELS = {
    "ready_for_packet": "Ready For Packet",
    "resolve_gates": "Resolve Gates",
    "get_package": "Get Package",
    "review_fit": "Review Fit",
    "watch": "Watch",
    "passed": "Passed",
}

STATUS_ORDER = {
    "ready_for_packet": 0,
    "resolve_gates": 1,
    "get_package": 2,
    "review_fit": 3,
    "watch": 4,
    "passed": 5,
}


def build_daily_bid_inbox(
    scan_result: dict[str, Any],
    analyses_by_opportunity: dict[str, dict[str, Any]] | None = None,
    *,
    limit: int = INBOX_LIMIT,
    generated_at: str = "",
) -> dict[str, Any]:
    analyses = analyses_by_opportunity or {}
    items = [
        _inbox_item(opportunity, analyses.get(_opportunity_id(opportunity)))
        for opportunity in _scan_opportunities(scan_result)
    ]
    items = [item for item in items if item["opportunity_id"]]
    items.sort(key=_item_sort_key)
    limited = items[: max(1, int(limit or INBOX_LIMIT))]
    counts = Counter(item["status"] for item in limited)
    top_item = limited[0] if limited else {}
    return {
        "generated_at": generated_at or _utc_now(),
        "as_of": str(scan_result.get("as_of") or ""),
        "profile_id": str((scan_result.get("business_profile") or {}).get("profile_id") or ""),
        "title": "Daily Bid Inbox",
        "summary": {
            "total": len(limited),
            "ready_for_packet": counts["ready_for_packet"],
            "needs_action": counts["resolve_gates"] + counts["get_package"] + counts["review_fit"],
            "needs_package": counts["get_package"],
            "passed": counts["passed"],
            "top_action": str(top_item.get("next_action") or "Run a scan to build the daily bid inbox."),
            "top_opportunity_id": str(top_item.get("opportunity_id") or ""),
        },
        "items": limited,
        "sections": _sections(limited),
    }


def _scan_opportunities(scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for bucket in ("top_opportunities", "watchlist", "all_evaluated", "skipped"):
        for item in scan_result.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            opportunity_id = _opportunity_id(item)
            if not opportunity_id or opportunity_id in seen:
                continue
            seen.add(opportunity_id)
            output.append(item)
    return output


def _inbox_item(opportunity: dict[str, Any], analysis: dict[str, Any] | None) -> dict[str, Any]:
    solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
    pricing = opportunity.get("pricing_breakdown") if isinstance(opportunity.get("pricing_breakdown"), dict) else {}
    decision = _decision(opportunity, analysis)
    status = _status(opportunity, analysis, decision)
    agent_task = _first_agent_task(analysis)
    next_action = _next_action(opportunity, analysis, status, decision)
    blocker = _blocker(opportunity, analysis, decision)
    return {
        "opportunity_id": _opportunity_id(opportunity),
        "title": str(solicitation.get("description") or opportunity.get("title") or "Untitled listing"),
        "decision_label": decision,
        "status": status,
        "label": STATUS_LABELS.get(status, status.replace("_", " ").title()),
        "status_label": STATUS_LABELS.get(status, status.replace("_", " ").title()),
        "next_action": next_action,
        "blocker": blocker,
        "submission_deadline": str(solicitation.get("submission_deadline") or ""),
        "days_until_deadline": opportunity.get("days_until_deadline"),
        "division": str(solicitation.get("division") or ""),
        "buyer_name": str(solicitation.get("buyer_name") or ""),
        "recommended_bid": float(pricing.get("recommended_bid") or opportunity.get("predicted_bid") or 0),
        "expected_profit": float(pricing.get("expected_profit") or 0),
        "win_probability": float(pricing.get("win_probability") or 0),
        "analysis_id": str((analysis or {}).get("analysis_id") or ""),
        "bid_state": str((analysis or {}).get("bid_state") or ""),
        "acquisition_status": str(((analysis or {}).get("acquisition") or {}).get("status") or ""),
        "task_type": _task_type(status, agent_task),
        "source_task_id": str(agent_task.get("task_id") or ""),
        "source_gate_id": str(agent_task.get("source_gate_id") or ""),
        "source_requirement_id": str(agent_task.get("requirement_id") or ""),
        "source": "server_scan",
    }


def _decision(opportunity: dict[str, Any], analysis: dict[str, Any] | None) -> str:
    decision = analysis.get("compliance_decision") if isinstance(analysis, dict) else {}
    if isinstance(decision, dict) and decision.get("label"):
        return str(decision.get("label"))
    return str(opportunity.get("label") or "Monitor")


def _first_agent_task(analysis: dict[str, Any] | None) -> dict[str, Any]:
    tasks = analysis.get("agent_tasks") if isinstance(analysis, dict) and isinstance(analysis.get("agent_tasks"), list) else []
    if tasks and isinstance(tasks[0], dict):
        return dict(tasks[0])
    return {}


def _task_type(status: str, agent_task: dict[str, Any]) -> str:
    if agent_task.get("task_type"):
        return str(agent_task.get("task_type"))
    return {
        "ready_for_packet": "owner_packet_approval",
        "resolve_gates": "resolve_compliance",
        "get_package": "acquire_official_package",
        "review_fit": "review_bid_fit",
        "watch": "monitor_opportunity",
        "passed": "pass_opportunity",
    }.get(status, "review_bid_fit")


def _status(opportunity: dict[str, Any], analysis: dict[str, Any] | None, decision: str) -> str:
    normalized = decision.lower()
    if normalized in {"skip", "pass", "blocked"}:
        return "passed"
    if isinstance(analysis, dict):
        if analysis.get("bid_state") == "owner_packet_ready":
            return "ready_for_packet"
        if analysis.get("agent_tasks"):
            if analysis.get("bid_state") == "metadata_intake":
                return "get_package"
            return "resolve_gates"
        if analysis.get("bid_state") == "metadata_intake":
            return "get_package"
    if normalized == "review":
        return "review_fit"
    if normalized == "monitor":
        return "watch"
    return "get_package"


def _next_action(
    opportunity: dict[str, Any],
    analysis: dict[str, Any] | None,
    status: str,
    decision: str,
) -> str:
    if isinstance(analysis, dict):
        decision_payload = analysis.get("compliance_decision") if isinstance(analysis.get("compliance_decision"), dict) else {}
        if decision_payload.get("next_action"):
            return str(decision_payload.get("next_action"))
        tasks = analysis.get("agent_tasks") if isinstance(analysis.get("agent_tasks"), list) else []
        if tasks and isinstance(tasks[0], dict):
            return str(tasks[0].get("title") or "Resolve next requirement")
    if status == "ready_for_packet":
        return "Prepare bid notes"
    if status == "get_package":
        return "Start from city record, then upload or fetch the official package"
    if status == "resolve_gates":
        return "Resolve open compliance gates"
    if status == "review_fit":
        return "Review scope, capacity, and deadline before assigning estimator time"
    if status == "watch":
        return "Keep watching until urgency or fit improves"
    if decision.lower() in {"skip", "pass", "blocked"}:
        return "Do not spend bid time today"
    return "Start package intake"


def _blocker(opportunity: dict[str, Any], analysis: dict[str, Any] | None, decision: str) -> str:
    if isinstance(analysis, dict):
        decision_payload = analysis.get("compliance_decision") if isinstance(analysis.get("compliance_decision"), dict) else {}
        if decision_payload.get("reason"):
            return str(decision_payload.get("reason"))
        tasks = analysis.get("agent_tasks") if isinstance(analysis.get("agent_tasks"), list) else []
        if tasks and isinstance(tasks[0], dict):
            return str(tasks[0].get("detail") or tasks[0].get("title") or "")
    for field in ("rejection_reasons", "risks", "missing_requirements"):
        values = opportunity.get(field) if isinstance(opportunity.get(field), list) else []
        if values:
            return str(values[0])
    if decision.lower() == "pursue":
        return "Official package still needs deterministic intake before packet prep."
    return "No single blocker selected."


def _sections(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = []
    for status in STATUS_ORDER:
        section_items = [item for item in items if item["status"] == status]
        if section_items:
            sections.append(
                {
                    "status": status,
                    "label": STATUS_LABELS.get(status, status.replace("_", " ").title()),
                    "count": len(section_items),
                    "opportunity_ids": [item["opportunity_id"] for item in section_items],
                }
            )
    return sections


def _item_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    days = item.get("days_until_deadline")
    try:
        deadline = int(days) if days is not None else 9999
    except (TypeError, ValueError):
        deadline = 9999
    return (STATUS_ORDER.get(item["status"], 99), deadline, item["opportunity_id"])


def _opportunity_id(opportunity: dict[str, Any]) -> str:
    solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
    return str(solicitation.get("document_number") or opportunity.get("opportunity_id") or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
