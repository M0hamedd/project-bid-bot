from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from contract_radar import config


PROFILE_SOURCE = "business_profile"
PROFILE_ASSERTED_STATUS = "profile_asserted"
USER_UPLOADED_SOURCE = "user_uploaded"
DEFAULT_EVIDENCE_STORAGE_DIR = Path(
    os.getenv("CONTRACT_RADAR_EVIDENCE_STORAGE_DIR", config.ROOT_DIR / "data" / "uploads" / "evidence")
)
MAX_EVIDENCE_BYTES = 15_000_000


def evidence_inventory_for_profile(
    profile: Any,
    persisted_records: Iterable[dict[str, Any]] | None = None,
    *,
    now: str = "",
) -> dict[str, Any]:
    """Build a deterministic local evidence inventory for requirement matching."""
    profile_payload = _profile_dict(profile)
    profile_id = str(profile_payload.get("profile_id") or "unknown-profile").strip()
    generated = profile_evidence_records(profile_payload, now=now)
    persisted = [
        _normalize_record(record)
        for record in persisted_records or []
        if isinstance(record, dict) and _record_profile_id(record) in {"", profile_id}
    ]
    records = _dedupe_records([*persisted, *generated])
    return {
        "profile_id": profile_id,
        "source": "local_evidence_vault",
        "generated_from_profile": len(generated),
        "persisted_records": len(persisted),
        "records": records,
        "terms": _inventory_terms(records),
        "updated_at": str(now or _utc_now()),
    }


def profile_evidence_records(profile: Any, *, now: str = "") -> list[dict[str, Any]]:
    profile_payload = _profile_dict(profile)
    profile_id = str(profile_payload.get("profile_id") or "unknown-profile").strip()
    created_at = str(now or _utc_now())
    records: list[dict[str, Any]] = []

    insurance = str(profile_payload.get("insurance_coverage") or "").strip()
    if insurance:
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type="insurance_certificate",
                label=insurance,
                source_field="insurance_coverage",
                tags=["insurance", "cgl", "liability", "certificate"],
                created_at=created_at,
            )
        )

    bonding_limit = _float_value(profile_payload.get("bonding_single_job_limit"))
    if bonding_limit > 0:
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type="bonding_capacity",
                label=f"Bonding capacity up to ${bonding_limit:,.0f}",
                source_field="bonding_single_job_limit",
                tags=["bond", "bonding", "surety", "capacity", "performance bond", "bid bond"],
                created_at=created_at,
                value={"limit": bonding_limit},
            )
        )

    for label in _list_value(profile_payload, "ready_documents"):
        evidence_type = _evidence_type_for_label(label)
        if evidence_type:
            records.append(
                _record(
                    profile_id=profile_id,
                    evidence_type=evidence_type,
                    label=label,
                    source_field="ready_documents",
                    tags=_tags_for_label(label, evidence_type),
                    created_at=created_at,
                )
            )

    for label in _list_value(profile_payload, "certifications"):
        evidence_type = "license" if _has_any(label, ("license", "licence", "licensed", "permit")) else "certification"
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type=evidence_type,
                label=label,
                source_field="certifications",
                tags=_tags_for_label(label, evidence_type),
                created_at=created_at,
            )
        )

    for label in _list_value(profile_payload, "recent_municipal_work"):
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type="reference_project",
                label=label,
                source_field="recent_municipal_work",
                tags=_tags_for_label(label, "reference_project"),
                created_at=created_at,
            )
        )

    equipment = _list_value(profile_payload, "owned_equipment")
    if equipment:
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type="equipment_list",
                label=", ".join(equipment[:6]),
                source_field="owned_equipment",
                tags=["equipment", *equipment],
                created_at=created_at,
                value={"equipment": equipment},
            )
        )

    crew_mix = str(profile_payload.get("crew_mix") or "").strip()
    if crew_mix:
        records.append(
            _record(
                profile_id=profile_id,
                evidence_type="crew_capacity",
                label=crew_mix,
                source_field="crew_mix",
                tags=["crew", "capacity", "staff", "team", "foreperson", "estimator"],
                created_at=created_at,
            )
        )

    return _dedupe_records(records)


def store_uploaded_evidence_record(
    *,
    profile: Any,
    filename: str,
    content: bytes,
    evidence_type: str = "",
    label: str = "",
    capability_tags: Iterable[str] | None = None,
    issued_at: str = "",
    expires_at: str = "",
    storage_dir: Path | str | None = None,
    now: str = "",
) -> dict[str, Any]:
    profile_payload = _profile_dict(profile)
    profile_id = str(profile_payload.get("profile_id") or "unknown-profile").strip()
    safe_filename = _clean_filename(filename)
    if not isinstance(content, bytes) or not content:
        raise ValueError("Evidence upload requires file bytes.")
    if len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence upload is larger than the local storage limit.")

    content_hash = hashlib.sha256(content).hexdigest()
    extension = _extension(safe_filename)
    root = Path(storage_dir) if storage_dir is not None else DEFAULT_EVIDENCE_STORAGE_DIR
    files_dir = root / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"files/{content_hash}{extension}"
    file_path = root / storage_key
    if not file_path.exists():
        file_path.write_bytes(content)

    resolved_type = evidence_type_for_label_or_category(evidence_type or label or safe_filename)
    record = {
        "evidence_id": _evidence_id(profile_id, resolved_type, content_hash, safe_filename),
        "evidence_type": resolved_type,
        "label": str(label or safe_filename).strip(),
        "filename": safe_filename,
        "content_hash": content_hash,
        "size": len(content),
        "storage_key": storage_key,
        "source": USER_UPLOADED_SOURCE,
        "source_field": "",
        "profile_id": profile_id,
        "capability_tags": _unique([
            resolved_type,
            safe_filename,
            str(label or ""),
            *[str(tag) for tag in capability_tags or []],
            *_tags_for_label(" ".join([safe_filename, str(label or ""), resolved_type]), resolved_type),
        ]),
        "verified_status": "user_confirmed",
        "issued_at": str(issued_at or ""),
        "expires_at": str(expires_at or ""),
        "created_at": str(now or _utc_now()),
        "updated_at": str(now or _utc_now()),
    }
    _write_upload_index(root, record)
    return record


def evidence_type_for_label_or_category(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "uploaded_evidence"
    if text in {
        "insurance_certificate",
        "bonding_capacity",
        "safety_document",
        "license",
        "certification",
        "reference_project",
        "equipment_list",
        "crew_capacity",
        "pricing_form",
        "submission_form",
        "site_visit_confirmation",
        "addendum_acknowledgement",
        "uploaded_evidence",
    }:
        return text
    category_map = {
        "insurance": "insurance_certificate",
        "bonding": "bonding_capacity",
        "safety": "safety_document",
        "license": "license",
        "certification": "certification",
        "experience": "reference_project",
        "pricing_sheet": "pricing_form",
        "form": "submission_form",
        "site_visit": "site_visit_confirmation",
        "addendum": "addendum_acknowledgement",
    }
    if text in category_map:
        return category_map[text]
    return _evidence_type_for_label(text) or "uploaded_evidence"


def _record(
    *,
    profile_id: str,
    evidence_type: str,
    label: str,
    source_field: str,
    tags: Iterable[str],
    created_at: str,
    value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    record = {
        "evidence_id": _evidence_id(profile_id, evidence_type, clean_label, source_field),
        "evidence_type": evidence_type,
        "label": clean_label,
        "filename": "",
        "content_hash": "",
        "source": PROFILE_SOURCE,
        "source_field": source_field,
        "profile_id": profile_id,
        "capability_tags": _unique([evidence_type, *tags, clean_label]),
        "verified_status": PROFILE_ASSERTED_STATUS,
        "issued_at": "",
        "expires_at": "",
        "created_at": created_at,
        "updated_at": created_at,
    }
    if value:
        record["value"] = value
    return record


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    label = str(record.get("label") or record.get("filename") or record.get("evidence_type") or "").strip()
    evidence_type = str(record.get("evidence_type") or _evidence_type_for_label(label) or "uploaded_evidence").strip()
    profile_id = _record_profile_id(record)
    normalized = {
        "evidence_id": str(record.get("evidence_id") or _evidence_id(profile_id, evidence_type, label, "persisted")).strip(),
        "evidence_type": evidence_type,
        "label": label,
        "filename": str(record.get("filename") or ""),
        "content_hash": str(record.get("content_hash") or ""),
        "source": str(record.get("source") or "user_uploaded"),
        "source_field": str(record.get("source_field") or ""),
        "profile_id": profile_id,
        "capability_tags": _unique([
            evidence_type,
            label,
            *[str(tag) for tag in record.get("capability_tags") or []],
        ]),
        "verified_status": str(record.get("verified_status") or "user_confirmed"),
        "issued_at": str(record.get("issued_at") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "created_at": str(record.get("created_at") or _utc_now()),
        "updated_at": str(record.get("updated_at") or record.get("created_at") or _utc_now()),
    }
    if isinstance(record.get("value"), dict):
        normalized["value"] = dict(record["value"])
    return normalized


def _inventory_terms(records: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for record in records:
        terms.append(str(record.get("label") or ""))
        terms.append(str(record.get("evidence_type") or ""))
        terms.extend(str(tag) for tag in record.get("capability_tags") or [])
    return _unique(terms)


def _dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        evidence_id = str(record.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        deduped.append(record)
    return deduped


def _evidence_type_for_label(label: str) -> str:
    lower = str(label or "").lower()
    if _has_any(lower, ("insurance", "cgl", "liability")):
        return "insurance_certificate"
    if _has_any(lower, ("bond", "surety")):
        return "bonding_capacity"
    if _has_any(lower, ("wsib", "safety", "traffic control", "cor")):
        return "safety_document"
    if _has_any(lower, ("license", "licence", "permit")):
        return "license"
    if _has_any(lower, ("certificate", "certification", "certified", "clearance")):
        return "certification"
    if _has_any(lower, ("reference", "past project", "municipal work")):
        return "reference_project"
    if _has_any(lower, ("pricing form", "price schedule", "pricing sheet")):
        return "pricing_form"
    if _has_any(lower, ("site visit", "site meeting", "mandatory meeting")):
        return "site_visit_confirmation"
    if _has_any(lower, ("addendum", "addenda")):
        return "addendum_acknowledgement"
    if _has_any(lower, ("form", "appendix", "schedule", "declaration")):
        return "submission_form"
    if _has_any(lower, ("equipment", "fleet")):
        return "equipment_list"
    return ""


def _tags_for_label(label: str, evidence_type: str) -> list[str]:
    lower = str(label or "").lower()
    tags = [evidence_type, lower]
    if "wsib" in lower:
        tags.extend(["wsib", "safety", "clearance"])
    if "traffic control" in lower or "book 7" in lower:
        tags.extend(["traffic control", "book 7", "safety"])
    if "insurance" in lower or "cgl" in lower:
        tags.extend(["insurance", "cgl", "liability", "certificate"])
    if "bond" in lower:
        tags.extend(["bond", "bonding", "surety"])
    if "reference" in lower or "municipal" in lower:
        tags.extend(["reference", "references", "similar experience", "past projects"])
    if "pricing" in lower or "price schedule" in lower:
        tags.extend(["pricing sheet", "pricing form", "price schedule", "unit price"])
    if "site visit" in lower or "site meeting" in lower:
        tags.extend(["site visit", "site meeting", "mandatory meeting attended"])
    if "addendum" in lower or "addenda" in lower:
        tags.extend(["addendum", "addenda", "addendum acknowledgement"])
    return tags


def _record_profile_id(record: dict[str, Any]) -> str:
    return str(record.get("profile_id") or "").strip()


def _profile_dict(profile: Any) -> dict[str, Any]:
    if isinstance(profile, dict):
        return dict(profile)
    if hasattr(profile, "to_dict"):
        return dict(profile.to_dict())
    return {
        key: getattr(profile, key)
        for key in dir(profile)
        if not key.startswith("_") and isinstance(getattr(profile, key), (str, int, float, list, tuple))
    }


def _list_value(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key) or []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if str(value).strip():
        return [str(value).strip()]
    return []


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _has_any(text: str, needles: Iterable[str]) -> bool:
    lower = str(text or "").lower()
    return any(needle in lower for needle in needles)


def _evidence_id(profile_id: str, evidence_type: str, label: str, source_field: str) -> str:
    payload = "|".join([profile_id, evidence_type, label.lower(), source_field])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"EVD-{digest.upper()}"


def _clean_filename(filename: str) -> str:
    text = str(filename or "").replace("\x00", "").strip()
    name = PurePosixPath(PureWindowsPath(text).name).name
    if not name:
        raise ValueError("Evidence upload requires a filename.")
    return name


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if not suffix or len(suffix) > 12:
        return ".bin"
    return suffix


def _write_upload_index(root: Path, record: dict[str, Any]) -> None:
    index_path = root / "evidence.json"
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    records = payload.setdefault("records", {})
    if not isinstance(records, dict):
        records = {}
        payload["records"] = records
    records[str(record.get("evidence_id") or "")] = dict(record)
    tmp_path = index_path.with_suffix(".json.tmp")
    root.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp_path.replace(index_path)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
