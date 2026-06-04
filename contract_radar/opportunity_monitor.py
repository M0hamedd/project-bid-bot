from __future__ import annotations

import copy
import hashlib
from typing import Any

from contract_radar.acquisition import acquisition_status_for_opportunity, public_pdf_candidates


EVENT_NEW_OPPORTUNITY = "new_opportunity"
EVENT_DEADLINE_CHANGED = "deadline_changed"
EVENT_STATUS_CHANGED = "status_changed"
EVENT_PACKAGE_AVAILABLE = "package_available"
EVENT_ADDENDUM_DETECTED = "addendum_detected"
EVENT_OPPORTUNITY_CLOSED = "opportunity_closed"

PACKAGE_AVAILABLE_STATUSES = {"candidate_urls_found", "package_fetched", "package_uploaded"}


def build_opportunity_snapshots(
    scan_result: dict[str, Any],
    analyses_by_opportunity: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    analyses = analyses_by_opportunity or {}
    snapshots: dict[str, dict[str, Any]] = {}
    for opportunity in _scan_opportunities(scan_result):
        opportunity_id = _opportunity_id(opportunity)
        if not opportunity_id:
            continue
        analysis = analyses.get(opportunity_id) if isinstance(analyses, dict) else {}
        snapshot = _snapshot_for_opportunity(opportunity, analysis if isinstance(analysis, dict) else {})
        snapshots[opportunity_id] = snapshot
    return snapshots


def detect_opportunity_changes(
    current_snapshots: dict[str, dict[str, Any]],
    previous_snapshots: dict[str, dict[str, Any]] | None = None,
    *,
    now: str = "",
) -> list[dict[str, Any]]:
    previous = _dict_of_dicts(previous_snapshots)
    current = _dict_of_dicts(current_snapshots)
    events: list[dict[str, Any]] = []

    for opportunity_id, snapshot in current.items():
        prior = previous.get(opportunity_id)
        if not prior:
            events.append(_event(EVENT_NEW_OPPORTUNITY, snapshot, now=now, reason="Opportunity appeared in today's scan."))
            if _has_package(snapshot):
                events.append(
                    _event(
                        EVENT_PACKAGE_AVAILABLE,
                        snapshot,
                        now=now,
                        reason="Direct package candidate is available on first sighting.",
                        old_value="",
                        new_value=", ".join(snapshot.get("candidate_public_package_urls") or []),
                    )
                )
            if snapshot.get("addenda_markers"):
                events.append(
                    _event(
                        EVENT_ADDENDUM_DETECTED,
                        snapshot,
                        now=now,
                        reason="Addendum marker is visible in the opportunity metadata.",
                        old_value="",
                        new_value=", ".join(snapshot.get("addenda_markers") or []),
                    )
                )
            continue

        if str(prior.get("submission_deadline") or "") != str(snapshot.get("submission_deadline") or ""):
            events.append(
                _event(
                    EVENT_DEADLINE_CHANGED,
                    snapshot,
                    now=now,
                    reason="Submission deadline changed in source data.",
                    old_value=str(prior.get("submission_deadline") or ""),
                    new_value=str(snapshot.get("submission_deadline") or ""),
                )
            )
        if str(prior.get("status_label") or "") != str(snapshot.get("status_label") or ""):
            events.append(
                _event(
                    EVENT_STATUS_CHANGED,
                    snapshot,
                    now=now,
                    reason="Opportunity status changed in source data.",
                    old_value=str(prior.get("status_label") or ""),
                    new_value=str(snapshot.get("status_label") or ""),
                )
            )
        if not _has_package(prior) and _has_package(snapshot):
            events.append(
                _event(
                    EVENT_PACKAGE_AVAILABLE,
                    snapshot,
                    now=now,
                    reason="Official package candidate became available.",
                    old_value=str(prior.get("acquisition_status") or ""),
                    new_value=str(snapshot.get("acquisition_status") or ""),
                )
            )
        prior_markers = set(str(item) for item in prior.get("addenda_markers") or [])
        current_markers = set(str(item) for item in snapshot.get("addenda_markers") or [])
        added_markers = sorted(current_markers - prior_markers)
        if added_markers:
            events.append(
                _event(
                    EVENT_ADDENDUM_DETECTED,
                    snapshot,
                    now=now,
                    reason="New addendum marker appeared in source data.",
                    old_value=", ".join(sorted(prior_markers)),
                    new_value=", ".join(added_markers),
                )
            )

    for opportunity_id, prior in previous.items():
        if opportunity_id in current:
            continue
        events.append(
            _event(
                EVENT_OPPORTUNITY_CLOSED,
                prior,
                now=now,
                reason="Opportunity disappeared from the current scan result.",
                old_value=str(prior.get("status_label") or ""),
                new_value="not_in_current_scan",
            )
        )

    return events


def monitor_scan_changes(
    scan_result: dict[str, Any],
    analyses_by_opportunity: dict[str, dict[str, Any]] | None = None,
    *,
    previous_snapshots: dict[str, dict[str, Any]] | None = None,
    now: str = "",
) -> dict[str, Any]:
    current = build_opportunity_snapshots(scan_result, analyses_by_opportunity)
    events = detect_opportunity_changes(current, previous_snapshots, now=now)
    return {
        "opportunity_snapshots": current,
        "opportunity_change_events": events,
        "monitor_summary": summarize_change_events(events),
    }


def summarize_change_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total": len(events),
        EVENT_NEW_OPPORTUNITY: 0,
        EVENT_DEADLINE_CHANGED: 0,
        EVENT_STATUS_CHANGED: 0,
        EVENT_PACKAGE_AVAILABLE: 0,
        EVENT_ADDENDUM_DETECTED: 0,
        EVENT_OPPORTUNITY_CLOSED: 0,
    }
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type in summary:
            summary[event_type] += 1
    return summary


def _snapshot_for_opportunity(opportunity: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    solicitation = opportunity.get("solicitation") if isinstance(opportunity.get("solicitation"), dict) else {}
    source_links = solicitation.get("source_links") if isinstance(solicitation.get("source_links"), dict) else {}
    candidates = public_pdf_candidates(opportunity)
    acquisition = analysis.get("acquisition") if isinstance(analysis.get("acquisition"), dict) else {}
    acquisition_status = str(acquisition.get("status") or acquisition_status_for_opportunity(opportunity, candidate_public_package_urls=candidates))
    markers = _addenda_markers(opportunity)
    snapshot = {
        "opportunity_id": _opportunity_id(opportunity),
        "title": str(solicitation.get("description") or opportunity.get("title") or ""),
        "division": str(solicitation.get("division") or ""),
        "buyer_name": str(solicitation.get("buyer_name") or ""),
        "submission_deadline": str(solicitation.get("submission_deadline") or ""),
        "status_label": str(opportunity.get("label") or solicitation.get("status") or ""),
        "acquisition_status": acquisition_status,
        "candidate_public_package_urls": candidates,
        "addenda_markers": markers,
        "open_data_record_url": str(source_links.get("open_data_record_url") or ""),
        "portal_url": str(source_links.get("toronto_bids_portal_url") or source_links.get("toronto_bids_search_url") or ""),
        "analysis_id": str(analysis.get("analysis_id") or ""),
        "bid_state": str(analysis.get("bid_state") or ""),
    }
    snapshot["fingerprint"] = _fingerprint(snapshot)
    return snapshot


def _event(
    event_type: str,
    snapshot: dict[str, Any],
    *,
    now: str,
    reason: str,
    old_value: str = "",
    new_value: str = "",
) -> dict[str, Any]:
    opportunity_id = str(snapshot.get("opportunity_id") or "")
    return {
        "event_id": _id("change", opportunity_id, event_type, old_value, new_value),
        "event_type": event_type,
        "opportunity_id": opportunity_id,
        "title": str(snapshot.get("title") or ""),
        "reason": reason,
        "old_value": old_value,
        "new_value": new_value,
        "detected_at": now,
        "source": "opportunity_snapshot_monitor",
        "snapshot_fingerprint": str(snapshot.get("fingerprint") or ""),
    }


def _has_package(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("candidate_public_package_urls"):
        return True
    return str(snapshot.get("acquisition_status") or "") in PACKAGE_AVAILABLE_STATUSES


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


def _addenda_markers(opportunity: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    for key, value in _walk_strings(opportunity):
        text = value.strip()
        lower = text.lower()
        if "addendum" not in lower and "addenda" not in lower:
            continue
        if "expected_documents" in key or "instructions" in key:
            continue
        markers.append(_marker_text(key, text))
    return _unique(markers)[:8]


def _marker_text(key: str, text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > 140:
        cleaned = f"{cleaned[:137]}..."
    return f"{key}: {cleaned}" if key else cleaned


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


def _dict_of_dicts(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): copy.deepcopy(item)
        for key, item in value.items()
        if str(key).strip() and isinstance(item, dict)
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    fields = {
        "title": str(snapshot.get("title") or ""),
        "division": str(snapshot.get("division") or ""),
        "buyer_name": str(snapshot.get("buyer_name") or ""),
        "submission_deadline": str(snapshot.get("submission_deadline") or ""),
        "status_label": str(snapshot.get("status_label") or ""),
        "acquisition_status": str(snapshot.get("acquisition_status") or ""),
        "candidate_public_package_urls": list(snapshot.get("candidate_public_package_urls") or []),
        "addenda_markers": list(snapshot.get("addenda_markers") or []),
    }
    return _id("snapshot", fields)


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
