from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contract_radar.models import BusinessProfile
from contract_radar.packet import create_approval_packet
from contract_radar.packet_export import build_packet_export, render_packet_markdown
from tests.test_packet import _opportunity


class PacketExportTests(unittest.TestCase):
    def test_markdown_export_includes_audit_ids_and_non_submission_warning(self) -> None:
        packet = create_approval_packet(
            BusinessProfile(),
            _opportunity(),
            approved=True,
            compliance_matrix=[
                {
                    "requirement_id": "REQ-INS",
                    "requirement": "Bidders must provide proof of insurance.",
                    "category": "insurance",
                    "resolved": True,
                    "citation": {"source": "rfq.pdf", "page": 1, "snippet": "proof of insurance"},
                    "uploaded_evidence": [{"evidence_id": "EVD-INS"}],
                }
            ],
            agent_evidence_ledger=[
                {
                    "fact_id": "fact-ins",
                    "fact_type": "uploaded_evidence",
                    "source_type": "evidence_vault",
                    "requirement_id": "REQ-INS",
                    "citation": {"source": "vault", "snippet": "insurance cert"},
                }
            ],
            agent_action_trace=[
                {
                    "action_id": "action-packet",
                    "action_type": "owner_packet_prepared",
                    "output_ids": ["packet-1"],
                    "source_fact_ids": ["fact-ins"],
                }
            ],
            pricing_worksheet={
                "source": "deterministic_pricing_worksheet",
                "status": "ready",
                "target_bid": 760000,
                "low_bid": 700000,
                "high_bid": 820000,
                "confidence": "Moderate",
                "estimator_approval_status": "approved",
                "can_use_for_owner_packet": True,
                "estimator_approval": {
                    "approval_id": "pricing-approval-1",
                    "approved_by": "Estimator",
                    "approved_at": "2026-06-04T12:00:00Z",
                    "approved_target_bid": 760000,
                },
                "pricing_line_items": [
                    {
                        "line_item_id": "pricing-line-1",
                        "description": "Asphalt milling",
                        "quantity": 1200,
                        "unit": "m2",
                        "citation": {"source": "rfq.pdf", "page": 7, "snippet": "Asphalt milling 1,200 m2"},
                    }
                ],
                "line_item_rollup": {
                    "source": "deterministic_profile_rate_card",
                    "target_bid": 25000,
                    "direct_cost": 21600,
                    "coverage": 1,
                    "priced_line_items": [
                        {
                            "line_item_id": "pricing-line-1",
                            "description": "Asphalt milling",
                            "quantity": 1200,
                            "unit": "m2",
                            "unit_direct_cost": 18,
                            "direct_cost": 21600,
                            "citation": {"source": "rfq.pdf", "page": 7, "snippet": "Asphalt milling 1,200 m2"},
                        }
                    ],
                },
            },
        ).to_dict()

        markdown = render_packet_markdown(
            packet,
            packet_id="packet-1",
            export_id="packet-export-1",
            created_at="2026-06-04T12:05:00Z",
        )

        self.assertIn("Submission Status: `not_submitted_by_project_bid_bot`", markdown)
        self.assertIn("Human submission required", markdown)
        self.assertIn("REQ-INS", markdown)
        self.assertIn("fact-ins", markdown)
        self.assertIn("action-packet", markdown)
        self.assertIn("pricing-approval-1", markdown)
        self.assertIn("PDF Quantity Basis", markdown)
        self.assertIn("pricing-line-1", markdown)
        self.assertIn("Line Item Rollup Target", markdown)
        self.assertIn("21,600", markdown)
        self.assertIn("rfq.pdf / p. 1", markdown)

    def test_packet_export_writes_versioned_markdown_file(self) -> None:
        packet = create_approval_packet(BusinessProfile(), _opportunity(), approved=True).to_dict()
        with tempfile.TemporaryDirectory() as tmpdir:
            export = build_packet_export(
                packet,
                analysis_id="analysis-1",
                packet_id="packet-1",
                storage_dir=tmpdir,
                created_at="2026-06-04T12:05:00Z",
            )
            path = Path(export["storage_path"])
            self.assertTrue(path.exists())
            markdown = path.read_text(encoding="utf-8")

        self.assertTrue(export["export_id"].startswith("packet-export-"))
        self.assertTrue(path.name.endswith(".md"))
        self.assertIn("packet_exports", str(path))
        self.assertIn("not_submitted_by_project_bid_bot", markdown)


if __name__ == "__main__":
    unittest.main()
