from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_radar.agent_runtime import decorate_agent_session
from contract_radar.compliance import extract_requirements, requirements_to_dicts
from contract_radar.profiles import profile_from_payload


DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "bid_flow"


def evaluate_fixture_directory(fixture_dir: Path | str = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    started = time.perf_counter()
    paths = sorted(Path(fixture_dir).glob("*.json"))
    fixtures = [evaluate_fixture_path(path) for path in paths]
    expected_total = sum(len(item["expected_categories"]) for item in fixtures)
    matched_total = sum(len(item["matched_expected_categories"]) for item in fixtures)
    row_total = sum(item["requirement_count"] for item in fixtures)
    cited_total = sum(item["cited_requirement_count"] for item in fixtures)
    false_packet_ready = [item for item in fixtures if item["false_packet_ready"]]
    hard_stop_misses = sum(len(item["missing_hard_stop_categories"]) for item in fixtures)
    review_misses = sum(len(item["missing_review_categories"]) for item in fixtures)
    uncited_pdf_facts = sum(item["uncited_pdf_fact_count"] for item in fixtures)
    pricing_sanity_failures = sum(len(item["pricing_sanity_failures"]) for item in fixtures)
    failures = [
        failure
        for item in fixtures
        for failure in item["failures"]
    ]
    summary = {
        "fixture_count": len(fixtures),
        "expected_requirement_categories": expected_total,
        "matched_requirement_categories": matched_total,
        "category_recall": round(matched_total / expected_total, 4) if expected_total else 1.0,
        "citation_coverage": round(cited_total / row_total, 4) if row_total else 1.0,
        "false_packet_ready_count": len(false_packet_ready),
        "false_hard_stop_clearance_count": hard_stop_misses,
        "review_gate_miss_count": review_misses,
        "uncited_pdf_fact_count": uncited_pdf_facts,
        "pricing_sanity_failure_count": pricing_sanity_failures,
        "runtime_ms": int((time.perf_counter() - started) * 1000),
        "passed": bool(fixtures) and not failures,
    }
    return {
        "summary": summary,
        "fixtures": fixtures,
        "failures": failures,
    }


def evaluate_fixture_path(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    fixture = json.loads(path.read_text(encoding="utf-8"))
    fixture_id = str(fixture.get("fixture_id") or path.stem)
    expected = fixture.get("expected") if isinstance(fixture.get("expected"), dict) else {}
    profile_payload = fixture.get("business_profile") if isinstance(fixture.get("business_profile"), dict) else fixture
    profile = profile_from_payload(profile_payload)
    chunks = [dict(item) for item in fixture.get("chunks") or [] if isinstance(item, dict)]
    rows = requirements_to_dicts(
        extract_requirements(
            chunks,
            contractor_profile=profile,
            document_inventory=fixture.get("document_inventory") or [],
        )
    )
    session = decorate_agent_session(
        {
            "analysis_id": f"fixture-{fixture_id}",
            "opportunity_id": str(fixture.get("opportunity_id") or fixture_id),
            "business_profile": profile.to_dict(),
            "document": {
                "filename": str(fixture.get("filename") or f"{fixture_id}.pdf"),
                "content_hash": fixture_id,
            },
            "text": {
                "page_count": _page_count(chunks),
                "character_count": sum(len(str(chunk.get("text") or "")) for chunk in chunks),
                "chunks": chunks,
            },
            "compliance_matrix": rows,
            "compliance_summary": _compliance_summary(rows),
            "pricing_context": fixture.get("pricing_context") if isinstance(fixture.get("pricing_context"), dict) else {},
            "created_at": "2026-06-04T12:00:00Z",
        },
        action_types=[
            "pdf_uploaded",
            "pdf_text_extracted",
            "requirements_extracted",
            "evidence_ledger_created",
            "gate_rules_run",
            "tasks_generated",
        ],
        now="2026-06-04T12:00:00Z",
    )
    return _fixture_report(fixture_id, path, expected, rows, session)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate deterministic bid-flow fixtures.")
    parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURE_DIR),
        help=f"Fixture directory. Default: {DEFAULT_FIXTURE_DIR}",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    report = evaluate_fixture_directory(Path(args.fixture_dir))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "Bid-flow evaluation: "
            f"fixtures={summary['fixture_count']}, "
            f"category_recall={summary['category_recall']:.2%}, "
            f"citation_coverage={summary['citation_coverage']:.2%}, "
            f"false_packet_ready={summary['false_packet_ready_count']}, "
            f"uncited_pdf_facts={summary['uncited_pdf_fact_count']}"
        )
        for failure in report["failures"]:
            print(f"FAIL: {failure}")
    return 0 if report["summary"]["passed"] else 1


def _fixture_report(
    fixture_id: str,
    path: Path,
    expected: dict[str, Any],
    rows: list[dict[str, Any]],
    session: dict[str, Any],
) -> dict[str, Any]:
    expected_categories = _strings(expected.get("categories"))
    expected_hard_stops = _strings(expected.get("hard_stop_categories"))
    expected_reviews = _strings(expected.get("review_categories"))
    detected_categories = _unique(row.get("category") for row in rows)
    matched_expected = [category for category in expected_categories if category in detected_categories]
    gates = [gate for gate in session.get("gate_results") or [] if isinstance(gate, dict)]
    hard_stop_categories = _unique(gate.get("category") for gate in gates if gate.get("gate_type") == "hard_stop")
    review_categories = _unique(gate.get("category") for gate in gates if gate.get("gate_type") == "review")
    cited_count = sum(1 for row in rows if _has_citation(row.get("citation")))
    uncited_pdf_fact_count = sum(
        1
        for fact in session.get("evidence_ledger") or []
        if isinstance(fact, dict)
        and fact.get("source_type") == "uploaded_pdf"
        and not _has_citation(fact.get("citation"))
    )
    missing_categories = [category for category in expected_categories if category not in detected_categories]
    missing_hard_stops = [category for category in expected_hard_stops if category not in hard_stop_categories]
    missing_reviews = [category for category in expected_reviews if category not in review_categories]
    allow_packet_ready = bool(expected.get("allow_packet_ready"))
    bid_state = str(session.get("bid_state") or "")
    false_packet_ready = bid_state == "owner_packet_ready" and not allow_packet_ready
    expected_bid_state = str(expected.get("bid_state") or "")
    pricing_failures = _pricing_sanity_failures(session)

    failures: list[str] = []
    for category in missing_categories:
        failures.append(f"{fixture_id}: missing expected requirement category {category}")
    for category in missing_hard_stops:
        failures.append(f"{fixture_id}: missing expected hard-stop gate for {category}")
    for category in missing_reviews:
        failures.append(f"{fixture_id}: missing expected review gate for {category}")
    if uncited_pdf_fact_count:
        failures.append(f"{fixture_id}: {uncited_pdf_fact_count} uploaded_pdf fact(s) lack citations")
    if false_packet_ready:
        failures.append(f"{fixture_id}: became owner_packet_ready despite expected blockers")
    if expected_bid_state and bid_state != expected_bid_state:
        failures.append(f"{fixture_id}: bid_state {bid_state} did not match expected {expected_bid_state}")
    failures.extend(f"{fixture_id}: {failure}" for failure in pricing_failures)

    return {
        "fixture_id": fixture_id,
        "path": str(path),
        "requirement_count": len(rows),
        "cited_requirement_count": cited_count,
        "citation_coverage": round(cited_count / len(rows), 4) if rows else 1.0,
        "expected_categories": expected_categories,
        "detected_categories": detected_categories,
        "matched_expected_categories": matched_expected,
        "missing_expected_categories": missing_categories,
        "hard_stop_categories": hard_stop_categories,
        "review_categories": review_categories,
        "missing_hard_stop_categories": missing_hard_stops,
        "missing_review_categories": missing_reviews,
        "bid_state": bid_state,
        "false_packet_ready": false_packet_ready,
        "uncited_pdf_fact_count": uncited_pdf_fact_count,
        "pricing_sanity_failures": pricing_failures,
        "task_count": len(session.get("agent_tasks") or []),
        "failures": failures,
    }


def _pricing_sanity_failures(session: dict[str, Any]) -> list[str]:
    worksheet = session.get("pricing_worksheet") if isinstance(session.get("pricing_worksheet"), dict) else {}
    if not worksheet:
        return []
    failures: list[str] = []
    confidence = str(worksheet.get("confidence") or "")
    comps = [
        comp
        for comp in worksheet.get("comparable_awards") or []
        if isinstance(comp, dict) and float(comp.get("award_value") or 0) > 0
    ]
    blockers = [str(item) for item in worksheet.get("blockers") or [] if str(item).strip()]
    if confidence == "High" and len(comps) < 2:
        failures.append("pricing confidence is High with fewer than two comparable awards")
    if worksheet.get("can_use_for_owner_packet") and (blockers or float(worksheet.get("target_bid") or 0) <= 0):
        failures.append("pricing worksheet is usable despite blockers or missing target bid")
    return failures


def _compliance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = sum(1 for row in rows if row.get("resolved"))
    return {
        "total": len(rows),
        "resolved": resolved,
        "unresolved": len(rows) - resolved,
        "ready_to_prepare": bool(rows) and resolved == len(rows),
    }


def _page_count(chunks: list[dict[str, Any]]) -> int:
    pages = {
        int(chunk.get("page_number") or chunk.get("page") or 0)
        for chunk in chunks
        if int(chunk.get("page_number") or chunk.get("page") or 0) > 0
    }
    return len(pages) or 1


def _has_citation(value: Any) -> bool:
    citation = value if isinstance(value, dict) else {}
    return bool(str(citation.get("source") or "").strip() and str(citation.get("snippet") or "").strip())


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item).strip()]


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
