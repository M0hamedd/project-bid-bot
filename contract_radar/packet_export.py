from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


def build_packet_export(
    packet: dict[str, Any],
    *,
    analysis_id: str = "",
    packet_id: str = "",
    storage_dir: Path | str,
    created_at: str = "",
) -> dict[str, Any]:
    export_id = _export_id(packet, analysis_id=analysis_id, packet_id=packet_id, created_at=created_at)
    filename = f"{_slug(packet.get('opportunity_id') or 'packet')}-{export_id}.md"
    markdown = render_packet_markdown(packet, export_id=export_id, packet_id=packet_id, created_at=created_at)
    target_dir = Path(storage_dir) / "packet_exports"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return {
        "export_id": export_id,
        "packet_id": packet_id,
        "analysis_id": analysis_id,
        "opportunity_id": str(packet.get("opportunity_id") or ""),
        "filename": filename,
        "storage_path": str(path),
        "content_type": "text/markdown; charset=utf-8",
        "created_at": created_at,
        "download_url": f"/api/packets/export/{export_id}",
        "markdown": markdown,
    }


def render_packet_markdown(
    packet: dict[str, Any],
    *,
    export_id: str = "",
    packet_id: str = "",
    created_at: str = "",
) -> str:
    title = _text(packet.get("title") or packet.get("opportunity_id") or "Bid Packet")
    manifest = _rows(packet.get("submission_manifest"))
    manifest_summary = packet.get("submission_manifest_summary") if isinstance(packet.get("submission_manifest_summary"), dict) else {}
    pricing = packet.get("pricing_worksheet") if isinstance(packet.get("pricing_worksheet"), dict) else {}
    compliance_rows = _rows(packet.get("compliance_matrix"))
    evidence = _rows(packet.get("agent_evidence_ledger"))
    actions = _rows(packet.get("agent_action_trace"))
    contact = packet.get("buyer_contact") if isinstance(packet.get("buyer_contact"), dict) else {}

    lines = [
        f"# {title}",
        "",
        f"- Packet ID: `{_text(packet_id)}`",
        f"- Export ID: `{_text(export_id)}`",
        f"- Opportunity ID: `{_text(packet.get('opportunity_id'))}`",
        f"- Created At: `{_text(created_at)}`",
        f"- Owner Ready: `{str(bool(packet.get('owner_ready'))).lower()}`",
        "- Submission Status: `not_submitted_by_project_bid_bot`",
        "",
        "**Human submission required:** Project Bid Bot prepared this packet for review. It did not submit a bid, email the buyer, upload files, or certify compliance in any buyer portal.",
        "",
        "## Summary",
        "",
        _text(packet.get("summary") or "No summary was generated."),
        "",
        "## Submission Readiness",
        "",
        f"- Required Open Items: `{int(manifest_summary.get('required_open') or 0)}`",
        f"- Ready For Submission Review: `{str(bool(manifest_summary.get('ready_for_submission'))).lower()}`",
        "",
    ]
    lines.extend(_manifest_table(manifest))
    lines.extend(
        [
            "",
            "## Pricing",
            "",
            f"- Target Bid: `{_money(pricing.get('target_bid'))}`",
            f"- Low/High Range: `{_money(pricing.get('low_bid'))}` to `{_money(pricing.get('high_bid'))}`",
            f"- Confidence: `{_text(pricing.get('confidence') or 'Unknown')}`",
            f"- Worksheet Status: `{_text(pricing.get('status'))}`",
            f"- Estimator Approval: `{_text(pricing.get('estimator_approval_status'))}`",
        ]
    )
    approval = pricing.get("estimator_approval") if isinstance(pricing.get("estimator_approval"), dict) else {}
    if approval:
        lines.extend(
            [
                f"- Approved By: `{_text(approval.get('approved_by'))}`",
                f"- Approved At: `{_text(approval.get('approved_at'))}`",
                f"- Approval ID: `{_text(approval.get('approval_id'))}`",
            ]
        )
    lines.extend(["", "## Compliance Matrix", ""])
    lines.extend(_compliance_table(compliance_rows))
    lines.extend(["", "## Evidence Ledger", ""])
    lines.extend(_evidence_table(evidence))
    lines.extend(["", "## Agent Action Trace", ""])
    lines.extend(_action_table(actions))
    lines.extend(["", "## Submission Steps", ""])
    lines.extend([f"{index}. {_text(step)}" for index, step in enumerate(packet.get("submission_steps") or [], start=1)])
    lines.extend(["", "## Buyer Contact", ""])
    for label in ("name", "email", "phone", "division"):
        lines.append(f"- {label.title()}: `{_text(contact.get(label))}`")
    draft_email = _text(packet.get("draft_email"))
    if draft_email:
        lines.extend(["", "## Draft Buyer Email", "", "```text", draft_email, "```"])
    lines.extend(["", "## Final Warning", "", "Do not submit from this export alone. A human must verify the official solicitation package, addenda, portal forms, uploaded attachments, final price, and buyer portal confirmation before submission."])
    return "\n".join(lines).strip() + "\n"


def _manifest_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No submission manifest rows were attached."]
    lines = [
        "| Item | Status | Owner | Evidence IDs | Citation | Manifest ID |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        citation = _citation_label(row.get("citation") if isinstance(row.get("citation"), dict) else {})
        evidence_ids = ", ".join(_text(item) for item in row.get("evidence_ids") or [])
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("label") or row.get("item_type"),
                    row.get("status"),
                    row.get("owner"),
                    evidence_ids,
                    citation,
                    row.get("manifest_id"),
                )
            )
            + " |"
        )
    return lines


def _compliance_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No compliance rows were attached."]
    lines = [
        "| Requirement ID | Category | Resolved | Requirement | Citation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        citation = _citation_label(row.get("citation") if isinstance(row.get("citation"), dict) else {})
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("requirement_id"),
                    row.get("category"),
                    str(bool(row.get("resolved"))).lower(),
                    row.get("requirement"),
                    citation,
                )
            )
            + " |"
        )
    return lines


def _evidence_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No evidence facts were attached."]
    lines = [
        "| Fact ID | Type | Source | Requirement | Citation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        citation = _citation_label(row.get("citation") if isinstance(row.get("citation"), dict) else {})
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("fact_id"),
                    row.get("fact_type"),
                    row.get("source_type"),
                    row.get("requirement_id"),
                    citation,
                )
            )
            + " |"
        )
    return lines


def _action_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No typed actions were attached."]
    lines = [
        "| Action ID | Type | Outputs | Source Fact IDs |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("action_id"),
                    row.get("action_type"),
                    ", ".join(_text(item) for item in row.get("output_ids") or []),
                    ", ".join(_text(item) for item in row.get("source_fact_ids") or []),
                )
            )
            + " |"
        )
    return lines


def _citation_label(citation: dict[str, Any]) -> str:
    source = _text(citation.get("source") or citation.get("source_label"))
    page = citation.get("page")
    snippet = _text(citation.get("snippet"))
    parts = [source]
    if page:
        parts.append(f"p. {page}")
    if snippet:
        parts.append(snippet[:120])
    return " / ".join(part for part in parts if part)


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _money(value: Any) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.0f}" if amount > 0 else "$0"


def _cell(value: Any) -> str:
    return _text(value).replace("|", "\\|").replace("\n", " ") or "-"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", _text(value).lower()).strip("-")
    return text[:60] or "packet"


def _export_id(packet: dict[str, Any], *, analysis_id: str, packet_id: str, created_at: str) -> str:
    digest = hashlib.sha256(
        repr(
            (
                packet.get("opportunity_id"),
                analysis_id,
                packet_id,
                created_at,
                packet.get("summary"),
            )
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"packet-export-{digest}"
