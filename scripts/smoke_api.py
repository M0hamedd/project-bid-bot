from __future__ import annotations

import argparse
import base64
import json
import sys
from typing import Any
from urllib import error, request


DEFAULT_BASE_URL = "http://127.0.0.1:8080"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test a running Project Bid Bot API. Start the app first with "
            "`python app.py`, then run this command."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL. Default: {DEFAULT_BASE_URL}")
    parser.add_argument("--timeout", type=float, default=20.0, help="Request timeout in seconds. Default: 20")
    parser.add_argument("--days", type=int, default=7, help="Simulation window for /api/simulate. Default: 7")
    parser.add_argument("--refresh", action="store_true", help="Ask /api/scan to refresh live Toronto data.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON result details.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    smoke = SmokeClient(base_url=base_url, timeout=args.timeout)

    try:
        health = smoke.get("/api/health")
        require(health.get("status") == "ok", "/api/health did not return status=ok")
        require("/api/scan" in health.get("endpoints", []), "/api/health did not advertise /api/scan")
        require("/api/agent/pipeline" in health.get("endpoints", []), "/api/health did not advertise /api/agent/pipeline")
        require("/api/daily/run" in health.get("endpoints", []), "/api/health did not advertise /api/daily/run")
        require("/api/pricing/input" in health.get("endpoints", []), "/api/health did not advertise /api/pricing/input")
        require("/api/pricing/approve" in health.get("endpoints", []), "/api/health did not advertise /api/pricing/approve")
        require("/api/packets/export" in health.get("endpoints", []), "/api/health did not advertise /api/packets/export")
        require("/api/outcomes/record" in health.get("endpoints", []), "/api/health did not advertise /api/outcomes/record")
        ok("GET /api/health", _health_summary(health))

        scan_payload = {"refresh": bool(args.refresh)}
        if not args.refresh:
            scan_payload["profile_id"] = "road_civil_infrastructure"
        scan = smoke.post("/api/scan", scan_payload)
        require(scan.get("business_profile"), "/api/scan missing business_profile")
        require(scan.get("metrics"), "/api/scan missing metrics")
        require(isinstance(scan.get("all_evaluated"), list), "/api/scan missing all_evaluated list")
        require_real_toronto_sources(scan)
        ok("POST /api/scan", _scan_summary(scan))

        daily = smoke.post("/api/daily/run", scan_payload)
        require(daily.get("daily_run"), "/api/daily/run missing daily_run")
        require(daily.get("daily_inbox"), "/api/daily/run missing daily_inbox")
        require(isinstance(daily.get("agent_task_state"), dict), "/api/daily/run missing agent_task_state")
        require(isinstance(daily.get("monitor_summary"), dict), "/api/daily/run missing monitor_summary")
        ok("POST /api/daily/run", _daily_run_summary(daily))

        pipeline_payload = dict(scan_payload)
        pipeline_payload["max_steps"] = 0
        pipeline = smoke.post("/api/agent/pipeline", pipeline_payload)
        require(pipeline.get("pipeline"), "/api/agent/pipeline missing pipeline summary")
        require(isinstance(pipeline.get("next_agent_actions"), list), "/api/agent/pipeline missing next_agent_actions")
        require("No bid was submitted." in (pipeline.get("pipeline") or {}).get("guardrails", []), "/api/agent/pipeline missing no-submit guardrail")
        ok("POST /api/agent/pipeline", (pipeline.get("pipeline") or {}).get("status") or "pipeline checked")

        simulate_payload = dict(scan_payload)
        simulate_payload["days"] = args.days
        simulate = smoke.post("/api/simulate", simulate_payload)
        require(isinstance(simulate.get("timeline"), list), "/api/simulate missing timeline list")
        require(simulate.get("metrics"), "/api/simulate missing metrics")
        ok("POST /api/simulate", f"{len(simulate.get('timeline') or [])} timeline events")

        opportunity_id = first_opportunity_id(scan)
        approve_result: dict[str, Any] | None = None
        if opportunity_id:
            if _has_ready_server_analysis(scan, opportunity_id):
                ok("POST /api/approve", "existing server-owned ready analysis found")
            else:
                smoke.expect_http_error(
                    "/api/approve",
                    {"approved": True, "opportunity_id": opportunity_id},
                    expected_status=400,
                    expected_text=["Analyze the official PDF", "Resolve all deterministic agent tasks"],
                )
                ok("POST /api/approve", "rejected before server-owned PDF analysis")

            analysis = smoke.post(
                "/api/documents/analyze",
                {
                    "profile_id": scan_payload.get("profile_id") or "road_civil_infrastructure",
                    "opportunity_id": opportunity_id,
                    "filename": "smoke-rfq.pdf",
                    "content_base64": _smoke_pdf_base64(),
                },
            )
            require(analysis.get("analysis_id"), "/api/documents/analyze missing analysis_id")
            require(analysis.get("submission_manifest"), "/api/documents/analyze missing submission_manifest")
            ok("POST /api/documents/analyze", f"analysis {analysis.get('analysis_id')}")

            analysis = resolve_analysis_tasks(smoke, analysis)
            require(
                analysis.get("bid_state") in {"requirements_resolved", "owner_packet_ready"},
                "/api/compliance/resolve did not produce a pricing-ready state",
            )
            ok("POST /api/compliance/resolve", "server-owned compliance gates resolved")

            if analysis.get("bid_state") != "owner_packet_ready":
                analysis = smoke.post(
                    "/api/pricing/approve",
                    {
                        "analysis_id": analysis.get("analysis_id"),
                        "approved_by": "Smoke Estimator",
                    },
                )
                require(
                    analysis.get("bid_state") == "owner_packet_ready",
                    "/api/pricing/approve did not produce owner_packet_ready state",
                )
                ok("POST /api/pricing/approve", "target bid approved")

            approve = smoke.post(
                "/api/approve",
                {
                    "approved": True,
                    "opportunity_id": opportunity_id,
                    "analysis_id": analysis.get("analysis_id"),
                },
            )
            packet = approve.get("packet") or {}
            require(approve.get("approved") is True, "/api/approve did not echo approved=true")
            require(packet.get("opportunity_id"), "/api/approve missing packet opportunity_id")
            require(packet.get("submission_manifest"), "/api/approve missing submission_manifest")
            packet_export = approve.get("packet_export") or {}
            require(packet_export.get("export_id"), "/api/approve missing packet_export export_id")
            require(
                "not_submitted_by_project_bid_bot" in str(packet_export.get("markdown") or ""),
                "/api/approve packet export missing non-submission warning",
            )
            export = smoke.post("/api/packets/export", {"packet_id": approve.get("packet_id")})
            require(
                (export.get("packet_export") or {}).get("export_id") == packet_export.get("export_id"),
                "/api/packets/export returned a different export",
            )
            markdown = smoke.get_text(packet_export.get("download_url") or "")
            require("Human submission required" in markdown, "packet Markdown download missing human warning")
            require("Agent Action Trace" in markdown, "packet Markdown download missing action trace")
            outcome = smoke.post(
                "/api/outcomes/record",
                {
                    "opportunity_id": packet.get("opportunity_id"),
                    "analysis_id": analysis.get("analysis_id"),
                    "submitted": True,
                    "award_status": "no_award_yet",
                    "final_bid_amount": (packet.get("pricing_worksheet") or {}).get("target_bid") or 0,
                    "hours_spent": 0.25,
                },
            )
            require(outcome.get("outcome"), "/api/outcomes/record missing outcome")
            require(
                (outcome.get("outcome_summary") or {}).get("total", 0) >= 1,
                "/api/outcomes/record missing outcome summary",
            )
            approve_result = {"opportunity_id": packet.get("opportunity_id"), "export_id": packet_export.get("export_id")}
            ok("POST /api/approve", f"packet for {packet.get('opportunity_id')}")
            ok("POST /api/outcomes/record", "submitted outcome recorded")
        else:
            ok("POST /api/approve", "skipped because scan returned no non-skipped opportunity")

        if args.json:
            print(
                json.dumps(
                    {
                        "base_url": base_url,
                        "health": {
                            "status": health.get("status"),
                            "briefs": health.get("briefs"),
                            "engine_story": health.get("engine_story"),
                        },
                        "scan": {
                            "profile": (scan.get("business_profile") or {}).get("name"),
                            "metrics": scan.get("metrics"),
                        },
                        "simulate": {"timeline_events": len(simulate.get("timeline") or [])},
                        "approve": approve_result or {"skipped": "no non-skipped opportunity"},
                    },
                    indent=2,
                )
            )
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL: could not reach {base_url}: {exc}", file=sys.stderr)
        print("Start the app with `python app.py` locally and retry.", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL: response was not JSON: {exc}", file=sys.stderr)
        return 1

    print("PASS: API smoke test completed")
    return 0


class SmokeFailure(RuntimeError):
    pass


class SmokeClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        with request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_text(self, path: str) -> str:
        with request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def expect_http_error(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        expected_status: int,
        expected_text: str | list[str],
    ) -> None:
        try:
            self.post(path, payload)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            expected = [expected_text] if isinstance(expected_text, str) else expected_text
            if exc.code != expected_status or not any(text in body for text in expected):
                raise SmokeFailure(
                    f"{path} returned {exc.code}, expected {expected_status} containing one of {expected!r}: {body}"
                ) from exc
            return
        raise SmokeFailure(f"{path} should have returned HTTP {expected_status}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def require_real_toronto_sources(scan: dict[str, Any]) -> None:
    metrics = scan.get("metrics") or {}
    data_sources = metrics.get("data_sources") or {}
    joined_sources = " ".join(str(value) for value in data_sources.values())
    require("dev_sample_only" not in joined_sources, "/api/scan used bundled dev sample data")
    for bucket in ("top_opportunities", "watchlist", "skipped", "all_evaluated"):
        for item in scan.get(bucket) or []:
            solicitation = item.get("solicitation") or {}
            source_links = solicitation.get("source_links") or {}
            document_number = str(solicitation.get("document_number") or "").strip()
            require(document_number, f"{bucket} item missing document number")
            require(
                source_links.get("is_sample_record") is False,
                f"{bucket} item {document_number} is a bundled sample fixture",
            )
            require(
                bool(source_links.get("open_data_record_url")),
                f"{bucket} item {document_number} missing Toronto Open Data verification link",
            )


def ok(step: str, detail: str) -> None:
    print(f"OK: {step} - {detail}")


def _health_summary(health: dict[str, Any]) -> str:
    briefs = health.get("briefs") or {}
    return (
        f"project={health.get('project', 'Project Bid Bot')}, "
        f"briefs={briefs.get('mode', 'unknown')}, "
        f"ranker={format_status(health.get('ranker'))}"
    )


def _scan_summary(scan: dict[str, Any]) -> str:
    profile = scan.get("business_profile") or {}
    metrics = scan.get("metrics") or {}
    return (
        f"profile={profile.get('name')}, "
        f"evaluated={metrics.get('opportunities_evaluated')}, "
        f"top={len(scan.get('top_opportunities') or [])}, "
        f"skipped={len(scan.get('skipped') or [])}, "
        f"brief_mode={metrics.get('brief_mode')}"
    )


def _daily_run_summary(result: dict[str, Any]) -> str:
    run = result.get("daily_run") or {}
    inbox = result.get("daily_inbox") or {}
    summary = inbox.get("summary") or {}
    run_summary = inbox.get("run_summary") or {}
    return (
        f"run={str(run.get('run_id') or '')[:18]}, "
        f"tasks={summary.get('total')}, "
        f"new={run_summary.get('new', 0)}, changed={run_summary.get('changed', 0)}, "
        f"source_changes={run_summary.get('change_events', 0)}"
    )


def format_status(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("mode") or value.get("status") or value.get("available") or "unknown")
    return str(value or "unknown")


def first_opportunity_id(scan: dict[str, Any]) -> str:
    for bucket in ("top_opportunities", "watchlist"):
        for item in scan.get(bucket) or []:
            if item.get("label") == "Skip":
                continue
            solicitation = item.get("solicitation") or {}
            document_number = str(solicitation.get("document_number") or "").strip()
            if document_number:
                return document_number
    return ""


def _has_ready_server_analysis(scan: dict[str, Any], opportunity_id: str) -> bool:
    analyses = scan.get("document_analyses") if isinstance(scan.get("document_analyses"), dict) else {}
    analysis = analyses.get(opportunity_id) if isinstance(analyses, dict) else {}
    return isinstance(analysis, dict) and analysis.get("bid_state") == "owner_packet_ready"


def resolve_analysis_tasks(smoke: SmokeClient, analysis: dict[str, Any]) -> dict[str, Any]:
    current = dict(analysis)
    for _ in range(8):
        tasks = current.get("agent_tasks") or []
        if not tasks:
            return current
        task = tasks[0]
        if task.get("task_type") == "approve_pricing":
            return current
        options = task.get("resolution_options") or []
        require(options, f"task {task.get('task_id')} has no deterministic resolution options")
        current = smoke.post(
            "/api/compliance/resolve",
            {
                "analysis_id": current.get("analysis_id"),
                "requirement_id": task.get("requirement_id"),
                "resolution_type": options[0].get("type"),
            },
        )
    raise SmokeFailure("analysis still had open agent tasks after 8 deterministic resolutions")


def _smoke_pdf_base64() -> str:
    try:
        import fitz
    except ImportError as exc:
        raise SmokeFailure("PyMuPDF is required for smoke PDF generation. Install requirements.txt.") from exc

    document = fitz.open()
    try:
        for text in (
            "A mandatory site meeting must be attended by all bidders.",
            "Bidders shall submit the completed pricing form with unit prices.",
        ):
            page = document.new_page(width=420, height=160)
            page.insert_text((36, 48), text, fontsize=11)
        return base64.b64encode(document.tobytes()).decode("ascii")
    finally:
        document.close()


if __name__ == "__main__":
    raise SystemExit(main())
