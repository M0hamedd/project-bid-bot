from __future__ import annotations

import hashlib
from typing import Any


PENDING_STATUS = "pending_owner_approval"
NOT_READY_STATUS = "not_ready_for_owner_approval"
APPROVED_STATUS = "owner_already_approved"


def build_owner_approval_request(
    session: dict[str, Any],
    *,
    opportunity: dict[str, Any] | None = None,
    business_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = dict(session or {})
    opportunity_data = opportunity if isinstance(opportunity, dict) else {}
    profile = (
        dict(business_profile)
        if isinstance(business_profile, dict) and business_profile
        else dict(analysis.get("business_profile") or {})
    )
    metadata = _metadata(analysis, opportunity_data)
    pricing = analysis.get("pricing_worksheet") if isinstance(analysis.get("pricing_worksheet"), dict) else {}
    manifest_summary = (
        analysis.get("submission_manifest_summary")
        if isinstance(analysis.get("submission_manifest_summary"), dict)
        else {}
    )
    gates = _rows(analysis.get("gate_results"))
    tasks = _rows(analysis.get("agent_tasks"))
    acquisition = analysis.get("acquisition") if isinstance(analysis.get("acquisition"), dict) else {}
    document = analysis.get("document") if isinstance(analysis.get("document"), dict) else {}
    status = _approval_status(analysis, manifest_summary, tasks)
    target_bid = _money(
        pricing.get("approved_target_bid")
        or pricing.get("target_bid")
        or (analysis.get("pricing_approval") or {}).get("approved_target_bid")
    )
    approval_payload = {
        "approved": True,
        "analysis_id": str(analysis.get("analysis_id") or ""),
        "opportunity_id": str(analysis.get("opportunity_id") or metadata.get("document_number") or ""),
    }
    request_id = _id(
        "approval-request",
        approval_payload.get("analysis_id"),
        approval_payload.get("opportunity_id"),
        status,
        target_bid,
        analysis.get("updated_at") or analysis.get("created_at"),
    )
    citations = _approval_citations(analysis, pricing, acquisition, document)
    return {
        "approval_request_id": request_id,
        "status": status,
        "ready_for_owner": status == PENDING_STATUS,
        "approval_required": status == PENDING_STATUS,
        "analysis_id": approval_payload["analysis_id"],
        "opportunity_id": approval_payload["opportunity_id"],
        "profile_id": str(profile.get("profile_id") or ""),
        "company_name": str(profile.get("name") or ""),
        "title": str(metadata.get("title") or approval_payload["opportunity_id"]),
        "buyer": {
            "name": str(metadata.get("buyer_name") or ""),
            "email": str(metadata.get("buyer_email") or ""),
            "phone": str(metadata.get("buyer_phone") or ""),
            "division": str(metadata.get("division") or ""),
        },
        "deadline": str(metadata.get("submission_deadline") or ""),
        "decision": {
            "label": str((analysis.get("compliance_decision") or {}).get("label") or ""),
            "reason": str((analysis.get("compliance_decision") or {}).get("reason") or ""),
            "bid_state": str(analysis.get("bid_state") or ""),
        },
        "pricing": {
            "target_bid": target_bid,
            "low_bid": _money(pricing.get("low_bid")),
            "high_bid": _money(pricing.get("high_bid")),
            "confidence": str(pricing.get("confidence") or ""),
            "estimator_approval_status": str(pricing.get("estimator_approval_status") or ""),
            "line_item_count": len([item for item in pricing.get("pricing_line_items") or [] if isinstance(item, dict)]),
        },
        "readiness": {
            "manifest_required_open": int(manifest_summary.get("required_open") or 0),
            "manifest_total": int(manifest_summary.get("total") or 0),
            "open_task_count": len(tasks),
            "hard_stop_count": sum(1 for gate in gates if str(gate.get("gate_type") or "") == "hard_stop"),
            "review_gate_count": sum(1 for gate in gates if str(gate.get("gate_type") or "") == "review"),
            "cleared_gate_count": sum(1 for gate in gates if gate.get("resolved") or gate.get("blocking") is False),
        },
        "package": {
            "status": str(acquisition.get("status") or ""),
            "primary_document": str(document.get("filename") or acquisition.get("fetched_url") or ""),
            "supporting_document_count": len([item for item in analysis.get("supporting_documents") or [] if isinstance(item, dict)]),
            "package_document_summary": acquisition.get("package_document_summary") if isinstance(acquisition.get("package_document_summary"), dict) else {},
        },
        "approval_payload": approval_payload,
        "approval_endpoint": "/api/approve",
        "citations": citations,
        "guardrails": [
            "This request does not approve the bid.",
            "This request does not submit the bid.",
            "Owner approval must call /api/approve with the server-owned analysis_id.",
        ],
        "created_from": "server_owned_analysis_state",
    }


def build_owner_approval_requests(
    scan_result: dict[str, Any],
    analyses_by_opportunity: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    analyses = analyses_by_opportunity or {}
    profile = scan_result.get("business_profile") if isinstance(scan_result.get("business_profile"), dict) else {}
    requests: list[dict[str, Any]] = []
    for opportunity in _scan_opportunities(scan_result):
        opportunity_id = _opportunity_id(opportunity)
        if not opportunity_id:
            continue
        analysis = analyses.get(opportunity_id)
        if not isinstance(analysis, dict):
            continue
        request = build_owner_approval_request(
            analysis,
            opportunity=opportunity,
            business_profile=profile,
        )
        if request["status"] == PENDING_STATUS:
            requests.append(request)
    requests.sort(key=lambda item: (str(item.get("deadline") or "9999"), str(item.get("opportunity_id") or "")))
    return requests


def _approval_status(
    analysis: dict[str, Any],
    manifest_summary: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> str:
    if analysis.get("owner_approved"):
        return APPROVED_STATUS
    if analysis.get("bid_state") != "owner_packet_ready":
        return NOT_READY_STATUS
    if int(manifest_summary.get("required_open") or 0) > 1:
        return NOT_READY_STATUS
    if tasks:
        return NOT_READY_STATUS
    return PENDING_STATUS


def _approval_citations(
    analysis: dict[str, Any],
    pricing: dict[str, Any],
    acquisition: dict[str, Any],
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for row in analysis.get("compliance_matrix") or []:
        if not isinstance(row, dict) or not isinstance(row.get("citation"), dict):
            continue
        citation = dict(row["citation"])
        citations.append(
            {
                "citation_type": "requirement",
                "source": str(citation.get("source") or ""),
                "page": citation.get("page"),
                "chunk_id": str(citation.get("chunk_id") or ""),
                "snippet": str(citation.get("snippet") or ""),
                "requirement_id": str(row.get("requirement_id") or ""),
            }
        )
    for item in pricing.get("pricing_line_items") or []:
        if not isinstance(item, dict) or not isinstance(item.get("citation"), dict):
            continue
        citation = dict(item["citation"])
        citations.append(
            {
                "citation_type": "pricing_line_item",
                "source": str(citation.get("source") or ""),
                "page": citation.get("page"),
                "chunk_id": str(citation.get("chunk_id") or ""),
                "snippet": str(citation.get("snippet") or ""),
                "line_item_id": str(item.get("line_item_id") or ""),
            }
        )
    if acquisition or document:
        citations.append(
            {
                "citation_type": "official_package",
                "source": str(acquisition.get("fetched_url") or document.get("filename") or acquisition.get("open_data_record_url") or ""),
                "page": None,
                "chunk_id": str(acquisition.get("status") or ""),
                "snippet": str(acquisition.get("message") or ""),
            }
        )
    return citations[:20]


def _metadata(analysis: dict[str, Any], opportunity: dict[str, Any]) -> dict[str, Any]:
    metadata = analysis.get("opportunity_metadata") if isinstance(analysis.get("opportunity_metadata"), dict) else {}
    solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
    merged = dict(solicitation)
    merged.update(metadata)
    if not merged.get("document_number"):
        merged["document_number"] = analysis.get("opportunity_id") or opportunity.get("opportunity_id") or ""
    if not merged.get("title"):
        merged["title"] = solicitation.get("description") or opportunity.get("title") or merged.get("document_number") or ""
    return merged


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


def _opportunity_id(opportunity: dict[str, Any]) -> str:
    solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
    return str(solicitation.get("document_number") or opportunity.get("opportunity_id") or "").strip()


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
