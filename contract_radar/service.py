from __future__ import annotations

import base64
import binascii
import hashlib
import copy
import time
from datetime import date, datetime, timezone
from threading import Lock
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from contract_radar.agent_runtime import decorate_agent_session
from contract_radar import config
from contract_radar.models import EvaluatedOpportunity, PipelineMetrics
from contract_radar.profiles import profile_from_payload, supported_profiles

ProgressCallback = Callable[[dict[str, Any]], None]


class ContractRadarService:
    def __init__(self, document_storage_dir: Any | None = None) -> None:
        self._lock = Lock()
        self._last_scan: dict[str, Any] | None = None
        self._scan_result_cache: dict[str, dict[str, Any]] = {}
        self._data_bundle_cache: dict[str, Any] = {}
        self._rag_retriever_cache: dict[str, Any] = {}
        self._market_model_cache: dict[str, Any] = {}
        self._document_storage_dir = document_storage_dir
        self._document_analysis_sessions: dict[str, dict[str, Any]] = {}
        self._latest_document_analysis_by_opportunity: dict[str, str] = {}

    def health(self) -> dict[str, Any]:
        from contract_radar.briefs import brief_status
        from contract_radar.ranker import ranker_status, value_model_status

        briefs = brief_status()
        ranker = ranker_status()
        value_model = value_model_status()
        engine_story = (
            "Bid department engine is ready: source ingestion, fit gates, historical awards, "
            "pricing worksheet, capacity planning, and owner approval packets."
        )
        return {
            "status": "ok",
            "project": "Project Bid Bot",
            "labels": ["Pursue", "Review", "Monitor", "Skip"],
            "priority_modes": ["best_win_chance", "best_fit", "highest_value"],
            "supported_profiles": supported_profiles(),
            "briefs": briefs,
            "ranker": ranker,
            "value_model": value_model,
            "engine_story": engine_story,
            "endpoints": [
                "/api/inbox",
                "/api/scan",
                "/api/simulate",
                "/api/approve",
                "/api/documents/acquire",
                "/api/documents/analyze",
                "/api/compliance/resolve",
            ],
        }

    def scan(
        self,
        payload: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        from contract_radar.data import load_procurement_data
        from contract_radar.backtest import scorecard_from_evaluated
        from contract_radar.bid_pricing import attach_bid_pricing
        from contract_radar.history import summarize_past_opportunities
        from contract_radar.inbox import build_daily_bid_inbox
        from contract_radar.matcher import evaluate_opportunities, normalize_priority_mode
        from contract_radar.briefs import enrich_opportunity_briefs_with_stats
        from contract_radar.portfolio import optimize_bid_portfolio
        from contract_radar.precomputed import load_precomputed_scan
        from contract_radar.rag import attach_rag_evidence
        from contract_radar.ranker import apply_market_intelligence
        from contract_radar.revenue_simulation import attach_revenue_simulations

        start = time.perf_counter()
        stage_timings_ms: dict[str, int] = {}

        def emit(event: dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(event)

        def mark_stage(stage_name: str, stage_start: float) -> float:
            stage_timings_ms[stage_name] = int((time.perf_counter() - stage_start) * 1000)
            emit(
                {
                    "event": "stage",
                    "stage": stage_name,
                    "message": _scan_stage_message(stage_name),
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                }
            )
            return time.perf_counter()

        payload = payload or {}
        profile = profile_from_payload(payload)
        today = _payload_date(payload) or date.today()
        priority_mode = normalize_priority_mode(payload.get("priority_mode"))
        cache_key = _scan_result_cache_key(profile, priority_mode, today, payload)
        emit(
            {
                "event": "stage",
                "stage": "start",
                "message": f"Scanning Toronto contracts for {getattr(profile, 'label', 'this business')}.",
            }
        )
        if not bool(payload.get("refresh")):
            cached_scan = self._cached_scan_result(cache_key)
            if cached_scan is not None:
                cached_scan["daily_inbox"] = build_daily_bid_inbox(
                    cached_scan,
                    self._latest_analysis_sessions_by_opportunity(),
                )
                _emit_progress_matches(emit, cached_scan, stage="scan_result_cache", preliminary=False)
                with self._lock:
                    self._last_scan = copy.deepcopy(cached_scan)
                return cached_scan
            precomputed = load_precomputed_scan(profile.profile_id, priority_mode, today)
            if precomputed is not None:
                precomputed["daily_inbox"] = build_daily_bid_inbox(
                    precomputed,
                    self._latest_analysis_sessions_by_opportunity(),
                )
                _emit_progress_matches(emit, precomputed, stage="precomputed_scan", preliminary=False)
                with self._lock:
                    if _scan_result_cache_enabled():
                        self._scan_result_cache[cache_key] = copy.deepcopy(precomputed)
                    self._last_scan = precomputed
                return precomputed
        stage_start = time.perf_counter()
        data_bundle = self._data_bundle(refresh=bool(payload.get("refresh")))
        stage_start = mark_stage("load_data", stage_start)
        historical_summary = summarize_past_opportunities(profile, data_bundle.awards).to_dict()
        stage_start = mark_stage("summarize_history", stage_start)
        seen_progress_matches: set[str] = set()

        def on_evaluated(item: EvaluatedOpportunity, index: int, total: int) -> None:
            if item.label == "Skip" or len(seen_progress_matches) >= 10:
                return
            document_number = item.solicitation.document_number
            if document_number in seen_progress_matches:
                return
            seen_progress_matches.add(document_number)
            emit(
                {
                    "event": "match",
                    "stage": "evaluate_opportunities",
                    "message": f"Found {item.label} candidate {len(seen_progress_matches)} while checking {index} of {total}.",
                    "count": len(seen_progress_matches),
                    "checked": index,
                    "total": total,
                    "preliminary": True,
                    "opportunity": item.to_dict(),
                }
            )

        evaluated = evaluate_opportunities(
            profile,
            data_bundle.solicitations,
            data_bundle.awards,
            today=today,
            priority_mode=priority_mode,
            on_evaluated=on_evaluated,
        )
        stage_start = mark_stage("evaluate_opportunities", stage_start)
        evaluated = attach_rag_evidence(
            profile,
            evaluated,
            data_bundle.awards,
            retriever=self._rag_retriever_for(profile, data_bundle.awards),
        )
        stage_start = mark_stage("attach_rag_evidence", stage_start)
        market_model = self._market_model_for(profile, data_bundle.awards)
        stage_start = mark_stage("market_model", stage_start)
        evaluated = apply_market_intelligence(
            profile=profile,
            opportunities=evaluated,
            awards=data_bundle.awards,
            trained_model=market_model,
            today=today,
            priority_mode=priority_mode,
        )
        stage_start = mark_stage("apply_market_intelligence", stage_start)
        evaluated = attach_bid_pricing(profile, evaluated)
        stage_start = mark_stage("bid_pricing_engine", stage_start)
        evaluated = attach_revenue_simulations(profile, evaluated)
        stage_start = mark_stage("revenue_simulation", stage_start)
        evaluated = optimize_bid_portfolio(profile, evaluated, priority_mode=priority_mode)
        stage_start = mark_stage("portfolio_optimization", stage_start)
        top_inbox, watch_inbox = _contract_inbox_items(evaluated)
        _emit_progress_matches(
            emit,
            {"top_opportunities": [item.to_dict() for item in top_inbox], "watchlist": [item.to_dict() for item in watch_inbox]},
            stage="portfolio_optimization",
            preliminary=True,
        )
        extraction_candidates = [*top_inbox, *watch_inbox]
        enriched, brief_mode, brief_stats = enrich_opportunity_briefs_with_stats(profile, extraction_candidates)
        stage_start = mark_stage("listing_brief_enrichment", stage_start)
        enriched_by_doc = {item.solicitation.document_number: item for item in enriched}
        evaluated = [enriched_by_doc.get(item.solicitation.document_number, item) for item in evaluated]
        top_inbox, watch_inbox = _contract_inbox_items(evaluated)
        skipped = _prioritized_skips(evaluated)
        scorecard = scorecard_from_evaluated(profile, evaluated, historical_summary)
        mark_stage("scorecard", stage_start)
        metrics = _metrics(data_bundle, evaluated, start, brief_mode, brief_stats, market_model.summary)
        metrics_dict = metrics.to_dict()
        metrics_dict["stage_timings_ms"] = stage_timings_ms
        metrics_dict["priority_mode"] = priority_mode
        metrics_dict["rag_mode"] = _first_rag_mode(evaluated)
        metrics_dict["value_model_mode"] = (market_model.value_summary or {}).get("mode", "historical_average")
        metrics_dict["value_model_mae"] = (market_model.value_summary or {}).get("mae", 0.0)
        metrics_dict["value_model_mape"] = (market_model.value_summary or {}).get("mape", 0.0)
        metrics_dict["portfolio_mode"] = _first_portfolio_engine(evaluated)
        technical_depth_proof = _technical_depth_proof(metrics_dict, scorecard)
        result = {
            "business_profile": profile.to_dict(),
            "as_of": today.isoformat(),
            "priority_mode": priority_mode,
            "historical_summary": historical_summary,
            "top_opportunities": [item.to_dict() for item in top_inbox],
            "watchlist": [item.to_dict() for item in watch_inbox],
            "skipped": [item.to_dict() for item in skipped[:10]],
            "all_evaluated": [item.to_dict() for item in evaluated[:40]],
            "market_model": market_model.summary,
            "insight_scorecard": scorecard,
            "technical_depth_proof": technical_depth_proof,
            "metrics": metrics_dict,
        }
        result["daily_inbox"] = build_daily_bid_inbox(
            result,
            self._latest_analysis_sessions_by_opportunity(),
        )
        with self._lock:
            self._last_scan = result
            if _scan_result_cache_enabled():
                self._scan_result_cache[cache_key] = copy.deepcopy(result)
        return result

    def simulate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from contract_radar.simulator import simulate_month

        scan_result = self.scan(payload or {})
        timeline = simulate_month(scan_result, days=int((payload or {}).get("days") or 30))
        scan_result["timeline"] = timeline
        return scan_result

    def inbox(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        scan_result = self.scan(payload or {})
        return {
            "daily_inbox": scan_result.get("daily_inbox") or {},
            "business_profile": scan_result.get("business_profile") or {},
            "as_of": scan_result.get("as_of") or "",
            "priority_mode": scan_result.get("priority_mode") or "",
        }

    def acquire_document(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from contract_radar.acquisition import (
            FETCH_FAILED_STATUS,
            METADATA_ONLY_STATUS,
            acquisition_report,
            build_metadata_only_session,
            fetch_public_pdf,
            opportunity_metadata,
            public_pdf_candidates,
        )

        payload = payload or {}
        opportunity_id = str(payload.get("opportunity_id") or "").strip()
        if not opportunity_id:
            raise ValueError("Select a listing before starting document acquisition.")

        selected, scan_result = self._selected_opportunity_for_payload(payload, opportunity_id)
        if selected is None:
            raise ValueError(
                f"Selected listing {opportunity_id} is no longer available. Refresh matches and choose a current listing."
            )

        candidates = public_pdf_candidates(selected)
        last_error = ""
        for url in candidates:
            try:
                pdf_bytes = fetch_public_pdf(url)
            except ValueError as exc:
                last_error = str(exc)
                continue
            analysis = self.analyze_document(
                {
                    **payload,
                    "opportunity_id": opportunity_id,
                    "filename": _filename_from_url(url),
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )
            updated_at = _utc_now()
            analysis["opportunity_metadata"] = opportunity_metadata(selected)
            analysis["acquisition"] = acquisition_report(
                opportunity=selected,
                status="fetched",
                now=updated_at,
                candidate_public_package_urls=candidates,
                fetched_url=url,
            )
            analysis["updated_at"] = updated_at
            decorate_agent_session(
                analysis,
                action_types=["document_acquisition_checked"],
                now=updated_at,
            )
            with self._lock:
                self._document_analysis_sessions[str(analysis.get("analysis_id") or "")] = copy.deepcopy(analysis)
                self._latest_document_analysis_by_opportunity[opportunity_id] = str(analysis.get("analysis_id") or "")
            return copy.deepcopy(analysis)

        now = _utc_now()
        business_profile = (scan_result or {}).get("business_profile") or profile_from_payload(payload).to_dict()
        session = build_metadata_only_session(
            opportunity=selected,
            business_profile=business_profile,
            now=now,
        )
        if candidates and last_error:
            session["acquisition"] = acquisition_report(
                opportunity=selected,
                status=FETCH_FAILED_STATUS,
                now=now,
                candidate_public_package_urls=candidates,
                error=last_error,
            )
        else:
            session["acquisition"] = acquisition_report(
                opportunity=selected,
                status=METADATA_ONLY_STATUS,
                now=now,
                candidate_public_package_urls=candidates,
            )
        decorate_agent_session(
            session,
            action_types=[
                "open_data_metadata_loaded",
                "document_acquisition_checked",
                "evidence_ledger_created",
                "gate_rules_run",
                "tasks_generated",
            ],
            now=now,
        )
        with self._lock:
            self._document_analysis_sessions[str(session.get("analysis_id") or "")] = copy.deepcopy(session)
            self._latest_document_analysis_by_opportunity[opportunity_id] = str(session.get("analysis_id") or "")
        return copy.deepcopy(session)

    def analyze_document(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from contract_radar.compliance import extract_requirements, requirements_to_dicts
        from contract_radar.document_text import PDFTextExtractionError, extract_pdf_text_from_bytes
        from contract_radar.documents import DocumentStore

        payload = payload or {}
        filename = str(payload.get("filename") or "solicitation.pdf")
        opportunity_id = str(payload.get("opportunity_id") or "").strip()
        if not opportunity_id:
            raise ValueError("Select a listing before analyzing a PDF.")
        pdf_bytes = _decode_base64_pdf(payload.get("content_base64") or payload.get("file_base64"))
        metadata = DocumentStore(self._document_storage_dir).store_pdf(
            filename=filename,
            content=pdf_bytes,
            opportunity_id=opportunity_id,
        )
        try:
            chunks = extract_pdf_text_from_bytes(
                pdf_bytes,
                source_filename=metadata.filename,
                source_hash=metadata.content_hash,
            )
        except PDFTextExtractionError as exc:
            raise ValueError(str(exc)) from exc
        profile = profile_from_payload(payload)
        rows = extract_requirements(chunks, contractor_profile=profile)
        matrix = requirements_to_dicts(rows)
        summary = _compliance_summary(matrix)
        analysis_id = _analysis_id(opportunity_id, metadata.content_hash)
        created_at = _utc_now()
        session = {
            "analysis_id": analysis_id,
            "opportunity_id": opportunity_id,
            "document": metadata.to_dict(),
            "text": {
                "page_count": len(chunks),
                "character_count": sum(len(chunk.text) for chunk in chunks),
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
            "compliance_matrix": matrix,
            "compliance_summary": summary,
            "created_at": created_at,
        }
        decorate_agent_session(
            session,
            action_types=[
                "pdf_uploaded",
                "pdf_text_extracted",
                "requirements_extracted",
                "evidence_ledger_created",
                "gate_rules_run",
                "tasks_generated",
            ],
            now=created_at,
        )
        with self._lock:
            self._document_analysis_sessions[analysis_id] = copy.deepcopy(session)
            self._latest_document_analysis_by_opportunity[opportunity_id] = analysis_id
        return copy.deepcopy(session)

    def resolve_requirement(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from contract_radar.compliance import apply_requirement_resolution

        payload = payload or {}
        analysis_id = str(payload.get("analysis_id") or "").strip()
        requirement_id = str(payload.get("requirement_id") or "").strip()
        resolution_type = str(payload.get("resolution_type") or "").strip()
        note = str(payload.get("note") or "").strip()
        if not analysis_id:
            raise ValueError("An analysis_id is required to resolve a compliance item.")

        with self._lock:
            session = copy.deepcopy(self._document_analysis_sessions.get(analysis_id))
        if not session:
            raise ValueError(f"Compliance analysis {analysis_id} was not found.")

        matrix = apply_requirement_resolution(
            session.get("compliance_matrix") or [],
            requirement_id,
            resolution_type,
            note=note,
            resolved_at=_utc_now(),
        )
        updated_at = _utc_now()
        session["compliance_matrix"] = matrix
        session["compliance_summary"] = _compliance_summary(matrix)
        session["updated_at"] = updated_at
        decorate_agent_session(
            session,
            action_types=[
                "requirement_resolved",
                "evidence_ledger_created",
                "gate_rules_run",
                "tasks_generated",
            ],
            action_context={
                "requirement_id": requirement_id,
                "resolution_type": resolution_type,
            },
            now=updated_at,
        )
        with self._lock:
            self._document_analysis_sessions[analysis_id] = copy.deepcopy(session)
            self._latest_document_analysis_by_opportunity[str(session.get("opportunity_id") or "")] = analysis_id
        return copy.deepcopy(session)

    def approve(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from contract_radar.packet import create_approval_packet

        payload = payload or {}
        approved = bool(payload.get("approved"))
        opportunity_id = str(payload.get("opportunity_id") or "")
        selected, scan_result = self._selected_opportunity_for_payload(payload, opportunity_id)
        if selected is None:
            if opportunity_id:
                raise ValueError(
                    f"Selected listing {opportunity_id} is no longer available for bid notes. "
                    "Refresh matches and choose a current recommended listing."
                )
            raise ValueError("No recommended listing is available for bid notes.")
        analysis = self._analysis_for_approval(payload, opportunity_id)
        if analysis is None:
            raise ValueError("Analyze the official PDF before preparing bid notes.")
        decorate_agent_session(analysis)
        if analysis.get("bid_state") != "owner_packet_ready":
            raise ValueError("Resolve all deterministic agent tasks before preparing bid notes.")
        packet = create_approval_packet(
            scan_result["business_profile"],
            selected,
            approved,
            compliance_matrix=analysis.get("compliance_matrix") if analysis else None,
            compliance_summary=analysis.get("compliance_summary") if analysis else None,
            compliance_decision=analysis.get("compliance_decision") if analysis else None,
            agent_summary=analysis.get("agent_summary") if analysis else None,
            agent_gate_results=analysis.get("gate_results") if analysis else None,
            agent_evidence_ledger=analysis.get("evidence_ledger") if analysis else None,
            agent_action_trace=analysis.get("agent_actions") if analysis else None,
        )
        approved_at = _utc_now()
        analysis["updated_at"] = approved_at
        decorate_agent_session(
            analysis,
            action_types=["owner_packet_prepared"],
            action_context={"packet_id": packet.opportunity_id},
            now=approved_at,
        )
        with self._lock:
            self._document_analysis_sessions[str(analysis.get("analysis_id") or "")] = copy.deepcopy(analysis)
        return {"packet": packet.to_dict(), "approved": approved}

    def _selected_opportunity_for_payload(
        self,
        payload: dict[str, Any],
        opportunity_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        scan_result = self._last_scan
        opportunities = _approval_opportunities(scan_result or {})
        selected = _find_opportunity(opportunities, opportunity_id)
        if selected is not None:
            return selected, scan_result

        scan_result = self.scan(payload)
        opportunities = _approval_opportunities(scan_result)
        return _find_opportunity(opportunities, opportunity_id), scan_result

    def _latest_analysis_sessions_by_opportunity(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            latest = dict(self._latest_document_analysis_by_opportunity)
            sessions = {
                opportunity_id: copy.deepcopy(self._document_analysis_sessions.get(analysis_id))
                for opportunity_id, analysis_id in latest.items()
            }
        return {opportunity_id: session for opportunity_id, session in sessions.items() if isinstance(session, dict)}

    def _analysis_for_approval(self, payload: dict[str, Any], opportunity_id: str) -> dict[str, Any] | None:
        analysis_id = str(payload.get("analysis_id") or "").strip()
        with self._lock:
            if not analysis_id and opportunity_id:
                analysis_id = self._latest_document_analysis_by_opportunity.get(opportunity_id, "")
            session = copy.deepcopy(self._document_analysis_sessions.get(analysis_id)) if analysis_id else None
        if analysis_id and not session:
            raise ValueError(f"Compliance analysis {analysis_id} was not found. Re-analyze the PDF.")
        if session and str(session.get("opportunity_id") or "") != opportunity_id:
            raise ValueError("Compliance analysis does not match the selected listing.")
        return session

    def _market_model_for(self, profile: Any, awards: list[Any]) -> Any:
        from contract_radar.ranker import train_award_history_market_model

        key = _market_cache_key(profile, awards)
        with self._lock:
            cached = self._market_model_cache.get(key)
        if cached is not None:
            return cached

        trained = train_award_history_market_model(profile, awards)
        with self._lock:
            self._market_model_cache[key] = trained
        return trained

    def _data_bundle(self, refresh: bool) -> Any:
        from contract_radar.data import load_procurement_data

        if refresh:
            bundle = load_procurement_data(refresh=True)
            with self._lock:
                self._data_bundle_cache[_data_bundle_cache_key()] = bundle
            return bundle

        key = _data_bundle_cache_key()
        with self._lock:
            cached = self._data_bundle_cache.get(key)
        if cached is not None:
            return cached

        bundle = load_procurement_data(refresh=False)
        with self._lock:
            self._data_bundle_cache[key] = bundle
        return bundle

    def _rag_retriever_for(self, profile: Any, awards: list[Any]) -> Any:
        from contract_radar.rag import AwardRetriever

        key = _rag_retriever_cache_key(profile, awards)
        with self._lock:
            cached = self._rag_retriever_cache.get(key)
        if cached is not None:
            return cached

        retriever = AwardRetriever(profile, awards)
        with self._lock:
            self._rag_retriever_cache[key] = retriever
        return retriever

    def _cached_scan_result(self, cache_key: str) -> dict[str, Any] | None:
        if not _scan_result_cache_enabled():
            return None
        with self._lock:
            cached = self._scan_result_cache.get(cache_key)
        if cached is None:
            return None
        return _with_scan_cache_hit(cached)


def _payload_date(payload: dict[str, Any] | None) -> date | None:
    from contract_radar.models import parse_date

    return parse_date((payload or {}).get("as_of"))


def _decode_base64_pdf(value: Any) -> bytes:
    text = str(value or "").strip()
    if not text:
        raise ValueError("PDF content is required.")
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("PDF content must be base64 encoded.") from exc


def _analysis_id(opportunity_id: str, content_hash: str) -> str:
    seed = f"{opportunity_id}:{content_hash}:{time.time_ns()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"analysis-{digest}"


def _filename_from_url(url: str) -> str:
    name = unquote(urlparse(str(url or "")).path.rsplit("/", 1)[-1] or "").strip()
    if not name or not name.lower().endswith(".pdf"):
        return "official-package.pdf"
    return name


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compliance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    open_items: list[dict[str, Any]] = []
    resolved = 0
    detected = 0
    evidence_needed = 0
    capability_confirmed = 0
    capability_gap = 0
    uploaded_evidence = 0
    needs_review = 0
    for row in rows:
        category = str(row.get("category") or "other")
        by_category[category] = by_category.get(category, 0) + 1
        if row.get("requirement_detected"):
            detected += 1
        if row.get("resolved"):
            resolved += 1
        if row.get("business_has_capability") is True:
            capability_confirmed += 1
        if row.get("business_has_capability") is False:
            capability_gap += 1
        if row.get("uploaded_evidence"):
            uploaded_evidence += 1
        if row.get("evidence_needed"):
            evidence_needed += 1
        if not row.get("resolved"):
            if row.get("business_has_capability") is not False and not row.get("evidence_needed"):
                needs_review += 1
            open_items.append(row)
    total = len(rows)
    unresolved = total - resolved
    return {
        "total": total,
        "requirement_detected": detected,
        "resolved": resolved,
        "unresolved": unresolved,
        "evidence_needed": evidence_needed,
        "business_has_capability": capability_confirmed,
        "capability_gap": capability_gap,
        "uploaded_evidence": uploaded_evidence,
        "needs_review": needs_review,
        "by_category": by_category,
        "open_items": [
            {
                "requirement": str(row.get("requirement") or ""),
                "category": str(row.get("category") or ""),
                "evidence_needed": row.get("evidence_needed") or [],
                "business_has_capability": row.get("business_has_capability"),
                "resolved": bool(row.get("resolved")),
                "citation": row.get("citation") or {},
            }
            for row in open_items[:5]
        ],
        "ready_to_prepare": total > 0 and unresolved == 0 and capability_gap == 0,
    }


def _scan_stage_message(stage_name: str) -> str:
    messages = {
        "load_data": "Loaded Toronto open-data contracts and award history.",
        "summarize_history": "Checked past awards for this business lane.",
        "evaluate_opportunities": "First bid/no-bid pass is ready.",
        "attach_rag_evidence": "Pulled similar-award evidence for promising listings.",
        "market_model": "Prepared local award-history model.",
        "apply_market_intelligence": "Re-ranked matches with market signals.",
        "bid_pricing_engine": "Estimated bid ranges for the best matches.",
        "revenue_simulation": "Estimated revenue upside and risk.",
        "portfolio_optimization": "Checked bid workload and owner capacity.",
        "listing_brief_enrichment": "Built owner-ready listing briefs.",
        "scorecard": "Final proof and validation are ready.",
    }
    return messages.get(stage_name, stage_name.replace("_", " ").title())


def _emit_progress_matches(
    emit: ProgressCallback,
    scan_result: dict[str, Any],
    stage: str,
    preliminary: bool,
) -> None:
    top = scan_result.get("top_opportunities") or []
    watch = scan_result.get("watchlist") or []
    opportunities = [item for item in [*top, *watch] if isinstance(item, dict)][:10]
    if not opportunities:
        return
    emit(
        {
            "event": "matches",
            "stage": stage,
            "message": f"Showing {len(opportunities)} promising contract match(es) found so far.",
            "count": len(opportunities),
            "preliminary": preliminary,
            "opportunities": opportunities,
        }
    )


def _scan_result_cache_enabled() -> bool:
    return not config.env_flag(config.DISABLE_SCAN_RESULT_CACHE_ENV)


def _scan_result_cache_key(
    profile: Any,
    priority_mode: str,
    today: date,
    payload: dict[str, Any],
) -> str:
    key_payload = {
        "profile_id": getattr(profile, "profile_id", ""),
        "profile_fingerprint": _profile_fingerprint(profile),
        "priority_mode": priority_mode,
        "as_of": today.isoformat(),
        "offline": config.env_flag(config.OFFLINE_ENV),
        "row_limit": config.row_limit(),
        "precomputed": config.env_flag(config.USE_PRECOMPUTED_SCAN_ENV),
    }
    digest = hashlib.sha256(repr(sorted(key_payload.items())).encode("utf-8")).hexdigest()[:20]
    return f"scan:{digest}"


def _data_bundle_cache_key() -> str:
    key_payload = {
        "offline": config.env_flag(config.OFFLINE_ENV),
        "cache_dir": str(config.CACHE_DIR),
        "row_limit": config.row_limit(),
    }
    digest = hashlib.sha256(repr(sorted(key_payload.items())).encode("utf-8")).hexdigest()[:20]
    return f"data:{digest}"


def _rag_retriever_cache_key(profile: Any, awards: list[Any]) -> str:
    digest = hashlib.sha256()
    for award in awards[:20] + awards[-20:]:
        digest.update(str(getattr(award, "document_number", "")).encode("utf-8"))
        digest.update(str(getattr(award, "supplier", "")).encode("utf-8"))
        digest.update(str(getattr(award, "award_value", "")).encode("utf-8"))
    key_payload = {
        "industry_lane": getattr(profile, "profile_id", ""),
        "business_type": getattr(profile, "business_type", ""),
        "skills": tuple(getattr(profile, "skills", []) or []),
        "good_fit_examples": tuple(getattr(profile, "good_fit_examples", []) or []),
        "bad_fit_examples": tuple(getattr(profile, "bad_fit_examples", []) or []),
        "missing_capabilities": tuple(getattr(profile, "missing_capabilities", []) or []),
        "top_divisions": tuple(getattr(profile, "top_divisions", []) or []),
        "awards": f"{len(awards)}:{digest.hexdigest()[:16]}",
    }
    key_digest = hashlib.sha256(repr(sorted(key_payload.items())).encode("utf-8")).hexdigest()[:20]
    return f"rag:{key_digest}"


def _profile_fingerprint(profile: Any) -> str:
    payload = profile.to_dict() if hasattr(profile, "to_dict") else {
        name: getattr(profile, name, "")
        for name in (
            "profile_id",
            "label",
            "name",
            "business_type",
            "team_size",
            "max_contract_value",
            "max_sites_per_day",
            "active_pursuit_count",
            "max_active_pursuits",
            "skills",
            "ready_documents",
            "missing_capabilities",
            "top_divisions",
        )
    }
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()[:20]


def _with_scan_cache_hit(cached: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(cached)
    metrics = result.setdefault("metrics", {})
    metrics["scan_result_cache_hit"] = True
    warnings = metrics.setdefault("warnings", [])
    if isinstance(warnings, list):
        warnings.append("In-process scan result cache hit; reused the previous matching scan.")
    return result


def _metrics(
    data_bundle: Any,
    evaluated: list[EvaluatedOpportunity],
    start: float,
    brief_mode: str,
    brief_stats: dict[str, Any],
    market_summary: dict[str, Any],
) -> PipelineMetrics:
    label_counts: dict[str, int] = {}
    for item in evaluated:
        label_counts[item.label] = label_counts.get(item.label, 0) + 1
    runtime_ms = int((time.perf_counter() - start) * 1000)
    loaded_records = len(data_bundle.solicitations) + len(data_bundle.awards)
    runtime_seconds = max(runtime_ms / 1000, 0.001)
    shortlisted_for_brief = int(brief_stats.get("shortlisted_for_brief") or 0)
    model_calls_attempted = 0
    model_calls_successful = 0
    model_calls_avoided = max(0, len(evaluated) - shortlisted_for_brief)
    briefs_generated = int(brief_stats.get("briefs_generated") or 0)
    label_changes_after_extraction = 0
    shortlist_reduction_ratio = (
        1.0 - (shortlisted_for_brief / len(evaluated)) if evaluated else 0.0
    )
    warnings = list(getattr(data_bundle, "warnings", []))
    return PipelineMetrics(
        solicitations_loaded=len(data_bundle.solicitations),
        awards_loaded=len(data_bundle.awards),
        opportunities_evaluated=len(evaluated),
        rejected_count=label_counts.get("Skip", 0),
        top_candidate_count=label_counts.get("Pursue", 0),
        runtime_ms=runtime_ms,
        records_per_second=round(loaded_records / runtime_seconds, 2),
        shortlist_reduction_ratio=round(shortlist_reduction_ratio, 4),
        model_calls_attempted=model_calls_attempted,
        model_calls_successful=model_calls_successful,
        model_calls_avoided=model_calls_avoided,
        briefs_generated=briefs_generated,
        label_changes_after_extraction=label_changes_after_extraction,
        market_model_mode=str(market_summary.get("mode") or "sklearn_award_history"),
        market_model_examples=int(market_summary.get("examples") or 0),
        market_model_positive_examples=int(market_summary.get("positive_examples") or 0),
        market_model_precision_at_10=float(market_summary.get("precision_at_10") or 0.0),
        market_model_top_decile_lift=float(market_summary.get("top_decile_lift") or 0.0),
        market_model_average_precision=float(market_summary.get("average_precision") or 0.0),
        data_sources=data_bundle.source_status,
        label_counts=label_counts,
        engine=getattr(data_bundle, "engine", "python"),
        portfolio_mode=_first_portfolio_engine(evaluated),
        brief_mode=brief_mode,
        fetched_at=getattr(data_bundle, "fetched_at", ""),
        warnings=warnings,
    )


def _technical_depth_proof(metrics: dict[str, Any], scorecard: dict[str, Any]) -> list[str]:
    total_records = int(metrics.get("solicitations_loaded") or 0) + int(metrics.get("awards_loaded") or 0)
    reduction_percent = round(float(metrics.get("shortlist_reduction_ratio") or 0.0) * 100, 1)
    label_counts = metrics.get("label_counts") if isinstance(metrics.get("label_counts"), dict) else {}
    decision_mix = ", ".join(
        f"{label}={count}"
        for label, count in sorted(label_counts.items())
        if count
    ) or "decision labels pending"
    return [
        (
            "Pipeline: Toronto Open Data ingestion -> deterministic bid gates -> historical award "
            "retrieval -> bid brief generation -> value/fit models -> revenue simulation -> "
            "capacity planner -> approval packet."
        ),
        (
            f"Local scan processed {total_records:,} records and evaluated "
            f"{int(metrics.get('opportunities_evaluated') or 0):,} opportunities in "
            f"{int(metrics.get('runtime_ms') or 0):,} ms."
        ),
        (
            f"Shortlisting reduced bid-brief workload by {reduction_percent}% and avoided "
            f"{int(metrics.get('model_calls_avoided') or 0):,} low-value brief generation step(s)."
        ),
        (
            f"Award-history ML used {int(metrics.get('market_model_examples') or 0):,} examples, "
            f"precision@10 {float(metrics.get('market_model_precision_at_10') or 0.0):.2f}, "
            f"top-decile lift {float(metrics.get('market_model_top_decile_lift') or 0.0):.2f}x, "
            f"and value model MAPE {float(metrics.get('value_model_mape') or 0.0):.2f}."
        ),
        (
            f"Recommendations are grounded in {int(scorecard.get('similar_awards_grounded') or 0):,} "
            f"similar awards while skipping {int(scorecard.get('false_positives_skipped') or 0):,} "
            f"false-positive lookalike(s)."
        ),
        (
            f"Runtime path: {metrics.get('engine', 'python')}; RAG={metrics.get('rag_mode', 'unknown')}; "
            f"portfolio={metrics.get('portfolio_mode', 'greedy_capacity_optimizer')}; "
            f"briefs={metrics.get('brief_mode', 'deterministic_bid_brief')}; decision mix: {decision_mix}."
        ),
    ]


def _market_cache_key(profile: Any, awards: list[Any]) -> str:
    latest = max(
        (award.award_date.isoformat() for award in awards if getattr(award, "award_date", None)),
        default="no-date",
    )
    digest = hashlib.sha256()
    for award in awards[:20] + awards[-20:]:
        digest.update(str(getattr(award, "document_number", "")).encode("utf-8"))
        digest.update(str(getattr(award, "supplier", "")).encode("utf-8"))
        digest.update(str(getattr(award, "award_value", "")).encode("utf-8"))
    return f"{getattr(profile, 'profile_id', '')}:{len(awards)}:{latest}:{digest.hexdigest()[:16]}"


def _find_opportunity(opportunities: list[dict[str, Any]], opportunity_id: str) -> dict[str, Any] | None:
    if not opportunities:
        return None
    if not opportunity_id:
        return opportunities[0]
    for item in opportunities:
        solicitation = item.get("solicitation", {})
        if solicitation.get("document_number") == opportunity_id:
            return item
    return None


def _approval_opportunities(scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    groups = [
        scan_result.get("top_opportunities") or [],
        scan_result.get("watchlist") or [],
        scan_result.get("all_evaluated") or [],
    ]
    opportunities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [candidate for group in groups for candidate in group]:
        if not isinstance(item, dict) or item.get("label") == "Skip":
            continue
        solicitation = item.get("solicitation") or {}
        document_number = str(solicitation.get("document_number") or "")
        key = document_number or repr(item)
        if key in seen:
            continue
        seen.add(key)
        opportunities.append(item)
    return opportunities


def _prioritized_skips(evaluated: list[EvaluatedOpportunity]) -> list[EvaluatedOpportunity]:
    skipped = [item for item in evaluated if item.label == "Skip"]
    return sorted(
        skipped,
        key=lambda item: (
            item.days_until_deadline is not None and item.days_until_deadline < 0,
            -(item.rank_score or 0),
            item.days_until_deadline if item.days_until_deadline is not None else 9999,
            item.solicitation.document_number,
        ),
    )


def _contract_inbox_items(
    evaluated: list[EvaluatedOpportunity],
) -> tuple[list[EvaluatedOpportunity], list[EvaluatedOpportunity]]:
    top = [item for item in evaluated if item.label == "Pursue"][:5]
    watch = [item for item in evaluated if item.label in {"Review", "Monitor"}][:8]
    return top, watch


def _first_rag_mode(evaluated: list[EvaluatedOpportunity]) -> str:
    for item in evaluated:
        if item.rag_evidence and item.rag_evidence.mode:
            return item.rag_evidence.mode
    return "not_retrieved"


def _first_portfolio_engine(evaluated: list[EvaluatedOpportunity]) -> str:
    for item in evaluated:
        if item.portfolio_decision and item.portfolio_decision.engine:
            return item.portfolio_decision.engine
    return "greedy_fallback"
