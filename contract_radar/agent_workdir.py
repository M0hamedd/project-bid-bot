from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from contract_radar.owner_approval_reports import is_unfilled_template, owner_approval_actions
from contract_radar.package_reports import (
    package_report_payload,
    portal_package_reports,
    report_package_path_value,
    validate_package_pdf_path,
)
from contract_radar.submission_reports import portal_submission_reports


DEFAULT_PROFILE_ID = "road_civil_infrastructure"


def load_agent_workdir_artifacts(
    value: Any,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
) -> dict[str, Any]:
    directories = agent_work_dirs(value)
    completed_actions = _dedupe_completed_actions(
        [
            *_completed_action_dirs(directories),
            *_owner_approval_report_dirs(directories),
            *_portal_package_report_dirs(directories, profile_id=profile_id),
            *_agent_work_package_actions(directories, profile_id=profile_id),
        ]
    )
    submission_reports = _dedupe_portal_submission_reports(_portal_submission_report_dirs(directories))
    return {
        "source": "agent_workdir_artifact_loader",
        "work_dirs": [str(path) for path in directories],
        "completed_actions": completed_actions,
        "portal_submission_reports": submission_reports,
        "summary": {
            "work_dir_count": len(directories),
            "completed_action_count": len(completed_actions),
            "portal_submission_report_count": len(submission_reports),
        },
    }


def agent_work_dirs(value: Any) -> list[Path]:
    raw_values: list[Any]
    if isinstance(value, (str, Path)):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []

    output: list[Path] = []
    seen: set[str] = set()
    for raw in raw_values:
        path_value = str(raw or "").strip()
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
    if not output:
        raise ValueError("At least one agent work directory is required.")
    return output


def _completed_action_dirs(directories: list[Path]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.json")):
            for action in _completed_actions_from_json_file(path):
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                output.append(action)
    return output


def _completed_actions_from_json_file(path: Path) -> list[dict[str, Any]]:
    payload = _read_json_payload(path)
    if isinstance(payload, dict):
        return [payload] if _is_completed_action_object(payload) else []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and _is_completed_action_object(item)]
    return []


def _is_completed_action_object(value: dict[str, Any]) -> bool:
    return bool(str(value.get("endpoint") or value.get("action_type") or "").strip())


def _owner_approval_report_dirs(directories: list[Path]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.json")):
            for action in owner_approval_actions(_read_json_payload(path), skip_templates=True):
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                output.append(action)
    return output


def _portal_package_report_dirs(directories: list[Path], *, profile_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.json")):
            payload = _read_json_payload(path)
            reports = portal_package_reports(payload)
            for report in reports:
                if _is_unfilled_portal_package_report_template(report):
                    continue
                report_payload = package_report_payload(report, profile_id=profile_id, base_dir=path.parent)
                action = _package_action_from_report_payload(report_payload)
                key = _completed_action_key(action)
                if key in seen:
                    continue
                seen.add(key)
                output.append(action)
    return output


def _agent_work_package_actions(directories: list[Path], *, profile_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
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
            output.append(_package_file_action(opportunity_id=opportunity_id, path=path, profile_id=profile_id))
    return output


def _portal_submission_report_dirs(directories: list[Path]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.rglob("*.json")):
            for report in portal_submission_reports(_read_json_payload(path)):
                if is_unfilled_template(report):
                    continue
                key = _portal_submission_report_key(report)
                if key in seen:
                    continue
                seen.add(key)
                output.append(report)
    return output


def _is_unfilled_portal_package_report_template(report: dict[str, Any]) -> bool:
    if is_unfilled_template(report):
        return True
    path_value = report_package_path_value(report)
    return "<" in path_value or ">" in path_value


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


def _opportunity_id_from_package_filename(path: Path) -> str:
    stem = path.stem
    if "__" not in stem:
        raise ValueError(f"Package directory PDF must be named OPPORTUNITY_ID__anything.pdf: {path.name}")
    opportunity_id = stem.split("__", 1)[0].strip()
    if not opportunity_id:
        raise ValueError(f"Package directory PDF is missing an opportunity id: {path.name}")
    return opportunity_id


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


def _completed_action_key(value: dict[str, Any]) -> str:
    action_id = str(value.get("action_id") or value.get("completed_action_id") or "").strip()
    if action_id:
        return f"id:{action_id}"
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


def _portal_submission_report_key(value: dict[str, Any]) -> str:
    report_id = str(value.get("report_id") or "").strip()
    if report_id:
        return f"id:{report_id}"
    request_id = str(value.get("request_id") or "").strip()
    if request_id:
        return f"request:{request_id}"
    return "payload:" + json.dumps(value, sort_keys=True, default=str)


def _read_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))
