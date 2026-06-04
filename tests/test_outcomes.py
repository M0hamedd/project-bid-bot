from __future__ import annotations

import tempfile
import unittest
from datetime import date

from contract_radar.models import (
    BidRecommendation,
    BusinessProfile,
    EvaluatedOpportunity,
    PricingBreakdown,
    Solicitation,
)
from contract_radar.outcomes import apply_outcome_feedback, build_outcome_record, summarize_outcomes
from contract_radar.pricing_worksheet import build_pricing_worksheet
from contract_radar.service import ContractRadarService


class BidOutcomeTests(unittest.TestCase):
    def test_outcome_records_are_normalized_and_summarized(self) -> None:
        record = build_outcome_record(
            {
                "opportunity_id": "RFQ-ROAD-1",
                "submitted": True,
                "award_status": "win",
                "final_bid_amount": 710000,
                "winning_amount": 705000,
                "hours_spent": 18,
                "margin_estimate": 0.11,
            },
            business_profile={"profile_id": "road_civil_infrastructure"},
            opportunity=_opportunity_payload("RFQ-ROAD-1"),
            now="2026-06-04T12:00:00Z",
        )
        summary = summarize_outcomes([record], profile_id="road_civil_infrastructure")

        self.assertTrue(record["outcome_id"].startswith("outcome-"))
        self.assertEqual(record["award_status"], "won")
        self.assertEqual(record["profile_id"], "road_civil_infrastructure")
        self.assertEqual(summary["submitted"], 1)
        self.assertEqual(summary["won"], 1)
        self.assertEqual(summary["win_rate"], 1.0)
        self.assertIn("road repairs", summary["good_fit_terms"])

    def test_outcome_feedback_changes_explainable_rank_signals(self) -> None:
        opportunity = _evaluated_opportunity()
        record = build_outcome_record(
            {
                "opportunity_id": "RFQ-OLD-ROAD",
                "submitted": True,
                "award_status": "won",
                "final_bid_amount": 700000,
                "winning_amount": 695000,
            },
            business_profile={"profile_id": "road_civil_infrastructure"},
            opportunity=_opportunity_payload("RFQ-OLD-ROAD"),
            now="2026-06-04T12:00:00Z",
        )

        apply_outcome_feedback(BusinessProfile(), [opportunity], [record])

        self.assertGreater(opportunity.rank_score, 50)
        self.assertEqual(opportunity.customer_outcomes["wins"], 1)
        self.assertTrue(
            any("Customer outcomes" in signal for signal in opportunity.bid_fitness_trace.positive_signals)
        )
        self.assertEqual(opportunity.bid_fitness_trace.scorecard_labels["Customer Outcomes"], "+4 score")

    def test_pricing_worksheet_uses_customer_outcomes_as_comps(self) -> None:
        opportunity = _evaluated_opportunity()
        opportunity.customer_outcomes = {
            "matches": [
                {
                    "opportunity_id": "RFQ-OLD-ROAD",
                    "opportunity_title": "Prior road repairs",
                    "division": "Transportation Services",
                    "matched_terms": ["road repairs"],
                    "award_status": "lost",
                    "final_bid_amount": 720000,
                    "winning_amount": 690000,
                    "winner_name": "Winning Paving Ltd.",
                }
            ],
            "evidence": ["1 similar customer loss found in recorded outcomes."],
        }

        worksheet = build_pricing_worksheet(opportunity)

        customer_comps = [
            comp for comp in worksheet["comparable_awards"] if comp["source"] == "customer_outcome"
        ]
        self.assertEqual(customer_comps[0]["award_value"], 690000)
        self.assertIn("recorded outcomes", " ".join(worksheet["evidence"]))

    def test_service_records_and_persists_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            service._last_scan = _scan_payload("RFQ-ROAD-2")
            service._scan_result_cache["stale"] = {"metrics": {}}

            result = service.record_outcome(
                {
                    "opportunity_id": "RFQ-ROAD-2",
                    "submitted": True,
                    "award_status": "lost",
                    "final_bid_amount": 735000,
                    "winning_amount": 700000,
                    "reason_lost": "Winner was lower.",
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)

        self.assertEqual(result["outcome"]["award_status"], "lost")
        self.assertEqual(result["outcome_summary"]["lost"], 1)
        self.assertFalse(service._scan_result_cache)
        self.assertEqual(len(reloaded._bid_outcomes), 1)
        self.assertEqual(reloaded._last_scan["outcome_summary"]["lost"], 1)


def _evaluated_opportunity() -> EvaluatedOpportunity:
    return EvaluatedOpportunity(
        solicitation=Solicitation(
            document_number="RFQ-ROAD-NEW",
            solicitation_type="Request for Tender",
            category="Construction Services",
            description="Road repairs, sidewalk repair, asphalt paving, and traffic staging.",
            division="Transportation Services",
            issue_date=date(2026, 6, 1),
            submission_deadline=date(2026, 6, 20),
        ),
        label="Pursue",
        rank_score=50,
        matched_terms=["road repairs"],
        bid_recommendation=BidRecommendation(
            recommended_bid=740000,
            low_bid=680000,
            high_bid=790000,
            confidence="Moderate",
        ),
        pricing_breakdown=PricingBreakdown(
            recommended_bid=740000,
            market_reference=710000,
            direct_cost=510000,
            estimated_cost=620000,
            win_probability=0.4,
            candidate_bids=[{"bid": 700000}, {"bid": 740000}, {"bid": 780000}],
        ),
    )


def _opportunity_payload(document_number: str) -> dict:
    return {
        "matched_terms": ["road repairs"],
        "solicitation": {
            "document_number": document_number,
            "description": "Road repairs and asphalt paving",
            "buyer_name": "City Buyer",
            "division": "Transportation Services",
            "category": "Construction Services",
        },
    }


def _scan_payload(document_number: str) -> dict:
    return {
        "business_profile": {
            "profile_id": "road_civil_infrastructure",
            "name": "Harbourfront Civil Works Ltd.",
        },
        "as_of": "2026-06-04",
        "priority_mode": "best_win_chance",
        "metrics": {},
        "top_opportunities": [_opportunity_payload(document_number)],
        "watchlist": [],
        "skipped": [],
        "all_evaluated": [_opportunity_payload(document_number)],
    }


if __name__ == "__main__":
    unittest.main()
