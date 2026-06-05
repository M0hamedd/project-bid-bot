from __future__ import annotations

import argparse
import base64
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_radar.service import ContractRadarService
from contract_radar.package_reports import package_report_payloads, portal_package_reports, validate_package_pdf_path
from contract_radar.submission_reports import portal_submission_reports


ServiceFactory = Callable[..., Any]


def run_bid_pipeline_cli(
    argv: Sequence[str] | None = None,
    service_factory: ServiceFactory = ContractRadarService,
) -> dict[str, Any]:
    args = _parser().parse_args(argv)
    service = _build_service(service_factory, args.state_dir)
    resume_agent_work_dirs = _agent_work_dirs(args.resume_agent_work_dir)
    payload = _payload(args, resume_agent_work_dirs=resume_agent_work_dirs)
    submission_reports = _dedupe_portal_submission_reports([
        *_portal_submission_report_files(args.portal_submission_report_file),
        *_portal_submission_report_dirs(args.portal_submission_report_dir),
        *_portal_submission_report_dirs([str(path) for path in resume_agent_work_dirs]),
    ])
    submission_report_application = (
        _record_portal_submission_reports(service, submission_reports) if submission_reports else {}
    )
    result = service.run_agent_pipeline(payload)
    if submission_report_application:
        result["portal_submission_report_application"] = submission_report_application
    if args.agent_work_dir:
        result["agent_handoff"] = _write_agent_handoff(
            result,
            Path(args.agent_work_dir),
            profile_id=str(payload.get("profile_id") or ""),
        )
    return result


def main(
    argv: Sequence[str] | None = None,
    service_factory: ServiceFactory = ContractRadarService,
) -> int:
    try:
        result = run_bid_pipeline_cli(argv, service_factory=service_factory)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the deterministic bid pipeline from deal discovery to owner approval handoff."
    )
    parser.add_argument("--profile-id", default="road_civil_infrastructure", help="Business profile id.")
    parser.add_argument("--business-profile-file", default="", help="Optional JSON file with business_profile fields.")
    parser.add_argument("--company-file", default="", help="Optional JSON file with company intake fields.")
    parser.add_argument("--as-of", default="", help="Optional YYYY-MM-DD scan date.")
    parser.add_argument("--priority-mode", default="best_win_chance", help="Ranking priority mode.")
    parser.add_argument("--max-steps", type=int, default=8, help="Maximum safe automatic task executions.")
    parser.add_argument("--refresh", action="store_true", help="Refresh source data instead of using cached scan state.")
    parser.add_argument(
        "--approval-request-id",
        action="append",
        default=[],
        help="Current owner approval request id to approve and generate into a packet. Repeat for multiple ids.",
    )
    parser.add_argument(
        "--approve-all-owner-requests",
        action="store_true",
        help="Approve every current owner approval request returned by this pipeline run.",
    )
    parser.add_argument("--approved-by", default="Owner", help="Owner name used when approving request ids.")
    parser.add_argument("--note", default="", help="Optional owner approval note.")
    parser.add_argument(
        "--completed-action-file",
        action="append",
        default=[],
        help="JSON file containing one completed action object or a list of completed actions, including owner approval, to apply before resuming.",
    )
    parser.add_argument(
        "--completed-action-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory tree containing completed action JSON files to apply before resuming.",
    )
    parser.add_argument(
        "--package-file",
        action="append",
        default=[],
        metavar="OPPORTUNITY_ID=PDF_PATH",
        help="Local official package PDF to analyze as a completed action before resuming. Repeat for multiple opportunities.",
    )
    parser.add_argument(
        "--package-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory of downloaded package PDFs named OPPORTUNITY_ID__anything.pdf to analyze before resuming.",
    )
    parser.add_argument(
        "--portal-package-report-file",
        action="append",
        default=[],
        metavar="REPORT.json",
        help="Portal/browser package download report JSON to convert into bounded package analysis actions.",
    )
    parser.add_argument(
        "--portal-package-report-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory tree containing portal package download report JSON files.",
    )
    parser.add_argument(
        "--portal-submission-report-file",
        action="append",
        default=[],
        metavar="REPORT.json",
        help="Portal/browser submission preparation report JSON to record for audit without submitting.",
    )
    parser.add_argument(
        "--portal-submission-report-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory tree containing portal submission preparation report JSON files.",
    )
    parser.add_argument(
        "--owner-approval-report-file",
        action="append",
        default=[],
        metavar="REPORT.json",
        help="Owner approval decision report JSON to convert into a server-owned approval completed action.",
    )
    parser.add_argument(
        "--owner-approval-report-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory tree containing owner approval decision report JSON files.",
    )
    parser.add_argument(
        "--resume-agent-work-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Resume from one agent handoff/work directory by loading completed actions, reports, and OPPORTUNITY_ID__*.pdf packages.",
    )
    parser.add_argument(
        "--agent-work-dir",
        default="",
        help="Write compact agent handoff JSON files into this directory after the pipeline run.",
    )
    parser.add_argument("--state-dir", default=None, help="Optional local state directory.")
    return parser


def _payload(args: argparse.Namespace, *, resume_agent_work_dirs: list[Path] | None = None) -> dict[str, Any]:
    resume_agent_work_dirs = resume_agent_work_dirs or []
    profile = _json_file(args.business_profile_file)
    profile_id = str(args.profile_id or profile.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("A --profile-id or business_profile.profile_id is required.")
    if profile:
        profile["profile_id"] = profile_id
    payload: dict[str, Any] = {
        "profile_id": profile_id,
        "business_profile": profile,
        "priority_mode": args.priority_mode,
        "max_steps": args.max_steps,
        "refresh": bool(args.refresh),
        "approval_request_ids": [item for item in args.approval_request_id if str(item or "").strip()],
        "approve_all_owner_requests": bool(args.approve_all_owner_requests),
        "approved_by": args.approved_by,
        "note": args.note,
    }
    completed_actions = [
        *_completed_action_files(args.completed_action_file),
        *_completed_action_dirs(args.completed_action_dir),
        *_portal_package_report_files(args.portal_package_report_file, profile_id=profile_id),
        *_portal_package_report_dirs(args.portal_package_report_dir, profile_id=profile_id),
        *_package_file_actions(args.package_file, profile_id=profile_id),
        *_package_dir_actions(args.package_dir, profile_id=profile_id),
        *_owner_approval_report_files(args.owner_approval_report_file),
        *_owner_approval_report_dirs(args.owner_approval_report_dir),
        *_completed_action_dirs([str(path) for path in resume_agent_work_dirs]),
        *_owner_approval_report_dirs([str(path) for path in resume_agent_work_dirs]),
        *_portal_package_report_dirs([str(path) for path in resume_agent_work_dirs], profile_id=profile_id),
        *_agent_work_package_actions(resume_agent_work_dirs, profile_id=profile_id),
    ]
    completed_actions = _dedupe_completed_actions(completed_actions)
    if completed_actions:
        payload["completed_actions"] = completed_actions
    if args.as_of:
        payload["as_of"] = args.as_of
    company = _json_file(args.company_file)
    if company:
        payload["company"] = company
    return payload


def _json_file(path_value: str) -> dict[str, Any]:
    path_value = str(path_value or "").strip()
    if not path_value:
        return {}
    payload = _read_json_payload(Path(path_value))
    if not isinstance(payload, dict):
        raise ValueError(f"{path_value} must contain a JSON object.")
    return payload


def _completed_action_files(paths: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        output.extend(_completed_actions_from_json_file(Path(path_value), require_action=True))
    return output


def _completed_action_dirs(paths: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        directory = Path(path_value)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Completed action directory does not exist: {directory}")
        for path in sorted(directory.rglob("*.json")):
            for action in _completed_actions_from_json_file(path, require_action=False):
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                output.append(action)
    return output


def _agent_work_dirs(paths: list[str]) -> list[Path]:
    output: list[Path] = []
    seen: set[str] = set()
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        directory = Path(path_value)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Agent work directory does not exist: {directory}")
        key = str(directory.resolve())
        if key in seen:
            continue
        seen.add(key)
        output.append(directory)
    return output


def _completed_actions_from_json_file(path: Path, *, require_action: bool) -> list[dict[str, Any]]:
    payload = _read_json_payload(path)
    if isinstance(payload, dict):
        if _is_completed_action_object(payload):
            return [payload]
        if require_action:
            raise ValueError(f"{path} must contain a completed action object.")
        return []
    if isinstance(payload, list):
        output = []
        for item in payload:
            if not isinstance(item, dict):
                if require_action:
                    raise ValueError(f"{path} must contain action objects.")
                continue
            if _is_completed_action_object(item):
                output.append(item)
            elif require_action:
                raise ValueError(f"{path} must contain completed action objects.")
        return output
    if require_action:
        raise ValueError(f"{path} must contain one completed action object or a list of completed action objects.")
    return []


def _is_completed_action_object(value: dict[str, Any]) -> bool:
    return bool(str(value.get("endpoint") or value.get("action_type") or "").strip())


def _completed_action_key(value: dict[str, Any]) -> str:
    action_id = str(value.get("action_id") or value.get("completed_action_id") or "").strip()
    if action_id:
        return f"id:{action_id}"
    return "payload:" + json.dumps(value, sort_keys=True, default=str)


def _dedupe_completed_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        key = _completed_action_dedupe_key(action)
        if key in seen:
            continue
        seen.add(key)
        output.append(action)
    return output


def _completed_action_dedupe_key(action: dict[str, Any]) -> str:
    endpoint = str(action.get("endpoint") or "").strip()
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    if endpoint == "/api/documents/analyze":
        opportunity_id = str(payload.get("opportunity_id") or "").strip()
        filename = str(payload.get("filename") or "").strip()
        if opportunity_id and filename:
            return f"document:{opportunity_id}:{filename}"
    return _completed_action_key(action)


def _package_file_actions(values: list[str], *, profile_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for value in values or []:
        spec = str(value or "").strip()
        if not spec:
            continue
        if "=" not in spec:
            raise ValueError("--package-file must use OPPORTUNITY_ID=PDF_PATH.")
        opportunity_id, path_value = spec.split("=", 1)
        opportunity_id = opportunity_id.strip()
        path = Path(path_value.strip())
        if not opportunity_id:
            raise ValueError("--package-file requires an opportunity id before '='.")
        if not path.exists() or not path.is_file():
            raise ValueError(f"Package file does not exist: {path}")
        validate_package_pdf_path(path)
        actions.append(_package_file_action(opportunity_id=opportunity_id, path=path, profile_id=profile_id))
    return actions


def _package_dir_actions(values: list[str], *, profile_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values or []:
        directory = Path(str(value or "").strip())
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Package directory does not exist: {directory}")
        pdf_paths = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
        if not pdf_paths:
            raise ValueError(f"Package directory contains no PDF files: {directory}")
        for path in pdf_paths:
            opportunity_id = _opportunity_id_from_package_filename(path)
            if opportunity_id in seen:
                raise ValueError(f"Duplicate package PDF for opportunity {opportunity_id}.")
            seen.add(opportunity_id)
            validate_package_pdf_path(path)
            actions.append(_package_file_action(opportunity_id=opportunity_id, path=path, profile_id=profile_id))
    return actions


def _agent_work_package_actions(directories: list[Path], *, profile_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.pdf")):
            if "__" not in path.stem:
                continue
            opportunity_id = _opportunity_id_from_package_filename(path)
            key = f"{opportunity_id}:{path.name}"
            if key in seen:
                continue
            seen.add(key)
            validate_package_pdf_path(path)
            actions.append(_package_file_action(opportunity_id=opportunity_id, path=path, profile_id=profile_id))
    return actions


def _owner_approval_report_files(paths: list[str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        actions.extend(_owner_approval_actions_from_report_file(Path(path_value), require_report=True))
    return actions


def _owner_approval_report_dirs(paths: list[str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        directory = Path(path_value)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Owner approval report directory does not exist: {directory}")
        for path in sorted(directory.rglob("*.json")):
            for action in _owner_approval_actions_from_report_file(path, require_report=False):
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                actions.append(action)
    return actions


def _owner_approval_actions_from_report_file(path: Path, *, require_report: bool) -> list[dict[str, Any]]:
    payload = _read_json_payload(path)
    reports = _owner_approval_reports(payload)
    if reports:
        return [_owner_approval_action_from_report(report) for report in reports]
    if require_report:
        raise ValueError(f"{path} must contain an owner approval decision report.")
    return []


def _owner_approval_reports(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if _is_owner_approval_report(value):
            return [dict(value)]
        for key in ("owner_approval_report", "approval_report", "report"):
            nested = value.get(key)
            if isinstance(nested, dict) and _is_owner_approval_report(nested):
                return [dict(nested)]
        for key in ("owner_approval_reports", "approval_reports", "reports"):
            nested_list = value.get(key)
            if isinstance(nested_list, list):
                reports = [dict(item) for item in nested_list if isinstance(item, dict) and _is_owner_approval_report(item)]
                if reports:
                    return reports
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict) and _is_owner_approval_report(item)]
    return []


def _is_owner_approval_report(value: dict[str, Any]) -> bool:
    if str(value.get("source") or "") == "owner_approval_decision_report":
        return True
    return bool(str(value.get("approval_request_id") or "").strip() and "approved" in value)


def _owner_approval_action_from_report(report: dict[str, Any]) -> dict[str, Any]:
    approval_request_id = str(report.get("approval_request_id") or "").strip()
    if not approval_request_id:
        raise ValueError("Owner approval report requires an approval_request_id.")
    if report.get("approved") is not True:
        raise ValueError("Owner approval report must have approved=true to generate a packet.")
    return {
        "action_id": f"completed-owner-approval-{approval_request_id}",
        "endpoint": "/api/owner-approval/approve",
        "payload": {
            "approval_request_id": approval_request_id,
            "approved": True,
            "approved_by": str(report.get("approved_by") or "Owner"),
            "note": str(report.get("note") or report.get("approval_note") or ""),
        },
    }


def _portal_package_report_files(paths: list[str], *, profile_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        actions.extend(_package_actions_from_report_file(Path(path_value), profile_id=profile_id, require_report=True))
    return actions


def _portal_package_report_dirs(paths: list[str], *, profile_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        directory = Path(path_value)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Portal package report directory does not exist: {directory}")
        for path in sorted(directory.rglob("*.json")):
            for action in _package_actions_from_report_file(path, profile_id=profile_id, require_report=False):
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                actions.append(action)
    return actions


def _package_actions_from_report_file(path: Path, *, profile_id: str, require_report: bool) -> list[dict[str, Any]]:
    payload = _read_json_payload(path)
    reports = portal_package_reports(payload)
    if not reports:
        if require_report:
            raise ValueError(f"{path} must contain a portal package download report.")
        return []
    report_payloads = package_report_payloads(reports, profile_id=profile_id, base_dir=path.parent)
    return [
        _package_action_from_report_payload(item)
        for item in report_payloads
    ]


def _package_action_from_report_payload(report_payload: dict[str, Any]) -> dict[str, Any]:
    payload = report_payload.get("payload") if isinstance(report_payload.get("payload"), dict) else {}
    opportunity_id = str(report_payload.get("opportunity_id") or payload.get("opportunity_id") or "")
    request_id = str(report_payload.get("request_id") or "").strip()
    action_id = f"completed-package-upload-{opportunity_id}"
    if request_id:
        action_id = f"completed-portal-package-{request_id}"
    return {
        "action_id": action_id,
        "endpoint": "/api/documents/analyze",
        "payload": payload,
    }


def _portal_submission_report_files(paths: list[str]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        reports.extend(_portal_submission_reports_from_json_file(Path(path_value), require_report=True))
    return reports


def _portal_submission_report_dirs(paths: list[str]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_value in paths or []:
        path_value = str(path_value or "").strip()
        if not path_value:
            continue
        directory = Path(path_value)
        if not directory.exists() or not directory.is_dir():
            raise ValueError(f"Portal submission report directory does not exist: {directory}")
        for path in sorted(directory.rglob("*.json")):
            for report in _portal_submission_reports_from_json_file(path, require_report=False):
                key = _portal_submission_report_key(report)
                if key in seen:
                    continue
                seen.add(key)
                reports.append(report)
    return reports


def _portal_submission_reports_from_json_file(path: Path, *, require_report: bool) -> list[dict[str, Any]]:
    payload = _read_json_payload(path)
    reports = portal_submission_reports(payload)
    if reports:
        return reports
    if require_report:
        raise ValueError(f"{path} must contain a portal submission preparation report.")
    return []


def _portal_submission_report_key(value: dict[str, Any]) -> str:
    report_id = str(value.get("report_id") or "").strip()
    if report_id:
        return f"id:{report_id}"
    request_id = str(value.get("request_id") or "").strip()
    if request_id:
        return f"request:{request_id}"
    return "payload:" + json.dumps(value, sort_keys=True, default=str)


def _dedupe_portal_submission_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for report in reports:
        key = _portal_submission_report_key(report)
        if key in seen:
            continue
        seen.add(key)
        output.append(report)
    return output


def _record_portal_submission_reports(service: Any, reports: list[dict[str, Any]]) -> dict[str, Any]:
    recorder = getattr(service, "record_portal_submission_report", None)
    if not callable(recorder):
        raise ValueError("The service cannot record portal submission reports.")
    return recorder({"portal_submission_reports": reports})


def _opportunity_id_from_package_filename(path: Path) -> str:
    stem = path.stem
    if "__" not in stem:
        raise ValueError(
            f"Package directory PDF must be named OPPORTUNITY_ID__anything.pdf: {path.name}"
        )
    opportunity_id = stem.split("__", 1)[0].strip()
    if not opportunity_id:
        raise ValueError(f"Package directory PDF is missing an opportunity id: {path.name}")
    return opportunity_id


def _package_file_action(*, opportunity_id: str, path: Path, profile_id: str) -> dict[str, Any]:
    content_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "action_id": f"completed-package-upload-{opportunity_id}",
        "endpoint": "/api/documents/analyze",
        "payload": {
            "opportunity_id": opportunity_id,
            "profile_id": profile_id,
            "filename": path.name,
            "content_base64": content_base64,
        },
    }


def _write_agent_handoff(result: dict[str, Any], directory: Path, *, profile_id: str = "") -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    completed_dir = directory / "completed-action-templates"
    completed_dir.mkdir(exist_ok=True)
    owner_approval_dir = directory / "owner-approval-requests"
    owner_approval_dir.mkdir(exist_ok=True)
    portal_request_dir = directory / "portal-package-requests"
    portal_request_dir.mkdir(exist_ok=True)
    submission_request_dir = directory / "portal-submission-requests"
    submission_request_dir.mkdir(exist_ok=True)

    completed_templates = _completed_action_templates(result.get("next_agent_actions"))
    owner_approval_requests = _owner_approval_handoff_requests(result.get("approval_actions"))
    generated_packages = _rows(result.get("generated_bid_packages"))
    manifest = result.get("package_directory_manifest") if isinstance(result.get("package_directory_manifest"), dict) else {}
    portal_requests = _rows(result.get("portal_package_requests"))
    submission_requests = _rows(result.get("portal_submission_requests"))
    files: dict[str, str] = {}
    files["pipeline_summary"] = _write_json(directory / "pipeline-summary.json", result.get("pipeline") or {})
    files["next_agent_actions"] = _write_json(directory / "next-agent-actions.json", _rows(result.get("next_agent_actions")))
    files["completed_action_templates"] = _write_json(directory / "completed-action-templates.json", completed_templates)
    files["owner_approval_requests"] = _write_json(directory / "owner-approval-requests.json", owner_approval_requests)
    files["package_directory_manifest"] = _write_json(directory / "package-directory-manifest.json", manifest)
    files["portal_package_requests"] = _write_json(directory / "portal-package-requests.json", portal_requests)
    files["portal_submission_requests"] = _write_json(directory / "portal-submission-requests.json", submission_requests)
    files["generated_bid_packages"] = _write_json(directory / "generated-bid-packages.json", generated_packages)

    completed_files: list[dict[str, str]] = []
    for index, action in enumerate(completed_templates, start=1):
        action_id = str(action.get("action_id") or f"completed-action-{index}")
        path = completed_dir / f"{_safe_filename(action_id)}.json"
        completed_files.append(
            {
                "action_id": action_id,
                "path": _write_json(path, action),
            }
        )

    owner_approval_files: list[dict[str, str]] = []
    for index, request in enumerate(owner_approval_requests, start=1):
        approval_request_id = str(request.get("approval_request_id") or f"owner-approval-request-{index}")
        path = owner_approval_dir / f"{_safe_filename(approval_request_id)}.json"
        owner_approval_files.append(
            {
                "approval_request_id": approval_request_id,
                "path": _write_json(path, request),
            }
        )

    portal_request_files: list[dict[str, str]] = []
    for index, request in enumerate(portal_requests, start=1):
        request_id = str(request.get("request_id") or f"portal-package-request-{index}")
        path = portal_request_dir / f"{_safe_filename(request_id)}.json"
        portal_request_files.append(
            {
                "request_id": request_id,
                "path": _write_json(path, request),
            }
        )

    submission_request_files: list[dict[str, str]] = []
    for index, request in enumerate(submission_requests, start=1):
        request_id = str(request.get("request_id") or f"portal-submission-request-{index}")
        path = submission_request_dir / f"{_safe_filename(request_id)}.json"
        submission_request_files.append(
            {
                "request_id": request_id,
                "path": _write_json(path, request),
            }
        )

    resume_command = "python scripts\\run_bid_pipeline.py"
    if profile_id:
        resume_command += f" --profile-id {_quote_cli_arg(profile_id)}"
    resume_command += f" --resume-agent-work-dir {_quote_cli_arg(str(directory))} --agent-work-dir {_quote_cli_arg(str(directory))}"
    handoff = {
        "source": "run_bid_pipeline_cli",
        "directory": str(directory),
        "resume_agent_work_dir": str(directory),
        "resume_agent_work_command": resume_command,
        "pipeline_status": str((result.get("pipeline") or {}).get("status") or ""),
        "next_action": str((result.get("pipeline") or {}).get("next_action") or ""),
        "next_agent_action_count": len(_rows(result.get("next_agent_actions"))),
        "completed_action_template_count": len(completed_templates),
        "owner_approval_request_count": len(owner_approval_requests),
        "package_download_count": len(_rows(manifest.get("entries"))),
        "portal_package_request_count": len(portal_requests),
        "portal_submission_request_count": len(submission_requests),
        "generated_bid_package_count": len(generated_packages),
        "package_dir_command": str(manifest.get("package_dir_command") or ""),
        "files": files,
        "completed_action_files": completed_files,
        "owner_approval_request_files": owner_approval_files,
        "portal_package_request_files": portal_request_files,
        "portal_submission_request_files": submission_request_files,
        "guardrails": [
            "These files are handoff artifacts for an agent or human operator.",
            "Completed action templates must still be filled with real facts or approvals before use.",
            "No bid was submitted by writing this handoff directory.",
        ],
    }
    handoff_path = directory / "agent-handoff.json"
    files["agent_handoff"] = str(handoff_path)
    _write_json(handoff_path, handoff)
    return handoff


def _completed_action_templates(actions: Any) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for action in _rows(actions):
        template = action.get("completed_action_template")
        if isinstance(template, dict) and template:
            templates.append(template)
    return templates


def _owner_approval_handoff_requests(actions: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for action in _rows(actions):
        approval_request_id = str(action.get("approval_request_id") or "").strip()
        if not approval_request_id:
            continue
        output.append(
            {
                "source": "deterministic_owner_approval_request_handoff",
                "approval_request_id": approval_request_id,
                "opportunity_id": str(action.get("opportunity_id") or ""),
                "analysis_id": str(action.get("analysis_id") or ""),
                "title": str(action.get("title") or ""),
                "deadline": str(action.get("deadline") or ""),
                "target_bid": action.get("target_bid"),
                "reason": str(action.get("reason") or "Owner approval is required before the packet can be generated."),
                "approval_endpoint": str(action.get("approval_endpoint") or action.get("endpoint") or "/api/owner-approval/approve"),
                "approval_payload": _copy_json(action.get("approval_payload")),
                "completion_criteria": [
                    "Owner reviewed the target bid, compliance readiness, and packet audit trail.",
                    "Owner explicitly approved packet generation for this approval_request_id.",
                    "No buyer portal submission was performed.",
                ],
                "approval_report_template": {
                    "source": "owner_approval_decision_report",
                    "approval_request_id": approval_request_id,
                    "approved": False,
                    "approved_by": "Owner",
                    "note": "",
                },
                "guardrails": [
                    "Do not fill approved=true unless the owner explicitly approves this exact approval_request_id.",
                    "Do not modify analysis_id, opportunity_id, compliance rows, or pricing rows in the approval payload.",
                    "Approval generates a packet only; buyer submission remains manual.",
                ],
            }
        )
    return output


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value else {}


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def _read_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _safe_filename(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:120] or "completed-action"


def _quote_cli_arg(value: str) -> str:
    value = str(value or "")
    if value and all(character not in value for character in " \t\""):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _build_service(service_factory: ServiceFactory, state_dir: str | None) -> Any:
    kwargs: dict[str, Any] = {}
    if state_dir and _supports_local_state_dir(service_factory):
        kwargs["local_state_dir"] = state_dir
    return service_factory(**kwargs)


def _supports_local_state_dir(service_factory: ServiceFactory) -> bool:
    try:
        parameters = inspect.signature(service_factory).parameters.values()
    except (TypeError, ValueError):
        return True

    for parameter in parameters:
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "local_state_dir" and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
