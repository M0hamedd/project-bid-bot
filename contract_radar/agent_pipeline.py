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
    loop_payload.pop("completed_actions", None)
    loop_payload.pop("action_payloads", None)

    applied_actions, action_application_errors, applied_generated_packets = _apply_completed_actions(service, payload)
    loop = service.run_until_approval(loop_payload)
    owner_requests = _rows(loop.get("owner_approval_requests"))
    selected_ids = _selected_approval_ids(payload, owner_requests)
    generated_packets: list[dict[str, Any]] = list(applied_generated_packets)
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
    package_directory_manifest = _package_directory_manifest(human_resolution_actions)
    portal_package_requests = _portal_package_requests(package_directory_manifest)
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
        errors=[*action_application_errors, *loop_errors, *approval_errors],
    )
    return {
        "source": SOURCE,
        "pipeline": {
            "pipeline_id": _pipeline_id(started_at, finished_at, owner_requests, generated_packets),
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "next_action": _next_action(status, approval_actions, human_actions, [*action_application_errors, *loop_errors, *approval_errors]),
            "approval_request_count": len(owner_requests),
            "applied_action_count": len(applied_actions),
            "generated_packet_count": len(generated_packets),
            "human_action_count": len(human_actions),
            "package_download_count": len(package_directory_manifest.get("entries") or []),
            "portal_package_request_count": len(portal_package_requests),
            "error_count": len(action_application_errors) + len(approval_errors) + int((loop.get("agent_loop") or {}).get("error_count") or 0),
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
        "applied_actions": applied_actions,
        "approval_actions": approval_actions,
        "pending_approval_actions": pending_approval_actions,
        "human_resolution_actions": human_resolution_actions,
        "generated_packet_actions": generated_packet_actions,
        "package_directory_manifest": package_directory_manifest,
        "portal_package_requests": portal_package_requests,
        "generated_packets": generated_packets,
        "generated_bid_packages": [
            copy.deepcopy(item.get("generated_bid_package") or {})
            for item in generated_packets
            if isinstance(item.get("generated_bid_package"), dict) and item.get("generated_bid_package")
        ],
        "packet_exports": [
            dict(item.get("packet_export") or {})
            for item in generated_packets
            if isinstance(item.get("packet_export"), dict) and item.get("packet_export")
        ],
        "approval_errors": approval_errors,
        "action_application_errors": action_application_errors,
        "errors": [*action_application_errors, *loop_errors, *approval_errors],
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


def _apply_completed_actions(service: Any, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    applied: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    generated_packets: list[dict[str, Any]] = []
    for index, action in enumerate(_completed_actions(payload), start=1):
        endpoint = _action_endpoint(action)
        action_payload = _action_payload(action)
        action_id = str(action.get("action_id") or action.get("completed_action_id") or f"completed-action-{index}")
        handler = _completed_action_handler(service, endpoint)
        if handler is None:
            errors.append(
                {
                    "action_id": action_id,
                    "endpoint": endpoint,
                    "error": "Unsupported completed action endpoint.",
                    "source": "completed_action_application",
                }
            )
            continue
        try:
            result = handler(action_payload)
            generated_packet = _packet_result(result) if endpoint == "/api/owner-approval/approve" else {}
            if generated_packet:
                generated_packets.append(generated_packet)
            applied.append(
                {
                    "action_id": action_id,
                    "endpoint": endpoint,
                    "method": "POST",
                    "status": "applied",
                    "output_ids": _action_output_ids(endpoint, result),
                    "result_summary": _action_result_summary(endpoint, result),
                    "generated_packet_id": str(generated_packet.get("packet_id") or ""),
                    "guardrails": [
                        "Applied through a bounded deterministic pipeline action.",
                        "No bid was submitted.",
                        "No buyer email was sent.",
                    ],
                }
            )
        except ValueError as exc:
            errors.append(
                {
                    "action_id": action_id,
                    "endpoint": endpoint,
                    "error": str(exc),
                    "source": "completed_action_application",
                }
            )
    return applied, errors, generated_packets


def _completed_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions = payload.get("completed_actions")
    if actions is None:
        actions = payload.get("action_payloads")
    return _rows(actions)


def _action_endpoint(action: dict[str, Any]) -> str:
    endpoint = str(action.get("endpoint") or "").strip()
    if endpoint:
        return endpoint
    action_type = str(action.get("action_type") or "").strip()
    return {
        "complete_company_profile": "/api/company/complete-profile",
        "record_pricing_input": "/api/pricing/input",
        "record_line_item_rate": "/api/pricing/line-item-rate",
        "approve_pricing": "/api/pricing/approve",
        "approve_owner_request": "/api/owner-approval/approve",
        "owner_approval": "/api/owner-approval/approve",
        "owner_approval_required": "/api/owner-approval/approve",
        "resolve_requirement": "/api/compliance/resolve",
        "resolve_compliance": "/api/compliance/resolve",
        "reanalyze_official_package": "/api/documents/recheck",
        "analyze_document": "/api/documents/analyze",
        "upload_evidence": "/api/evidence/upload",
        "attach_evidence": "/api/compliance/attach-evidence",
    }.get(action_type, "")


def _action_payload(action: dict[str, Any]) -> dict[str, Any]:
    action_payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    if action_payload:
        return copy.deepcopy(action_payload)
    ignored = {"action_id", "completed_action_id", "action_type", "endpoint", "method", "payload"}
    return {key: copy.deepcopy(value) for key, value in action.items() if key not in ignored}


def _completed_action_handler(service: Any, endpoint: str) -> Any:
    method_name = {
        "/api/company/complete-profile": "complete_company_profile",
        "/api/pricing/input": "record_pricing_input",
        "/api/pricing/line-item-rate": "record_pricing_line_item_rate",
        "/api/pricing/approve": "approve_pricing",
        "/api/owner-approval/approve": "approve_owner_request",
        "/api/compliance/resolve": "resolve_requirement",
        "/api/documents/recheck": "recheck_document",
        "/api/documents/analyze": "analyze_document",
        "/api/evidence/upload": "upload_evidence",
        "/api/compliance/attach-evidence": "attach_evidence_to_requirement",
    }.get(endpoint)
    if not method_name:
        return None
    return getattr(service, method_name, None)


def _action_output_ids(endpoint: str, result: dict[str, Any]) -> list[str]:
    candidates = [
        result.get("analysis_id"),
        result.get("evidence_id"),
        result.get("pricing_input_id"),
        result.get("pricing_line_item_rate_id"),
        result.get("packet_id"),
        (result.get("owner_approval_request") or {}).get("approval_request_id") if isinstance(result.get("owner_approval_request"), dict) else "",
        (result.get("pricing_approval") or {}).get("approval_id") if isinstance(result.get("pricing_approval"), dict) else "",
        (result.get("business_profile") or {}).get("profile_id") if isinstance(result.get("business_profile"), dict) else "",
    ]
    return [str(item) for item in candidates if str(item or "").strip()]


def _action_result_summary(endpoint: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "analysis_id": str(result.get("analysis_id") or ""),
        "opportunity_id": str(result.get("opportunity_id") or ""),
        "bid_state": str(result.get("bid_state") or ""),
        "packet_id": str(result.get("packet_id") or ""),
        "packet_export_id": str((result.get("packet_export") or {}).get("export_id") or "") if isinstance(result.get("packet_export"), dict) else "",
        "owner_approval_request_id": str((result.get("owner_approval_request") or {}).get("approval_request_id") or "") if isinstance(result.get("owner_approval_request"), dict) else "",
        "profile_id": str((result.get("business_profile") or {}).get("profile_id") or "") if isinstance(result.get("business_profile"), dict) else "",
        "evidence_id": str(result.get("evidence_id") or ""),
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
    completed_action = {
        "action_id": f"completed-owner-approval-{approval_request_id}",
        "endpoint": str(request.get("approval_endpoint") or "/api/owner-approval/approve"),
        "payload": {
            "approval_request_id": approval_request_id,
            "approved": True,
            "approved_by": "Owner",
            "note": "",
        },
    }
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
        "completed_action_template": completed_action,
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
    payload_template = _payload_template_for_human_action(action, required)
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
        "acquisition_status": str(action.get("acquisition_status") or ""),
        "acquisition_guidance": copy.deepcopy(action.get("acquisition_guidance") or {}) if isinstance(action.get("acquisition_guidance"), dict) else {},
        "endpoint": endpoint,
        "method": "POST" if endpoint else "",
        "required_payload": required,
        "payload_template": payload_template,
        "completed_action_template": _completed_action_template_for_human_action(action, endpoint, payload_template),
        "cli_command": _human_cli_command(action),
        "guardrails": [
            "Use only source-backed facts, uploaded evidence, or explicit human approvals.",
            "Do not invent missing capabilities, prices, documents, or buyer confirmations.",
            "Run the pipeline again after this action is completed.",
        ],
    }


def _package_directory_manifest(human_resolution_actions: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for action in human_resolution_actions:
        required = action.get("required_payload") if isinstance(action.get("required_payload"), dict) else {}
        if str(action.get("endpoint") or "") != "/api/documents/analyze":
            continue
        if required.get("manual_file_required") is not True:
            continue
        opportunity_id = str(action.get("opportunity_id") or "").strip()
        if not opportunity_id:
            continue
        filename = f"{opportunity_id}__official-package.pdf"
        guidance = action.get("acquisition_guidance") if isinstance(action.get("acquisition_guidance"), dict) else {}
        entries.append(
            {
                "opportunity_id": opportunity_id,
                "analysis_id": str(action.get("analysis_id") or ""),
                "task_id": str(action.get("task_id") or ""),
                "task_type": str(action.get("task_type") or ""),
                "title": str(action.get("title") or ""),
                "reason": str(action.get("reason") or ""),
                "recommended_filename": filename,
                "required_filename_pattern": "OPPORTUNITY_ID__anything.pdf",
                "package_file_argument": f"{opportunity_id}=<download-dir>\\{filename}",
                "package_file_command": f"python scripts\\run_bid_pipeline.py --package-file {opportunity_id}=<download-dir>\\{filename}",
                "package_dir_command": "python scripts\\run_bid_pipeline.py --package-dir <download-dir>",
                "portal_url": str(guidance.get("portal_url") or ""),
                "search_hint": str(guidance.get("search_hint") or ""),
                "expected_documents": [str(item) for item in guidance.get("expected_documents") or [] if str(item).strip()],
                "instructions": [str(item) for item in guidance.get("instructions") or [] if str(item).strip()],
            }
        )
    return {
        "source": "deterministic_package_directory_manifest",
        "status": "packages_needed" if entries else "no_package_downloads_needed",
        "entry_count": len(entries),
        "directory_naming_convention": "OPPORTUNITY_ID__anything.pdf",
        "package_dir_command": "python scripts\\run_bid_pipeline.py --package-dir <download-dir>" if entries else "",
        "entries": entries,
        "guardrails": [
            "Use only official buyer package PDFs.",
            "Do not rename unrelated files as official packages.",
            "The pipeline will analyze PDFs through the bounded /api/documents/analyze action.",
        ],
    }


def _portal_package_requests(package_directory_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for entry in _rows(package_directory_manifest.get("entries")):
        opportunity_id = str(entry.get("opportunity_id") or "").strip()
        recommended_filename = str(entry.get("recommended_filename") or "").strip()
        if not opportunity_id or not recommended_filename:
            continue
        request_id = _portal_package_request_id(entry)
        package_file_path = f"<download-dir>\\{recommended_filename}"
        package_file_command = str(
            entry.get("package_file_command")
            or f"python scripts\\run_bid_pipeline.py --package-file {opportunity_id}={package_file_path}"
        )
        package_dir_command = str(
            entry.get("package_dir_command")
            or package_directory_manifest.get("package_dir_command")
            or "python scripts\\run_bid_pipeline.py --package-dir <download-dir>"
        )
        portal_url = str(entry.get("portal_url") or "").strip()
        search_hint = str(entry.get("search_hint") or f"Search {opportunity_id}").strip()
        expected_documents = [
            str(item).strip()
            for item in entry.get("expected_documents") or []
            if str(item).strip()
        ] or [f"{opportunity_id} official solicitation package"]
        requests.append(
            {
                "request_id": request_id,
                "source": "deterministic_portal_package_request",
                "status": "download_required",
                "opportunity_id": opportunity_id,
                "analysis_id": str(entry.get("analysis_id") or ""),
                "task_id": str(entry.get("task_id") or ""),
                "task_type": str(entry.get("task_type") or ""),
                "title": str(entry.get("title") or "Download official package"),
                "reason": str(entry.get("reason") or "Official solicitation package is required before compliance analysis."),
                "portal_url": portal_url,
                "search_hint": search_hint,
                "expected_documents": expected_documents,
                "download_target": {
                    "directory": "<download-dir>",
                    "filename": recommended_filename,
                    "path": package_file_path,
                    "required_filename_pattern": str(entry.get("required_filename_pattern") or "OPPORTUNITY_ID__anything.pdf"),
                    "accepted_extensions": [".pdf"],
                    "accepted_content_types": ["application/pdf"],
                },
                "browser_agent_steps": _portal_browser_steps(
                    opportunity_id=opportunity_id,
                    portal_url=portal_url,
                    search_hint=search_hint,
                    expected_documents=expected_documents,
                    package_file_path=package_file_path,
                ),
                "completion_criteria": [
                    "Downloaded file exists at the requested path.",
                    "Downloaded file is the official buyer solicitation package or package bundle.",
                    "Downloaded file is a PDF, not an award notice, summary page, or unrelated attachment.",
                    "Filename preserves the opportunity id prefix so the pipeline can bind it to the listing.",
                ],
                "resume": {
                    "package_report_endpoint": "/api/agent/package-report",
                    "package_file_command": package_file_command,
                    "package_dir_command": package_dir_command,
                    "package_report_command": "python scripts\\run_bid_pipeline.py --portal-package-report-file <report.json>",
                    "package_report_payload_template": {
                        "profile_id": "<profile-id>",
                        "resume_pipeline": True,
                        "max_steps": 8,
                        "portal_package_report": {
                            "source": "portal_package_download_report",
                            "request_id": request_id,
                            "opportunity_id": opportunity_id,
                            "status": "downloaded",
                            "downloaded_files": [
                                {
                                    "path": package_file_path,
                                    "document_type": "solicitation_package",
                                    "is_primary_package": True,
                                    "source_url": portal_url,
                                    "notes": "",
                                }
                            ],
                            "notes": "",
                        },
                    },
                    "completed_action_template": {
                        "action_id": f"completed-package-upload-{opportunity_id}",
                        "endpoint": "/api/documents/analyze",
                        "payload": {
                            "opportunity_id": opportunity_id,
                            "profile_id": "<profile-id>",
                            "filename": recommended_filename,
                            "content_base64": "<base64-pdf-content>",
                        },
                    },
                },
                "completion_report_template": {
                    "source": "portal_package_download_report",
                    "request_id": request_id,
                    "opportunity_id": opportunity_id,
                    "status": "downloaded",
                    "downloaded_files": [
                        {
                            "path": package_file_path,
                            "document_type": "solicitation_package",
                            "is_primary_package": True,
                            "source_url": portal_url,
                            "notes": "",
                        }
                    ],
                    "notes": "",
                },
                "guardrails": [
                    "Use only official buyer/source documents for this opportunity.",
                    "Do not bypass buyer authentication, terms, payment, or access controls.",
                    "Do not submit, certify, upload final bid files, or email the buyer.",
                    "If the portal requires a human login or purchase step, stop and return this request as human-required.",
                ],
            }
        )
    return requests


def _portal_browser_steps(
    *,
    opportunity_id: str,
    portal_url: str,
    search_hint: str,
    expected_documents: list[str],
    package_file_path: str,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if portal_url:
        steps.append(
            {
                "step_id": "open_portal",
                "action": "open_url",
                "target": portal_url,
                "required": True,
            }
        )
    steps.extend(
        [
            {
                "step_id": "authenticate_if_prompted",
                "action": "use_existing_session_or_request_human_login",
                "required": True,
                "stop_if_credentials_needed": True,
            },
            {
                "step_id": "find_opportunity",
                "action": "search_or_filter",
                "query": search_hint or opportunity_id,
                "required": True,
            },
            {
                "step_id": "download_package_documents",
                "action": "download_matching_documents",
                "expected_documents": expected_documents,
                "required": True,
            },
            {
                "step_id": "save_primary_pdf",
                "action": "save_file_as",
                "path": package_file_path,
                "required": True,
            },
            {
                "step_id": "resume_pipeline",
                "action": "run_resume_command",
                "command": f"python scripts\\run_bid_pipeline.py --package-file {opportunity_id}={package_file_path}",
                "required": True,
            },
        ]
    )
    return steps


def _portal_package_request_id(entry: dict[str, Any]) -> str:
    import hashlib

    key = "|".join(
        [
            str(entry.get("opportunity_id") or ""),
            str(entry.get("task_id") or ""),
            str(entry.get("portal_url") or ""),
            str(entry.get("recommended_filename") or ""),
        ]
    )
    return f"portal-package-request-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _generated_packet_action(packet: dict[str, Any]) -> dict[str, Any]:
    download_url = str(packet.get("download_url") or "")
    opportunity_id = str(packet.get("opportunity_id") or "")
    generated = packet.get("generated_bid_package") if isinstance(packet.get("generated_bid_package"), dict) else {}
    return {
        "action_id": f"next-action-download-packet-{packet.get('packet_id') or opportunity_id}",
        "action_type": "download_packet_and_submit_manually",
        "status": "packet_generated",
        "opportunity_id": opportunity_id,
        "analysis_id": str(packet.get("analysis_id") or ""),
        "packet_id": str(packet.get("packet_id") or ""),
        "generated_bid_package_id": str(generated.get("generated_bid_package_id") or ""),
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
        "generated_bid_package": _generated_bid_package(packet, packet_export, approval_request),
        "guardrails": [
            "Packet prepared from server-owned analysis state.",
            "No bid was submitted.",
            "Human buyer-portal submission is still required.",
        ],
    }


def _generated_bid_package(
    packet: dict[str, Any],
    packet_export: dict[str, Any],
    approval_request: dict[str, Any],
) -> dict[str, Any]:
    pricing = packet.get("pricing_worksheet") if isinstance(packet.get("pricing_worksheet"), dict) else {}
    assembly = packet.get("submission_assembly") if isinstance(packet.get("submission_assembly"), dict) else {}
    assembly_summary = assembly.get("summary") if isinstance(assembly.get("summary"), dict) else {}
    manifest_summary = (
        packet.get("submission_manifest_summary")
        if isinstance(packet.get("submission_manifest_summary"), dict)
        else {}
    )
    form_blueprint = packet.get("form_blueprint") if isinstance(packet.get("form_blueprint"), dict) else {}
    export_id = str(packet_export.get("export_id") or "")
    packet_id = str(packet_export.get("packet_id") or approval_request.get("packet_id") or "")
    opportunity_id = str(packet.get("opportunity_id") or approval_request.get("opportunity_id") or "")
    return {
        "generated_bid_package_id": _generated_package_id(packet_id, export_id, opportunity_id),
        "source": "server_owned_generated_bid_package",
        "status": _generated_package_status(packet, assembly, manifest_summary),
        "approval_request_id": str(approval_request.get("approval_request_id") or ""),
        "opportunity_id": opportunity_id,
        "analysis_id": str(packet_export.get("analysis_id") or approval_request.get("analysis_id") or ""),
        "packet_id": packet_id,
        "title": str(packet.get("title") or opportunity_id),
        "owner_ready": bool(packet.get("owner_ready")),
        "export": _compact_export(packet_export),
        "pricing": _pricing_summary(pricing),
        "submission_manifest_summary": copy.deepcopy(manifest_summary),
        "submission_manifest_open_items": _open_manifest_items(packet.get("submission_manifest")),
        "submission_assembly_summary": {
            "assembly_id": str(assembly.get("assembly_id") or ""),
            "status": str(assembly.get("status") or ""),
            "ready_for_human_submission": bool(assembly.get("ready_for_human_submission")),
            "human_submission_required": bool(assembly.get("human_submission_required", True)),
            "prefilled_field_count": int(assembly_summary.get("prefilled_fields") or len(_rows(assembly.get("prefilled_fields")))),
            "attachment_count": int(assembly_summary.get("attachments") or len(_rows(assembly.get("attachments")))),
            "portal_step_count": len(_rows(assembly.get("portal_steps"))),
            "final_check_count": len([item for item in assembly.get("final_checks") or [] if str(item or "").strip()]),
            "warning": str(assembly.get("warning") or ""),
        },
        "form_blueprint_summary": _form_blueprint_summary(form_blueprint),
        "prefilled_fields": _prefilled_fields(assembly, form_blueprint),
        "attachment_manifest": _attachment_manifest(assembly, form_blueprint),
        "portal_steps": _portal_steps(assembly, form_blueprint),
        "final_human_checks": [str(item).strip() for item in assembly.get("final_checks") or [] if str(item).strip()],
        "guardrails": [
            "No bid was submitted by Project Bid Bot.",
            "No buyer email was sent by Project Bid Bot.",
            "Human buyer-portal upload, certification, and final submission are still required.",
            "Use only source-backed fields and attached packet/export artifacts.",
        ],
    }


def _generated_package_status(
    packet: dict[str, Any],
    assembly: dict[str, Any],
    manifest_summary: dict[str, Any],
) -> str:
    if not packet.get("owner_ready"):
        return "owner_review_required"
    if int(manifest_summary.get("required_open") or 0) > 0:
        return "submission_items_open"
    if assembly.get("ready_for_human_submission"):
        return "ready_for_human_submission"
    return "packet_generated_review_required"


def _generated_package_id(packet_id: str, export_id: str, opportunity_id: str) -> str:
    import hashlib

    key = repr((packet_id, export_id, opportunity_id))
    return f"generated-bid-package-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _compact_export(packet_export: dict[str, Any]) -> dict[str, Any]:
    return {
        "export_id": str(packet_export.get("export_id") or ""),
        "filename": str(packet_export.get("filename") or ""),
        "download_url": str(packet_export.get("download_url") or ""),
        "content_type": str(packet_export.get("content_type") or ""),
        "created_at": str(packet_export.get("created_at") or ""),
        "storage_path": str(packet_export.get("storage_path") or ""),
    }


def _pricing_summary(pricing: dict[str, Any]) -> dict[str, Any]:
    approval = pricing.get("estimator_approval") if isinstance(pricing.get("estimator_approval"), dict) else {}
    return {
        "target_bid": _money(pricing.get("target_bid")),
        "low_bid": _money(pricing.get("low_bid")),
        "high_bid": _money(pricing.get("high_bid")),
        "confidence": str(pricing.get("confidence") or ""),
        "status": str(pricing.get("status") or ""),
        "estimator_approval_status": str(pricing.get("estimator_approval_status") or ""),
        "approved_by": str(approval.get("approved_by") or ""),
        "approved_at": str(approval.get("approved_at") or ""),
        "pricing_line_item_count": len(_rows(pricing.get("pricing_line_items"))),
        "can_use_for_owner_packet": bool(pricing.get("can_use_for_owner_packet")),
    }


def _open_manifest_items(value: Any) -> list[dict[str, Any]]:
    rows = []
    for row in _rows(value):
        status = str(row.get("status") or "")
        if status == "ready":
            continue
        rows.append(
            {
                "manifest_id": str(row.get("manifest_id") or ""),
                "item_type": str(row.get("item_type") or ""),
                "label": str(row.get("label") or row.get("item_type") or ""),
                "status": status,
                "reason": str(row.get("reason") or ""),
                "required": bool(row.get("required")),
            }
        )
    return rows[:20]


def _form_blueprint_summary(form_blueprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "blueprint_id": str(form_blueprint.get("blueprint_id") or ""),
        "ready_for_form_work": bool(form_blueprint.get("ready_for_form_work")),
        "field_count": len(_rows(form_blueprint.get("form_fields"))),
        "attachment_count": len(_rows(form_blueprint.get("attachments"))),
        "blocker_count": len(_rows(form_blueprint.get("blockers"))),
        "guardrails": [str(item) for item in form_blueprint.get("guardrails") or [] if str(item).strip()],
    }


def _prefilled_fields(assembly: dict[str, Any], form_blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    fields = _rows(form_blueprint.get("form_fields")) or _rows(assembly.get("prefilled_fields"))
    output: list[dict[str, Any]] = []
    for field in fields[:40]:
        output.append(
            {
                "field_id": str(field.get("field_id") or ""),
                "label": str(field.get("label") or field.get("field_id") or ""),
                "value": str(field.get("value") or ""),
                "status": str(field.get("status") or ""),
                "source": str(field.get("source") or field.get("source_type") or ""),
            }
        )
    return output


def _attachment_manifest(assembly: dict[str, Any], form_blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = _rows(form_blueprint.get("attachments")) or _rows(assembly.get("attachments"))
    output: list[dict[str, Any]] = []
    for item in attachments[:60]:
        output.append(
            {
                "attachment_id": str(item.get("attachment_id") or ""),
                "item_type": str(item.get("item_type") or ""),
                "label": str(item.get("label") or item.get("item_type") or ""),
                "filename": str(item.get("filename") or ""),
                "status": str(item.get("status") or ""),
                "required": bool(item.get("required")),
                "evidence_ids": [str(value) for value in item.get("evidence_ids") or [] if str(value).strip()],
                "source": str(item.get("source") or ""),
            }
        )
    return output


def _portal_steps(assembly: dict[str, Any], form_blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _rows(form_blueprint.get("manual_steps")) or _rows(assembly.get("portal_steps"))
    output: list[dict[str, Any]] = []
    for index, step in enumerate(steps[:30], start=1):
        output.append(
            {
                "sequence": int(step.get("sequence") or index),
                "step_id": str(step.get("step_id") or step.get("portal_step_id") or ""),
                "label": str(step.get("label") or step.get("title") or ""),
                "instruction": str(step.get("instruction") or ""),
                "actor": str(step.get("actor") or ""),
                "status": str(step.get("status") or ""),
            }
        )
    return output


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


def _completed_action_template_for_human_action(
    action: dict[str, Any],
    endpoint: str,
    payload_template: dict[str, Any],
) -> dict[str, Any]:
    if not endpoint:
        return {}
    task_type = str(action.get("task_type") or "human-input").strip() or "human-input"
    action_id = "completed-" + "-".join(
        item
        for item in [
            task_type.replace("_", "-"),
            str(action.get("opportunity_id") or "").strip(),
            str(action.get("analysis_id") or "").strip(),
            str(action.get("source_requirement_id") or "").strip(),
        ]
        if item
    )
    return {
        "action_id": action_id,
        "endpoint": endpoint,
        "payload": copy.deepcopy(payload_template),
    }


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


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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
