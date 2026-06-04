from __future__ import annotations

import hashlib
import json
from typing import Any

from contract_radar.submission_manifest import summarize_submission_manifest


SOURCE = "deterministic_form_blueprint"

SKIPPED_MANIFEST_ATTACHMENT_TYPES = {
    "owner_approval",
    "portal_submission_steps",
    "deadline_confirmation",
    "scope_confirmation",
}

PLACEHOLDER_VALUES = {
    "not listed",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "unknown-opportunity",
}


def build_form_blueprint(packet_or_session: dict, *, created_at: str = "") -> dict:
    """Build a deterministic buyer form and attachment blueprint without filling or submitting anything."""
    payload = _payload(packet_or_session)
    manifest = _rows(payload.get("submission_manifest") or payload.get("manifest"))
    manifest_summary = _manifest_summary(payload, manifest)
    assembly = payload.get("submission_assembly") if isinstance(payload.get("submission_assembly"), dict) else {}
    pricing = _pricing_worksheet(payload)

    assembly_fields = _assembly_field_index(assembly)
    opportunity_id, opportunity_source = _opportunity_id(payload, assembly)
    form_fields = _form_fields(payload, assembly_fields, pricing, opportunity_id, opportunity_source)
    attachments = _attachments(manifest, assembly)
    blockers = _blockers(payload, manifest, manifest_summary, assembly, pricing, attachments, form_fields)

    return {
        "source": SOURCE,
        "blueprint_id": _blueprint_id(opportunity_id, created_at, form_fields),
        "created_at": str(created_at or ""),
        "opportunity_id": opportunity_id,
        "ready_for_form_work": not blockers,
        "form_fields": form_fields,
        "attachments": attachments,
        "manual_steps": _manual_steps(payload, opportunity_id, form_fields, attachments, blockers),
        "blockers": blockers,
        "guardrails": [
            "no_submission: This blueprint does not submit, certify, upload, or click final buyer portal controls.",
            "no_buyer_email: This blueprint does not send buyer email or buyer-facing outreach.",
            "no_invented_fields: Copy only source-backed values; leave unknown buyer form fields for human completion.",
            "no_pdf_filling: This blueprint does not fill PDFs or alter buyer forms.",
        ],
    }


def _payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = dict(value)
    packet = payload.get("packet")
    if isinstance(packet, dict):
        unwrapped = dict(packet)
        for key in ("packet_id", "analysis_id", "packet_export"):
            if key in payload and key not in unwrapped:
                unwrapped[key] = payload[key]
        return unwrapped
    return payload


def _form_fields(
    payload: dict[str, Any],
    assembly_fields: dict[str, dict[str, Any]],
    pricing: dict[str, Any],
    opportunity_id: str,
    opportunity_source: str,
) -> list[dict[str, Any]]:
    profile = _dict_at(payload, "business_profile") or _dict_at(payload, "profile") or _dict_at(payload, "company_profile")
    buyer = _dict_at(payload, "buyer_contact")
    metadata = _dict_at(payload, "opportunity_metadata")
    solicitation = _solicitation(payload)

    company_name, company_source = _first_text(
        (profile.get("name"), "business_profile.name"),
        (_assembly_field_value(assembly_fields, "company_name"), "submission_assembly.prefilled_fields.company_name"),
    )
    buyer_name, buyer_name_source = _first_text(
        (buyer.get("name"), "buyer_contact.name"),
        (metadata.get("buyer_name"), "opportunity_metadata.buyer_name"),
        (solicitation.get("buyer_name"), "solicitation.buyer_name"),
        (_assembly_field_value(assembly_fields, "buyer_name"), "submission_assembly.prefilled_fields.buyer_name"),
    )
    buyer_email, buyer_email_source = _first_text(
        (buyer.get("email"), "buyer_contact.email"),
        (metadata.get("buyer_email"), "opportunity_metadata.buyer_email"),
        (solicitation.get("buyer_email"), "solicitation.buyer_email"),
        (_assembly_field_value(assembly_fields, "buyer_email"), "submission_assembly.prefilled_fields.buyer_email"),
    )
    deadline, deadline_source = _first_text(
        (payload.get("deadline"), "deadline"),
        (metadata.get("submission_deadline"), "opportunity_metadata.submission_deadline"),
        (solicitation.get("submission_deadline"), "solicitation.submission_deadline"),
        (_assembly_field_value(assembly_fields, "submission_deadline"), "submission_assembly.prefilled_fields.submission_deadline"),
        (_assembly_field_value(assembly_fields, "deadline"), "submission_assembly.prefilled_fields.deadline"),
    )
    target_bid, target_source = _target_bid(payload, pricing, assembly_fields)

    rows = [
        _field("company_name", "Company legal name", company_name, company_source),
        _field("opportunity_id", "Opportunity ID", opportunity_id, opportunity_source),
        _field("buyer_name", "Buyer name", buyer_name, buyer_name_source),
        _field("buyer_email", "Buyer email", buyer_email, buyer_email_source),
        _field("approved_target_bid", "Approved target bid", target_bid, target_source),
        _field("deadline", "Submission deadline", deadline, deadline_source),
    ]
    return [row for row in rows if row]


def _field(field_id: str, label: str, value: str, source: str) -> dict[str, Any]:
    text = _clean_text(value)
    if not text:
        return {}
    return {
        "field_id": field_id,
        "label": label,
        "value": text,
        "status": "copy_ready",
        "source": source,
    }


def _attachments(manifest: list[dict[str, Any]], assembly: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    covered_manifest_ids: set[str] = set()
    for item in _rows(assembly.get("attachments")):
        attachment = _assembly_attachment(item)
        if not attachment:
            continue
        source_manifest_id = str(item.get("source_manifest_id") or "").strip()
        if source_manifest_id:
            covered_manifest_ids.add(source_manifest_id)
        rows.append(attachment)

    for item in manifest:
        manifest_id = str(item.get("manifest_id") or "").strip()
        if manifest_id and manifest_id in covered_manifest_ids:
            continue
        attachment = _manifest_attachment(item)
        if attachment:
            rows.append(attachment)

    return _dedupe_attachments(rows)


def _assembly_attachment(item: dict[str, Any]) -> dict[str, Any]:
    label = _clean_text(item.get("label") or item.get("filename") or "Submission attachment")
    if not label:
        return {}
    attachment_id = _clean_text(item.get("attachment_id")) or _id(
        "attachment",
        "assembly",
        item.get("source_manifest_id"),
        item.get("filename"),
        label,
    )
    row = {
        "attachment_id": attachment_id,
        "label": label,
        "status": _clean_text(item.get("status")) or "review",
        "source": "submission_assembly",
        "evidence_ids": _text_list(item.get("evidence_ids")),
        "citation": _citation(item.get("citation")),
    }
    for key in ("item_type", "required", "filename", "source_manifest_id", "source_package_document_id"):
        if key in item:
            row[key] = item.get(key)
    return row


def _manifest_attachment(item: dict[str, Any]) -> dict[str, Any]:
    item_type = _clean_text(item.get("item_type"))
    if not item_type or item_type in SKIPPED_MANIFEST_ATTACHMENT_TYPES:
        return {}
    label = _clean_text(item.get("label") or item_type.replace("_", " ").title())
    if not label:
        return {}
    manifest_id = _clean_text(item.get("manifest_id"))
    row = {
        "attachment_id": _id("attachment", "manifest", manifest_id, item_type, label),
        "label": label,
        "status": _clean_text(item.get("status")) or "review",
        "source": "submission_manifest",
        "evidence_ids": _text_list(item.get("evidence_ids")),
        "citation": _citation(item.get("citation")),
        "item_type": item_type,
        "required": _bool_value(item.get("required", True)),
        "source_manifest_id": manifest_id,
    }
    return row


def _blockers(
    payload: dict[str, Any],
    manifest: list[dict[str, Any]],
    manifest_summary: dict[str, Any],
    assembly: dict[str, Any],
    pricing: dict[str, Any],
    attachments: list[dict[str, Any]],
    form_fields: list[dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    owner_ready, owner_known = _owner_ready(payload)
    if owner_known and not owner_ready:
        rows.append(
            _blocker(
                "owner_ready_false",
                "Owner approval missing",
                "Owner readiness is false; a human owner must approve the packet before buyer form work.",
                "owner_ready",
            )
        )

    required_open = _int_value(manifest_summary.get("required_open"))
    if required_open > 0:
        rows.append(
            _blocker(
                "manifest_required_open",
                "Required manifest items open",
                f"{required_open} required submission manifest item(s) remain open.",
                "submission_manifest_summary.required_open",
            )
        )

    if not pricing:
        rows.append(
            _blocker(
                "pricing_worksheet_missing",
                "Pricing worksheet missing",
                "No deterministic pricing worksheet is attached to this packet or session.",
                "pricing_worksheet",
            )
        )

    has_target_bid = any(row.get("field_id") == "approved_target_bid" for row in form_fields)
    if not has_target_bid:
        rows.append(
            _blocker(
                "approved_target_bid_missing",
                "Approved target bid missing",
                "No approved_target_bid or target_bid value is available for buyer form entry.",
                "pricing_worksheet.target_bid",
            )
        )

    if _attachments_required(manifest, manifest_summary, assembly) and not attachments:
        rows.append(
            _blocker(
                "attachments_missing",
                "Assembly attachments missing",
                "Submission attachments appear to be required, but no manifest or assembly attachment rows are available.",
                "submission_assembly.attachments",
            )
        )

    return _dedupe_blockers(rows)


def _blocker(blocker_id: str, label: str, detail: str, source: str) -> dict[str, str]:
    return {
        "blocker_id": blocker_id,
        "label": label,
        "detail": detail,
        "source": source,
    }


def _manual_steps(
    payload: dict[str, Any],
    opportunity_id: str,
    form_fields: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    blockers: list[dict[str, str]],
) -> list[dict[str, Any]]:
    acquisition = _dict_at(payload, "acquisition")
    guidance = acquisition.get("guidance") if isinstance(acquisition.get("guidance"), dict) else {}
    source_links = _dict_at(_solicitation(payload), "source_links")
    portal_url = _clean_text(
        acquisition.get("portal_url")
        or guidance.get("portal_url")
        or source_links.get("toronto_bids_portal_url")
    )
    search_hint = _clean_text(
        acquisition.get("search_hint")
        or guidance.get("search_hint")
        or source_links.get("toronto_bids_search_hint")
    )
    status = "ready" if not blockers else "blocked"
    step_data = [
        (
            "open_buyer_portal",
            "Open buyer portal",
            portal_url or "Open the official buyer portal for this opportunity.",
        ),
        (
            "find_opportunity",
            "Find opportunity",
            search_hint or f"Search for {opportunity_id or 'the opportunity'} in the buyer portal.",
        ),
        (
            "copy_known_fields",
            "Copy known fields",
            f"Copy {len(form_fields)} source-backed field value(s) into matching buyer form fields only.",
        ),
        (
            "prepare_attachments",
            "Prepare attachments",
            f"Prepare {len(attachments)} expected attachment(s) and resolve any non-ready status before human upload.",
        ),
        (
            "complete_buyer_specific_fields",
            "Complete buyer-specific fields",
            "A human must complete portal-only fields, certifications, acknowledgements, and any field not listed here.",
        ),
        (
            "human_review",
            "Human review",
            "A human verifies addenda, attachments, portal validation, and price before any action outside this blueprint.",
        ),
    ]
    return [
        {
            "step_id": _id("manual-step", opportunity_id, step_type, index),
            "sequence": index,
            "step_type": step_type,
            "label": label,
            "instruction": instruction,
            "actor": "human",
            "status": status,
        }
        for index, (step_type, label, instruction) in enumerate(step_data, start=1)
    ]


def _opportunity_id(payload: dict[str, Any], assembly: dict[str, Any]) -> tuple[str, str]:
    metadata = _dict_at(payload, "opportunity_metadata")
    solicitation = _solicitation(payload)
    opportunity = _dict_at(payload, "opportunity")
    text, source = _first_text(
        (payload.get("opportunity_id"), "opportunity_id"),
        (metadata.get("document_number"), "opportunity_metadata.document_number"),
        (metadata.get("opportunity_id"), "opportunity_metadata.opportunity_id"),
        (solicitation.get("document_number"), "solicitation.document_number"),
        (opportunity.get("opportunity_id"), "opportunity.opportunity_id"),
        (assembly.get("opportunity_id"), "submission_assembly.opportunity_id"),
    )
    return text, source


def _target_bid(
    payload: dict[str, Any],
    pricing: dict[str, Any],
    assembly_fields: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    approval = pricing.get("estimator_approval") if isinstance(pricing.get("estimator_approval"), dict) else {}
    pricing_approval = _dict_at(payload, "pricing_approval")
    candidates = [
        (approval.get("approved_target_bid"), "pricing_worksheet.estimator_approval.approved_target_bid"),
        (pricing.get("approved_target_bid"), "pricing_worksheet.approved_target_bid"),
        (pricing_approval.get("approved_target_bid"), "pricing_approval.approved_target_bid"),
        (pricing.get("target_bid"), "pricing_worksheet.target_bid"),
        (_assembly_field_value(assembly_fields, "approved_target_bid"), "submission_assembly.prefilled_fields.approved_target_bid"),
        (_assembly_field_value(assembly_fields, "target_bid"), "submission_assembly.prefilled_fields.target_bid"),
    ]
    for value, source in candidates:
        text = _money_text(value)
        if text:
            return text, source
    return "", ""


def _pricing_worksheet(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("pricing_worksheet")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    opportunity = payload.get("opportunity")
    if isinstance(opportunity, dict) and isinstance(opportunity.get("pricing_worksheet"), dict):
        return dict(opportunity.get("pricing_worksheet") or {})
    return {}


def _manifest_summary(payload: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any]:
    summary = payload.get("submission_manifest_summary")
    if isinstance(summary, dict) and summary:
        return dict(summary)
    if manifest:
        return summarize_submission_manifest(manifest)
    return {}


def _attachments_required(
    manifest: list[dict[str, Any]],
    manifest_summary: dict[str, Any],
    assembly: dict[str, Any],
) -> bool:
    if any(_manifest_attachment(item) for item in manifest if _bool_value(item.get("required", True))):
        return True
    assembly_summary = assembly.get("summary") if isinstance(assembly.get("summary"), dict) else {}
    if _int_value(assembly_summary.get("attachments")) > 0:
        return True
    return _int_value(manifest_summary.get("attachment_count")) > 0


def _owner_ready(payload: dict[str, Any]) -> tuple[bool, bool]:
    for key in ("owner_ready", "owner_approved", "approved"):
        if key in payload:
            return _bool_value(payload.get(key)), True
    owner = payload.get("owner_approval")
    if isinstance(owner, dict):
        if "approved" in owner:
            return _bool_value(owner.get("approved")), True
        status = _clean_text(owner.get("status")).lower()
        if status:
            return status == "approved", True
    return False, False


def _assembly_field_index(assembly: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for field in _rows(assembly.get("prefilled_fields") or assembly.get("form_fields")):
        field_id = _clean_text(field.get("field_id") or field.get("id"))
        if field_id and field_id not in rows:
            rows[field_id] = field
    return rows


def _assembly_field_value(fields: dict[str, dict[str, Any]], field_id: str) -> str:
    field = fields.get(field_id) or {}
    return _clean_text(field.get("value"))


def _solicitation(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("solicitation")
    if isinstance(direct, dict):
        return direct
    opportunity = payload.get("opportunity")
    if isinstance(opportunity, dict) and isinstance(opportunity.get("solicitation"), dict):
        return dict(opportunity.get("solicitation") or {})
    return {}


def _dict_at(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _first_text(*candidates: tuple[Any, str]) -> tuple[str, str]:
    for value, source in candidates:
        text = _clean_text(value)
        if text:
            return text, source
    return "", ""


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in PLACEHOLDER_VALUES:
        return ""
    return text


def _money_text(value: Any) -> str:
    amount = _money(value)
    if amount <= 0:
        return ""
    if float(amount).is_integer():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _money(value: Any) -> float:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return bool(value)


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    output: list[str] = []
    for item in value:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _citation(value: Any) -> dict[str, Any]:
    citation = value if isinstance(value, dict) else {}
    row = {
        "source": _clean_text(citation.get("source")),
        "page": citation.get("page"),
        "chunk_id": _clean_text(citation.get("chunk_id")),
        "snippet": _clean_text(citation.get("snippet")),
    }
    for key in ("source_type", "source_label"):
        if citation.get(key):
            row[key] = _clean_text(citation.get(key))
    return row


def _dedupe_attachments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        attachment_id = _clean_text(row.get("attachment_id"))
        key = attachment_id or f"{row.get('source')}:{row.get('label')}"
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _dedupe_blockers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        blocker_id = row.get("blocker_id", "")
        if not blocker_id or blocker_id in seen:
            continue
        seen.add(blocker_id)
        output.append(row)
    return output


def _blueprint_id(opportunity_id: str, created_at: str, form_fields: list[dict[str, Any]]) -> str:
    key_values = [
        {
            "field_id": str(field.get("field_id") or ""),
            "value": str(field.get("value") or ""),
        }
        for field in form_fields
        if field.get("field_id")
    ]
    return _id("form-blueprint", opportunity_id, str(created_at or ""), key_values)


def _id(prefix: str, *parts: Any) -> str:
    stable = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
