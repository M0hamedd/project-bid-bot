from __future__ import annotations

import copy
import shlex
from datetime import datetime, timezone
from typing import Any


SOURCE = "deterministic_agent_pipeline"


def run_agent_pipeline(service: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the agent from deal discovery to owner approval handoff or packet generation."""
    payload = copy.deepcopy(payload or {})
    started_at = _utc_now()
    loop_payload = copy.deepcopy(payload)
    loop_payload.pop("approval_request_id", None)
    loop_payload.pop("approval_request_ids", None)
    loop_payload.pop("approve_all_owner_requests", None)
    loop_payload.pop("approved_by", None)
    loop_payload.pop("approval_note", None)
    loop_payload.pop("note", None)

    loop = service.run_until_approval(loop_payload)
    owner_requests = _rows(loop.get("owner_approval_requests"))
    selected_ids = _selected_approval_ids(payload, owner_requests)
    generated_packets: list[dict[str, Any]] = []
    approval_errors: list[dict[str, Any]] = []
    loop_errors = _rows((loop.get("agent_loop") or {}).get("errors"))

    for approval_request_id in selected_ids:
        try:
            approved = service.approve_owner_request(
                {
                    "approval_request_id": approval_request_id,
                    "approved": True,
                    "approved_by": str(payload.get("approved_by") or "Owner"),
                    "note": str(payload.get("approval_note") or payload.get("note") or ""),
                }
            )
            generated_packets.append(_packet_result(approved))
        except ValueError as exc:
            approval_errors.append(
                {
                    "approval_request_id": approval_request_id,
                    "error": str(exc),
                    "source": "owner_approval_execution",
                }
            )

    finished_at = _utc_now()
    approval_actions = [_approval_action(item) for item in owner_requests]
    human_actions = _rows(loop.get("human_required_actions"))
    generated_packet_actions = [_generated_packet_action(item) for item in generated_packets]
    human_resolution_actions = [_human_resolution_action(item, loop) for item in human_actions]
    generated_approval_ids = {
        str(item.get("approval_request_id") or "")
        for item in generated_packets
        if str(item.get("approval_request_id") or "")
    }
    pending_approval_actions = [
        action
        for action in approval_actions
        if str(action.get("approval_request_id") or "") not in generated_approval_ids
    ]
    next_agent_actions = [
        *pending_approval_actions,
        *human_resolution_actions,
        *generated_packet_actions,
    ]
    status = _pipeline_status(
        generated_packets=generated_packets,
        owner_requests=owner_requests,
        human_actions=human_actions,
        errors=[*loop_errors, *approval_errors],
    )
    return {
        "source": SOURCE,
        "pipeline": {
            "pipeline_id": _pipeline_id(started_at, finished_at, owner_requests, generated_packets),
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "next_action": _next_action(status, approval_actions, human_actions, [*loop_errors, *approval_errors]),
            "approval_request_count": len(owner_requests),
            "generated_packet_count": len(generated_packets),
            "human_action_count": len(human_actions),
            "error_count": len(approval_errors) + int((loop.get("agent_loop") or {}).get("error_count") or 0),
            "next_agent_action_count": len(next_agent_actions),
            "mode": "find_deals_advance_safe_tasks_request_approval_generate_packets",
            "guardrails": [
                "No bid was submitted.",
                "No buyer email was sent.",
                "No owner approval was inferred.",
                "Packets are generated only for current server-owned owner approval request ids.",
                "Buyer portal upload, certification, and final submission remain human actions.",
            ],
        },
        "next_agent_actions": next_agent_actions,
        "approval_actions": approval_actions,
        "pending_approval_actions": pending_approval_actions,
        "human_resolution_actions": human_resolution_actions,
        "generated_packet_actions": generated_packet_actions,
        "generated_packets": generated_packets,
        "packet_exports": [
            dict(item.get("packet_export") or {})
            for item in generated_packets
            if isinstance(item.get("packet_export"), dict) and item.get("packet_export")
        ],
        "approval_errors": approval_errors,
        "errors": [*loop_errors, *approval_errors],
        "agent_loop": loop.get("agent_loop") or {},
        "agent_run": loop.get("agent_run") or {},
        "daily_inbox": loop.get("daily_inbox") or {},
        "daily_run": loop.get("daily_run") or {},
        "document_analyses": loop.get("document_analyses") or {},
        "owner_approval_requests": owner_requests,
        "human_required_actions": human_actions,
        "business_profile": loop.get("business_profile") or {},
        "scan": loop.get("scan") or {},
        "as_of": loop.get("as_of") or "",
        "priority_mode": loop.get("priority_mode") or "",
    }


def _selected_approval_ids(payload: dict[str, Any], owner_requests: list[dict[str, Any]]) -> list[str]:
    available = {
        str(item.get("approval_request_id") or "").strip()
        for item in owner_requests
        if str(item.get("approval_request_id") or "").strip()
    }
    requested = []
    if payload.get("approval_request_id"):
        requested.append(str(payload.get("approval_request_id") or "").strip())
    for value in _string_list(payload.get("approval_request_ids")):
        if str(value or "").strip():
            requested.append(str(value or "").strip())
    if payload.get("approve_all_owner_requests") is True:
        requested.extend(sorted(available))

    selected: list[str] = []
    for approval_request_id in requested:
        if approval_request_id and approval_request_id not in selected:
            selected.append(approval_request_id)
    unknown = [approval_request_id for approval_request_id in selected if approval_request_id not in available]
    if unknown:
        raise ValueError(
            "Approval request ids are not current or not pending: "
            + ", ".join(unknown)
        )
    return selected


def _approval_action(request: dict[str, Any]) -> dict[str, Any]:
    approval_request_id = str(request.get("approval_request_id") or "")
    command = _approval_command(approval_request_id)
    return {
        "action_id": f"next-action-owner-approval-{approval_request_id}",
        "action_type": "owner_approval_required",
        "status": "requires_owner_approval",
        "approval_request_id": approval_request_id,
        "opportunity_id": str(request.get("opportunity_id") or ""),
        "analysis_id": str(request.get("analysis_id") or ""),
        "title": str(request.get("title") or ""),
        "deadline": str(request.get("deadline") or ""),
        "target_bid": (request.get("pricing") or {}).get("target_bid"),
        "reason": "Owner approval is required before the packet can be generated.",
        "approval_endpoint": str(request.get("approval_endpoint") or "/api/owner-approval/approve"),
        "endpoint": str(request.get("approval_endpoint") or "/api/owner-approval/approve"),
        "method": "POST",
        "approval_payload": copy.deepcopy(request.get("approval_payload") or {}),
        "payload_template": copy.deepcopy(request.get("approval_payload") or {}),
        "cli_command": command,
        "resume_pipeline_command": _pipeline_approval_command(approval_request_id),
        "citation_count": len([item for item in request.get("citations") or [] if isinstance(item, dict)]),
        "guardrails": copy.deepcopy(request.get("guardrails") or []),
    }


def _human_resolution_action(action: dict[str, Any], loop: dict[str, Any]) -> dict[str, Any]:
    task_type = str(action.get("task_type") or "")
    required = _required_payload_for_human_action(action)
    endpoint = str(required.get("endpoint") or "")
    opportunity_id = str(action.get("opportunity_id") or "")
    analysis_id = str(action.get("analysis_id") or "")
    task_id = _task_id_for_human_action(action, loop)
    return {
        "action_id": f"next-action-human-{task_type or 'task'}-{opportunity_id or analysis_id or task_id}",
        "action_type": "human_input_required",
        "status": str(action.get("status") or "waiting_on_human_input"),
        "task_type": task_type,
        "task_id": task_id,
        "opportunity_id": opportunity_id,
        "analysis_id": analysis_id,
        "title": str(action.get("title") or task_type or "Resolve required bid task"),
        "reason": str(action.get("blocker") or action.get("title") or "Human-supplied facts or approval are required."),
        "endpoint": endpoint,
        "method": "POST" if endpoint else "",
        "required_payload": required,
        "payload_template": _payload_template_for_human_action(action, required),
        "cli_command": _human_cli_command(action),
        "guardrails": [
            "Use only source-backed facts, uploaded evidence, or explicit human approvals.",
            "Do not invent missing capabilities, prices, documents, or buyer confirmations.",
            "Run the pipeline again after this action is completed.",
        ],
    }


def _generated_packet_action(packet: dict[str, Any]) -> dict[str, Any]:
    download_url = str(packet.get("download_url") or "")
    opportunity_id = str(packet.get("opportunity_id") or "")
    return {
        "action_id": f"next-action-download-packet-{packet.get('packet_id') or opportunity_id}",
        "action_type": "download_packet_and_submit_manually",
        "status": "packet_generated",
        "opportunity_id": opportunity_id,
        "analysis_id": str(packet.get("analysis_id") or ""),
        "packet_id": str(packet.get("packet_id") or ""),
        "title": "Download generated owner packet",
        "reason": "The packet is generated, but buyer portal upload, certification, and final submission are human actions.",
        "endpoint": download_url,
        "method": "GET" if download_url else "",
        "download_url": download_url,
        "payload_template": {},
        "guardrails": copy.deepcopy(packet.get("guardrails") or []),
    }


def _packet_result(result: dict[str, Any]) -> dict[str, Any]:
    packet = result.get("packet") if isinstance(result.get("packet"), dict) else {}
    packet_export = result.get("packet_export") if isinstance(result.get("packet_export"), dict) else {}
    approval_request = (
        result.get("owner_approval_request")
        if isinstance(result.get("owner_approval_request"), dict)
        else {}
    )
    return {
        "approval_request_id": str(approval_request.get("approval_request_id") or ""),
        "opportunity_id": str(packet.get("opportunity_id") or approval_request.get("opportunity_id") or ""),
        "analysis_id": str(packet.get("analysis_id") or approval_request.get("analysis_id") or ""),
        "packet_id": str(result.get("packet_id") or ""),
        "packet_export": copy.deepcopy(packet_export),
        "download_url": str(packet_export.get("download_url") or ""),
        "owner_ready": bool(packet.get("owner_ready")),
        "human_submission_required": bool((packet.get("submission_assembly") or {}).get("human_submission_required", True)),
        "guardrails": [
            "Packet prepared from server-owned analysis state.",
            "No bid was submitted.",
            "Human buyer-portal submission is still required.",
        ],
    }


def _pipeline_status(
    *,
    generated_packets: list[dict[str, Any]],
    owner_requests: list[dict[str, Any]],
    human_actions: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> str:
    if errors:
        return "error"
    if generated_packets:
        return "packets_generated"
    if owner_requests:
        return "awaiting_owner_approval"
    if human_actions:
        return "waiting_on_human_input"
    return "no_ready_packets"


def _next_action(
    status: str,
    approval_actions: list[dict[str, Any]],
    human_actions: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> str:
    if status == "packets_generated":
        return "Download the packet export, then complete final human buyer-portal submission."
    if status == "awaiting_owner_approval" and approval_actions:
        return f"Ask owner to approve {approval_actions[0]['approval_request_id']} before packet generation."
    if status == "waiting_on_human_input" and human_actions:
        return str(human_actions[0].get("next_action") or human_actions[0].get("task_type") or "Resolve required human action.")
    if status == "error" and errors:
        return str(errors[0].get("error") or errors[0].get("message") or errors[0].get("detail") or "Resolve pipeline error.")
    return "No approval-ready packets were found; review the daily inbox for blockers."


def _approval_command(approval_request_id: str) -> str:
    if not approval_request_id:
        return ""
    return " ".join(
        [
            "python",
            "scripts\\approve_owner_request.py",
            "--approval-request-id",
            shlex.quote(approval_request_id),
            "--approved-by",
            "Owner",
        ]
    )


def _pipeline_approval_command(approval_request_id: str) -> str:
    if not approval_request_id:
        return ""
    return " ".join(
        [
            "python",
            "scripts\\run_bid_pipeline.py",
            "--approval-request-id",
            shlex.quote(approval_request_id),
            "--approved-by",
            "Owner",
        ]
    )


def _human_cli_command(action: dict[str, Any]) -> str:
    task_type = str(action.get("task_type") or "")
    analysis_id = str(action.get("analysis_id") or "")
    if task_type == "approve_pricing" and analysis_id:
        return " ".join(
            [
                "curl",
                "-X",
                "POST",
                "http://127.0.0.1:8080/api/pricing/approve",
                "-H",
                shlex.quote("Content-Type: application/json"),
                "-d",
                shlex.quote(f'{{"analysis_id":"{analysis_id}","approved_by":"Estimator"}}'),
            ]
        )
    return ""


def _required_payload_for_human_action(action: dict[str, Any]) -> dict[str, Any]:
    task_type = str(action.get("task_type") or "")
    if task_type == "complete_company_profile":
        return {
            "endpoint": "/api/company/complete-profile",
            "required": ["profile_id", "profile_facts"],
            "optional": ["analysis_id", "business_profile"],
            "profile_missing_facts": action.get("profile_missing_facts") or [],
        }
    if task_type == "record_pricing_input":
        return {
            "endpoint": "/api/pricing/input",
            "required": ["analysis_id", "input_type", "value"],
            "optional": ["line_item_id", "unit", "note", "created_by"],
        }
    if task_type == "approve_pricing":
        return {
            "endpoint": "/api/pricing/approve",
            "required": ["analysis_id", "approved_by"],
            "optional": ["target_bid", "note"],
            "approval_required": True,
        }
    if task_type in {"resolve_requirement", "resolve_compliance"}:
        return {
            "endpoint": "/api/compliance/resolve",
            "required": ["analysis_id", "requirement_id", "resolution_type"],
            "optional": ["note"],
            "requirement_id": str(action.get("source_requirement_id") or ""),
        }
    if task_type in {"acquire_official_package", "upload_official_package"}:
        return {
            "endpoint": "/api/documents/analyze",
            "required": ["opportunity_id", "filename", "content_base64"],
            "optional": ["profile_id", "business_profile"],
            "manual_file_required": True,
        }
    if task_type == "reanalyze_official_package":
        return {
            "endpoint": "/api/documents/recheck",
            "required": ["analysis_id", "opportunity_id"],
            "optional": ["profile_id", "business_profile"],
        }
    return {
        "endpoint": "",
        "required": [],
        "optional": ["note"],
    }


def _payload_template_for_human_action(action: dict[str, Any], required: dict[str, Any]) -> dict[str, Any]:
    task_type = str(action.get("task_type") or "")
    template: dict[str, Any] = {}
    for key in required.get("required") or []:
        template[str(key)] = ""
    if action.get("opportunity_id"):
        template["opportunity_id"] = str(action.get("opportunity_id") or "")
    if action.get("analysis_id"):
        template["analysis_id"] = str(action.get("analysis_id") or "")
    if action.get("source_requirement_id"):
        template["requirement_id"] = str(action.get("source_requirement_id") or "")
    if task_type == "approve_pricing":
        template["approved_by"] = "Estimator"
    if task_type in {"resolve_requirement", "resolve_compliance"}:
        template["resolution_type"] = "capability_confirmed"
    if task_type == "record_pricing_input":
        template["created_by"] = "Estimator"
    return template


def _task_id_for_human_action(action: dict[str, Any], loop: dict[str, Any]) -> str:
    opportunity_id = str(action.get("opportunity_id") or "")
    analysis_id = str(action.get("analysis_id") or "")
    task_type = str(action.get("task_type") or "")
    for task in _rows((loop.get("scan") or {}).get("current_agent_tasks")):
        if task_type and str(task.get("task_type") or "") != task_type:
            continue
        if opportunity_id and str(task.get("opportunity_id") or "") != opportunity_id:
            continue
        if analysis_id and str(task.get("analysis_id") or "") != analysis_id:
            continue
        return str(task.get("task_id") or "")
    return str(action.get("task_id") or "")


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item or "") for item in value]


def _pipeline_id(
    started_at: str,
    finished_at: str,
    owner_requests: list[dict[str, Any]],
    generated_packets: list[dict[str, Any]],
) -> str:
    import hashlib

    key = repr(
        (
            started_at,
            finished_at,
            [item.get("approval_request_id") for item in owner_requests],
            [item.get("packet_id") for item in generated_packets],
        )
    )
    return f"agent-pipeline-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
