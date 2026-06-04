from __future__ import annotations

import hashlib
from typing import Any


READY_STATUS = "ready"
MISSING_STATUS = "missing"
BLOCKED_STATUS = "blocked"
REVIEW_STATUS = "review"
PENDING_OWNER_APPROVAL_STATUS = "pending_owner_approval"

OPEN_STATUSES = {MISSING_STATUS, BLOCKED_STATUS, REVIEW_STATUS, PENDING_OWNER_APPROVAL_STATUS}
PACKAGE_READY_STATUSES = {"package_fetched", "package_uploaded", "fetched", "public_package_found"}

CATEGORY_ITEM_TYPES = {
    "site_visit": "site_visit_confirmation",
    "addendum": "addendum_acknowledgement",
    "pricing_sheet": "pricing_form",
    "form": "required_form",
    "insurance": "insurance_certificate",
    "bonding": "bonding_letter",
    "license": "license",
    "certification": "certification",
    "safety": "safety_document",
    "experience": "references",
    "deadline": "deadline_confirmation",
    "submission_instruction": "portal_submission_steps",
    "scope": "scope_confirmation",
    "other": "requirement_confirmation",
}

CATEGORY_LABELS = {
    "site_visit": "Site visit confirmation",
    "addendum": "Addendum acknowledgement",
    "pricing_sheet": "Pricing form",
    "form": "Required bid form",
    "insurance": "Insurance certificate",
    "bonding": "Bonding letter",
    "license": "License",
    "certification": "Certification",
    "safety": "Safety document",
    "experience": "References",
    "deadline": "Deadline confirmation",
    "submission_instruction": "Portal submission steps",
    "scope": "Scope confirmation",
    "other": "Requirement confirmation",
}

CATEGORY_OWNERS = {
    "site_visit": "Bid Coordinator",
    "addendum": "Bid Coordinator",
    "pricing_sheet": "Estimator",
    "form": "Bid Coordinator",
    "insurance": "Operations",
    "bonding": "Operations",
    "license": "Operations",
    "certification": "Operations",
    "safety": "Operations",
    "experience": "Operations",
    "deadline": "Bid Coordinator",
    "submission_instruction": "Bid Coordinator",
    "scope": "Estimator",
    "other": "Bid Coordinator",
}


def build_submission_manifest(
    session: dict[str, Any] | None = None,
    *,
    compliance_matrix: Any | None = None,
    gate_results: Any | None = None,
    evidence_ledger: Any | None = None,
    acquisition: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
    pricing_worksheet: dict[str, Any] | None = None,
    approved: bool = False,
) -> list[dict[str, Any]]:
    source = session if isinstance(session, dict) else {}
    rows = _rows(compliance_matrix if compliance_matrix is not None else source.get("compliance_matrix"))
    gates = _rows(gate_results if gate_results is not None else source.get("gate_results"))
    facts = _rows(evidence_ledger if evidence_ledger is not None else source.get("evidence_ledger"))
    acquisition_data = dict(acquisition if acquisition is not None else source.get("acquisition") or {})
    document_data = dict(document if document is not None else source.get("document") or {})
    pricing_data = dict(pricing_worksheet or {})
    deadline = _deadline(source)

    items: list[dict[str, Any]] = []
    package_item = _package_item(source, acquisition_data, document_data, facts, deadline)
    if package_item:
        items.append(package_item)

    gate_index = _gate_index(gates)
    for row in rows:
        item = _requirement_item(row, gate_index.get(str(row.get("requirement_id") or "")), facts, deadline)
        if item:
            items.append(item)

    pricing_item = _pricing_item(pricing_data, facts, deadline)
    if pricing_item:
        items.append(pricing_item)

    items.append(_owner_approval_item(source, approved, deadline))
    return _dedupe_items(items)


def summarize_submission_manifest(items: Any) -> dict[str, Any]:
    rows = _rows(items)
    counts = {
        "total": len(rows),
        READY_STATUS: 0,
        MISSING_STATUS: 0,
        BLOCKED_STATUS: 0,
        REVIEW_STATUS: 0,
        PENDING_OWNER_APPROVAL_STATUS: 0,
        "required_open": 0,
        "ready_for_submission": False,
        "next_item": "",
    }
    for row in rows:
        status = str(row.get("status") or REVIEW_STATUS)
        if status in counts:
            counts[status] += 1
        if bool(row.get("required", True)) and status in OPEN_STATUSES:
            counts["required_open"] += 1
            if not counts["next_item"]:
                counts["next_item"] = str(row.get("label") or row.get("item_type") or "")
    counts["ready_for_submission"] = counts["total"] > 0 and counts["required_open"] == 0
    return counts


def with_submission_manifest_summary(items: Any) -> dict[str, Any]:
    manifest = _rows(items)
    return {
        "submission_manifest": manifest,
        "submission_manifest_summary": summarize_submission_manifest(manifest),
    }


def _package_item(
    session: dict[str, Any],
    acquisition: dict[str, Any],
    document: dict[str, Any],
    facts: list[dict[str, Any]],
    deadline: str,
) -> dict[str, Any] | None:
    if not acquisition and not document:
        return None
    has_document = bool(document)
    status_value = str(acquisition.get("status") or "")
    package_ready = has_document or status_value in PACKAGE_READY_STATUSES or not acquisition.get("package_required", True)
    status = READY_STATUS if package_ready else BLOCKED_STATUS
    reason = (
        f"Official package available: {document.get('filename') or acquisition.get('fetched_url') or status_value}."
        if package_ready
        else str(acquisition.get("message") or "Official solicitation package is required before submission prep.")
    )
    evidence_ids = _fact_ids(
        facts,
        fact_types={"document_acquisition_status", "opportunity_metadata"},
        source_types={"document_acquisition", "open_data_metadata"},
    )
    return {
        "manifest_id": _id("manifest", session.get("analysis_id"), "official_package", status_value, document.get("content_hash")),
        "item_type": "official_package",
        "label": "Official solicitation package",
        "required": True,
        "status": status,
        "reason": reason,
        "source_requirement_id": "official-package",
        "source_gate_id": _gate_id_for_package(session),
        "citation": _citation_from_acquisition(acquisition),
        "evidence_ids": evidence_ids,
        "owner": "Bid Coordinator",
        "due_at": deadline,
    }


def _requirement_item(
    row: dict[str, Any],
    gate: dict[str, Any] | None,
    facts: list[dict[str, Any]],
    deadline: str,
) -> dict[str, Any] | None:
    requirement_id = str(row.get("requirement_id") or "")
    if not requirement_id:
        return None
    category = str(row.get("category") or "other")
    item_type = CATEGORY_ITEM_TYPES.get(category, CATEGORY_ITEM_TYPES["other"])
    label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["other"])
    evidence_ids = _evidence_ids(row, facts)
    status = _requirement_status(row, gate)
    reason = _requirement_reason(row, gate, status, evidence_ids)
    citation = gate.get("citation") if isinstance(gate, dict) and isinstance(gate.get("citation"), dict) else row.get("citation")
    return {
        "manifest_id": _id("manifest", requirement_id, item_type),
        "item_type": item_type,
        "label": label,
        "required": True,
        "status": status,
        "reason": reason,
        "source_requirement_id": requirement_id,
        "source_gate_id": str((gate or {}).get("gate_id") or ""),
        "citation": _citation(citation),
        "evidence_ids": evidence_ids,
        "owner": CATEGORY_OWNERS.get(category, "Bid Coordinator"),
        "due_at": deadline,
    }


def _pricing_item(
    pricing: dict[str, Any],
    facts: list[dict[str, Any]],
    deadline: str,
) -> dict[str, Any] | None:
    if not pricing:
        return None
    blockers = [str(item).strip() for item in pricing.get("blockers") or [] if str(item).strip()]
    target_bid = _money(pricing.get("target_bid"))
    status_value = str(pricing.get("status") or "")
    approval_status = str(pricing.get("estimator_approval_status") or "")
    missing_inputs = [
        item for item in pricing.get("missing_inputs") or []
        if isinstance(item, dict) and str(item.get("input_type") or "").strip()
    ]
    if missing_inputs:
        status = BLOCKED_STATUS
    elif blockers or status_value.startswith("blocked") or target_bid <= 0:
        status = BLOCKED_STATUS
    elif approval_status != "approved":
        status = REVIEW_STATUS
    elif status_value == "draft_estimate":
        status = REVIEW_STATUS
    else:
        status = READY_STATUS
    if status == BLOCKED_STATUS:
        reason = (
            str(missing_inputs[0].get("reason") or "")
            if missing_inputs
            else blockers[0] if blockers else "No deterministic target bid is available."
        )
    elif approval_status != "approved":
        reason = f"Estimator must approve the target bid before packet preparation: ${target_bid:,.0f}."
    elif status == REVIEW_STATUS:
        reason = "Agent pricing is a draft estimate; estimator should review before submission."
    else:
        reason = f"Estimator approved pricing worksheet target at ${target_bid:,.0f}."
    return {
        "manifest_id": _id("manifest", "pricing_worksheet", pricing.get("source"), target_bid, status_value, approval_status),
        "item_type": "pricing_worksheet",
        "label": "Pricing worksheet",
        "required": True,
        "status": status,
        "reason": reason,
        "source_requirement_id": "",
        "source_gate_id": "",
        "citation": {
            "source": "deterministic_pricing_worksheet",
            "page": None,
            "chunk_id": "",
            "snippet": reason,
        },
        "evidence_ids": _fact_ids(facts, fact_types={"gate_result"}),
        "owner": "Estimator",
        "due_at": deadline,
    }


def _owner_approval_item(session: dict[str, Any], approved: bool, deadline: str) -> dict[str, Any]:
    status = READY_STATUS if approved else PENDING_OWNER_APPROVAL_STATUS
    reason = (
        "Owner approved packet preparation."
        if approved
        else "Owner approval is required before a human submits the bid."
    )
    return {
        "manifest_id": _id("manifest", session.get("analysis_id"), "owner_approval"),
        "item_type": "owner_approval",
        "label": "Owner approval",
        "required": True,
        "status": status,
        "reason": reason,
        "source_requirement_id": "",
        "source_gate_id": "",
        "citation": {
            "source": "owner_approval",
            "page": None,
            "chunk_id": "",
            "snippet": reason,
        },
        "evidence_ids": [],
        "owner": "Owner",
        "due_at": deadline,
    }


def _requirement_status(row: dict[str, Any], gate: dict[str, Any] | None) -> str:
    if row.get("resolved"):
        return READY_STATUS
    if row.get("business_has_capability") is False:
        return BLOCKED_STATUS
    if isinstance(gate, dict):
        if gate.get("gate_type") == "hard_stop" or gate.get("blocking") is True:
            return BLOCKED_STATUS
        return REVIEW_STATUS
    if row.get("evidence_needed"):
        return MISSING_STATUS
    return REVIEW_STATUS


def _requirement_reason(
    row: dict[str, Any],
    gate: dict[str, Any] | None,
    status: str,
    evidence_ids: list[str],
) -> str:
    if status == READY_STATUS:
        if evidence_ids:
            return "Requirement resolved with attached evidence or confirmation."
        return "Requirement has been resolved by user confirmation."
    if isinstance(gate, dict) and gate.get("message"):
        return str(gate.get("message"))
    if status == BLOCKED_STATUS:
        return "Required capability, document, or confirmation is still blocking submission prep."
    if status == MISSING_STATUS:
        needed = ", ".join(str(item) for item in row.get("evidence_needed") or [] if str(item).strip())
        return f"Evidence still needed: {needed}." if needed else "Evidence still needed."
    return "Requirement needs human review before submission prep."


def _gate_index(gates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for gate in gates:
        requirement_id = str(gate.get("requirement_id") or "")
        if requirement_id and requirement_id not in indexed:
            indexed[requirement_id] = gate
    return indexed


def _evidence_ids(row: dict[str, Any], facts: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for evidence in row.get("uploaded_evidence") or []:
        if not isinstance(evidence, dict):
            continue
        ids.append(str(evidence.get("evidence_id") or evidence.get("type") or "").strip())
    requirement_id = str(row.get("requirement_id") or "")
    for fact in facts:
        if str(fact.get("requirement_id") or "") != requirement_id:
            continue
        if fact.get("fact_type") in {"uploaded_evidence", "user_resolution"}:
            ids.append(str(fact.get("fact_id") or "").strip())
    return _unique(ids)


def _fact_ids(
    facts: list[dict[str, Any]],
    *,
    fact_types: set[str] | None = None,
    source_types: set[str] | None = None,
) -> list[str]:
    ids: list[str] = []
    for fact in facts:
        if fact_types is not None and fact.get("fact_type") not in fact_types:
            continue
        if source_types is not None and fact.get("source_type") not in source_types:
            continue
        ids.append(str(fact.get("fact_id") or "").strip())
    return _unique(ids)


def _gate_id_for_package(session: dict[str, Any]) -> str:
    for gate in session.get("gate_results") or []:
        if isinstance(gate, dict) and gate.get("rule_id") == "official_package_required":
            return str(gate.get("gate_id") or "")
    return ""


def _citation_from_acquisition(acquisition: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(
            acquisition.get("open_data_record_url")
            or acquisition.get("fetched_url")
            or acquisition.get("portal_url")
            or acquisition.get("source_label")
            or "document_acquisition"
        ),
        "page": None,
        "chunk_id": str(acquisition.get("status") or ""),
        "snippet": str(acquisition.get("message") or acquisition.get("next_step") or ""),
        "source_type": str(acquisition.get("source_type") or "document_acquisition"),
        "source_label": str(acquisition.get("source_label") or "Document Acquisition"),
    }


def _citation(value: Any) -> dict[str, Any]:
    citation = value if isinstance(value, dict) else {}
    return {
        "source": str(citation.get("source") or ""),
        "page": citation.get("page"),
        "chunk_id": str(citation.get("chunk_id") or ""),
        "snippet": str(citation.get("snippet") or ""),
    }


def _deadline(session: dict[str, Any]) -> str:
    metadata = session.get("opportunity_metadata") if isinstance(session.get("opportunity_metadata"), dict) else {}
    deadline = str(metadata.get("submission_deadline") or "").strip()
    if deadline:
        return deadline
    solicitation = session.get("solicitation") if isinstance(session.get("solicitation"), dict) else {}
    return str(solicitation.get("submission_deadline") or "").strip()


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        manifest_id = str(item.get("manifest_id") or "").strip()
        key = manifest_id or f"{item.get('item_type')}:{item.get('source_requirement_id')}"
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
