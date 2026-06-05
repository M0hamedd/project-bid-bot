from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_agent_handoff(
    result: dict[str, Any],
    directory: str | Path,
    *,
    profile_id: str = "",
    source: str = "deterministic_agent_handoff_writer",
) -> dict[str, Any]:
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    completed_dir = output_dir / "completed-action-templates"
    completed_dir.mkdir(exist_ok=True)
    owner_approval_dir = output_dir / "owner-approval-requests"
    owner_approval_dir.mkdir(exist_ok=True)
    portal_request_dir = output_dir / "portal-package-requests"
    portal_request_dir.mkdir(exist_ok=True)
    submission_request_dir = output_dir / "portal-submission-requests"
    submission_request_dir.mkdir(exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(exist_ok=True)

    completed_templates = completed_action_templates(result.get("next_agent_actions"))
    owner_approval_requests = owner_approval_handoff_requests(result.get("approval_actions"))
    generated_packages = _rows(result.get("generated_bid_packages"))
    manifest = result.get("package_directory_manifest") if isinstance(result.get("package_directory_manifest"), dict) else {}
    portal_requests = _rows(result.get("portal_package_requests"))
    submission_requests = _rows(result.get("portal_submission_requests"))
    files: dict[str, str] = {}
    files["pipeline_summary"] = _write_json(output_dir / "pipeline-summary.json", result.get("pipeline") or {})
    files["next_agent_actions"] = _write_json(output_dir / "next-agent-actions.json", _rows(result.get("next_agent_actions")))
    files["completed_action_templates"] = _write_json(output_dir / "completed-action-templates.json", completed_templates)
    files["owner_approval_requests"] = _write_json(output_dir / "owner-approval-requests.json", owner_approval_requests)
    files["package_directory_manifest"] = _write_json(output_dir / "package-directory-manifest.json", manifest)
    files["portal_package_requests"] = _write_json(output_dir / "portal-package-requests.json", portal_requests)
    files["portal_submission_requests"] = _write_json(output_dir / "portal-submission-requests.json", submission_requests)
    files["generated_bid_packages"] = _write_json(output_dir / "generated-bid-packages.json", generated_packages)

    completed_files: list[dict[str, str]] = []
    for index, action in enumerate(completed_templates, start=1):
        action_id = str(action.get("action_id") or f"completed-action-{index}")
        path = completed_dir / f"{safe_filename(action_id)}.json"
        completed_files.append(
            {
                "action_id": action_id,
                "path": _write_json(path, action),
            }
        )

    owner_approval_files: list[dict[str, str]] = []
    for index, request in enumerate(owner_approval_requests, start=1):
        approval_request_id = str(request.get("approval_request_id") or f"owner-approval-request-{index}")
        path = owner_approval_dir / f"{safe_filename(approval_request_id)}.json"
        owner_approval_files.append(
            {
                "approval_request_id": approval_request_id,
                "path": _write_json(path, request),
            }
        )

    report_template_files: list[dict[str, str]] = []
    for request in owner_approval_requests:
        approval_request_id = str(request.get("approval_request_id") or "").strip()
        template = request.get("approval_report_template") if isinstance(request.get("approval_report_template"), dict) else {}
        if not approval_request_id or not template:
            continue
        path = reports_dir / f"owner-approval-report-{safe_filename(approval_request_id)}.json"
        report_template_files.append(
            {
                "report_type": "owner_approval_decision_report",
                "request_id": approval_request_id,
                "path": _write_json(path, fillable_report_template(template)),
            }
        )

    portal_request_files: list[dict[str, str]] = []
    for index, request in enumerate(portal_requests, start=1):
        request_id = str(request.get("request_id") or f"portal-package-request-{index}")
        path = portal_request_dir / f"{safe_filename(request_id)}.json"
        portal_request_files.append(
            {
                "request_id": request_id,
                "path": _write_json(path, request),
            }
        )
        template = request.get("completion_report_template") if isinstance(request.get("completion_report_template"), dict) else {}
        if template:
            report_path = reports_dir / f"portal-package-report-{safe_filename(request_id)}.json"
            report_template_files.append(
                {
                    "report_type": "portal_package_download_report",
                    "request_id": request_id,
                    "path": _write_json(report_path, fillable_report_template(template)),
                }
            )

    submission_request_files: list[dict[str, str]] = []
    for index, request in enumerate(submission_requests, start=1):
        request_id = str(request.get("request_id") or f"portal-submission-request-{index}")
        path = submission_request_dir / f"{safe_filename(request_id)}.json"
        submission_request_files.append(
            {
                "request_id": request_id,
                "path": _write_json(path, request),
            }
        )
        template = request.get("completion_report_template") if isinstance(request.get("completion_report_template"), dict) else {}
        if template:
            report_path = reports_dir / f"portal-submission-report-{safe_filename(request_id)}.json"
            report_template_files.append(
                {
                    "report_type": "portal_submission_preparation_report",
                    "request_id": request_id,
                    "path": _write_json(report_path, fillable_report_template(template)),
                }
            )

    files["report_templates"] = _write_json(output_dir / "report-templates.json", report_template_files)
    resume_command = "python scripts\\run_bid_pipeline.py"
    if profile_id:
        resume_command += f" --profile-id {quote_cli_arg(profile_id)}"
    resume_command += f" --resume-agent-work-dir {quote_cli_arg(str(output_dir))} --agent-work-dir {quote_cli_arg(str(output_dir))}"
    handoff = {
        "source": source,
        "directory": str(output_dir),
        "resume_agent_work_dir": str(output_dir),
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
        "report_template_count": len(report_template_files),
        "package_dir_command": str(manifest.get("package_dir_command") or ""),
        "files": files,
        "completed_action_files": completed_files,
        "owner_approval_request_files": owner_approval_files,
        "portal_package_request_files": portal_request_files,
        "portal_submission_request_files": submission_request_files,
        "report_template_files": report_template_files,
        "guardrails": [
            "These files are handoff artifacts for an agent or human operator.",
            "Completed action templates must still be filled with real facts or approvals before use.",
            "No bid was submitted by writing this handoff directory.",
        ],
    }
    handoff_path = output_dir / "agent-handoff.json"
    files["agent_handoff"] = str(handoff_path)
    _write_json(handoff_path, handoff)
    return handoff


def completed_action_templates(actions: Any) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for action in _rows(actions):
        template = action.get("completed_action_template")
        if isinstance(template, dict) and template:
            templates.append(template)
    return templates


def owner_approval_handoff_requests(actions: Any) -> list[dict[str, Any]]:
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
                "approval_payload": copy_json(action.get("approval_payload")),
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


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value else {}


def fillable_report_template(template: dict[str, Any]) -> dict[str, Any]:
    payload = copy_json(template)
    if isinstance(payload, dict):
        payload["template"] = True
    return payload


def safe_filename(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:120] or "completed-action"


def quote_cli_arg(value: str) -> str:
    value = str(value or "")
    if value and all(character not in value for character in " \t\""):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
