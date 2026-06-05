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


ServiceFactory = Callable[..., Any]


def run_bid_pipeline_cli(
    argv: Sequence[str] | None = None,
    service_factory: ServiceFactory = ContractRadarService,
) -> dict[str, Any]:
    args = _parser().parse_args(argv)
    service = _build_service(service_factory, args.state_dir)
    payload = _payload(args)
    result = service.run_agent_pipeline(payload)
    if args.agent_work_dir:
        result["agent_handoff"] = _write_agent_handoff(result, Path(args.agent_work_dir))
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
        "--agent-work-dir",
        default="",
        help="Write compact agent handoff JSON files into this directory after the pipeline run.",
    )
    parser.add_argument("--state-dir", default=None, help="Optional local state directory.")
    return parser


def _payload(args: argparse.Namespace) -> dict[str, Any]:
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
        *_package_file_actions(args.package_file, profile_id=profile_id),
        *_package_dir_actions(args.package_dir, profile_id=profile_id),
    ]
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
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
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


def _completed_actions_from_json_file(path: Path, *, require_action: bool) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
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
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Package file must be a PDF: {path}")
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
            actions.append(_package_file_action(opportunity_id=opportunity_id, path=path, profile_id=profile_id))
    return actions


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


def _write_agent_handoff(result: dict[str, Any], directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    completed_dir = directory / "completed-action-templates"
    completed_dir.mkdir(exist_ok=True)

    completed_templates = _completed_action_templates(result.get("next_agent_actions"))
    generated_packages = _rows(result.get("generated_bid_packages"))
    manifest = result.get("package_directory_manifest") if isinstance(result.get("package_directory_manifest"), dict) else {}
    files: dict[str, str] = {}
    files["pipeline_summary"] = _write_json(directory / "pipeline-summary.json", result.get("pipeline") or {})
    files["next_agent_actions"] = _write_json(directory / "next-agent-actions.json", _rows(result.get("next_agent_actions")))
    files["completed_action_templates"] = _write_json(directory / "completed-action-templates.json", completed_templates)
    files["package_directory_manifest"] = _write_json(directory / "package-directory-manifest.json", manifest)
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

    handoff = {
        "source": "run_bid_pipeline_cli",
        "directory": str(directory),
        "pipeline_status": str((result.get("pipeline") or {}).get("status") or ""),
        "next_action": str((result.get("pipeline") or {}).get("next_action") or ""),
        "next_agent_action_count": len(_rows(result.get("next_agent_actions"))),
        "completed_action_template_count": len(completed_templates),
        "package_download_count": len(_rows(manifest.get("entries"))),
        "generated_bid_package_count": len(generated_packages),
        "package_dir_command": str(manifest.get("package_dir_command") or ""),
        "files": files,
        "completed_action_files": completed_files,
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


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def _safe_filename(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:120] or "completed-action"


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
