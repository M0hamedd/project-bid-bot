from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_radar import config


STATE_FILENAME = "project_bid_bot_state.json"
SCHEMA_VERSION = 1


class LocalStateStore:
    def __init__(self, state_dir: Path | str | None = None) -> None:
        self.state_dir = Path(state_dir) if state_dir is not None else config.LOCAL_STATE_DIR
        self.state_path = self.state_dir / STATE_FILENAME

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _empty_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_state()
        if not isinstance(payload, dict):
            return _empty_state()
        return _normalized_state(payload)

    def save_scan(self, scan_result: dict[str, Any]) -> None:
        if not isinstance(scan_result, dict):
            return
        state = self.load()
        key = scan_key(scan_result)
        if key:
            state["scan_results"][key] = copy.deepcopy(scan_result)
            state["daily_inboxes"][key] = copy.deepcopy(scan_result.get("daily_inbox") or {})
            state["last_scan_key"] = key
        state["last_scan"] = copy.deepcopy(scan_result)
        self.save(state)

    def save_analysis(self, session: dict[str, Any]) -> None:
        if not isinstance(session, dict):
            return
        analysis_id = str(session.get("analysis_id") or "").strip()
        opportunity_id = str(session.get("opportunity_id") or "").strip()
        if not analysis_id:
            return
        state = self.load()
        state["document_analysis_sessions"][analysis_id] = copy.deepcopy(session)
        if opportunity_id:
            state["latest_document_analysis_by_opportunity"][opportunity_id] = analysis_id
        self.save(state)

    def save_packet(
        self,
        packet: dict[str, Any],
        *,
        analysis_id: str = "",
        opportunity_id: str = "",
    ) -> None:
        if not isinstance(packet, dict):
            return
        packet_id = _packet_key(packet, analysis_id=analysis_id, opportunity_id=opportunity_id)
        state = self.load()
        state["approval_packets"][packet_id] = {
            "packet_id": packet_id,
            "analysis_id": analysis_id,
            "opportunity_id": opportunity_id or str(packet.get("opportunity_id") or ""),
            "saved_at": _utc_now(),
            "packet": copy.deepcopy(packet),
        }
        self.save(state)

    def save_evidence(self, record: dict[str, Any]) -> None:
        if not isinstance(record, dict):
            return
        evidence_id = str(record.get("evidence_id") or "").strip()
        if not evidence_id:
            return
        state = self.load()
        state["evidence_vault"][evidence_id] = copy.deepcopy(record)
        self.save(state)

    def save(self, state: dict[str, Any]) -> None:
        payload = _normalized_state(state)
        payload["updated_at"] = _utc_now()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp_path.replace(self.state_path)


def scan_key(scan_result: dict[str, Any]) -> str:
    profile = scan_result.get("business_profile") if isinstance(scan_result.get("business_profile"), dict) else {}
    profile_id = str(profile.get("profile_id") or "unknown-profile").strip()
    as_of = str(scan_result.get("as_of") or "unknown-date").strip()
    priority_mode = str(scan_result.get("priority_mode") or "best_win_chance").strip()
    if not profile_id or not as_of:
        return ""
    return f"{profile_id}:{priority_mode}:{as_of}"


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": "",
        "last_scan_key": "",
        "last_scan": None,
        "scan_results": {},
        "daily_inboxes": {},
        "document_analysis_sessions": {},
        "latest_document_analysis_by_opportunity": {},
        "approval_packets": {},
        "evidence_vault": {},
    }


def _normalized_state(payload: dict[str, Any]) -> dict[str, Any]:
    state = _empty_state()
    state.update({key: value for key, value in payload.items() if key in state})
    state["schema_version"] = SCHEMA_VERSION
    for key in (
        "scan_results",
        "daily_inboxes",
        "document_analysis_sessions",
        "latest_document_analysis_by_opportunity",
        "approval_packets",
        "evidence_vault",
    ):
        if not isinstance(state.get(key), dict):
            state[key] = {}
    if state.get("last_scan") is not None and not isinstance(state.get("last_scan"), dict):
        state["last_scan"] = None
    return state


def _packet_key(packet: dict[str, Any], *, analysis_id: str, opportunity_id: str) -> str:
    base = str(packet.get("opportunity_id") or opportunity_id or "packet")
    timestamp = str(packet.get("approved_at") or packet.get("saved_at") or _utc_now())
    suffix = analysis_id or timestamp
    return f"{base}:{suffix}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
