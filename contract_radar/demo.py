from __future__ import annotations

import base64
import copy
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "golden_demo" / "road_repair_agent_demo.json"
DEFAULT_STATE_DIR = ROOT / "data" / "local_state" / "golden_demo"
DEFAULT_DOCUMENT_DIR = ROOT / "data" / "uploads" / "golden_demo"

ServiceFactory = Callable[..., Any]


def run_golden_demo(
    *,
    fixture: str | Path = DEFAULT_FIXTURE,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    document_dir: str | Path = DEFAULT_DOCUMENT_DIR,
    reset: bool = False,
    max_steps: int = 4,
    estimator: str = "Demo Estimator",
    approved_by: str = "",
    note: str | None = None,
    skip_owner_approval: bool = False,
    service: Any | None = None,
    service_factory: ServiceFactory | None = None,
) -> dict[str, Any]:
    """Run the local deterministic golden demo against either a supplied or fresh service."""
    fixture_path = Path(fixture)
    state_path = Path(state_dir)
    document_path = Path(document_dir)
    owns_service = service is None
    if owns_service:
        if reset:
            _reset_demo_dirs(state_path, document_path)
        if service_factory is None:
            from contract_radar.service import ContractRadarService

            service_factory = ContractRadarService
        service = service_factory(document_storage_dir=document_path, local_state_dir=state_path)

    def run_workflow() -> dict[str, Any]:
        return _run_golden_demo_workflow(
            service=service,
            fixture_path=fixture_path,
            state_path=state_path,
            document_path=document_path,
            max_steps=max_steps,
            estimator=estimator,
            approved_by=approved_by,
            note=note,
            skip_owner_approval=skip_owner_approval,
            restore_fixture_scan=not owns_service,
        )

    lock = getattr(service, "_lock", None)
    if lock is not None:
        with lock:
            return run_workflow()
    return run_workflow()


def _run_golden_demo_workflow(
    *,
    service: Any,
    fixture_path: Path,
    state_path: Path,
    document_path: Path,
    max_steps: int,
    estimator: str,
    approved_by: str,
    note: str | None,
    skip_owner_approval: bool,
    restore_fixture_scan: bool,
) -> dict[str, Any]:
    fixture_data = _load_fixture(fixture_path)
    rate_import = service.import_profile_rate_card(
        {
            "profile_id": str((fixture_data.get("company") or {}).get("profile_id") or ""),
            "business_profile": fixture_data.get("company") or {},
            "rate_card_csv": fixture_data.get("rate_card_csv") or "",
            "replace": True,
        }
    )
    profile = rate_import["business_profile"]
    restore_scan = _install_fixture_scan(service, fixture_data, profile)
    try:
        pdf_bytes = _pdf_bytes((fixture_data.get("pdf") or {}).get("pages") or [])
        analysis = service.analyze_document(
            {
                "filename": str((fixture_data.get("pdf") or {}).get("filename") or "golden-demo.pdf"),
                "opportunity_id": _fixture_opportunity_id(fixture_data),
                "profile_id": str(profile.get("profile_id") or ""),
                "business_profile": profile,
                "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            }
        )
        resolved = _apply_fixture_resolutions(service, analysis, fixture_data.get("resolutions") or [])
        priced = service.approve_pricing(
            {
                "analysis_id": resolved["analysis_id"],
                "approved_by": str(estimator or "Demo Estimator"),
            }
        )
        loop = service.run_until_approval(
            {
                "profile_id": str(profile.get("profile_id") or ""),
                "business_profile": profile,
                "max_steps": int(max_steps),
            }
        )
        owner_request = _first_owner_request(loop)
        approval_result: dict[str, Any] = {}
        if owner_request and not skip_owner_approval:
            owner_defaults = fixture_data.get("owner_approval") if isinstance(fixture_data.get("owner_approval"), dict) else {}
            approval_result = service.approve_owner_request(
                {
                    "approval_request_id": owner_request["approval_request_id"],
                    "approved_by": str(approved_by or owner_defaults.get("approved_by") or "Demo Owner"),
                    "note": str(note if note is not None else owner_defaults.get("note") or ""),
                }
            )
        final_scan = _service_scan_snapshot(service, loop)
    finally:
        if restore_fixture_scan:
            restore_scan()

    return _demo_result(
        fixture=fixture_data,
        fixture_path=fixture_path,
        state_dir=state_path,
        document_dir=document_path,
        rate_import=rate_import,
        analysis=analysis,
        resolved=resolved,
        priced=priced,
        loop=loop,
        owner_request=owner_request,
        approval_result=approval_result,
        final_scan=final_scan,
    )


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Demo fixture {path} must contain a JSON object.")
    return payload


def _reset_demo_dirs(*paths: Path) -> None:
    for path in paths:
        resolved = path.resolve()
        allowed_root = (ROOT / "data").resolve()
        if allowed_root not in resolved.parents:
            raise ValueError(f"Refusing to reset non-demo path: {resolved}")
        if path.exists():
            shutil.rmtree(path)


def _install_fixture_scan(service: Any, fixture: dict[str, Any], profile: dict[str, Any]) -> Callable[[], None]:
    original_scan = service.scan
    scan = copy.deepcopy(fixture.get("scan") or {})
    scan["business_profile"] = copy.deepcopy(profile)
    for bucket in ("top_opportunities", "watchlist", "all_evaluated", "skipped"):
        for item in scan.get(bucket) or []:
            if isinstance(item, dict):
                item["business_profile"] = copy.deepcopy(profile)
    if not scan.get("all_evaluated"):
        scan["all_evaluated"] = copy.deepcopy(scan.get("top_opportunities") or [])

    def fixture_scan(payload: dict[str, Any] | None = None, progress_callback: Any | None = None) -> dict[str, Any]:
        hydrated = service._scan_with_runtime_state(copy.deepcopy(scan))
        service._last_scan = copy.deepcopy(hydrated)
        return hydrated

    service._last_scan = copy.deepcopy(scan)
    service.scan = fixture_scan

    def restore() -> None:
        service.scan = original_scan

    return restore


def _pdf_bytes(pages: Sequence[Any]) -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError("PyMuPDF is required to generate the golden demo PDF.") from exc

    document = fitz.open()
    try:
        for page_text in pages:
            page = document.new_page(width=612, height=792)
            page.insert_textbox((54, 54, 558, 738), str(page_text or ""), fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def _fixture_opportunity_id(fixture: dict[str, Any]) -> str:
    scan = fixture.get("scan") if isinstance(fixture.get("scan"), dict) else {}
    for bucket in ("top_opportunities", "watchlist", "all_evaluated"):
        for item in scan.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            solicitation = item.get("solicitation") if isinstance(item.get("solicitation"), dict) else {}
            opportunity_id = str(solicitation.get("document_number") or item.get("opportunity_id") or "").strip()
            if opportunity_id:
                return opportunity_id
    raise ValueError("Golden demo fixture does not include an opportunity id.")


def _apply_fixture_resolutions(service: Any, analysis: dict[str, Any], resolutions: list[Any]) -> dict[str, Any]:
    current = copy.deepcopy(analysis)
    for resolution in resolutions:
        if not isinstance(resolution, dict):
            continue
        category = str(resolution.get("category") or "").strip()
        row = _first_unresolved_row(current, category)
        if not row:
            continue
        current = service.resolve_requirement(
            {
                "analysis_id": current["analysis_id"],
                "requirement_id": row["requirement_id"],
                "resolution_type": str(resolution.get("resolution_type") or "capability_confirmed"),
                "note": str(resolution.get("note") or ""),
            }
        )
    return current


def _first_unresolved_row(analysis: dict[str, Any], category: str) -> dict[str, Any]:
    for row in analysis.get("compliance_matrix") or []:
        if not isinstance(row, dict):
            continue
        if category and str(row.get("category") or "") != category:
            continue
        if not bool(row.get("resolved")):
            return row
    return {}


def _first_owner_request(loop: dict[str, Any]) -> dict[str, Any]:
    for request in loop.get("owner_approval_requests") or []:
        if isinstance(request, dict):
            return dict(request)
    return {}


def _service_scan_snapshot(service: Any, loop: dict[str, Any]) -> dict[str, Any]:
    scan = loop.get("scan") if isinstance(loop.get("scan"), dict) else {}
    last_scan = getattr(service, "_last_scan", None)
    if isinstance(last_scan, dict):
        try:
            refreshed = service._scan_with_runtime_state(copy.deepcopy(last_scan))
            service._last_scan = copy.deepcopy(refreshed)
            return refreshed
        except Exception:
            return copy.deepcopy(last_scan)
    return copy.deepcopy(scan)


def _demo_result(
    *,
    fixture: dict[str, Any],
    fixture_path: Path,
    state_dir: Path,
    document_dir: Path,
    rate_import: dict[str, Any],
    analysis: dict[str, Any],
    resolved: dict[str, Any],
    priced: dict[str, Any],
    loop: dict[str, Any],
    owner_request: dict[str, Any],
    approval_result: dict[str, Any],
    final_scan: dict[str, Any],
) -> dict[str, Any]:
    packet = approval_result.get("packet") if isinstance(approval_result.get("packet"), dict) else {}
    packet_export = approval_result.get("packet_export") if isinstance(approval_result.get("packet_export"), dict) else {}
    form_blueprint = packet.get("form_blueprint") if isinstance(packet.get("form_blueprint"), dict) else {}
    summary = {
        "status": _demo_status(loop, approval_result),
        "highest_value_gap": _highest_value_gap(loop, approval_result),
        "requirement_count": len(analysis.get("compliance_matrix") or []),
        "pricing_line_item_count": int((priced.get("pricing_worksheet") or {}).get("quantity_summary", {}).get("line_item_count") or 0),
        "packet_export_ready": bool(packet_export.get("export_id")),
        "form_blueprint_ready": bool(form_blueprint.get("ready_for_form_work")),
    }
    return {
        "source": "golden_agent_demo",
        "fixture_id": str(fixture.get("fixture_id") or ""),
        "fixture_path": str(fixture_path),
        "state_dir": str(state_dir),
        "document_dir": str(document_dir),
        "status": summary["status"],
        "highest_value_gap": summary["highest_value_gap"],
        "demo_summary": summary,
        "rate_card_import": {
            "imported_count": rate_import.get("rate_card_import", {}).get("imported_count"),
            "skipped_count": rate_import.get("rate_card_import", {}).get("skipped_count"),
        },
        "analysis": {
            "analysis_id": analysis.get("analysis_id"),
            "initial_bid_state": analysis.get("bid_state"),
            "resolved_bid_state": resolved.get("bid_state"),
            "priced_bid_state": priced.get("bid_state"),
            "requirement_count": summary["requirement_count"],
            "pricing_line_item_count": summary["pricing_line_item_count"],
        },
        "agent_loop": loop.get("agent_loop") or {},
        "owner_approval_request": owner_request,
        "approval": {
            "approved": bool(approval_result.get("approved")),
            "packet_id": approval_result.get("packet_id"),
            "packet_export": {
                "export_id": packet_export.get("export_id"),
                "storage_path": packet_export.get("storage_path"),
                "download_url": packet_export.get("download_url"),
            },
        },
        "packet": packet,
        "packet_export": packet_export,
        "owner_approval": approval_result.get("owner_approval") if isinstance(approval_result.get("owner_approval"), dict) else {},
        "scan": final_scan,
        "form_blueprint": form_blueprint,
        "form_blueprint_summary": {
            "blueprint_id": form_blueprint.get("blueprint_id"),
            "ready_for_form_work": form_blueprint.get("ready_for_form_work"),
            "field_count": len(form_blueprint.get("form_fields") or []),
            "attachment_count": len(form_blueprint.get("attachments") or []),
            "blocker_count": len(form_blueprint.get("blockers") or []),
        },
    }


def _demo_status(loop: dict[str, Any], approval_result: dict[str, Any]) -> str:
    if approval_result.get("approved"):
        return "owner_packet_approved"
    agent_loop = loop.get("agent_loop") if isinstance(loop.get("agent_loop"), dict) else {}
    return str(agent_loop.get("status") or "unknown")


def _highest_value_gap(loop: dict[str, Any], approval_result: dict[str, Any]) -> str:
    if approval_result.get("approved"):
        return "authenticated_buyer_portal_submission_and_final_upload_remain_manual"
    human_actions = [
        item
        for item in loop.get("human_required_actions") or []
        if isinstance(item, dict)
    ]
    if human_actions:
        return f"human_input_required:{human_actions[0].get('task_type') or 'unknown_task'}"
    agent_loop = loop.get("agent_loop") if isinstance(loop.get("agent_loop"), dict) else {}
    if agent_loop.get("error_count"):
        return "agent_loop_error"
    return "no_gap_detected"
