from __future__ import annotations

import tempfile
import unittest

from contract_radar.agent_runtime import decorate_agent_session
from contract_radar.service import ContractRadarService


class PricingInputServiceTests(unittest.TestCase):
    def test_record_pricing_input_updates_server_owned_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            session = _analysis_session()
            service._document_analysis_sessions[session["analysis_id"]] = session
            service._latest_document_analysis_by_opportunity[session["opportunity_id"]] = session["analysis_id"]

            updated = service.record_pricing_input(
                {
                    "analysis_id": session["analysis_id"],
                    "input_type": "quantity",
                    "value": 42,
                    "unit": "lane-m",
                    "created_by": "Estimator",
                }
            )
            approved = service.approve_pricing(
                {
                    "analysis_id": session["analysis_id"],
                    "approved_by": "Estimator",
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)

        self.assertEqual(updated["pricing_inputs"][0]["input_type"], "quantity")
        self.assertEqual(updated["pricing_worksheet"]["status"], "estimator_review_required")
        self.assertEqual(updated["agent_tasks"][0]["task_type"], "approve_pricing")
        self.assertIn("pricing_input_recorded", [action["action_type"] for action in updated["agent_actions"]])
        self.assertEqual(approved["bid_state"], "owner_packet_ready")
        persisted = reloaded._document_analysis_sessions[session["analysis_id"]]
        self.assertEqual(persisted["pricing_inputs"][0]["value"], 42.0)

    def test_approve_pricing_rejects_missing_required_input(self) -> None:
        service = ContractRadarService()
        session = _analysis_session()
        service._document_analysis_sessions[session["analysis_id"]] = session

        with self.assertRaises(ValueError) as context:
            service.approve_pricing({"analysis_id": session["analysis_id"]})

        self.assertIn("Record required estimator pricing inputs", str(context.exception))

    def test_record_line_item_unit_cost_unblocks_pricing_worksheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            session = _analysis_session()
            session["pricing_context"]["required_pricing_inputs"] = []
            session["pricing_context"]["pricing_line_items"] = [
                {
                    "line_item_id": "pricing-line-custom",
                    "description": "Custom aggregate bag supply",
                    "quantity": 25,
                    "unit": "bag",
                    "source": "uploaded_pdf",
                    "confidence": "deterministic",
                    "citation": {
                        "source": "rfq.pdf",
                        "page": 7,
                        "chunk_id": "p7",
                        "snippet": "Custom aggregate bag supply 25 bag Unit Price",
                    },
                }
            ]
            session = decorate_agent_session(
                session,
                action_types=["pricing_worksheet_created", "gate_rules_run", "tasks_generated"],
                now="2026-06-04T12:05:00Z",
            )
            service._document_analysis_sessions[session["analysis_id"]] = session
            service._latest_document_analysis_by_opportunity[session["opportunity_id"]] = session["analysis_id"]

            updated = service.record_pricing_line_item_rate(
                {
                    "analysis_id": session["analysis_id"],
                    "line_item_id": "pricing-line-custom",
                    "unit_direct_cost": 37,
                    "created_by": "Estimator",
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)

        self.assertEqual(session["agent_tasks"][0]["task_type"], "fix_pricing_worksheet")
        self.assertEqual(updated["pricing_inputs"][0]["input_type"], "line_item_unit_cost")
        self.assertEqual(updated["pricing_inputs"][0]["line_item_id"], "pricing-line-custom")
        self.assertEqual(updated["pricing_worksheet"]["line_item_rollup"]["unpriced_line_item_count"], 0)
        self.assertEqual(
            updated["pricing_worksheet"]["line_item_rollup"]["priced_line_items"][0]["rate_source_type"],
            "estimator_input",
        )
        self.assertEqual(updated["agent_tasks"][0]["task_type"], "approve_pricing")
        self.assertIn("pricing_input_recorded", [action["action_type"] for action in updated["agent_actions"]])
        self.assertEqual(
            reloaded._document_analysis_sessions[session["analysis_id"]]["pricing_inputs"][0]["line_item_id"],
            "pricing-line-custom",
        )

    def test_line_item_rate_rejects_unknown_server_line_item(self) -> None:
        service = ContractRadarService()
        session = _analysis_session()
        service._document_analysis_sessions[session["analysis_id"]] = session

        with self.assertRaises(ValueError) as context:
            service.record_pricing_line_item_rate(
                {
                    "analysis_id": session["analysis_id"],
                    "line_item_id": "missing-line",
                    "unit_direct_cost": 37,
                }
            )

        self.assertIn("was not found", str(context.exception))


def _analysis_session() -> dict:
    session = {
        "analysis_id": "analysis-pricing-inputs",
        "opportunity_id": "RFQ-PRICE-INPUTS",
        "document": {"filename": "rfq.pdf", "content_hash": "pricing-inputs"},
        "text": {
            "page_count": 1,
            "character_count": 80,
            "chunks": [{"chunk_id": "1", "text": "Bidders must provide proof of insurance."}],
        },
        "compliance_matrix": [
            {
                "requirement_id": "REQ-INS",
                "requirement": "Bidders must provide proof of insurance.",
                "category": "insurance",
                "requirement_detected": True,
                "evidence_needed": [],
                "business_has_capability": True,
                "uploaded_evidence": [{"type": "certificate_available", "label": "Certificate available"}],
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
        "compliance_summary": {"total": 1, "resolved": 1, "unresolved": 0},
        "pricing_context": {
            "required_pricing_inputs": ["quantity"],
            "pricing_breakdown": {
                "recommended_bid": 760000,
                "market_reference": 720000,
                "direct_cost": 500000,
                "estimated_cost": 620000,
                "win_probability": 0.42,
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
        },
        "created_at": "2026-06-04T12:00:00Z",
        "agent_actions": [],
    }
    return decorate_agent_session(
        session,
        action_types=["requirements_extracted", "evidence_ledger_created", "gate_rules_run", "tasks_generated"],
        now="2026-06-04T12:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
