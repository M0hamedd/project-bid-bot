from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PUBLIC_PDF_STATUSES = {"public_package_found", "fetched", "package_fetched", "package_uploaded"}
NOT_CHECKED_STATUS = "not_checked"
METADATA_ONLY_STATUS = "metadata_only"
CANDIDATE_URLS_FOUND_STATUS = "candidate_urls_found"
PORTAL_REQUIRED_STATUS = "portal_login_required"
MANUAL_DOWNLOAD_REQUIRED_STATUS = "manual_download_required"
FETCH_FAILED_STATUS = "fetch_failed"
PACKAGE_FETCHED_STATUS = "package_fetched"
PACKAGE_UPLOADED_STATUS = "package_uploaded"


class DocumentAcquisitionError(ValueError):
    pass


def build_metadata_only_session(
    *,
    opportunity: dict[str, Any],
    business_profile: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    opportunity_id = opportunity_identifier(opportunity)
    metadata = opportunity_metadata(opportunity)
    candidates = public_pdf_candidates(opportunity)
    status = acquisition_status_for_opportunity(opportunity, candidate_public_package_urls=candidates)
    acquisition = acquisition_report(
        opportunity=opportunity,
        status=status,
        now=now,
        candidate_public_package_urls=candidates,
    )
    analysis_id = metadata_analysis_id(opportunity_id, acquisition)
    return {
        "analysis_id": analysis_id,
        "opportunity_id": opportunity_id,
        "business_profile": dict(business_profile or {}),
        "opportunity_metadata": metadata,
        "acquisition": acquisition,
        "text": {
            "page_count": 0,
            "character_count": 0,
            "chunks": [],
        },
        "compliance_matrix": [],
        "compliance_summary": {
            "total": 0,
            "detected": 0,
            "resolved": 0,
            "unresolved": 0,
            "evidence_needed": 0,
            "business_has_capability": 0,
            "capability_gap": 0,
            "needs_review": 1,
            "hard_stops": 0,
            "review_gates": 1,
            "ready_to_prepare": False,
            "package_required": True,
            "source": "open_data_metadata",
        },
        "created_at": now,
    }


def acquisition_report(
    *,
    opportunity: dict[str, Any],
    status: str,
    now: str,
    candidate_public_package_urls: list[str] | None = None,
    fetched_url: str = "",
    error: str = "",
) -> dict[str, Any]:
    source_links = _source_links(opportunity)
    candidates = list(
        candidate_public_package_urls
        if candidate_public_package_urls is not None
        else public_pdf_candidates(opportunity)
    )
    package_required = status not in PUBLIC_PDF_STATUSES
    portal_url = str(
        source_links.get("toronto_bids_portal_url")
        or source_links.get("toronto_bids_search_url")
        or ""
    )
    search_hint = str(source_links.get("toronto_bids_search_hint") or "")
    guidance = acquisition_guidance(
        opportunity=opportunity,
        status=status,
        candidate_public_package_urls=candidates,
        fetched_url=fetched_url,
        error=error,
    )
    return {
        "status": status,
        "source_type": "user_upload" if status == PACKAGE_UPLOADED_STATUS else "open_data_metadata",
        "source_label": str(source_links.get("source_label") or "Open Data"),
        "open_data_record_url": str(source_links.get("open_data_record_url") or ""),
        "portal_url": portal_url,
        "search_hint": search_hint,
        "candidate_public_package_urls": candidates,
        "fetched_url": fetched_url,
        "package_required": package_required,
        "checked_at": now,
        "message": _acquisition_message(status, bool(candidates), fetched_url=fetched_url, error=error),
        "next_step": guidance["next_step"],
        "guidance": guidance,
        "error": error,
    }


def acquisition_status_for_opportunity(
    opportunity: dict[str, Any],
    *,
    candidate_public_package_urls: list[str] | None = None,
) -> str:
    candidates = list(candidate_public_package_urls if candidate_public_package_urls is not None else public_pdf_candidates(opportunity))
    if candidates:
        return CANDIDATE_URLS_FOUND_STATUS
    source_links = _source_links(opportunity)
    if source_links.get("toronto_bids_portal_url") or source_links.get("toronto_bids_search_url"):
        return PORTAL_REQUIRED_STATUS
    if source_links.get("toronto_bids_search_hint") or source_links.get("open_data_record_url"):
        return MANUAL_DOWNLOAD_REQUIRED_STATUS
    return METADATA_ONLY_STATUS


def acquisition_guidance(
    *,
    opportunity: dict[str, Any],
    status: str,
    candidate_public_package_urls: list[str] | None = None,
    fetched_url: str = "",
    error: str = "",
) -> dict[str, Any]:
    solicitation = _solicitation(opportunity)
    source_links = _source_links(opportunity)
    opportunity_id = opportunity_identifier(opportunity)
    portal_url = str(source_links.get("toronto_bids_portal_url") or source_links.get("toronto_bids_search_url") or "")
    search_hint = str(source_links.get("toronto_bids_search_hint") or f"Search {opportunity_id} in the buyer portal").strip()
    candidates = list(candidate_public_package_urls or [])
    expected_documents = expected_document_names(opportunity)
    instructions: list[str] = []
    reason = ""
    next_step = "Upload official package"

    if status == CANDIDATE_URLS_FOUND_STATUS:
        reason = "Open data exposed one or more direct PDF candidates."
        next_step = "Fetch direct PDF candidate"
        instructions = [
            "Use Start Intake to fetch the direct public PDF candidate automatically.",
            "If automatic fetch fails, upload the official package manually.",
        ]
    elif status == PACKAGE_FETCHED_STATUS or status == "fetched":
        reason = "The official package was fetched from a direct public PDF URL."
        next_step = "Analyze fetched package"
        instructions = ["Review the deterministic compliance results before preparing the owner packet."]
    elif status == PACKAGE_UPLOADED_STATUS:
        reason = "The official package was uploaded by the user."
        next_step = "Analyze uploaded package"
        instructions = ["Review the deterministic compliance results before preparing the owner packet."]
    elif status == FETCH_FAILED_STATUS:
        reason = "A direct PDF candidate was found, but automatic fetch failed."
        next_step = "Upload official package"
        instructions = [
            "Open the candidate URL or buyer portal manually.",
            "Download the official solicitation package.",
            "Upload the PDF here for deterministic compliance analysis.",
        ]
    elif status == PORTAL_REQUIRED_STATUS:
        reason = "The buyer keeps package documents in a portal that cannot be fetched without user access."
        next_step = "Open buyer portal and upload package"
        instructions = [
            "Open the buyer portal.",
            search_hint,
            "Download the official solicitation package, addenda, forms, and pricing sheets.",
            "Upload the official PDF package here.",
        ]
    elif status == MANUAL_DOWNLOAD_REQUIRED_STATUS:
        reason = "Open data provides listing metadata but no direct public package URL."
        next_step = "Manually download and upload package"
        instructions = [
            search_hint,
            "Download the official solicitation package from the buyer source.",
            "Upload the PDF here for deterministic compliance analysis.",
        ]
    else:
        reason = "Only listing metadata is available in the current open-data record."
        instructions = [
            "Locate the official solicitation package from the buyer source.",
            "Upload the PDF here for deterministic compliance analysis.",
        ]

    return {
        "reason": reason,
        "next_step": next_step,
        "portal_url": portal_url,
        "search_hint": search_hint,
        "candidate_public_package_urls": candidates,
        "expected_documents": expected_documents,
        "instructions": _unique([item for item in instructions if item]),
        "error": str(error or ""),
        "opportunity_id": opportunity_id,
        "title": str(solicitation.get("description") or opportunity.get("title") or opportunity_id),
    }


def opportunity_identifier(opportunity: dict[str, Any]) -> str:
    solicitation = _solicitation(opportunity)
    return str(
        solicitation.get("document_number")
        or opportunity.get("opportunity_id")
        or opportunity.get("id")
        or ""
    ).strip()


def opportunity_metadata(opportunity: dict[str, Any]) -> dict[str, Any]:
    solicitation = _solicitation(opportunity)
    source_links = _source_links(opportunity)
    return {
        "document_number": str(solicitation.get("document_number") or opportunity_identifier(opportunity)),
        "title": str(solicitation.get("description") or opportunity.get("title") or ""),
        "description": str(solicitation.get("description") or ""),
        "solicitation_type": str(solicitation.get("solicitation_type") or ""),
        "category": str(solicitation.get("category") or ""),
        "division": str(solicitation.get("division") or ""),
        "issue_date": str(solicitation.get("issue_date") or ""),
        "submission_deadline": str(solicitation.get("submission_deadline") or ""),
        "buyer_name": str(solicitation.get("buyer_name") or ""),
        "buyer_email": str(solicitation.get("buyer_email") or ""),
        "buyer_phone": str(solicitation.get("buyer_phone") or ""),
        "wards": str(solicitation.get("wards") or ""),
        "source_label": str(source_links.get("source_label") or "Open Data"),
    }


def public_pdf_candidates(opportunity: dict[str, Any]) -> list[str]:
    urls = []
    for key, value in _walk_strings(opportunity):
        lower_key = key.lower()
        if not any(token in lower_key for token in ("url", "link", "pdf", "document", "package", "attachment")):
            continue
        text = value.strip()
        if _is_public_pdf_url(text):
            urls.append(text)
    return _unique(urls)


def expected_document_names(opportunity: dict[str, Any]) -> list[str]:
    solicitation = _solicitation(opportunity)
    title = str(solicitation.get("description") or opportunity.get("title") or "solicitation package").strip()
    document_number = opportunity_identifier(opportunity)
    names = [
        f"{document_number} solicitation package" if document_number else "solicitation package",
        "addenda",
        "required forms",
        "pricing form",
    ]
    lower_title = title.lower()
    if any(token in lower_title for token in ("construction", "road", "sidewalk", "paving", "watermain", "sewer", "park")):
        names.extend(["drawings", "specifications"])
    return _unique([name for name in names if name])


def fetch_public_pdf(url: str, *, timeout: int = 20, max_bytes: int = 25_000_000) -> bytes:
    if not _is_public_pdf_url(url):
        raise DocumentAcquisitionError("Only direct public PDF URLs can be fetched automatically.")
    request = Request(url, headers={"User-Agent": "ProjectBidBot/0.1"})
    with urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise DocumentAcquisitionError("Public PDF is larger than the local acquisition limit.")
    if not content.startswith(b"%PDF-") and "pdf" not in content_type:
        raise DocumentAcquisitionError("Public document URL did not return a PDF.")
    return content


def metadata_analysis_id(opportunity_id: str, acquisition: dict[str, Any]) -> str:
    seed = f"{opportunity_id}:{acquisition.get('status')}:{acquisition.get('checked_at')}:{time.time_ns()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"analysis-{digest}"


def _acquisition_message(status: str, has_candidates: bool, *, fetched_url: str = "", error: str = "") -> str:
    if status in {"fetched", PACKAGE_FETCHED_STATUS}:
        return f"Official package was fetched from a direct public PDF URL: {fetched_url}"
    if status == PACKAGE_UPLOADED_STATUS:
        return "Official package was uploaded and is ready for deterministic compliance analysis."
    if status == CANDIDATE_URLS_FOUND_STATUS:
        return "A direct public PDF candidate was found. Start intake can try fetching it automatically."
    if status == "public_package_found":
        return "A direct public PDF candidate was found and is ready for deterministic PDF analysis."
    if status == FETCH_FAILED_STATUS:
        detail = f" ({error})" if error else ""
        return f"A public PDF candidate was found, but automatic fetch failed{detail}. Upload the official package."
    if status == PORTAL_REQUIRED_STATUS:
        return "The listing points to a buyer portal. Open the portal or upload the official package before compliance clearance."
    if status == MANUAL_DOWNLOAD_REQUIRED_STATUS:
        return "No direct public PDF was found. Manually download the official package from the buyer source and upload it."
    if has_candidates:
        return "Open data exposed a direct PDF candidate. Fetch it or upload the official package before compliance clearance."
    return "Open data contains listing metadata, but not the official solicitation package. Upload or fetch the package before compliance clearance."


def _is_public_pdf_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = parsed.path.lower()
    return path.endswith(".pdf") or "pdf" in path


def _solicitation(opportunity: dict[str, Any]) -> dict[str, Any]:
    value = opportunity.get("solicitation") if isinstance(opportunity, dict) else {}
    return value if isinstance(value, dict) else {}


def _source_links(opportunity: dict[str, Any]) -> dict[str, Any]:
    solicitation = _solicitation(opportunity)
    value = solicitation.get("source_links") if isinstance(solicitation, dict) else {}
    return value if isinstance(value, dict) else {}


def _walk_strings(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_walk_strings(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_strings(child, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        found.append((prefix, value))
    return found


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
