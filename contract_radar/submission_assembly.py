from __future__ import annotations

import hashlib
from typing import Any

from contract_radar.models import BusinessProfile
from contract_radar.submission_manifest import OPEN_STATUSES, summarize_submission_manifest


READY_STATUS = "ready_for_human_submission_review"
BLOCKED_STATUS = "blocked_required_items"
PENDING_OWNER_STATUS = "pending_owner_approval"


def build_submission_assembly(
    business_profile: BusinessProfile | dict[str, Any],
    opportunity: Any,
    *,
    submission_manifest: Any | None = None,
    pricing_worksheet: dict[str, Any] | None = None,
    acquisition: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
    buyer_contact: dict[str, Any] | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    profile = _as_profile(business_profile)
    solicitation = _value(opportunity, "solicitation", {}) or {}
    manifest = _rows(submission_manifest)
    manifest_summary = summarize_submission_manifest(manifest)
    pricing = dict(pricing_worksheet or {})
    acquisition_data = dict(acquisition or {})
    document_data = dict(document or {})
    contact = dict(buyer_contact or {})
    opportunity_id = str(_value(solicitation, "document_number") or _value(opportunity, "opportunity_id") or "").strip()
    title = str(_value(solicitation, "description") or _value(opportunity, "title") or opportunity_id).strip()
    status = _assembly_status(approved=approved, manifest_summary=manifest_summary)
    fields = _prefilled_fields(profile, solicitation, contact, pricing, opportunity_id, title)
    attachments = _attachments(manifest, document_data, acquisition_data)
    portal_steps = _portal_steps(
        opportunity_id=opportunity_id,
        title=title,
        acquisition=acquisition_data,
        pricing=pricing,
        attachments=attachments,
        approved=approved,
        status=status,
    )
    final_checks = _final_checks(status=status, manifest_summary=manifest_summary, acquisition=acquisition_data)
    assembly_id = _id(
        "assembly",
        opportunity_id,
        status,
        manifest_summary.get("total"),
        manifest_summary.get("required_open"),
        pricing.get("target_bid"),
    )
    return {
        "assembly_id": assembly_id,
        "opportunity_id": opportunity_id,
        "title": title,
        "status": status,
        "ready_for_human_submission": status == READY_STATUS,
        "human_submission_required": True,
        "warning": (
            "Project Bid Bot assembled deterministic submission materials for human review only. "
            "It did not upload, certify, email, or submit a bid."
        ),
        "summary": {
            "prefilled_fields": len(fields),
            "missing_prefilled_fields": sum(1 for field in fields if field.get("status") == "missing"),
            "attachments": len(attachments),
            "open_attachments": sum(1 for item in attachments if item.get("status") in OPEN_STATUSES),
            "portal_steps": len(portal_steps),
            "required_open": int(manifest_summary.get("required_open") or 0),
            "ready_for_submission_review": status == READY_STATUS,
        },
        "prefilled_fields": fields,
        "attachments": attachments,
        "portal_steps": portal_steps,
        "final_checks": final_checks,
    }


def _assembly_status(*, approved: bool, manifest_summary: dict[str, Any]) -> str:
    if not approved:
        return PENDING_OWNER_STATUS
    if int(manifest_summary.get("required_open") or 0) > 0:
        return BLOCKED_STATUS
    return READY_STATUS


def _prefilled_fields(
    profile: BusinessProfile,
    solicitation: Any,
    contact: dict[str, Any],
    pricing: dict[str, Any],
    opportunity_id: str,
    title: str,
) -> list[dict[str, Any]]:
    target_bid = _money(pricing.get("approved_target_bid") or pricing.get("target_bid"))
    rows = [
        _field("company_name", "Company legal name", profile.name, "business_profile", "name"),
        _field("business_type", "Business type", profile.business_type, "business_profile", "business_type"),
        _field("service_area", "Service area", profile.service_area, "business_profile", "service_area"),
        _field("years_in_business", "Years in business", profile.years_in_business, "business_profile", "years_in_business"),
        _field("team_size", "Team size", profile.team_size, "business_profile", "team_size"),
        _field("insurance_coverage", "Insurance coverage", profile.insurance_coverage, "business_profile", "insurance_coverage"),
        _field("bonding_limit", "Single-job bonding limit", profile.bonding_single_job_limit, "business_profile", "bonding_single_job_limit"),
        _field("document_number", "Solicitation document number", opportunity_id, "opportunity_metadata", "document_number"),
        _field("opportunity_title", "Opportunity title", title, "opportunity_metadata", "title"),
        _field("submission_deadline", "Submission deadline", _value(solicitation, "submission_deadline"), "opportunity_metadata", "submission_deadline"),
        _field("buyer_name", "Buyer name", contact.get("name") or _value(solicitation, "buyer_name"), "opportunity_metadata", "buyer_name"),
        _field("buyer_email", "Buyer email", contact.get("email") or _value(solicitation, "buyer_email"), "opportunity_metadata", "buyer_email"),
        _field("buyer_phone", "Buyer phone", contact.get("phone") or _value(solicitation, "buyer_phone"), "opportunity_metadata", "buyer_phone"),
        _field("buyer_division", "Buyer division", contact.get("division") or _value(solicitation, "division"), "opportunity_metadata", "division"),
        _field("approved_target_bid", "Approved target bid", target_bid, "pricing_worksheet", "target_bid"),
    ]
    return rows


def _field(field_id: str, label: str, value: Any, source_type: str, source_id: str) -> dict[str, Any]:
    text = _display_value(value)
    return {
        "field_id": field_id,
        "label": label,
        "value": text,
        "status": "prefilled" if text else "missing",
        "source_type": source_type,
        "source_id": source_id,
    }


def _attachments(manifest: list[dict[str, Any]], document: dict[str, Any], acquisition: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in manifest:
        item_type = str(item.get("item_type") or "").strip()
        if item_type in {"owner_approval", "portal_submission_steps", "deadline_confirmation", "scope_confirmation"}:
            continue
        label = str(item.get("label") or item_type or "Submission item").strip()
        evidence_ids = [str(value).strip() for value in item.get("evidence_ids") or [] if str(value).strip()]
        status = str(item.get("status") or "review")
        filename = ""
        if item_type == "official_package" and document:
            filename = str(document.get("filename") or "official-package.pdf")
        rows.append(
            {
                "attachment_id": _id("attachment", item.get("manifest_id"), item_type, label),
                "label": label,
                "item_type": item_type,
                "status": status,
                "required": bool(item.get("required", True)),
                "owner": str(item.get("owner") or "Bid Coordinator"),
                "filename": filename,
                "evidence_ids": evidence_ids,
                "citation": item.get("citation") if isinstance(item.get("citation"), dict) else {},
                "source_manifest_id": str(item.get("manifest_id") or ""),
                "upload_instruction": _upload_instruction(item_type, label, status),
            }
        )
    rows.extend(_package_document_attachments(acquisition, document, rows))
    return rows


def _package_document_attachments(
    acquisition: dict[str, Any],
    document: dict[str, Any],
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_filenames = {
        str(row.get("filename") or "").strip().lower()
        for row in existing_rows
        if str(row.get("filename") or "").strip()
    }
    fetched_filename = str(document.get("filename") or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for package_doc in acquisition.get("package_documents") or []:
        if not isinstance(package_doc, dict) or not package_doc.get("include_for_submission"):
            continue
        filename = str(package_doc.get("filename") or "").strip()
        if not filename:
            continue
        if filename.lower() in existing_filenames or filename.lower() == fetched_filename:
            continue
        document_type = str(package_doc.get("document_type") or "package_document")
        label = _package_document_label(document_type, str(package_doc.get("label") or filename))
        rows.append(
            {
                "attachment_id": _id("attachment", "package-document", package_doc.get("package_document_id"), filename),
                "label": label,
                "item_type": f"package_document:{document_type}",
                "status": "ready",
                "required": document_type in {"addendum", "pricing_form", "required_form"},
                "owner": "Bid Coordinator" if document_type != "pricing_form" else "Estimator",
                "filename": filename,
                "url": str(package_doc.get("url") or ""),
                "content_hash": str(package_doc.get("content_hash") or ""),
                "storage_key": str(package_doc.get("storage_key") or ""),
                "mime_type": str(package_doc.get("mime_type") or "application/pdf"),
                "evidence_ids": [],
                "citation": {
                    "source": str(package_doc.get("url") or ""),
                    "page": None,
                    "chunk_id": str(package_doc.get("document_type") or ""),
                    "snippet": str(package_doc.get("reason") or ""),
                },
                "source_manifest_id": "",
                "source_package_document_id": str(package_doc.get("package_document_id") or ""),
                "upload_instruction": _package_document_upload_instruction(document_type, filename),
            }
        )
    return rows


def _portal_steps(
    *,
    opportunity_id: str,
    title: str,
    acquisition: dict[str, Any],
    pricing: dict[str, Any],
    attachments: list[dict[str, Any]],
    approved: bool,
    status: str,
) -> list[dict[str, Any]]:
    guidance = acquisition.get("guidance") if isinstance(acquisition.get("guidance"), dict) else {}
    portal_url = str(acquisition.get("portal_url") or guidance.get("portal_url") or "").strip()
    search_hint = str(acquisition.get("search_hint") or guidance.get("search_hint") or "").strip()
    target_bid = _money(pricing.get("approved_target_bid") or pricing.get("target_bid"))
    ready_attachments = sum(1 for item in attachments if item.get("status") == "ready")
    steps = [
        ("open_portal", "Open buyer portal", portal_url or "Open the official buyer portal for this buyer.", "human_action_required"),
        ("search_opportunity", "Find solicitation", search_hint or f"Search {opportunity_id or title} in the buyer portal.", "human_action_required"),
        ("complete_forms", "Complete buyer forms", "Copy deterministic prefilled fields into the official portal or buyer forms.", "human_action_required"),
        ("enter_price", "Enter approved price", f"Enter approved target bid {target_bid or 'from the estimator worksheet'}.", "human_action_required"),
        ("upload_attachments", "Upload attachments", f"Upload {ready_attachments} ready attachment(s), then verify every required portal upload.", "human_action_required"),
        ("acknowledge_addenda", "Acknowledge addenda", "Confirm all official addenda visible in the buyer portal before submission.", "human_action_required"),
        ("final_submit", "Final human submission", "Submit only after owner approval, portal validation, and final price verification.", "human_action_required"),
    ]
    output: list[dict[str, Any]] = []
    for index, (step_type, label, instruction, actor) in enumerate(steps, start=1):
        output.append(
            {
                "step_id": _id("portal-step", opportunity_id, step_type, index),
                "sequence": index,
                "step_type": step_type,
                "label": label,
                "instruction": instruction,
                "actor": actor,
                "status": "ready" if approved and status == READY_STATUS else "blocked",
            }
        )
    return output


def _final_checks(*, status: str, manifest_summary: dict[str, Any], acquisition: dict[str, Any]) -> list[str]:
    checks = [
        "Verify the official solicitation package and all addenda in the buyer portal.",
        "Confirm uploaded attachment filenames match the portal requirements.",
        "Confirm the approved target bid matches the estimator worksheet.",
        "Save the portal confirmation number and final submitted package outside Project Bid Bot.",
    ]
    if status != READY_STATUS:
        next_item = str(manifest_summary.get("next_item") or "").strip()
        checks.insert(0, f"Resolve required open item before submission assembly: {next_item or 'open manifest item'}.")
    if acquisition.get("portal_url"):
        checks.append(f"Use official portal URL: {acquisition.get('portal_url')}.")
    return checks


def _upload_instruction(item_type: str, label: str, status: str) -> str:
    if status != "ready":
        return f"Resolve {label} before upload."
    if item_type == "official_package":
        return "Keep the official solicitation package with the submission audit trail."
    if item_type == "pricing_form":
        return "Transfer estimator-approved pricing into the official buyer pricing form."
    return f"Upload or confirm {label} in the buyer portal."


def _package_document_label(document_type: str, label: str) -> str:
    prefix = {
        "addendum": "Public addendum",
        "pricing_form": "Public pricing form",
        "drawings": "Public drawings",
        "specifications": "Public specifications",
        "required_form": "Public required form",
        "other_public_pdf": "Public package document",
    }.get(document_type, "Public package document")
    return f"{prefix}: {label}"


def _package_document_upload_instruction(document_type: str, filename: str) -> str:
    if document_type == "pricing_form":
        return f"Download {filename}, apply estimator-approved pricing, and upload or enter it in the buyer portal."
    if document_type == "addendum":
        return f"Download {filename}, verify acknowledgement requirements, and confirm it in the buyer portal."
    return f"Download and retain {filename} with the submission package if the buyer portal requires it."


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _as_profile(profile: BusinessProfile | dict[str, Any]) -> BusinessProfile:
    if isinstance(profile, BusinessProfile):
        return profile
    return BusinessProfile.from_payload(profile if isinstance(profile, dict) else {})


def _value(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _display_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return str(value or "").strip()


def _money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.0f}" if amount > 0 else ""


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
