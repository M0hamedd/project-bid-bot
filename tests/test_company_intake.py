from __future__ import annotations

import tempfile
import unittest

from contract_radar.agent_runtime import decorate_agent_session
from contract_radar.company_intake import build_company_intake_profile
from contract_radar.service import ContractRadarService


class CompanyIntakeTests(unittest.TestCase):
    def test_company_intake_normalizes_profile_without_demo_evidence(self) -> None:
        profile = build_company_intake_profile(
            {
                "company": {
                    "name": "Northline Grounds",
                    "services": ["park landscaping", "sod repair", "tree planting"],
                    "documents_on_hand": ["WSIB clearance", "insurance certificate"],
                    "equipment": ["watering trailer", "skid steer"],
                    "rate_card": [
                        {
                            "label": "Sod repair",
                            "keywords": ["sod", "turf"],
                            "unit": "m2",
                            "rate": "18",
                        }
                    ],
                    "pricing_policy": {"overhead_rate": "12", "margin_rate": 0.15},
                }
            },
            now="2026-06-04T12:00:00Z",
        )

        self.assertEqual(profile["profile_id"], "parks_landscape")
        self.assertEqual(profile["profile_source"], "company_intake")
        self.assertEqual(profile["name"], "Northline Grounds")
        self.assertEqual(profile["ready_documents"], ["WSIB clearance", "insurance certificate"])
        self.assertNotIn("playground installer references", profile["ready_documents"])
        self.assertEqual(profile["pricing_rate_card"][0]["label"], "Sod repair")
        self.assertEqual(profile["pricing_policy"]["overhead_rate"], 0.12)
        self.assertIn("max_contract_value", profile["missing_profile_facts"])
        self.assertGreater(profile["profile_completeness"], 0)

    def test_company_intake_service_persists_profile_and_evidence_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            result = service.intake_company(
                {
                    "profile_id": "road_civil_infrastructure",
                    "company": {
                        "name": "Custom Road Co",
                        "services": ["asphalt paving", "curb repair"],
                        "documents_on_hand": ["WSIB clearance"],
                        "insurance": "$5M CGL",
                        "bonding_limit": 500000,
                        "equipment": ["roller"],
                        "past_projects": ["municipal curb repair"],
                    },
                }
            )

            reloaded = ContractRadarService(local_state_dir=tmpdir)
            health_profile = next(
                profile
                for profile in reloaded.health()["supported_profiles"]
                if profile["profile_id"] == "road_civil_infrastructure"
            )

        evidence_types = {record["evidence_type"] for record in result["evidence_vault"]["records"]}
        self.assertEqual(result["business_profile"]["name"], "Custom Road Co")
        self.assertIn("insurance_certificate", evidence_types)
        self.assertIn("bonding_capacity", evidence_types)
        self.assertIn("safety_document", evidence_types)
        self.assertEqual(health_profile["name"], "Custom Road Co")
        self.assertTrue(health_profile["locally_saved"])

    def test_complete_company_profile_refreshes_blocked_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            session = _profile_blocked_session()
            service._document_analysis_sessions[session["analysis_id"]] = session
            service._latest_document_analysis_by_opportunity[session["opportunity_id"]] = session["analysis_id"]

            before = service._document_analysis_sessions[session["analysis_id"]]
            result = service.complete_company_profile(
                {
                    "analysis_id": session["analysis_id"],
                    "profile_id": "parks_landscape",
                    "profile_facts": {
                        "ready_documents": ["WSIB clearance", "insurance certificate"],
                        "recent_municipal_work": ["City park sod repair"],
                        "pricing_rate_card": [
                            {
                                "label": "Sod repair",
                                "keywords": ["sod", "turf"],
                                "units": ["m2"],
                                "unit_direct_cost": 18,
                            }
                        ],
                        "max_contract_value": "$500,000",
                        "team_size": "8",
                    },
                }
            )
            reloaded = ContractRadarService(local_state_dir=tmpdir)

        updated = result["analysis"]
        persisted = reloaded._document_analysis_sessions[session["analysis_id"]]
        self.assertEqual(before["agent_tasks"][0]["task_type"], "complete_company_profile")
        self.assertEqual(updated["bid_state"], "owner_packet_ready")
        self.assertEqual(updated["gate_results"], [])
        self.assertEqual(result["missing_profile_facts"], [])
        self.assertIn("RFQ-PROFILE-COMPLETE", result["updated_analyses"])
        self.assertIn("company_profile_completed", [action["action_type"] for action in updated["agent_actions"]])
        self.assertEqual(persisted["bid_state"], "owner_packet_ready")
        self.assertEqual(persisted["business_profile"]["team_size"], 8.0)

    def test_complete_company_profile_rejects_empty_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            with self.assertRaises(ValueError) as context:
                service.complete_company_profile(
                    {
                        "profile_id": "parks_landscape",
                        "profile_facts": {"team_size": ""},
                    }
                )

        self.assertIn("At least one company profile fact", str(context.exception))


def _profile_blocked_session() -> dict:
    row = {
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
            "page": 2,
            "chunk_id": "1",
            "snippet": "Bidders must provide proof of insurance.",
        },
    }
    session = {
        "analysis_id": "analysis-profile-complete",
        "opportunity_id": "RFQ-PROFILE-COMPLETE",
        "document": {"filename": "rfq.pdf", "content_hash": "profile-complete"},
        "text": {"chunks": [{"chunk_id": "1", "text": "fixture"}]},
        "compliance_matrix": [row],
        "compliance_summary": {"total": 1, "resolved": 1, "unresolved": 0},
        "business_profile": {
            "profile_id": "parks_landscape",
            "profile_source": "company_intake",
            "name": "Northline Grounds",
            "skills": ["sod repair"],
            "ready_documents": [],
            "insurance_coverage": "$5M CGL",
            "bonding_single_job_limit": 250000,
            "owned_equipment": ["watering trailer"],
            "recent_municipal_work": [],
            "pricing_rate_card": [],
            "max_contract_value": 0,
            "team_size": 0,
            "missing_profile_facts": [],
        },
        "pricing_context": {
            "pricing_breakdown": {
                "market_reference": 720000,
                "direct_cost": 500000,
                "contingency": 65000,
                "overhead": 55000,
                "estimated_cost": 620000,
                "margin": 120000,
                "recommended_bid": 760000,
                "candidate_bids": [{"bid": 700000}, {"bid": 760000}, {"bid": 820000}],
            },
            "bid_recommendation": {
                "recommended_bid": 760000,
                "low_bid": 650000,
                "high_bid": 880000,
                "confidence": "Moderate",
            },
        },
        "pricing_approval": {
            "approval_id": "pricing-approval-profile",
            "status": "approved",
            "approved_target_bid": 760000,
            "approved_by": "Estimator",
            "approved_at": "2026-06-02T12:10:00Z",
        },
        "created_at": "2026-06-02T12:00:00Z",
    }
    return decorate_agent_session(session, now="2026-06-02T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
