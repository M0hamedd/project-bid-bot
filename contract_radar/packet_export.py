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
    assembly = packet.get("submission_assembly") if isinstance(packet.get("submission_assembly"), dict) else {}
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
    lines.extend(["", "## Submission Assembly", ""])
    lines.extend(_assembly_section(assembly))
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
    pricing_line_items = _rows(pricing.get("pricing_line_items"))
    line_item_rollup = pricing.get("line_item_rollup") if isinstance(pricing.get("line_item_rollup"), dict) else {}
    priced_line_items = _rows(line_item_rollup.get("priced_line_items"))
    if line_item_rollup:
        lines.extend(
            [
                f"- Line Item Rollup Target: `{_money(line_item_rollup.get('target_bid'))}`",
                f"- Line Item Direct Cost: `{_money(line_item_rollup.get('direct_cost'))}`",
                f"- Line Item Coverage: `{float(line_item_rollup.get('coverage') or 0):.0%}`",
                f"- Line Item Rate Source: `{_text(line_item_rollup.get('rate_card_source') or 'deterministic_profile_rate_card')}`",
                f"- Business Profile Rates Used: `{int(line_item_rollup.get('business_rate_count') or 0)}`",
            ]
        )
    if pricing_line_items:
        lines.extend(["", "### PDF Quantity Basis", ""])
        lines.extend(_pricing_line_item_table(priced_line_items or pricing_line_items))
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


def _assembly_section(assembly: dict[str, Any]) -> list[str]:
    if not assembly:
        return ["No deterministic submission assembly was attached."]
    summary = assembly.get("summary") if isinstance(assembly.get("summary"), dict) else {}
    lines = [
        f"- Assembly ID: `{_text(assembly.get('assembly_id'))}`",
        f"- Status: `{_text(assembly.get('status'))}`",
        f"- Ready For Human Submission: `{str(bool(assembly.get('ready_for_human_submission'))).lower()}`",
        f"- Human Submission Required: `{str(bool(assembly.get('human_submission_required'))).lower()}`",
        f"- Prefilled Fields: `{int(summary.get('prefilled_fields') or 0)}`",
        f"- Attachments: `{int(summary.get('attachments') or 0)}`",
        "",
        "### Prefilled Fields",
        "",
    ]
    lines.extend(_assembly_field_table(_rows(assembly.get("prefilled_fields"))))
    lines.extend(["", "### Attachments", ""])
    lines.extend(_assembly_attachment_table(_rows(assembly.get("attachments"))))
    lines.extend(["", "### Portal Steps", ""])
    steps = _rows(assembly.get("portal_steps"))
    if steps:
        lines.extend([f"{int(step.get('sequence') or index)}. {_text(step.get('instruction'))}" for index, step in enumerate(steps, start=1)])
    else:
        lines.append("No portal steps were attached.")
    final_checks = [str(item).strip() for item in assembly.get("final_checks") or [] if str(item).strip()]
    if final_checks:
        lines.extend(["", "### Final Checks", ""])
        lines.extend([f"- {_text(item)}" for item in final_checks])
    warning = _text(assembly.get("warning"))
    if warning:
        lines.extend(["", f"**Assembly warning:** {warning}"])
    return lines


def _assembly_field_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No prefilled fields were attached."]
    lines = [
        "| Field | Value | Status | Source |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("label") or row.get("field_id"),
                    row.get("value"),
                    row.get("status"),
                    row.get("source_type"),
                )
            )
            + " |"
        )
    return lines


def _assembly_attachment_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No attachment rows were attached."]
    lines = [
        "| Attachment | Status | Owner | Evidence IDs | Instruction |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("label") or row.get("item_type"),
                    row.get("status"),
                    row.get("owner"),
                    ", ".join(_text(item) for item in row.get("evidence_ids") or []),
                    row.get("upload_instruction"),
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


def _pricing_line_item_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Description | Quantity | Unit | Unit Direct Cost | Direct Cost | Citation | Line Item ID |",
        "| --- | ---: | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows[:20]:
        citation = _citation_label(row.get("citation") if isinstance(row.get("citation"), dict) else {})
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("description"),
                    _number(row.get("quantity")),
                    row.get("unit"),
                    _money(row.get("unit_direct_cost")) if row.get("unit_direct_cost") is not None else "",
                    _money(row.get("direct_cost")) if row.get("direct_cost") is not None else "",
                    citation,
                    row.get("line_item_id"),
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


def _number(value: Any) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:,.2f}".rstrip("0").rstrip(".") if amount else "0"


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
