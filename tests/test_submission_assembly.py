from __future__ import annotations

import unittest

from contract_radar.models import BusinessProfile
from contract_radar.packet import create_approval_packet
from contract_radar.packet_export import render_packet_markdown
from contract_radar.submission_assembly import (
    BLOCKED_STATUS,
    PENDING_OWNER_STATUS,
    READY_STATUS,
    build_submission_assembly,
)
from tests.test_packet import _opportunity


class SubmissionAssemblyTests(unittest.TestCase):
    def test_ready_manifest_creates_human_submission_assembly(self) -> None:
        assembly = build_submission_assembly(
            BusinessProfile(),
            _opportunity(),
            submission_manifest=[
                {
                    "manifest_id": "manifest-package",
                    "item_type": "official_package",
                    "label": "Official solicitation package",
                    "required": True,
                    "status": "ready",
                    "owner": "Bid Coordinator",
                    "evidence_ids": ["fact-package"],
                },
                {
                    "manifest_id": "manifest-insurance",
                    "item_type": "insurance_certificate",
                    "label": "Insurance certificate",
                    "required": True,
                    "status": "ready",
                    "owner": "Operations",
                    "evidence_ids": ["ev-ins"],
                },
                {
                    "manifest_id": "manifest-owner",
                    "item_type": "owner_approval",
                    "label": "Owner approval",
                    "required": True,
                    "status": "ready",
                    "owner": "Owner",
                },
            ],
            pricing_worksheet={"target_bid": 760000, "estimator_approval_status": "approved"},
            acquisition={
                "portal_url": "https://example.test/portal",
                "search_hint": "Search RFQ-123 in TO Bids",
            },
            document={"filename": "rfq.pdf"},
            buyer_contact={"name": "City Buyer", "email": "buyer@toronto.ca", "division": "Transportation Services"},
            approved=True,
        )

        self.assertEqual(assembly["status"], READY_STATUS)
        self.assertTrue(assembly["ready_for_human_submission"])
        self.assertTrue(assembly["human_submission_required"])
        self.assertEqual(assembly["summary"]["attachments"], 2)
        self.assertIn("Company legal name", {field["label"] for field in assembly["prefilled_fields"]})
        self.assertIn("Approved target bid", {field["label"] for field in assembly["prefilled_fields"]})
        self.assertEqual(assembly["attachments"][0]["filename"], "rfq.pdf")
        self.assertTrue(all(step["actor"] == "human_action_required" for step in assembly["portal_steps"]))
        self.assertIn("not upload", assembly["warning"])

    def test_open_manifest_item_blocks_submission_assembly(self) -> None:
        assembly = build_submission_assembly(
            BusinessProfile(),
            _opportunity(),
            submission_manifest=[
                {
                    "manifest_id": "manifest-pricing",
                    "item_type": "pricing_form",
                    "label": "Pricing form",
                    "required": True,
                    "status": "blocked",
                    "owner": "Estimator",
                },
                {
                    "manifest_id": "manifest-owner",
                    "item_type": "owner_approval",
                    "label": "Owner approval",
                    "required": True,
                    "status": "ready",
                    "owner": "Owner",
                },
            ],
            approved=True,
        )

        self.assertEqual(assembly["status"], BLOCKED_STATUS)
        self.assertFalse(assembly["ready_for_human_submission"])
        self.assertEqual(assembly["summary"]["open_attachments"], 1)
        self.assertIn("Resolve required open item", assembly["final_checks"][0])

    def test_owner_approval_is_required_before_assembly_is_ready(self) -> None:
        assembly = build_submission_assembly(
            BusinessProfile(),
            _opportunity(),
            submission_manifest=[
                {
                    "manifest_id": "manifest-owner",
                    "item_type": "owner_approval",
                    "label": "Owner approval",
                    "required": True,
                    "status": "pending_owner_approval",
                    "owner": "Owner",
                }
            ],
            approved=False,
        )

        self.assertEqual(assembly["status"], PENDING_OWNER_STATUS)
        self.assertFalse(assembly["ready_for_human_submission"])

    def test_packet_and_markdown_export_include_submission_assembly(self) -> None:
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
                    "uploaded_evidence": [{"evidence_id": "ev-ins"}],
                    "citation": {"source": "rfq.pdf", "page": 1, "snippet": "proof of insurance"},
                }
            ],
            compliance_summary={"total": 1, "resolved": 1, "unresolved": 0, "ready_to_prepare": True},
            acquisition={"status": "package_uploaded", "package_required": False, "portal_url": "https://example.test/portal"},
            document={"filename": "rfq.pdf", "content_hash": "abc"},
            pricing_worksheet={
                "status": "ready",
                "target_bid": 760000,
                "low_bid": 700000,
                "high_bid": 820000,
                "confidence": "Moderate",
                "estimator_approval_status": "approved",
                "can_use_for_owner_packet": True,
            },
        ).to_dict()

        markdown = render_packet_markdown(packet, packet_id="packet-1", export_id="packet-export-1")

        self.assertIn("submission_assembly", packet)
        self.assertEqual(packet["submission_assembly"]["status"], READY_STATUS)
        self.assertIn("Submission Assembly", markdown)
        self.assertIn("Prefilled Fields", markdown)
        self.assertIn("Human Submission Required: `true`", markdown)


if __name__ == "__main__":
    unittest.main()
