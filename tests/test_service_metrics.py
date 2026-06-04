from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contract_radar import config
from contract_radar.precomputed import write_precomputed_scan
from contract_radar.service import ContractRadarService


class ServiceMetricsTests(unittest.TestCase):
    def test_health_and_scan_expose_judging_metrics(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CONTRACT_RADAR_OFFLINE": "1",
                "CONTRACT_RADAR_ALLOW_SAMPLE_DATA": "1",
            },
            clear=False,
        ):
            service = ContractRadarService()
            health = service.health()
            scan = service.scan({})

        self.assertEqual(health["project"], "Project Bid Bot")
        self.assertIn("briefs", health)
        self.assertIn("ranker", health)
        self.assertIn("engine_story", health)
        self.assertIn("/api/inbox", health["endpoints"])
        self.assertIn("/api/agent/task/execute", health["endpoints"])
        self.assertIn("/api/owner-approval/approve", health["endpoints"])
        ranker_available = bool(health["ranker"]["available"])

        metrics = scan["metrics"]
        self.assertGreater(metrics["records_per_second"], 0)
        self.assertGreaterEqual(metrics["shortlist_reduction_ratio"], 0)
        self.assertGreaterEqual(metrics["model_calls_avoided"], 1)
        self.assertIn("model_calls_successful", metrics)
        self.assertIn("briefs_generated", metrics)
        self.assertIn("label_changes_after_extraction", metrics)
        self.assertIn("brief_mode", metrics)
        if ranker_available:
            self.assertEqual(metrics["market_model_mode"], "sklearn_award_history")
            self.assertGreater(metrics["market_model_examples"], 0)
        else:
            self.assertEqual(metrics["market_model_mode"], "deterministic_historical_fallback")
            self.assertIn("missing_dependencies", health["ranker"]["mode"])
        self.assertGreaterEqual(metrics["market_model_precision_at_10"], 0)
        self.assertIn("market_model", scan)
        self.assertIn("technical_depth_proof", scan)
        self.assertGreaterEqual(len(scan["technical_depth_proof"]), 5)
        self.assertIn("Pipeline:", scan["technical_depth_proof"][0])
        self.assertTrue(any("Award-history" in line for line in scan["technical_depth_proof"]))
        self.assertIn("engine", metrics)
        self.assertIn("insight_scorecard", scan)
        self.assertGreaterEqual(scan["insight_scorecard"]["false_positives_skipped"], 1)
        self.assertTrue(scan["insight_scorecard"]["best_current_opportunity"]["document_number"])
        self.assertGreater(len(scan["insight_scorecard"]["similar_award_examples"]), 0)
        self.assertGreater(len(scan["insight_scorecard"]["false_positive_categories"]), 0)
        first = (scan["top_opportunities"] or scan["watchlist"] or scan["all_evaluated"])[0]
        self.assertIn(first["market_fit"]["source"], {"sklearn_award_history", "deterministic_historical_fallback"})
        self.assertIn(
            first["bid_recommendation"]["source"],
            {"trained_award_value_model", "historical_value_fallback"},
        )
        self.assertGreater(first["bid_recommendation"]["recommended_bid"], 0)
        self.assertGreater(first["predicted_bid"], 0)
        self.assertGreaterEqual(first["fit_probability"], 0)
        self.assertIn("rag_evidence", first)
        self.assertGreater(len(first["rag_evidence"]["analogs"]), 0)
        self.assertIn("simulation_summary", first)
        self.assertGreater(first["simulation_summary"]["iterations"], 0)
        self.assertIn("portfolio_decision", first)
        self.assertIn(first["portfolio_decision"]["decision"], {"Pursue Now", "Pursue If Capacity Frees", "Review", "Monitor", "Pass"})
        self.assertIn("value_model_mode", metrics)
        self.assertIn("rag_mode", metrics)
        self.assertIn("portfolio_mode", metrics)
        self.assertIn("daily_inbox", scan)
        self.assertGreater(scan["daily_inbox"]["summary"]["total"], 0)
        self.assertTrue(scan["daily_inbox"]["items"][0]["next_action"])

    def test_scan_uses_deterministic_market_fallback_when_ranker_training_is_unavailable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CONTRACT_RADAR_OFFLINE": "1",
                "CONTRACT_RADAR_ALLOW_SAMPLE_DATA": "1",
                "CONTRACT_RADAR_USE_PRECOMPUTED_SCAN": "0",
            },
            clear=False,
        ):
            service = ContractRadarService()
            with patch(
                "contract_radar.ranker.train_award_history_market_model",
                side_effect=RuntimeError("training dependency unavailable"),
            ):
                scan = service.scan({"profile_id": "road_civil_infrastructure", "refresh": True})

        metrics = scan["metrics"]
        first = (scan["top_opportunities"] or scan["watchlist"] or scan["all_evaluated"])[0]
        self.assertEqual(metrics["market_model_mode"], "deterministic_historical_fallback")
        self.assertEqual(first["market_fit"]["source"], "deterministic_historical_fallback")
        self.assertGreaterEqual(first["fit_probability"], 0)
        self.assertIn("daily_inbox", scan)
        self.assertTrue(scan["daily_inbox"]["items"][0]["next_action"])

    def test_scan_can_replay_precomputed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(config, "PRECOMPUTED_DIR", Path(tmpdir)):
                write_precomputed_scan(
                    scan_result={
                        "business_profile": {"profile_id": "road_civil_infrastructure"},
                        "priority_mode": "best_win_chance",
                        "metrics": {"runtime_ms": 123, "warnings": []},
                        "top_opportunities": [],
                        "watchlist": [],
                        "skipped": [],
                        "all_evaluated": [],
                    },
                    profile_id="road_civil_infrastructure",
                    priority_mode="best_win_chance",
                    as_of=None,
                )
                with patch.dict(os.environ, {"CONTRACT_RADAR_USE_PRECOMPUTED_SCAN": "1"}, clear=False):
                    with patch("contract_radar.data.load_procurement_data") as load_data:
                        scan = ContractRadarService().scan(
                            {
                                "profile_id": "road_civil_infrastructure",
                                "priority_mode": "best_win_chance",
                            }
                        )

                load_data.assert_not_called()
                self.assertTrue(scan["metrics"]["precomputed_scan_replay"])
                self.assertIn("Precomputed scan replay", scan["metrics"]["warnings"][0])

    def test_scan_result_is_cached_after_first_run(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CONTRACT_RADAR_OFFLINE": "1",
                "CONTRACT_RADAR_ALLOW_SAMPLE_DATA": "1",
            },
            clear=False,
        ):
            service = ContractRadarService()
            first = service.scan({"profile_id": "road_civil_infrastructure"})
            with patch("contract_radar.data.load_procurement_data") as load_data:
                second = service.scan({"profile_id": "road_civil_infrastructure"})

        load_data.assert_not_called()
        self.assertFalse(first["metrics"].get("scan_result_cache_hit", False))
        self.assertTrue(second["metrics"]["scan_result_cache_hit"])
        self.assertEqual(first["business_profile"]["profile_id"], second["business_profile"]["profile_id"])

    def test_profile_variant_reuses_artifacts_without_exact_result_cache(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CONTRACT_RADAR_OFFLINE": "1",
                "CONTRACT_RADAR_ALLOW_SAMPLE_DATA": "1",
            },
            clear=False,
        ):
            service = ContractRadarService()
            first = service.scan({"profile_id": "road_civil_infrastructure"})
            with patch("contract_radar.data.load_procurement_data") as load_data:
                second = service.scan(
                    {
                        "profile_id": "road_civil_infrastructure",
                        "business_profile": {
                            "profile_id": "road_civil_infrastructure",
                            "name": "Variant Civil Works",
                            "max_contract_value": 900000,
                            "active_pursuit_count": 0,
                        },
                    }
                )

        load_data.assert_not_called()
        self.assertFalse(first["metrics"].get("scan_result_cache_hit", False))
        self.assertFalse(second["metrics"].get("scan_result_cache_hit", False))
        self.assertEqual(second["business_profile"]["name"], "Variant Civil Works")

    def test_listing_briefs_are_limited_to_contract_inbox(self) -> None:
        captured_document_numbers: list[str] = []

        def passthrough_briefs(profile, opportunities):
            captured_document_numbers.extend(
                item.solicitation.document_number for item in opportunities
            )
            return opportunities, "deterministic_fallback", {
                "opportunity_count": len(opportunities),
                "shortlisted_for_brief": len(opportunities),
                "model_calls_attempted": 0,
                "model_calls_successful": 0,
                "model_calls_failed": 0,
                "briefs_generated": 0,
                "label_changes_after_extraction": 0,
                "model_calls_avoided_by_preflight": len(opportunities),
                "model_calls_avoided_by_failure": 0,
                "listing_extraction_cache_hits": 0,
                "model_latency_ms": 0,
            }

        with patch.dict(
            os.environ,
            {
                "CONTRACT_RADAR_OFFLINE": "1",
                "CONTRACT_RADAR_ALLOW_SAMPLE_DATA": "1",
            },
            clear=False,
        ):
            service = ContractRadarService()
            with patch(
                "contract_radar.briefs.enrich_opportunity_briefs_with_stats",
                side_effect=passthrough_briefs,
            ):
                scan = service.scan({"profile_id": "road_civil_infrastructure"})

        inbox_document_numbers = [
            item["solicitation"]["document_number"]
            for item in [*scan["top_opportunities"], *scan["watchlist"]]
        ]
        skipped_document_numbers = {
            item["solicitation"]["document_number"] for item in scan["skipped"]
        }

        self.assertEqual(captured_document_numbers, inbox_document_numbers)
        self.assertLessEqual(len(captured_document_numbers), 13)
        self.assertFalse(set(captured_document_numbers) & skipped_document_numbers)

    def test_approve_falls_back_to_payload_scan_when_last_scan_is_stale(self) -> None:
        service = ContractRadarService()
        service._last_scan = _approval_scan("other-profile", "OTHER-1")
        selected_scan = _approval_scan("road_civil_infrastructure", "RFQ-SELECTED")
        _attach_ready_analysis(service, "RFQ-SELECTED")

        with patch.object(service, "scan", return_value=selected_scan) as scan:
            result = service.approve(
                {
                    "profile_id": "road_civil_infrastructure",
                    "priority_mode": "best_win_chance",
                    "as_of": "2026-05-30",
                    "approved": True,
                    "opportunity_id": "RFQ-SELECTED",
                }
            )

        scan.assert_called_once()
        self.assertEqual(result["packet"]["opportunity_id"], "RFQ-SELECTED")

    def test_approve_can_use_displayed_top_opportunity_without_all_evaluated(self) -> None:
        service = ContractRadarService()
        service._last_scan = _approval_scan("road_civil_infrastructure", "RFQ-TOP")
        service._last_scan["all_evaluated"] = []
        _attach_ready_analysis(service, "RFQ-TOP")

        with patch.object(service, "scan") as scan:
            result = service.approve({"approved": True, "opportunity_id": "RFQ-TOP"})

        scan.assert_not_called()
        self.assertEqual(result["packet"]["opportunity_id"], "RFQ-TOP")


def _approval_scan(profile_id: str, document_number: str) -> dict:
    return {
        "business_profile": {
            "profile_id": profile_id,
            "name": "Harbourfront Civil Works Ltd.",
        },
        "top_opportunities": [_approval_opportunity(document_number)],
        "watchlist": [],
        "skipped": [],
        "all_evaluated": [_approval_opportunity(document_number)],
    }


def _approval_opportunity(document_number: str) -> dict:
    return {
        "label": "Pursue",
        "matched_terms": ["road repairs"],
        "missing_requirements": [],
        "solicitation": {
            "document_number": document_number,
            "description": "Road and sidewalk repair",
            "submission_deadline": "2026-06-18",
            "buyer_name": "City Buyer",
            "buyer_email": "buyer@toronto.ca",
            "buyer_phone": "416-555-0100",
            "division": "Transportation Services",
        },
    }


def _attach_ready_analysis(service: ContractRadarService, document_number: str) -> None:
    analysis_id = f"analysis-ready-{document_number.lower()}"
    session = {
        "analysis_id": analysis_id,
        "opportunity_id": document_number,
        "document": {"filename": "rfq.pdf", "content_hash": analysis_id},
        "text": {
            "page_count": 1,
            "character_count": 80,
            "chunks": [{"chunk_id": "1", "text": "Bidders must provide proof of insurance."}],
        },
        "compliance_matrix": [
            {
                "requirement_id": f"REQ-{document_number}",
                "requirement": "Bidders must provide proof of insurance.",
                "category": "insurance",
                "requirement_detected": True,
                "evidence_needed": [],
                "business_has_capability": True,
                "uploaded_evidence": [
                    {
                        "type": "certificate_available",
                        "label": "Certificate available",
                        "note": "",
                        "resolved_at": "2026-06-02T12:00:00Z",
                    }
                ],
                "matched_capabilities": ["Commercial general liability insurance"],
                "resolved": True,
                "citation": {
                    "source": "rfq.pdf",
                    "page": 1,
                    "chunk_id": "1",
                    "snippet": "Bidders must provide proof of insurance.",
                },
            }
        ],
        "compliance_summary": {
            "total": 1,
            "resolved": 1,
            "unresolved": 0,
            "ready_to_prepare": True,
        },
        "created_at": "2026-06-02T12:00:00Z",
        "pricing_context": _pricing_context(),
        "pricing_approval": {
            "approval_id": f"pricing-approval-{document_number.lower()}",
            "status": "approved",
            "approved_target_bid": 760000,
            "approved_by": "Estimator",
            "approved_at": "2026-06-02T12:10:00Z",
        },
        "bid_state": "owner_packet_ready",
        "gate_results": [],
        "agent_tasks": [],
        "evidence_ledger": [],
        "agent_actions": [],
    }
    service._document_analysis_sessions[analysis_id] = session
    service._latest_document_analysis_by_opportunity[document_number] = analysis_id


def _pricing_context() -> dict:
    return {
        "pricing_breakdown": {
            "recommended_bid": 760000,
            "market_reference": 720000,
            "direct_cost": 500000,
            "estimated_cost": 620000,
            "win_probability": 0.42,
            "expected_profit": 52000,
            "candidate_bids": [{"bid": 700000}, {"bid": 760000}, {"bid": 820000}],
        },
        "bid_recommendation": {
            "recommended_bid": 760000,
            "low_bid": 650000,
            "high_bid": 880000,
            "confidence": "Moderate",
        },
        "historical": {
            "examples": [
                {"document_number": "A1", "description": "Road repair", "award_value": 690000},
                {"document_number": "A2", "description": "Asphalt paving", "award_value": 735000},
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
