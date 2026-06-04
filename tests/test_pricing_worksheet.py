from __future__ import annotations

import unittest
from datetime import date

from contract_radar.bid_pricing import attach_bid_pricing
from contract_radar.models import (
    BidRecommendation,
    BusinessProfile,
    EvaluatedOpportunity,
    HistoricalComparison,
    MarketFitSignal,
    PricingBreakdown,
    RAGEvidence,
    Solicitation,
)
from contract_radar.packet import create_approval_packet
from contract_radar.pricing_worksheet import build_pricing_worksheet, with_estimator_approval


class PricingWorksheetTests(unittest.TestCase):
    def test_pricing_worksheet_builds_owner_range_and_confidence(self) -> None:
        opportunity = _opportunity()
        worksheet = build_pricing_worksheet(opportunity)

        self.assertEqual(worksheet["status"], "draft_estimate")
        self.assertEqual(worksheet["target_bid"], 760000)
        self.assertLessEqual(worksheet["low_bid"], worksheet["target_bid"])
        self.assertGreaterEqual(worksheet["high_bid"], worksheet["target_bid"])
        self.assertIn(worksheet["confidence"], {"High", "Moderate", "Low"})
        self.assertTrue(worksheet["assumptions"])
        self.assertTrue(worksheet["comparable_awards"])

    def test_pricing_worksheet_blocks_unresolved_pricing_form(self) -> None:
        worksheet = build_pricing_worksheet(
            _opportunity(),
            compliance_matrix=[
                {
                    "requirement": "Bidders shall submit the completed pricing form.",
                    "category": "pricing_sheet",
                    "resolved": False,
                }
            ],
        )

        self.assertEqual(worksheet["status"], "blocked")
        self.assertFalse(worksheet["can_use_for_owner_packet"])
        self.assertTrue(any("pricing" in blocker.lower() for blocker in worksheet["blockers"]))

    def test_estimator_approval_controls_owner_packet_use(self) -> None:
        worksheet = build_pricing_worksheet(_opportunity())

        pending = with_estimator_approval(worksheet)
        approved = with_estimator_approval(
            worksheet,
            {
                "approval_id": "pricing-approval-test",
                "status": "approved",
                "approved_target_bid": worksheet["target_bid"],
                "approved_by": "Estimator",
                "approved_at": "2026-06-03T12:00:00Z",
            },
        )

        self.assertEqual(pending["estimator_approval_status"], "pending_estimator_approval")
        self.assertFalse(pending["can_use_for_owner_packet"])
        self.assertEqual(approved["estimator_approval_status"], "approved")
        self.assertTrue(approved["can_use_for_owner_packet"])

    def test_attach_bid_pricing_adds_worksheet_to_opportunities(self) -> None:
        opportunity = _opportunity()
        attach_bid_pricing(BusinessProfile(), [opportunity])

        self.assertEqual(opportunity.pricing_worksheet["source"], "deterministic_pricing_worksheet")
        self.assertGreater(opportunity.pricing_worksheet["target_bid"], 0)
        self.assertIn("pricing_worksheet", opportunity.to_dict())

    def test_packet_includes_pricing_worksheet(self) -> None:
        packet = create_approval_packet(
            BusinessProfile(),
            _opportunity(),
            approved=True,
            compliance_matrix=[
                {
                    "requirement": "Bidders shall submit the completed pricing form.",
                    "category": "pricing_sheet",
                    "resolved": True,
                }
            ],
        )

        self.assertEqual(packet.pricing_worksheet["status"], "ready")
        self.assertGreater(packet.pricing_worksheet["target_bid"], 0)
        self.assertTrue(any("Pricing worksheet" in item for item in packet.checklist))


def _opportunity() -> EvaluatedOpportunity:
    return EvaluatedOpportunity(
        solicitation=Solicitation(
            document_number="ROAD-PRICE",
            solicitation_type="Request for Tender",
            category="Construction Services",
            description="Road repairs, asphalt paving, bridge rehabilitation, and traffic staging.",
            division="Transportation Services",
            issue_date=date(2026, 5, 30),
            submission_deadline=date(2026, 6, 12),
        ),
        label="Pursue",
        rank_score=82,
        matched_terms=["road repairs", "asphalt paving", "traffic staging"],
        days_until_deadline=13,
        historical=HistoricalComparison(
            similar_count=5,
            award_min=500000,
            award_median=700000,
            award_max=900000,
            examples=[
                {"document_number": "A1", "description": "Road repair", "award_value": 690000},
                {"document_number": "A2", "description": "Asphalt paving", "award_value": 735000},
            ],
            evidence=["5 similar awarded contracts found."],
        ),
        market_fit=MarketFitSignal(score=0.72, supplier_concentration={"top_supplier_share": 0.20}),
        bid_recommendation=BidRecommendation(
            source="trained_award_value_model",
            recommended_bid=760000,
            low_bid=650000,
            high_bid=880000,
            confidence="Moderate",
            median_award=710000,
            evidence=["Historical value model produced a moderate-confidence bid estimate."],
        ),
        pricing_breakdown=PricingBreakdown(
            source="scope_cost_market_optimizer",
            market_reference=720000,
            direct_cost=500000,
            contingency=65000,
            overhead=55000,
            margin=120000,
            estimated_cost=620000,
            recommended_bid=760000,
            win_probability=0.42,
            expected_profit=52000,
            bid_prep_cost=1800,
            contingency_rate=0.13,
            overhead_rate=0.11,
            margin_rate=0.12,
            candidate_bids=[
                {"bid": 700000, "win_probability": 0.52, "expected_profit": 39000},
                {"bid": 760000, "win_probability": 0.42, "expected_profit": 52000},
                {"bid": 820000, "win_probability": 0.31, "expected_profit": 48000},
            ],
            evidence=["Cost stack: direct $500,000, contingency $65,000."],
        ),
        rag_evidence=RAGEvidence(
            value_median=720000,
            analogs=[{"document_number": "R1", "description": "Bridge rehab", "award_value": 740000}],
            evidence=["Retrieved comparable award median was $720,000."],
        ),
        fit_probability=0.72,
    )


if __name__ == "__main__":
    unittest.main()
