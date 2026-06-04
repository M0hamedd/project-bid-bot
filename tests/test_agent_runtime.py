from __future__ import annotations

import unittest

from contract_radar.agent_runtime import (
    ALLOWED_ACTION_TYPES,
    SOURCE_TYPES,
    build_agent_runtime,
    decorate_agent_session,
)


class AgentRuntimeTests(unittest.TestCase):
    def test_evidence_ledger_requires_pdf_citations_for_pdf_facts(self) -> None:
        session = _session(
            [
                _row(
                    "REQ-1",
                    "Bidders must provide proof of insurance.",
                    "insurance",
                    matched_capabilities=["Commercial general liability insurance"],
                ),
                {
                    **_row("REQ-2", "Bidders must provide an uncited form.", "form"),
                    "citation": {"source": "", "page": None, "snippet": ""},
                },
            ]
        )

        runtime = build_agent_runtime(session, now="2026-06-02T12:00:00Z")
        facts = runtime["evidence_ledger"]

        self.assertTrue(facts)
        self.assertTrue(all(required in fact for fact in facts for required in _FACT_KEYS))
        self.assertTrue(all(fact["source_type"] in SOURCE_TYPES for fact in facts))
        pdf_facts = [fact for fact in facts if fact["source_type"] == "uploaded_pdf"]
        self.assertEqual(len(pdf_facts), 1)
        self.assertEqual(pdf_facts[0]["requirement_id"], "REQ-1")
        self.assertTrue(pdf_facts[0]["citation"]["source"])
        self.assertTrue(pdf_facts[0]["citation"]["snippet"])

    def test_gate_rules_split_hard_stops_and_review_gates(self) -> None:
        runtime = build_agent_runtime(
            _session(
                [
                    _row("REQ-SITE", "A mandatory site meeting must be attended.", "site_visit"),
                    _row("REQ-DEADLINE", "Bids must be submitted before closing date.", "deadline"),
                    _row(
                        "REQ-SCOPE",
                        "Contractor shall complete professional engineering design.",
                        "scope",
                        business_has_capability=False,
                    ),
                ]
            ),
            now="2026-06-02T12:00:00Z",
        )

        gates = runtime["gate_results"]
        by_requirement = {gate["requirement_id"]: gate for gate in gates}
        self.assertEqual(by_requirement["REQ-SITE"]["gate_type"], "hard_stop")
        self.assertEqual(by_requirement["REQ-DEADLINE"]["gate_type"], "review")
        self.assertEqual(by_requirement["REQ-SCOPE"]["rule_id"], "capability_gap")
        self.assertTrue(all(gate["citation"]["source"] for gate in gates))
        self.assertTrue(all(gate["source_fact_ids"] for gate in gates))

    def test_tasks_are_generated_from_open_gates_with_resolution_options(self) -> None:
        runtime = build_agent_runtime(
            _session([_row("REQ-PRICE", "Bidders shall submit the pricing form.", "pricing_sheet")]),
            now="2026-06-02T12:00:00Z",
        )

        tasks = runtime["agent_tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["requirement_id"], "REQ-PRICE")
        self.assertTrue(tasks[0]["blocking"])
        self.assertIn("pricing_form_assigned", {option["type"] for option in tasks[0]["resolution_options"]})

    def test_compliance_decision_blocks_hard_stops(self) -> None:
        runtime = build_agent_runtime(
            _session([_row("REQ-SITE", "A mandatory site meeting must be attended.", "site_visit")]),
            now="2026-06-02T12:00:00Z",
        )

        decision = runtime["compliance_decision"]
        self.assertEqual(decision["label"], "Blocked")
        self.assertTrue(decision["blocking"])
        self.assertFalse(decision["can_prepare_packet"])

    def test_compliance_decision_reviews_review_gates(self) -> None:
        runtime = build_agent_runtime(
            _session([_row("REQ-DEADLINE", "Bids must be submitted before closing date.", "deadline")]),
            now="2026-06-02T12:00:00Z",
        )

        decision = runtime["compliance_decision"]
        self.assertEqual(decision["label"], "Review")
        self.assertEqual(decision["review_gate_count"], 1)
        self.assertFalse(decision["can_prepare_packet"])

    def test_compliance_decision_passes_capability_gaps(self) -> None:
        runtime = build_agent_runtime(
            _session(
                [
                    _row(
                        "REQ-SCOPE",
                        "Contractor shall complete professional engineering design.",
                        "scope",
                        business_has_capability=False,
                    )
                ]
            ),
            now="2026-06-02T12:00:00Z",
        )

        decision = runtime["compliance_decision"]
        self.assertEqual(decision["label"], "Pass")
        self.assertTrue(decision["requires_owner_override"])
        self.assertFalse(decision["can_prepare_packet"])

    def test_compliance_decision_allows_pursuit_when_ready(self) -> None:
        row = {
            **_row("REQ-INS", "Bidders must provide proof of insurance.", "insurance"),
            "evidence_needed": [],
            "uploaded_evidence": [{"type": "certificate_available", "label": "Certificate available"}],
            "resolved": True,
        }
        runtime = build_agent_runtime(_approved_pricing_session([row]), now="2026-06-02T12:00:00Z")

        decision = runtime["compliance_decision"]
        self.assertEqual(runtime["bid_state"], "owner_packet_ready")
        self.assertEqual(decision["label"], "Pursue")
        self.assertTrue(decision["can_prepare_packet"])

    def test_resolved_requirements_wait_for_estimator_pricing_approval(self) -> None:
        row = {
            **_row("REQ-INS", "Bidders must provide proof of insurance.", "insurance"),
            "evidence_needed": [],
            "uploaded_evidence": [{"type": "certificate_available", "label": "Certificate available"}],
            "resolved": True,
        }

        runtime = build_agent_runtime(_priced_session([row]), now="2026-06-02T12:00:00Z")

        self.assertEqual(runtime["bid_state"], "requirements_resolved")
        self.assertEqual(runtime["compliance_decision"]["status"], "Price Approval Needed")
        self.assertEqual(runtime["agent_tasks"][0]["task_type"], "approve_pricing")
        self.assertEqual(runtime["pricing_worksheet"]["estimator_approval_status"], "pending_estimator_approval")

    def test_action_trace_only_uses_allowed_actions(self) -> None:
        session = decorate_agent_session(
            _session([_row("REQ-1", "Bidders must provide proof of insurance.", "insurance")]),
            action_types=["pdf_uploaded", "requirements_extracted", "gate_rules_run", "tasks_generated"],
            now="2026-06-02T12:00:00Z",
        )

        actions = session["agent_actions"]
        self.assertEqual([action["action_type"] for action in actions], [
            "pdf_uploaded",
            "requirements_extracted",
            "gate_rules_run",
            "tasks_generated",
        ])
        self.assertTrue(all(action["action_type"] in ALLOWED_ACTION_TYPES for action in actions))
        self.assertTrue(all(action["validation"]["passed"] for action in actions))
        self.assertEqual(session["agent_summary"]["action_count"], 4)
        self.assertEqual(session["agent_summary"]["hard_stop_count"], 1)
        self.assertEqual(session["agent_summary"]["next_action"], "Resolve Insurance")

    def test_metadata_only_session_creates_acquisition_gate(self) -> None:
        session = decorate_agent_session(
            {
                "analysis_id": "analysis-metadata",
                "opportunity_id": "RFQ-OPEN",
                "opportunity_metadata": {
                    "document_number": "RFQ-OPEN",
                    "title": "Road repair open data listing",
                    "submission_deadline": "2026-06-18",
                    "category": "Construction",
                    "division": "Transportation Services",
                    "buyer_name": "City Buyer",
                },
                "acquisition": {
                    "status": "metadata_only",
                    "source_type": "open_data_metadata",
                    "source_label": "Toronto Bids Solicitations",
                    "open_data_record_url": "https://example.test/open-data-record",
                    "package_required": True,
                    "message": "Open data contains listing metadata, but not the official solicitation package.",
                },
                "compliance_matrix": [],
                "compliance_summary": {"total": 0},
                "created_at": "2026-06-02T12:00:00Z",
            },
            action_types=["open_data_metadata_loaded", "document_acquisition_checked", "gate_rules_run", "tasks_generated"],
            now="2026-06-02T12:00:00Z",
        )

        self.assertEqual(session["bid_state"], "metadata_intake")
        self.assertEqual(session["compliance_decision"]["label"], "Review")
        self.assertFalse(session["compliance_decision"]["can_prepare_packet"])
        self.assertEqual(session["gate_results"][0]["rule_id"], "official_package_required")
        self.assertEqual(session["agent_tasks"][0]["task_type"], "acquire_official_package")
        self.assertEqual(session["agent_tasks"][0]["acquisition_status"], "metadata_only")
        self.assertIn("open_data_metadata", {fact["source_type"] for fact in session["evidence_ledger"]})
        self.assertIn("document_acquisition_checked", [action["action_type"] for action in session["agent_actions"]])


_FACT_KEYS = {"fact_id", "fact_type", "value", "source_type", "citation", "confidence", "created_at"}


def _session(rows: list[dict]) -> dict:
    return {
        "analysis_id": "analysis-test",
        "opportunity_id": "RFQ-123",
        "document": {"filename": "rfq.pdf", "content_hash": "abc123"},
        "text": {"chunks": [{"chunk_id": "1", "text": "fixture"}]},
        "compliance_matrix": rows,
        "compliance_summary": {"total": len(rows)},
        "created_at": "2026-06-02T12:00:00Z",
    }


def _priced_session(rows: list[dict]) -> dict:
    session = _session(rows)
    session["pricing_context"] = _pricing_context()
    return session


def _approved_pricing_session(rows: list[dict]) -> dict:
    session = _priced_session(rows)
    session["pricing_approval"] = {
        "approval_id": "pricing-approval-test",
        "status": "approved",
        "approved_target_bid": 760000,
        "approved_by": "Estimator",
        "approved_at": "2026-06-02T12:10:00Z",
    }
    return session


def _pricing_context() -> dict:
    return {
        "pricing_breakdown": {
            "market_reference": 720000,
            "direct_cost": 500000,
            "contingency": 65000,
            "overhead": 55000,
            "estimated_cost": 620000,
            "margin": 120000,
            "recommended_bid": 760000,
            "win_probability": 0.42,
            "expected_profit": 52000,
            "candidate_bids": [
                {"bid": 700000},
                {"bid": 760000},
                {"bid": 820000},
            ],
            "evidence": ["Cost stack: direct $500,000, contingency $65,000."],
        },
        "bid_recommendation": {
            "recommended_bid": 760000,
            "low_bid": 650000,
            "high_bid": 880000,
            "confidence": "Moderate",
            "evidence": ["Historical value model produced a bid estimate."],
        },
        "historical": {
            "examples": [
                {"document_number": "A1", "description": "Road repair", "award_value": 690000},
                {"document_number": "A2", "description": "Asphalt paving", "award_value": 735000},
            ]
        },
    }


def _row(
    requirement_id: str,
    requirement: str,
    category: str,
    *,
    business_has_capability: bool | None = None,
    matched_capabilities: list[str] | None = None,
) -> dict:
    return {
        "requirement_id": requirement_id,
        "requirement": requirement,
        "category": category,
        "requirement_detected": True,
        "evidence_needed": ["evidence"],
        "business_has_capability": business_has_capability,
        "uploaded_evidence": [],
        "matched_capabilities": matched_capabilities or [],
        "resolved": False,
        "citation": {
            "source": "rfq.pdf",
            "page": 2,
            "chunk_id": "1",
            "snippet": requirement,
        },
    }


if __name__ == "__main__":
    unittest.main()
