from __future__ import annotations

import unittest
from datetime import date

from contract_radar.models import BusinessProfile, EvaluatedOpportunity, HistoricalComparison, OpportunityBrief, Solicitation
from contract_radar.packet import create_approval_packet


class PacketTests(unittest.TestCase):
    def test_unapproved_packet_waits_for_owner_approval(self) -> None:
        packet = create_approval_packet(BusinessProfile(), _opportunity(), approved=False)

        self.assertFalse(packet.approved)
        self.assertFalse(packet.owner_ready)
        self.assertIn("Owner approval required", packet.checklist[0])
        self.assertIn("Wait for owner approval", packet.submission_steps[-1])

    def test_approved_packet_without_brief_still_generates_packet(self) -> None:
        packet = create_approval_packet(BusinessProfile(), _opportunity(), approved=True)

        self.assertTrue(packet.approved)
        self.assertTrue(packet.owner_ready)
        self.assertTrue(any("Upload attachments" in step for step in packet.submission_steps))
        self.assertIn("The owner approved packet preparation", packet.summary)
        self.assertIn("proof of insurance", " ".join(packet.checklist))

    def test_approved_packet_uses_bid_brief(self) -> None:
        packet = create_approval_packet(BusinessProfile(), _opportunity(with_local_brief=True), approved=True)

        self.assertTrue(packet.approved)
        self.assertTrue(packet.owner_ready)
        self.assertTrue(any("Upload attachments" in step for step in packet.submission_steps))
        self.assertIn("Owner summary from bid brief", packet.summary)
        self.assertIn("Confirm site count", " ".join(packet.clarification_questions))
        self.assertIn("Subject: Clarification for RFQ-123", packet.draft_email)

    def test_packet_accepts_service_layer_dicts(self) -> None:
        opportunity = _opportunity().to_dict()
        profile = BusinessProfile().to_dict()

        packet = create_approval_packet(profile, opportunity, approved=True)

        self.assertEqual(packet.opportunity_id, "RFQ-123")
        self.assertEqual(packet.buyer_contact["email"], "buyer@toronto.ca")


def _opportunity(with_local_brief: bool = False) -> EvaluatedOpportunity:
    opportunity = EvaluatedOpportunity(
        solicitation=Solicitation(
            document_number="RFQ-123",
            solicitation_type="Request for Tender",
            category="Construction Services",
            description="Road and sidewalk repair",
            division="Transportation Services",
            issue_date=date(2026, 5, 30),
            submission_deadline=date(2026, 6, 18),
            buyer_name="City Buyer",
            buyer_email="buyer@toronto.ca",
            buyer_phone="416-555-0100",
        ),
        label="Pursue",
        rank_score=91,
        matched_terms=["road repairs", "sidewalk repairs"],
        missing_requirements=["proof of insurance"],
        reasons=["RFT format fits civil contractor capacity"],
        days_until_deadline=19,
        historical=HistoricalComparison(similar_count=3, award_min=30000, award_median=65000, award_max=90000),
    )
    if with_local_brief:
        opportunity.opportunity_brief = OpportunityBrief(
            source="deterministic_bid_brief",
            owner_summary="Owner summary from bid brief.",
            fit_reason="Fits the civil crew's road repair lane.",
            required_documents=["insurance", "WSIB"],
            missing_items=["proof of insurance"],
            clarification_questions=["Confirm site count and traffic staging requirements."],
            next_steps=["Confirm pricing.", "Assign estimator."],
            buyer_email_draft="Subject: Clarification for RFQ-123\n\nHello City Buyer,\n\nCan you confirm site count?\n\nThank you,\nHarbourfront Civil Works Ltd.",
        )
    return opportunity


if __name__ == "__main__":
    unittest.main()
