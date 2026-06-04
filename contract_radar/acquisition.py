from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import time
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse
from urllib.error import HTTPError, URLError
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
    candidate_discovery: dict[str, Any] | None = None,
    fetched_url: str = "",
    error: str = "",
) -> dict[str, Any]:
    source_links = _source_links(opportunity)
    candidates = list(
        candidate_public_package_urls
        if candidate_public_package_urls is not None
        else public_pdf_candidates(opportunity)
    )
    package_documents = _package_documents_for_report(candidate_discovery, opportunity, candidates, fetched_url=fetched_url)
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
        "candidate_discovery": candidate_discovery or {},
        "package_documents": package_documents,
        "package_document_summary": summarize_package_documents(package_documents),
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
        field_label = key.rsplit(".", 1)[-1]
        if _is_source_page_field(field_label) and not _is_public_pdf_url(text):
            continue
        if _is_public_package_document_url(text, label=field_label):
            urls.append(text)
    return _unique(urls)


def discover_public_package_candidates(
    opportunity: dict[str, Any],
    *,
    fetcher: Callable[[str], str] | None = None,
    max_pages: int = 4,
) -> dict[str, Any]:
    """Discover public PDF package candidates from source pages without logging into portals."""
    direct = public_pdf_candidates(opportunity)
    source_pages = public_source_page_urls(opportunity)
    attempts: list[dict[str, Any]] = []
    discovered: list[dict[str, str]] = []
    fetch_html = fetcher or fetch_public_html

    for source_url in source_pages[: max(0, int(max_pages or 0))]:
        try:
            html = fetch_html(source_url)
        except ValueError as exc:
            attempts.append(
                {
                    "source_url": source_url,
                    "status": "fetch_failed",
                    "candidate_count": 0,
                    "error": str(exc),
                }
            )
            continue
        links = public_pdf_links_from_html(html, base_url=source_url)
        ranked = rank_public_pdf_links(links, opportunity)
        discovered.extend(ranked)
        attempts.append(
            {
                "source_url": source_url,
                "status": "fetched",
                "candidate_count": len(ranked),
                "error": "",
            }
        )

    package_documents = build_package_document_inventory(
        opportunity,
        direct_candidate_urls=direct,
        discovered_links=discovered,
    )
    fetchable_urls = [
        str(item.get("url") or "")
        for item in package_documents
        if item.get("include_for_analysis")
    ]
    discovered_urls = _unique([item["url"] for item in discovered])
    return {
        "method": "public_html_pdf_link_discovery",
        "source_page_urls": source_pages,
        "direct_candidate_urls": direct,
        "discovered_candidate_urls": discovered_urls,
        "candidate_public_package_urls": _unique(fetchable_urls),
        "excluded_public_pdf_urls": [
            str(item.get("url") or "")
            for item in package_documents
            if not item.get("include_for_analysis")
        ],
        "ranked_discovered_links": discovered,
        "package_documents": package_documents,
        "package_document_summary": summarize_package_documents(package_documents),
        "attempts": attempts,
    }


def build_package_document_inventory(
    opportunity: dict[str, Any],
    *,
    direct_candidate_urls: list[str] | None = None,
    discovered_links: list[dict[str, str]] | None = None,
    fetched_url: str = "",
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for url in direct_candidate_urls or []:
        links.append({"url": str(url or ""), "label": "", "source_type": "direct_candidate", "score": ""})
    for link in discovered_links or []:
        links.append(
            {
                "url": str(link.get("url") or ""),
                "label": str(link.get("label") or ""),
                "source_type": "public_page_discovery",
                "score": str(link.get("score") or ""),
            }
        )

    seen: set[str] = set()
    documents: list[dict[str, Any]] = []
    for index, link in enumerate(links):
        url = str(link.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        label = str(link.get("label") or _filename_from_url(url)).strip()
        document_type = classify_package_document(url=url, label=label, opportunity=opportunity)
        include = document_type not in {"award_summary", "bid_results", "notice", "unknown_excluded"}
        document = {
            "package_document_id": _id("package-doc", opportunity_identifier(opportunity), url),
            "url": url,
            "filename": _filename_from_url(url, label=label),
            "label": label,
            "document_type": document_type,
            "role": "supporting",
            "status": "fetched" if fetched_url and url == fetched_url else "available" if include else "excluded",
            "source_type": str(link.get("source_type") or "public_candidate"),
            "include_for_analysis": include,
            "include_for_submission": include,
            "reason": _package_document_reason(document_type, include),
            "score": str(link.get("score") or ""),
            "discovery_order": index,
        }
        documents.append(document)

    documents.sort(key=_package_document_sort_key)
    primary_assigned = False
    for document in documents:
        if not document.get("include_for_analysis"):
            continue
        if not primary_assigned:
            document["role"] = "primary"
            primary_assigned = True
        elif str(document.get("document_type") or "") in {"addendum", "pricing_form", "drawings", "specifications", "required_form"}:
            document["role"] = "supporting_required"
    return documents


def classify_package_document(*, url: str, label: str = "", opportunity: dict[str, Any] | None = None) -> str:
    text = _normalize_words(f"{url} {label}")
    if any(token in text for token in ("award", "awarded", "bid result", "results summary", "vendor summary")):
        return "award_summary"
    if any(token in text for token in ("notice of intent", "intent to award")):
        return "notice"
    if any(token in text for token in ("addendum", "addenda")):
        return "addendum"
    if any(token in text for token in ("pricing", "price form", "price schedule", "schedule of prices", "bid form")):
        return "pricing_form"
    if any(token in text for token in ("drawing", "drawings", "plan set", "plans")):
        return "drawings"
    if any(token in text for token in ("specification", "specifications", "specs")):
        return "specifications"
    if any(token in text for token in ("form", "forms", "declaration", "certificate")):
        return "required_form"
    opportunity_id = _normalize_score_text(opportunity_identifier(opportunity or {}))
    if opportunity_id and opportunity_id in _normalize_score_text(f"{url} {label}"):
        return "solicitation_package"
    if any(token in text for token in ("solicitation", "tender", "rfq", "rft", "request for quotation", "package")):
        return "solicitation_package"
    return "other_public_pdf"


def summarize_package_documents(documents: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [dict(item) for item in documents or [] if isinstance(item, dict)]
    fetchable = [item for item in rows if item.get("include_for_analysis")]
    primary = next((item for item in fetchable if str(item.get("role") or "") == "primary"), {})
    return {
        "total_public_pdfs": len(rows),
        "fetchable_public_pdfs": len(fetchable),
        "excluded_public_pdfs": len(rows) - len(fetchable),
        "supporting_required_documents": sum(1 for item in rows if str(item.get("role") or "") == "supporting_required"),
        "has_addenda": any(str(item.get("document_type") or "") == "addendum" for item in fetchable),
        "has_pricing_form": any(str(item.get("document_type") or "") == "pricing_form" for item in fetchable),
        "has_drawings_or_specs": any(str(item.get("document_type") or "") in {"drawings", "specifications"} for item in fetchable),
        "primary_document_url": str(primary.get("url") or ""),
        "primary_document_type": str(primary.get("document_type") or ""),
    }


def public_source_page_urls(opportunity: dict[str, Any]) -> list[str]:
    source_links = _source_links(opportunity)
    preferred_keys = (
        "open_data_record_url",
        "toronto_bids_portal_url",
        "toronto_bids_search_url",
        "portal_url",
        "source_url",
        "record_url",
    )
    urls: list[str] = []
    for key in preferred_keys:
        value = source_links.get(key)
        if isinstance(value, str) and _is_public_source_page_url(value):
            urls.append(value.strip())
    for key, value in _walk_strings(opportunity):
        lower_key = key.lower()
        if not any(token in lower_key for token in ("url", "link", "portal", "record", "source", "page")):
            continue
        text = value.strip()
        if _is_public_source_page_url(text):
            urls.append(text)
    return _unique(urls)


def public_pdf_links_from_html(html: str, *, base_url: str) -> list[dict[str, str]]:
    parser = _PdfLinkParser(base_url)
    parser.feed(html or "")
    parser.close()
    return parser.links()


def rank_public_pdf_links(links: list[dict[str, str]], opportunity: dict[str, Any]) -> list[dict[str, str]]:
    scored: list[tuple[int, int, dict[str, str]]] = []
    opportunity_id = _normalize_score_text(opportunity_identifier(opportunity))
    for index, link in enumerate(links):
        url = str(link.get("url") or "")
        label = str(link.get("label") or "")
        haystack = _normalize_score_text(f"{url} {label}")
        score = 0
        if opportunity_id and opportunity_id in haystack:
            score += 40
        for token in ("solicitation", "tender", "rfq", "rft", "request", "package", "specification", "specifications"):
            if token in haystack:
                score += 12
        for token in ("pricing", "price", "form", "schedule", "drawings", "drawing"):
            if token in haystack:
                score += 8
        if "addendum" in haystack or "addenda" in haystack:
            score += 6
        for token in ("award", "awarded", "vendor", "minutes", "summary", "notice of intent"):
            if token in haystack:
                score -= 20
        scored.append((score, -index, {"url": url, "label": label, "score": str(score)}))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored]


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
    if not _is_public_http_url(url):
        raise DocumentAcquisitionError("Only public HTTP document URLs can be fetched automatically.")
    request = Request(url, headers={"User-Agent": "ProjectBidBot/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            content = response.read(max_bytes + 1)
    except (HTTPError, URLError, OSError) as exc:
        raise DocumentAcquisitionError(f"Could not fetch public PDF: {exc}") from exc
    if len(content) > max_bytes:
        raise DocumentAcquisitionError("Public PDF is larger than the local acquisition limit.")
    if not content.startswith(b"%PDF-") and "pdf" not in content_type:
        raise DocumentAcquisitionError("Public document URL did not return a PDF.")
    return content


def fetch_public_html(url: str, *, timeout: int = 15, max_bytes: int = 2_000_000) -> str:
    if not _is_public_source_page_url(url):
        raise DocumentAcquisitionError("Only public HTTP source pages can be checked automatically.")
    request = Request(url, headers={"User-Agent": "ProjectBidBot/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            content = response.read(max_bytes + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, OSError) as exc:
        raise DocumentAcquisitionError(f"Could not fetch public source page: {exc}") from exc
    if len(content) > max_bytes:
        raise DocumentAcquisitionError("Public source page is larger than the local discovery limit.")
    if content.startswith(b"%PDF-") or "pdf" in content_type:
        raise DocumentAcquisitionError("Source page URL returned a PDF instead of an HTML page.")
    if content_type and not any(token in content_type for token in ("html", "text", "xml")):
        raise DocumentAcquisitionError("Source page did not return HTML or text content.")
    return content.decode(charset, errors="replace")


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


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_public_package_document_url(value: str, *, label: str = "") -> bool:
    if _is_public_pdf_url(value):
        return True
    if not _is_public_http_url(value):
        return False
    url_words = _normalize_words(value)
    label_words = _normalize_words(label)
    url_intent_tokens = (
        "download",
        "document",
        "documents",
        "attachment",
        "attachments",
        "file",
        "package",
        "solicitation",
        "addendum",
        "addenda",
        "pricing",
        "price schedule",
        "bid form",
        "specification",
        "specifications",
        "drawing",
        "drawings",
    )
    return (
        any(token in url_words for token in url_intent_tokens)
        or any(token in label_words for token in url_intent_tokens)
    )


def _is_source_page_field(label: str) -> bool:
    words = _normalize_words(label)
    return any(
        token in words
        for token in (
            "open data record",
            "record url",
            "portal url",
            "search url",
            "source url",
        )
    )


def _is_public_source_page_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return not _is_public_package_document_url(value)


def _normalize_score_text(value: str) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def _normalize_words(value: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in str(value or "")).split())


def _filename_from_url(url: str, *, label: str = "") -> str:
    name = unquote(urlparse(str(url or "")).path.rsplit("/", 1)[-1] or "").strip()
    if name and name.lower().endswith(".pdf"):
        return name
    fallback = _safe_pdf_filename(label) if label else ""
    return fallback or "public-package-document.pdf"


def _safe_pdf_filename(label: str) -> str:
    words = []
    for token in _normalize_words(label).split():
        if token in {"pdf", "download", "document", "documents", "click", "here"}:
            continue
        words.append(token)
    stem = "-".join(words[:12]).strip("-")
    return f"{stem}.pdf" if stem else ""


def _package_document_reason(document_type: str, include: bool) -> str:
    if not include:
        return "Public PDF appears to be an award, result, notice, or other non-package artifact."
    return {
        "solicitation_package": "Likely official solicitation package.",
        "addendum": "Public addendum document should be reviewed before submission.",
        "pricing_form": "Public pricing form may need estimator-approved values.",
        "drawings": "Public drawings should be included in estimator review.",
        "specifications": "Public specifications should be included in compliance review.",
        "required_form": "Public form may need to be completed for submission.",
    }.get(document_type, "Public PDF candidate may be part of the bid package.")


def _package_document_sort_key(document: dict[str, Any]) -> tuple[int, int, int]:
    priority = {
        "solicitation_package": 0,
        "specifications": 1,
        "addendum": 2,
        "pricing_form": 3,
        "required_form": 4,
        "drawings": 5,
        "other_public_pdf": 6,
        "award_summary": 98,
        "bid_results": 98,
        "notice": 99,
        "unknown_excluded": 99,
    }.get(str(document.get("document_type") or ""), 50)
    try:
        score = int(str(document.get("score") or "0"))
    except ValueError:
        score = 0
    return (priority, -score, int(document.get("discovery_order") or 0))


def _package_documents_for_report(
    candidate_discovery: dict[str, Any] | None,
    opportunity: dict[str, Any],
    candidates: list[str],
    *,
    fetched_url: str,
) -> list[dict[str, Any]]:
    discovery = candidate_discovery if isinstance(candidate_discovery, dict) else {}
    documents = [
        dict(item)
        for item in discovery.get("package_documents") or []
        if isinstance(item, dict)
    ]
    if not documents:
        documents = build_package_document_inventory(
            opportunity,
            direct_candidate_urls=candidates,
            fetched_url=fetched_url,
        )
    for document in documents:
        url = str(document.get("url") or "")
        if fetched_url and url == fetched_url:
            document["status"] = "fetched"
        elif document.get("include_for_analysis"):
            document["status"] = str(document.get("status") or "available")
    return documents


class _PdfLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._links: list[dict[str, str]] = []
        self._current_href = ""
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): str(value or "") for key, value in attrs}
        href = values.get("href") or values.get("src") or ""
        if tag.lower() == "a":
            self._current_href = href
            self._current_text = []
            return
        self._add_link(href, values.get("title") or values.get("alt") or tag)

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        self._add_link(self._current_href, " ".join(self._current_text))
        self._current_href = ""
        self._current_text = []

    def links(self) -> list[dict[str, str]]:
        return _unique_links(self._links)

    def _add_link(self, href: str, label: str) -> None:
        if not href:
            return
        url = urljoin(self._base_url, href.strip())
        if not _is_public_package_document_url(url, label=label):
            return
        self._links.append({"url": url, "label": " ".join(str(label or "").split())})


def _unique_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for link in links:
        url = str(link.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(link)
    return output


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


def _id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
