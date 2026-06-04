from __future__ import annotations

import hashlib
from typing import Any, Iterable

from contract_radar.compliance import RESOLUTION_TYPES
from contract_radar.pricing_worksheet import build_pricing_worksheet, with_estimator_approval
from contract_radar.submission_manifest import build_submission_manifest, summarize_submission_manifest


ALLOWED_ACTION_TYPES = {
    "open_data_metadata_loaded",
    "document_acquisition_checked",
    "pdf_uploaded",
    "pdf_text_extracted",
    "pricing_worksheet_created",
    "requirements_extracted",
    "evidence_ledger_created",
    "gate_rules_run",
    "tasks_generated",
    "requirement_resolved",
    "pricing_approved",
    "owner_packet_prepared",
}

SOURCE_TYPES = {
    "open_data_metadata",
    "document_acquisition",
    "uploaded_pdf",
    "business_profile",
    "evidence_vault",
    "uploaded_evidence",
    "user_resolution",
    "gate_result",
    "pricing_worksheet",
    "estimator_approval",
}

BID_STATES = (
    "metadata_intake",
    "uploaded",
    "pdf_parsed",
    "requirements_extracted",
    "evidence_gaps_open",
    "requirements_resolved",
    "owner_packet_ready",
)

HARD_STOP_CATEGORIES = {
    "site_visit",
    "addendum",
    "pricing_sheet",
    "form",
    "insurance",
    "bonding",
    "license",
    "certification",
    "safety",
}

REVIEW_CATEGORIES = {
    "deadline",
    "experience",
    "submission_instruction",
    "scope",
    "other",
}

RESOLUTION_OPTIONS_BY_CATEGORY = {
    "site_visit": ("site_visit_attended", "not_applicable"),
    "addendum": ("addendum_acknowledged", "not_applicable"),
    "pricing_sheet": ("pricing_form_assigned", "not_applicable"),
    "insurance": ("certificate_available", "not_applicable"),
    "bonding": ("certificate_available", "not_applicable"),
    "license": ("certificate_available", "not_applicable"),
    "certification": ("certificate_available", "not_applicable"),
    "safety": ("certificate_available", "not_applicable"),
    "form": ("uploaded_evidence", "not_applicable"),
    "experience": ("uploaded_evidence", "not_applicable"),
    "deadline": ("uploaded_evidence", "not_applicable"),
    "submission_instruction": ("uploaded_evidence", "not_applicable"),
    "scope": ("capability_confirmed", "not_applicable"),
    "other": ("uploaded_evidence", "not_applicable"),
}


def decorate_agent_session(
    session: dict[str, Any],
    *,
    action_types: Iterable[str] = (),
    action_context: dict[str, Any] | None = None,
    now: str = "",
) -> dict[str, Any]:
    """Rebuild deterministic agent artifacts for a server-owned analysis session."""
    timestamp = str(now or session.get("updated_at") or session.get("created_at") or "")
    runtime = build_agent_runtime(session, now=timestamp)
    session.update(runtime)
    session["compliance_summary"] = _with_runtime_summary(session.get("compliance_summary"), runtime)

    actions = [
        dict(action)
        for action in session.get("agent_actions", [])
        if isinstance(action, dict) and action.get("action_type") in ALLOWED_ACTION_TYPES
    ]
    for action_type in action_types:
        actions.append(_agent_action(action_type, session, runtime, action_context or {}, len(actions), timestamp))
    session["agent_actions"] = actions
    session["agent_summary"] = _agent_summary(session)
    return session


def build_agent_runtime(session: dict[str, Any], *, now: str = "") -> dict[str, Any]:
    rows = _rows(session)
    base_facts, fact_index = _base_evidence_facts(session, rows, now=now)
    metadata_facts = _metadata_evidence_facts(session, now=now)
    metadata_fact_ids = [fact["fact_id"] for fact in metadata_facts]
    pricing_worksheet = _runtime_pricing_worksheet(session, rows)
    pricing_facts = _pricing_evidence_facts(session, pricing_worksheet, now=now)
    pricing_fact_ids = [fact["fact_id"] for fact in pricing_facts]
    metadata_gates = _metadata_gate_results(session, metadata_fact_ids)
    requirement_gates = _gate_results(rows, fact_index)
    pricing_gates = (
        []
        if metadata_gates or requirement_gates or not rows
        else _pricing_gate_results(session, pricing_worksheet, pricing_fact_ids)
    )
    gate_results = metadata_gates + requirement_gates + pricing_gates
    gate_facts = _gate_facts(gate_results, now=now)
    evidence_ledger = metadata_facts + base_facts + pricing_facts + gate_facts
    agent_tasks = _agent_tasks(gate_results)
    bid_state = _bid_state(session, rows, gate_results)
    compliance_decision = _compliance_decision(bid_state, gate_results, agent_tasks)
    submission_manifest = build_submission_manifest(
        session,
        compliance_matrix=rows,
        gate_results=gate_results,
        evidence_ledger=evidence_ledger,
        pricing_worksheet=pricing_worksheet,
        approved=bool(session.get("owner_approved")),
    )
    submission_manifest_summary = summarize_submission_manifest(submission_manifest)
    return {
        "evidence_ledger": evidence_ledger,
        "gate_results": gate_results,
        "agent_tasks": agent_tasks,
        "bid_state": bid_state,
        "pricing_worksheet": pricing_worksheet,
        "pricing_approval": pricing_worksheet.get("estimator_approval") if isinstance(pricing_worksheet, dict) else {},
        "compliance_decision": compliance_decision,
        "submission_manifest": submission_manifest,
        "submission_manifest_summary": submission_manifest_summary,
        "agent_summary": _agent_summary(
            {
                "bid_state": bid_state,
                "compliance_decision": compliance_decision,
                "evidence_ledger": evidence_ledger,
                "gate_results": gate_results,
                "agent_tasks": agent_tasks,
                "submission_manifest": submission_manifest,
                "submission_manifest_summary": submission_manifest_summary,
                "agent_actions": session.get("agent_actions") or [],
            }
        ),
    }


def _metadata_evidence_facts(session: dict[str, Any], *, now: str = "") -> list[dict[str, Any]]:
    acquisition = session.get("acquisition") if isinstance(session.get("acquisition"), dict) else {}
    metadata = session.get("opportunity_metadata") if isinstance(session.get("opportunity_metadata"), dict) else {}
    if not acquisition and not metadata:
        return []

    analysis_id = str(session.get("analysis_id") or "")
    citation = _metadata_citation(session)
    facts = []
    if metadata:
        facts.append(
            _fact(
                analysis_id,
                "opportunity_metadata",
                {
                    "document_number": str(metadata.get("document_number") or ""),
                    "title": str(metadata.get("title") or ""),
                    "submission_deadline": str(metadata.get("submission_deadline") or ""),
                    "category": str(metadata.get("category") or ""),
                    "division": str(metadata.get("division") or ""),
                    "buyer_name": str(metadata.get("buyer_name") or ""),
                },
                "open_data_metadata",
                citation,
                "deterministic",
                now,
            )
        )
    if acquisition:
        facts.append(
            _fact(
                analysis_id,
                "document_acquisition_status",
                {
                    "status": str(acquisition.get("status") or ""),
                    "package_required": bool(acquisition.get("package_required")),
                    "message": str(acquisition.get("message") or ""),
                },
                "document_acquisition",
                citation,
                "deterministic",
                now,
            )
        )
    return facts


def _base_evidence_facts(
    session: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: str = "",
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]]]:
    facts: list[dict[str, Any]] = []
    fact_index: dict[str, dict[str, list[str]]] = {}
    analysis_id = str(session.get("analysis_id") or "")

    for row in rows:
        requirement_id = str(row.get("requirement_id") or "")
        if not requirement_id:
            continue
        fact_index.setdefault(requirement_id, {"requirement": [], "capability": [], "evidence": [], "resolution": []})
        citation = _citation(row)
        if _has_pdf_citation(citation):
            fact = _fact(
                analysis_id,
                "requirement_detected",
                row.get("requirement") or "",
                "uploaded_pdf",
                citation,
                "deterministic",
                now,
                requirement_id=requirement_id,
            )
            facts.append(fact)
            fact_index[requirement_id]["requirement"].append(fact["fact_id"])

        for capability in row.get("matched_capabilities") or []:
            fact = _fact(
                analysis_id,
                "business_capability",
                capability,
                "business_profile",
                _profile_citation(row),
                "deterministic",
                now,
                requirement_id=requirement_id,
            )
            facts.append(fact)
            fact_index[requirement_id]["capability"].append(fact["fact_id"])

        for evidence in row.get("uploaded_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            evidence_type = str(evidence.get("type") or "uploaded_evidence")
            if evidence_type == "vault_evidence":
                source_type = "evidence_vault"
                confidence = str(evidence.get("verified_status") or "deterministic")
                fact_type = "uploaded_evidence"
                evidence_citation = _evidence_vault_citation(evidence)
            elif evidence_type in RESOLUTION_TYPES and evidence_type != "uploaded_evidence":
                source_type = "user_resolution"
                confidence = "user_confirmed"
                fact_type = "user_resolution"
                evidence_citation = citation
            else:
                source_type = "uploaded_evidence"
                confidence = "deterministic"
                fact_type = "uploaded_evidence"
                evidence_citation = citation
            fact = _fact(
                analysis_id,
                fact_type,
                {
                    "type": evidence_type,
                    "label": str(evidence.get("label") or evidence_type),
                    "note": str(evidence.get("note") or ""),
                    "evidence_id": str(evidence.get("evidence_id") or ""),
                    "evidence_type": str(evidence.get("evidence_type") or ""),
                },
                source_type,
                evidence_citation,
                confidence,
                str(evidence.get("resolved_at") or now),
                requirement_id=requirement_id,
            )
            facts.append(fact)
            bucket = "resolution" if source_type == "user_resolution" else "evidence"
            fact_index[requirement_id][bucket].append(fact["fact_id"])
    return facts, fact_index


def _gate_results(rows: list[dict[str, Any]], fact_index: dict[str, dict[str, list[str]]]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for row in rows:
        if row.get("resolved"):
            continue
        requirement_id = str(row.get("requirement_id") or "")
        if not requirement_id:
            continue
        category = str(row.get("category") or "other")
        citation = _citation(row)
        if not _has_pdf_citation(citation):
            continue

        gate_type = ""
        rule_id = ""
        if row.get("business_has_capability") is False:
            gate_type = "hard_stop"
            rule_id = "capability_gap"
        elif category in HARD_STOP_CATEGORIES:
            gate_type = "hard_stop"
            rule_id = f"unresolved_{category}"
        elif category in REVIEW_CATEGORIES:
            gate_type = "review"
            rule_id = f"review_{category}"
        elif row.get("evidence_needed"):
            gate_type = "review"
            rule_id = "unresolved_evidence"
        else:
            gate_type = "review"
            rule_id = "manual_review"

        source_fact_ids = _source_fact_ids(requirement_id, fact_index)
        gate_id = _id("gate", requirement_id, rule_id)
        gates.append(
            {
                "gate_id": gate_id,
                "gate_type": gate_type,
                "rule_id": rule_id,
                "requirement_id": requirement_id,
                "requirement": str(row.get("requirement") or ""),
                "category": category,
                "message": _gate_message(row, gate_type, rule_id),
                "blocking": gate_type == "hard_stop",
                "citation": citation,
                "source_fact_ids": source_fact_ids,
                "resolution_options": _resolution_options(category, rule_id),
            }
        )
    return gates


def _metadata_gate_results(session: dict[str, Any], source_fact_ids: list[str]) -> list[dict[str, Any]]:
    acquisition = session.get("acquisition") if isinstance(session.get("acquisition"), dict) else {}
    if not acquisition or session.get("document"):
        return []
    if not acquisition.get("package_required", True):
        return []

    opportunity_id = str(session.get("opportunity_id") or "selected-opportunity")
    message = str(
        acquisition.get("message")
        or "Official solicitation package is required before compliance clearance."
    )
    guidance = acquisition.get("guidance") if isinstance(acquisition.get("guidance"), dict) else {}
    citation = _metadata_citation(session)
    return [
        {
            "gate_id": _id("gate", opportunity_id, "official_package_required"),
            "gate_type": "review",
            "rule_id": "official_package_required",
            "requirement_id": "official-package",
            "requirement": "Fetch or upload the official solicitation package before preparing bid notes.",
            "category": "document_acquisition",
            "message": message,
            "blocking": True,
            "citation": citation,
            "source_fact_ids": list(source_fact_ids),
            "resolution_options": [],
            "acquisition_status": str(acquisition.get("status") or ""),
            "acquisition_guidance": guidance,
        }
    ]


def _runtime_pricing_worksheet(session: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not session.get("document"):
        return {}
    source = (
        session.get("pricing_context")
        if isinstance(session.get("pricing_context"), dict)
        else session.get("opportunity")
        if isinstance(session.get("opportunity"), dict)
        else {}
    )
    worksheet = build_pricing_worksheet(source, compliance_matrix=rows)
    approval = session.get("pricing_approval") if isinstance(session.get("pricing_approval"), dict) else {}
    return with_estimator_approval(worksheet, approval)


def _pricing_evidence_facts(
    session: dict[str, Any],
    pricing_worksheet: dict[str, Any],
    *,
    now: str = "",
) -> list[dict[str, Any]]:
    if not pricing_worksheet:
        return []
    analysis_id = str(session.get("analysis_id") or "")
    target_bid = _money(pricing_worksheet.get("target_bid"))
    facts = [
        _fact(
            analysis_id,
            "pricing_worksheet",
            {
                "status": str(pricing_worksheet.get("status") or ""),
                "estimator_approval_status": str(pricing_worksheet.get("estimator_approval_status") or ""),
                "target_bid": target_bid,
                "low_bid": _money(pricing_worksheet.get("low_bid")),
                "high_bid": _money(pricing_worksheet.get("high_bid")),
                "confidence": str(pricing_worksheet.get("confidence") or ""),
            },
            "pricing_worksheet",
            _pricing_citation(pricing_worksheet),
            "deterministic",
            now,
            requirement_id="pricing-approval",
        )
    ]
    approval = pricing_worksheet.get("estimator_approval") if isinstance(pricing_worksheet.get("estimator_approval"), dict) else {}
    if approval:
        facts.append(
            _fact(
                analysis_id,
                "estimator_pricing_approval",
                {
                    "approval_id": str(approval.get("approval_id") or ""),
                    "approved_target_bid": _money(approval.get("approved_target_bid") or target_bid),
                    "approved_by": str(approval.get("approved_by") or ""),
                },
                "estimator_approval",
                _pricing_approval_citation(approval),
                "user_confirmed",
                str(approval.get("approved_at") or now),
                requirement_id="pricing-approval",
            )
        )
    return facts


def _pricing_gate_results(
    session: dict[str, Any],
    pricing_worksheet: dict[str, Any],
    source_fact_ids: list[str],
) -> list[dict[str, Any]]:
    if not pricing_worksheet or not session.get("document"):
        return []
    blockers = [str(item).strip() for item in pricing_worksheet.get("blockers") or [] if str(item).strip()]
    target_bid = _money(pricing_worksheet.get("target_bid"))
    status = str(pricing_worksheet.get("status") or "")
    approval_status = str(pricing_worksheet.get("estimator_approval_status") or "")
    if blockers or status == "blocked" or target_bid <= 0:
        rule_id = "pricing_blocked"
        gate_type = "hard_stop"
        message = blockers[0] if blockers else "No deterministic target bid is available for estimator approval."
    elif approval_status != "approved":
        rule_id = "estimator_pricing_approval_required"
        gate_type = "review"
        message = f"Estimator must approve the target bid before packet preparation: ${target_bid:,.0f}."
    else:
        return []

    return [
        {
            "gate_id": _id("gate", session.get("analysis_id"), rule_id, target_bid),
            "gate_type": gate_type,
            "rule_id": rule_id,
            "requirement_id": "pricing-approval",
            "requirement": "Approve the deterministic pricing worksheet before preparing bid notes.",
            "category": "pricing_approval",
            "message": message,
            "blocking": True,
            "citation": _pricing_citation(pricing_worksheet),
            "source_fact_ids": list(source_fact_ids),
            "resolution_options": [
                {"type": "approve_pricing", "label": "Approve Target Bid"}
            ] if rule_id == "estimator_pricing_approval_required" else [],
            "pricing_worksheet": {
                "target_bid": target_bid,
                "low_bid": _money(pricing_worksheet.get("low_bid")),
                "high_bid": _money(pricing_worksheet.get("high_bid")),
                "confidence": str(pricing_worksheet.get("confidence") or ""),
            },
        }
    ]


def _gate_facts(gate_results: list[dict[str, Any]], *, now: str = "") -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for gate in gate_results:
        fact = _fact(
            str(gate.get("gate_id") or ""),
            "gate_result",
            {
                "gate_type": gate.get("gate_type"),
                "rule_id": gate.get("rule_id"),
                "message": gate.get("message"),
            },
            "gate_result",
            gate.get("citation") or {},
            "deterministic",
            now,
            requirement_id=str(gate.get("requirement_id") or ""),
        )
        fact["source_fact_ids"] = list(gate.get("source_fact_ids") or [])
        facts.append(fact)
    return facts


def _agent_tasks(gate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for gate in gate_results:
        category = str(gate.get("category") or "other")
        requirement_id = str(gate.get("requirement_id") or "")
        task_id = _id("task", str(gate.get("gate_id") or ""), requirement_id)
        citation = gate.get("citation") if isinstance(gate.get("citation"), dict) else {}
        page = citation.get("page")
        source_label = str(citation.get("source_label") or citation.get("source_type") or "").strip()
        location = f"page {page}" if page else source_label or "source PDF"
        if gate.get("rule_id") == "official_package_required":
            task_type = "acquire_official_package"
        elif str(gate.get("rule_id") or "").startswith("pricing") or gate.get("rule_id") == "estimator_pricing_approval_required":
            task_type = "approve_pricing"
        else:
            task_type = "resolve_requirement"
        tasks.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "title": _task_title(gate),
                "detail": _task_detail(gate, location),
                "requirement_id": requirement_id,
                "source_gate_id": gate.get("gate_id"),
                "blocking": bool(gate.get("blocking")),
                "citation": citation,
                "source_fact_ids": list(gate.get("source_fact_ids") or []),
                "resolution_options": list(gate.get("resolution_options") or []),
                "acquisition_status": str(gate.get("acquisition_status") or ""),
                "acquisition_guidance": gate.get("acquisition_guidance") if isinstance(gate.get("acquisition_guidance"), dict) else {},
                "pricing_worksheet": gate.get("pricing_worksheet") if isinstance(gate.get("pricing_worksheet"), dict) else {},
            }
        )
    return tasks


def _bid_state(session: dict[str, Any], rows: list[dict[str, Any]], gate_results: list[dict[str, Any]]) -> str:
    if not session.get("document"):
        if isinstance(session.get("acquisition"), dict):
            return "metadata_intake"
        return "uploaded"
    text = session.get("text") if isinstance(session.get("text"), dict) else {}
    if not text.get("chunks"):
        return "uploaded"
    if "compliance_matrix" not in session:
        return "pdf_parsed"
    if not rows:
        return "requirements_extracted"
    if gate_results:
        if _only_pricing_gates(gate_results) and all(bool(row.get("resolved")) for row in rows):
            return "requirements_resolved"
        return "evidence_gaps_open"
    return "owner_packet_ready"


def _compliance_decision(
    bid_state: str,
    gate_results: list[dict[str, Any]],
    agent_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    capability_gates = [gate for gate in gate_results if gate.get("rule_id") == "capability_gap"]
    hard_stops = [gate for gate in gate_results if gate.get("gate_type") == "hard_stop"]
    review_gates = [gate for gate in gate_results if gate.get("gate_type") == "review"]
    pricing_gates = [
        gate
        for gate in gate_results
        if str(gate.get("rule_id") or "").startswith("pricing") or gate.get("rule_id") == "estimator_pricing_approval_required"
    ]
    source_fact_ids = _unique_ids(
        fact_id
        for gate in gate_results
        for fact_id in gate.get("source_fact_ids") or []
    )
    source_gate_ids = [str(gate.get("gate_id") or "") for gate in gate_results if gate.get("gate_id")]
    next_task = agent_tasks[0] if agent_tasks else {}

    if capability_gates:
        return {
            "label": "Pass",
            "status": "Capability Gap",
            "reason": str(capability_gates[0].get("message") or "Capability gap found in the official PDF."),
            "blocking": True,
            "can_prepare_packet": False,
            "requires_owner_override": True,
            "hard_stop_count": len(hard_stops),
            "review_gate_count": len(review_gates),
            "source_gate_ids": source_gate_ids,
            "source_fact_ids": source_fact_ids,
            "next_action": str(next_task.get("title") or "Confirm capability"),
        }
    if hard_stops:
        return {
            "label": "Blocked",
            "status": "Blocked",
            "reason": str(hard_stops[0].get("message") or "Hard-stop compliance gate is open."),
            "blocking": True,
            "can_prepare_packet": False,
            "requires_owner_override": False,
            "hard_stop_count": len(hard_stops),
            "review_gate_count": len(review_gates),
            "source_gate_ids": source_gate_ids,
            "source_fact_ids": source_fact_ids,
            "next_action": str(next_task.get("title") or "Resolve hard stop"),
        }
    if review_gates:
        if pricing_gates:
            return {
                "label": "Review",
                "status": "Price Approval Needed",
                "reason": str(pricing_gates[0].get("message") or "Estimator pricing approval is required."),
                "blocking": True,
                "can_prepare_packet": False,
                "requires_owner_override": False,
                "hard_stop_count": 0,
                "review_gate_count": len(review_gates),
                "source_gate_ids": source_gate_ids,
                "source_fact_ids": source_fact_ids,
                "next_action": str(next_task.get("title") or "Approve target bid"),
            }
        return {
            "label": "Review",
            "status": "Needs Review",
            "reason": str(review_gates[0].get("message") or "Review gate is open."),
            "blocking": True,
            "can_prepare_packet": False,
            "requires_owner_override": False,
            "hard_stop_count": 0,
            "review_gate_count": len(review_gates),
            "source_gate_ids": source_gate_ids,
            "source_fact_ids": source_fact_ids,
            "next_action": str(next_task.get("title") or "Resolve review gate"),
        }
    if bid_state == "owner_packet_ready":
        return {
            "label": "Pursue",
            "status": "Eligible",
            "reason": "All deterministic PDF compliance gates are resolved.",
            "blocking": False,
            "can_prepare_packet": True,
            "requires_owner_override": False,
            "hard_stop_count": 0,
            "review_gate_count": 0,
            "source_gate_ids": [],
            "source_fact_ids": source_fact_ids,
            "next_action": "Prepare bid notes",
        }
    return {
        "label": "Review",
        "status": "Needs Review",
        "reason": "The official PDF did not produce enough cited requirements to prepare bid notes automatically.",
        "blocking": True,
        "can_prepare_packet": False,
        "requires_owner_override": False,
        "hard_stop_count": 0,
        "review_gate_count": 0,
        "source_gate_ids": [],
        "source_fact_ids": source_fact_ids,
        "next_action": "Review PDF manually",
    }


def _with_runtime_summary(summary: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    data = dict(summary) if isinstance(summary, dict) else {}
    gates = runtime.get("gate_results") or []
    hard_stops = sum(1 for gate in gates if gate.get("gate_type") == "hard_stop")
    review_gates = sum(1 for gate in gates if gate.get("gate_type") == "review")
    data["hard_stops"] = hard_stops
    data["review_gates"] = review_gates
    data["ready_to_prepare"] = runtime.get("bid_state") == "owner_packet_ready"
    return data


def _agent_summary(session: dict[str, Any]) -> dict[str, Any]:
    gates = session.get("gate_results") if isinstance(session.get("gate_results"), list) else []
    tasks = session.get("agent_tasks") if isinstance(session.get("agent_tasks"), list) else []
    facts = session.get("evidence_ledger") if isinstance(session.get("evidence_ledger"), list) else []
    actions = session.get("agent_actions") if isinstance(session.get("agent_actions"), list) else []
    manifest = session.get("submission_manifest") if isinstance(session.get("submission_manifest"), list) else []
    manifest_summary = (
        session.get("submission_manifest_summary")
        if isinstance(session.get("submission_manifest_summary"), dict)
        else summarize_submission_manifest(manifest)
    )
    hard_stops = sum(1 for gate in gates if isinstance(gate, dict) and gate.get("gate_type") == "hard_stop")
    review_gates = sum(1 for gate in gates if isinstance(gate, dict) and gate.get("gate_type") == "review")
    bid_state = str(session.get("bid_state") or "uploaded")
    compliance_decision = session.get("compliance_decision") if isinstance(session.get("compliance_decision"), dict) else {}
    next_task = tasks[0] if tasks and isinstance(tasks[0], dict) else {}
    if next_task:
        next_action = str(next_task.get("title") or "Resolve next deterministic task")
    elif bid_state == "owner_packet_ready":
        next_action = "Prepare bid notes"
    else:
        next_action = "Upload and review the official PDF"
    return {
        "bid_state": bid_state,
        "compliance_decision_label": str(compliance_decision.get("label") or ""),
        "compliance_decision_reason": str(compliance_decision.get("reason") or ""),
        "ready_to_prepare": bid_state == "owner_packet_ready",
        "evidence_fact_count": len(facts),
        "gate_count": len(gates),
        "hard_stop_count": hard_stops,
        "review_gate_count": review_gates,
        "task_count": len(tasks),
        "action_count": len(actions),
        "submission_manifest_count": len(manifest),
        "submission_manifest_required_open": int(manifest_summary.get("required_open") or 0),
        "next_action": next_action,
    }


def _agent_action(
    action_type: str,
    session: dict[str, Any],
    runtime: dict[str, Any],
    context: dict[str, Any],
    index: int,
    now: str,
) -> dict[str, Any]:
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ValueError(f"Unsupported agent action type: {action_type}")
    outputs = _action_output_ids(action_type, session, runtime, context)
    source_fact_ids = _action_source_fact_ids(action_type, session, runtime, context)
    return {
        "action_id": _id("action", session.get("analysis_id"), action_type, index, now),
        "action_type": action_type,
        "inputs": _action_inputs(action_type, session, context),
        "output_ids": outputs,
        "validation": {
            "passed": True,
            "messages": [],
        },
        "created_at": now,
        "source_fact_ids": source_fact_ids,
    }


def _action_inputs(action_type: str, session: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    document = session.get("document") if isinstance(session.get("document"), dict) else {}
    acquisition = session.get("acquisition") if isinstance(session.get("acquisition"), dict) else {}
    metadata = session.get("opportunity_metadata") if isinstance(session.get("opportunity_metadata"), dict) else {}
    base = {
        "analysis_id": session.get("analysis_id"),
        "opportunity_id": session.get("opportunity_id"),
    }
    if action_type == "open_data_metadata_loaded":
        base.update(
            {
                "document_number": metadata.get("document_number"),
                "source_label": acquisition.get("source_label"),
                "open_data_record_url": acquisition.get("open_data_record_url"),
            }
        )
    if action_type == "document_acquisition_checked":
        base.update(
            {
                "status": acquisition.get("status"),
                "package_required": acquisition.get("package_required"),
                "candidate_public_package_urls": acquisition.get("candidate_public_package_urls") or [],
            }
        )
    if action_type == "pdf_uploaded":
        base.update(
            {
                "filename": document.get("filename"),
                "content_hash": document.get("content_hash"),
            }
        )
    if action_type == "pdf_text_extracted":
        text = session.get("text") if isinstance(session.get("text"), dict) else {}
        base.update({"page_count": text.get("page_count"), "character_count": text.get("character_count")})
    if action_type == "requirement_resolved":
        base.update(
            {
                "requirement_id": context.get("requirement_id"),
                "resolution_type": context.get("resolution_type"),
            }
        )
    if action_type == "pricing_approved":
        pricing_worksheet = {}
        if isinstance(context.get("pricing_worksheet"), dict):
            pricing_worksheet = context.get("pricing_worksheet") or {}
        elif isinstance(session.get("pricing_worksheet"), dict):
            pricing_worksheet = session.get("pricing_worksheet") or {}
        base.update(
            {
                "target_bid": context.get("target_bid") or pricing_worksheet.get("target_bid"),
                "approved_by": context.get("approved_by"),
            }
        )
    if action_type == "owner_packet_prepared":
        base.update({"packet_id": context.get("packet_id")})
    return base


def _action_output_ids(
    action_type: str,
    session: dict[str, Any],
    runtime: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    rows = _rows(session)
    document = session.get("document") if isinstance(session.get("document"), dict) else {}
    acquisition = session.get("acquisition") if isinstance(session.get("acquisition"), dict) else {}
    metadata = session.get("opportunity_metadata") if isinstance(session.get("opportunity_metadata"), dict) else {}
    if action_type == "open_data_metadata_loaded":
        return [str(metadata.get("document_number") or session.get("opportunity_id") or "open_data_metadata")]
    if action_type == "document_acquisition_checked":
        return [str(acquisition.get("status") or "document_acquisition_checked")]
    if action_type == "pdf_uploaded":
        return [str(document.get("content_hash") or document.get("storage_key") or "uploaded_pdf")]
    if action_type == "pdf_text_extracted":
        text = session.get("text") if isinstance(session.get("text"), dict) else {}
        return [str(chunk.get("chunk_id") or index) for index, chunk in enumerate(text.get("chunks") or []) if isinstance(chunk, dict)]
    if action_type == "requirements_extracted":
        return [str(row.get("requirement_id") or "") for row in rows if row.get("requirement_id")]
    if action_type == "evidence_ledger_created":
        return [fact["fact_id"] for fact in runtime.get("evidence_ledger") or []]
    if action_type == "gate_rules_run":
        return [gate["gate_id"] for gate in runtime.get("gate_results") or []]
    if action_type == "tasks_generated":
        return [task["task_id"] for task in runtime.get("agent_tasks") or []]
    if action_type == "pricing_worksheet_created":
        pricing = runtime.get("pricing_worksheet") if isinstance(runtime.get("pricing_worksheet"), dict) else {}
        return [str(pricing.get("source") or "pricing_worksheet")] if pricing else []
    if action_type == "requirement_resolved":
        requirement_id = str(context.get("requirement_id") or "")
        return [
            fact["fact_id"]
            for fact in runtime.get("evidence_ledger") or []
            if fact.get("requirement_id") == requirement_id and fact.get("source_type") == "user_resolution"
        ]
    if action_type == "pricing_approved":
        pricing = runtime.get("pricing_worksheet") if isinstance(runtime.get("pricing_worksheet"), dict) else {}
        approval = pricing.get("estimator_approval") if isinstance(pricing.get("estimator_approval"), dict) else {}
        return [str(approval.get("approval_id") or "pricing_approval")]
    if action_type == "owner_packet_prepared":
        return [str(context.get("packet_id") or session.get("opportunity_id") or "approval_packet")]
    return []


def _action_source_fact_ids(
    action_type: str,
    session: dict[str, Any],
    runtime: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    facts = runtime.get("evidence_ledger") or []
    if action_type == "document_acquisition_checked":
        return [
            fact["fact_id"]
            for fact in facts
            if fact.get("source_type") in {"open_data_metadata", "document_acquisition"}
        ]
    if action_type in {"gate_rules_run", "tasks_generated"}:
        return [
            fact["fact_id"]
            for fact in facts
            if fact.get("fact_type") in {
                "requirement_detected",
                "opportunity_metadata",
                "document_acquisition_status",
                "pricing_worksheet",
            }
        ]
    if action_type == "pricing_worksheet_created":
        return [fact["fact_id"] for fact in facts if fact.get("fact_type") == "pricing_worksheet"]
    if action_type == "requirement_resolved":
        requirement_id = str(context.get("requirement_id") or "")
        return [
            fact["fact_id"]
            for fact in facts
            if fact.get("requirement_id") == requirement_id
        ]
    if action_type == "pricing_approved":
        return [
            fact["fact_id"]
            for fact in facts
            if fact.get("requirement_id") == "pricing-approval"
        ]
    if action_type == "owner_packet_prepared":
        return [
            fact["fact_id"]
            for fact in facts
            if fact.get("fact_type") in {"gate_result", "pricing_worksheet", "estimator_pricing_approval"}
        ]
    return []


def _source_fact_ids(requirement_id: str, fact_index: dict[str, dict[str, list[str]]]) -> list[str]:
    buckets = fact_index.get(requirement_id) or {}
    return [
        fact_id
        for bucket in ("requirement", "capability", "evidence", "resolution")
        for fact_id in buckets.get(bucket, [])
    ]


def _resolution_options(category: str, rule_id: str) -> list[dict[str, str]]:
    option_keys = RESOLUTION_OPTIONS_BY_CATEGORY.get(category, ("uploaded_evidence", "not_applicable"))
    if rule_id == "capability_gap":
        option_keys = ("capability_confirmed", "not_applicable")
    return [
        {"type": key, "label": RESOLUTION_TYPES[key]}
        for key in option_keys
        if key in RESOLUTION_TYPES
    ]


def _gate_message(row: dict[str, Any], gate_type: str, rule_id: str) -> str:
    requirement = str(row.get("requirement") or "this requirement")
    if rule_id == "capability_gap":
        return f"Capability gap must be confirmed before bidding: {requirement}"
    if gate_type == "hard_stop":
        return f"Resolve required evidence before preparing the bid packet: {requirement}"
    return f"Review and resolve this requirement before preparing the bid packet: {requirement}"


def _task_title(gate: dict[str, Any]) -> str:
    if gate.get("rule_id") == "official_package_required":
        return "Get Official Package"
    if gate.get("rule_id") == "estimator_pricing_approval_required":
        return "Approve Target Bid"
    if gate.get("rule_id") == "pricing_blocked":
        return "Fix Pricing Worksheet"
    category = str(gate.get("category") or "requirement").replace("_", " ").title()
    if gate.get("gate_type") == "hard_stop":
        return f"Resolve {category}"
    return f"Review {category}"


def _task_detail(gate: dict[str, Any], location: str) -> str:
    guidance = gate.get("acquisition_guidance") if isinstance(gate.get("acquisition_guidance"), dict) else {}
    parts = [str(gate.get("message") or "").strip()]
    pricing = gate.get("pricing_worksheet") if isinstance(gate.get("pricing_worksheet"), dict) else {}
    if pricing:
        parts.append(
            "Range: "
            f"${_money(pricing.get('low_bid')):,.0f}-${_money(pricing.get('high_bid')):,.0f}; "
            f"confidence {pricing.get('confidence') or 'Unknown'}."
        )
    if guidance.get("next_step"):
        parts.append(f"Next: {guidance.get('next_step')}")
    if guidance.get("portal_url"):
        parts.append(f"Portal: {guidance.get('portal_url')}")
    if guidance.get("search_hint"):
        parts.append(str(guidance.get("search_hint")))
    parts.append(f"Source: {location}.")
    return " ".join(part for part in parts if part)


def _only_pricing_gates(gate_results: list[dict[str, Any]]) -> bool:
    return bool(gate_results) and all(
        str(gate.get("rule_id") or "").startswith("pricing")
        or gate.get("rule_id") == "estimator_pricing_approval_required"
        for gate in gate_results
    )


def _rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    value = session.get("compliance_matrix")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _citation(row: dict[str, Any]) -> dict[str, Any]:
    citation = row.get("citation") if isinstance(row.get("citation"), dict) else {}
    return {
        "source": str(citation.get("source") or ""),
        "page": citation.get("page"),
        "chunk_id": str(citation.get("chunk_id") or ""),
        "snippet": str(citation.get("snippet") or ""),
    }


def _profile_citation(row: dict[str, Any]) -> dict[str, Any]:
    citation = _citation(row)
    citation["source_type"] = "business_profile"
    return citation


def _evidence_vault_citation(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence_id = str(evidence.get("evidence_id") or "").strip()
    source = str(evidence.get("source") or "evidence_vault").strip()
    label = str(evidence.get("label") or evidence.get("evidence_type") or "Evidence vault item").strip()
    return {
        "source": source,
        "page": None,
        "chunk_id": evidence_id,
        "snippet": label,
        "source_type": "evidence_vault",
        "source_label": "Evidence Vault",
    }


def _metadata_citation(session: dict[str, Any]) -> dict[str, Any]:
    acquisition = session.get("acquisition") if isinstance(session.get("acquisition"), dict) else {}
    metadata = session.get("opportunity_metadata") if isinstance(session.get("opportunity_metadata"), dict) else {}
    source = (
        str(acquisition.get("open_data_record_url") or "").strip()
        or str(acquisition.get("portal_url") or "").strip()
        or str(acquisition.get("source_label") or "Open data record")
    )
    snippet = str(metadata.get("title") or metadata.get("description") or acquisition.get("message") or "").strip()
    return {
        "source": source,
        "page": None,
        "chunk_id": str(metadata.get("document_number") or session.get("opportunity_id") or ""),
        "snippet": snippet,
        "source_type": str(acquisition.get("source_type") or "open_data_metadata"),
        "source_label": str(acquisition.get("source_label") or "Open Data"),
    }


def _pricing_citation(pricing_worksheet: dict[str, Any]) -> dict[str, Any]:
    target_bid = _money(pricing_worksheet.get("target_bid"))
    confidence = str(pricing_worksheet.get("confidence") or "Unknown")
    return {
        "source": "deterministic_pricing_worksheet",
        "page": None,
        "chunk_id": str(pricing_worksheet.get("source") or "pricing_worksheet"),
        "snippet": f"Target bid ${target_bid:,.0f}; confidence {confidence}.",
        "source_type": "pricing_worksheet",
        "source_label": "Pricing Worksheet",
    }


def _pricing_approval_citation(approval: dict[str, Any]) -> dict[str, Any]:
    target_bid = _money(approval.get("approved_target_bid"))
    return {
        "source": "estimator_approval",
        "page": None,
        "chunk_id": str(approval.get("approval_id") or "pricing_approval"),
        "snippet": f"Estimator approved target bid ${target_bid:,.0f}.",
        "source_type": "estimator_approval",
        "source_label": "Estimator Approval",
    }


def _has_pdf_citation(citation: dict[str, Any]) -> bool:
    return bool(str(citation.get("source") or "").strip() and str(citation.get("snippet") or "").strip())


def _fact(
    analysis_id: str,
    fact_type: str,
    value: Any,
    source_type: str,
    citation: dict[str, Any],
    confidence: str,
    created_at: str,
    *,
    requirement_id: str = "",
) -> dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Unsupported evidence source type: {source_type}")
    payload = {
        "fact_id": _id("fact", analysis_id, fact_type, source_type, requirement_id, value),
        "fact_type": fact_type,
        "value": value,
        "source_type": source_type,
        "citation": dict(citation or {}),
        "confidence": confidence,
        "created_at": created_at,
    }
    if requirement_id:
        payload["requirement_id"] = requirement_id
    return payload


def _unique_ids(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
