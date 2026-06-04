from __future__ import annotations

import unittest

from contract_radar.agent_runtime import build_agent_runtime
from contract_radar.models import BusinessProfile
from contract_radar.packet import create_approval_packet
from contract_radar.submission_manifest import build_submission_manifest, summarize_submission_manifest

from tests.test_packet import _opportunity


class SubmissionManifestTests(unittest.TestCase):
    def test_metadata_only_session_has_official_package_blocker(self) -> None:
        manifest = build_submission_manifest(
            {
                "analysis_id": "analysis-metadata",
                "opportunity_id": "RFQ-OPEN",
                "acquisition": {
                    "status": "portal_login_required",
                    "source_type": "open_data_metadata",
                    "source_label": "Toronto Bids Solicitations",
                    "open_data_record_url": "https://example.test/open-data-record",
                    "package_required": True,
                    "message": "Open data contains listing metadata, but not the official solicitation package.",
                },
                "gate_results": [
                    {
                        "gate_id": "gate-package",
                        "rule_id": "official_package_required",
                        "requirement_id": "official-package",
                    }
                ],
            },
            approved=False,
        )

        by_type = {item["item_type"]: item for item in manifest}
        self.assertEqual(by_type["official_package"]["status"], "blocked")
        self.assertEqual(by_type["official_package"]["source_gate_id"], "gate-package")
        self.assertEqual(by_type["owner_approval"]["status"], "pending_owner_approval")
        self.assertEqual(summarize_submission_manifest(manifest)["required_open"], 2)

    def test_resolved_requirement_carries_evidence_ids_and_citation(self) -> None:
        manifest = build_submission_manifest(
            {
                "analysis_id": "analysis-ready",
                "document": {"filename": "rfq.pdf", "content_hash": "abc"},
                "acquisition": {"status": "package_uploaded", "package_required": False},
            },
            compliance_matrix=[
                {
                    "requirement_id": "REQ-INS",
                    "requirement": "Bidders must provide proof of insurance.",
                    "category": "insurance",
                    "evidence_needed": [],
                    "business_has_capability": True,
                    "uploaded_evidence": [{"type": "vault_evidence", "evidence_id": "ev-ins"}],
                    "resolved": True,
                    "citation": {"source": "rfq.pdf", "page": 3, "snippet": "proof of insurance"},
                }
            ],
            evidence_ledger=[
                {
                    "fact_id": "fact-evidence",
                    "fact_type": "uploaded_evidence",
                    "source_type": "evidence_vault",
                    "requirement_id": "REQ-INS",
                }
            ],
            approved=True,
        )

        insurance = next(item for item in manifest if item["item_type"] == "insurance_certificate")
        self.assertEqual(insurance["status"], "ready")
        self.assertIn("ev-ins", insurance["evidence_ids"])
        self.assertIn("fact-evidence", insurance["evidence_ids"])
        self.assertEqual(insurance["citation"]["page"], 3)
        self.assertTrue(summarize_submission_manifest(manifest)["ready_for_submission"])

    def test_pricing_worksheet_blocker_is_manifest_blocker(self) -> None:
        manifest = build_submission_manifest(
            {"analysis_id": "analysis-pricing"},
            pricing_worksheet={
                "status": "blocked",
                "target_bid": 0,
                "blockers": ["No deterministic bid amount is available."],
            },
            approved=True,
        )

        pricing = next(item for item in manifest if item["item_type"] == "pricing_worksheet")
        self.assertEqual(pricing["status"], "blocked")
        self.assertIn("No deterministic bid amount", pricing["reason"])
        self.assertEqual(summarize_submission_manifest(manifest)["required_open"], 1)

    def test_agent_runtime_adds_submission_manifest_to_analysis_shape(self) -> None:
        runtime = build_agent_runtime(
            {
                "analysis_id": "analysis-runtime",
                "opportunity_id": "RFQ-123",
                "document": {"filename": "rfq.pdf", "content_hash": "abc"},
                "text": {"chunks": [{"chunk_id": "1", "text": "fixture"}]},
                "compliance_matrix": [
                    {
                        "requirement_id": "REQ-PRICE",
                        "requirement": "Bidders shall submit the pricing form.",
                        "category": "pricing_sheet",
                        "evidence_needed": ["pricing form"],
                        "business_has_capability": None,
                        "uploaded_evidence": [],
                        "matched_capabilities": [],
                        "resolved": False,
                        "citation": {
                            "source": "rfq.pdf",
                            "page": 2,
                            "chunk_id": "1",
                            "snippet": "submit the pricing form",
                        },
                    }
                ],
                "compliance_summary": {"total": 1},
            },
            now="2026-06-03T12:00:00Z",
        )

        self.assertIn("submission_manifest", runtime)
        self.assertIn("submission_manifest_summary", runtime)
        self.assertGreaterEqual(runtime["submission_manifest_summary"]["required_open"], 1)
        self.assertEqual(runtime["agent_summary"]["submission_manifest_count"], len(runtime["submission_manifest"]))

    def test_packet_includes_submission_manifest_with_pricing(self) -> None:
        packet = create_approval_packet(
            BusinessProfile(),
            _opportunity(),
            approved=True,
            compliance_matrix=[
                {
                    "requirement_id": "REQ-SITE",
                    "requirement": "A mandatory site meeting must be attended.",
                    "category": "site_visit",
                    "evidence_needed": [],
                    "business_has_capability": None,
                    "uploaded_evidence": [{"type": "site_visit_attended", "label": "Attended"}],
                    "resolved": True,
                    "citation": {"source": "rfq.pdf", "page": 2, "snippet": "mandatory site meeting"},
                }
            ],
            compliance_summary={"total": 1, "resolved": 1, "unresolved": 0, "ready_to_prepare": True},
            acquisition={"status": "package_uploaded", "package_required": False},
            document={"filename": "rfq.pdf", "content_hash": "abc"},
        )

        manifest_types = {item["item_type"] for item in packet.submission_manifest}
        self.assertIn("official_package", manifest_types)
        self.assertIn("site_visit_confirmation", manifest_types)
        self.assertIn("pricing_worksheet", manifest_types)
        self.assertIn("owner_approval", manifest_types)
        self.assertIn("submission_manifest_summary", packet.to_dict())


if __name__ == "__main__":
    unittest.main()
