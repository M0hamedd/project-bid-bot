from __future__ import annotations

import unittest

from contract_radar.form_blueprint import build_form_blueprint
from contract_radar.models import BusinessProfile
from contract_radar.packet import create_approval_packet
from tests.test_packet import _opportunity


CREATED_AT = "2026-06-04T12:00:00Z"


class FormBlueprintTests(unittest.TestCase):
    def test_ready_packet_builds_copyable_form_blueprint(self) -> None:
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
            pricing_worksheet=_approved_pricing(),
        ).to_dict()

        blueprint = build_form_blueprint(packet, created_at=CREATED_AT)

        self.assertEqual(
            set(blueprint),
            {
                "source",
                "blueprint_id",
                "created_at",
                "opportunity_id",
                "ready_for_form_work",
                "form_fields",
                "attachments",
                "manual_steps",
                "blockers",
                "guardrails",
            },
        )
        self.assertTrue(blueprint["ready_for_form_work"])
        self.assertEqual(blueprint["blockers"], [])
        fields = {field["field_id"]: field["value"] for field in blueprint["form_fields"]}
        self.assertEqual(fields["company_name"], "Harbourfront Civil Works Ltd.")
        self.assertEqual(fields["opportunity_id"], "RFQ-123")
        self.assertEqual(fields["buyer_name"], "City Buyer")
        self.assertEqual(fields["buyer_email"], "buyer@toronto.ca")
        self.assertEqual(fields["approved_target_bid"], "$760,000")
        self.assertEqual(fields["deadline"], "2026-06-18")
        self.assertTrue(blueprint["attachments"])
        self.assertTrue(any("no_submission" in item for item in blueprint["guardrails"]))
        self.assertTrue(any("no_buyer_email" in item for item in blueprint["guardrails"]))
        self.assertTrue(any("no_invented_fields" in item for item in blueprint["guardrails"]))

    def test_blocked_packet_reports_required_blockers(self) -> None:
        blueprint = build_form_blueprint(
            {
                "owner_ready": False,
                "opportunity_id": "RFQ-BLOCKED",
                "submission_manifest": [],
                "submission_manifest_summary": {"total": 1, "required_open": 1},
                "submission_assembly": {"summary": {"attachments": 1}, "attachments": []},
            },
            created_at=CREATED_AT,
        )

        blocker_ids = {item["blocker_id"] for item in blueprint["blockers"]}
        self.assertFalse(blueprint["ready_for_form_work"])
        self.assertIn("owner_ready_false", blocker_ids)
        self.assertIn("manifest_required_open", blocker_ids)
        self.assertIn("pricing_worksheet_missing", blocker_ids)
        self.assertIn("approved_target_bid_missing", blocker_ids)
        self.assertIn("attachments_missing", blocker_ids)

    def test_manifest_rows_become_attachment_blueprint_rows(self) -> None:
        blueprint = build_form_blueprint(
            {
                "owner_ready": True,
                "opportunity_id": "RFQ-MANIFEST",
                "pricing_worksheet": _approved_pricing(),
                "submission_manifest_summary": {"total": 1, "required_open": 0},
                "submission_manifest": [
                    {
                        "manifest_id": "manifest-insurance",
                        "item_type": "insurance_certificate",
                        "label": "Insurance certificate",
                        "required": True,
                        "status": "ready",
                        "evidence_ids": ["ev-ins"],
                        "citation": {"source": "rfq.pdf", "page": 2, "snippet": "insurance certificate"},
                    }
                ],
            },
            created_at=CREATED_AT,
        )

        attachment = blueprint["attachments"][0]
        self.assertEqual(attachment["source"], "submission_manifest")
        self.assertEqual(attachment["label"], "Insurance certificate")
        self.assertEqual(attachment["status"], "ready")
        self.assertEqual(attachment["evidence_ids"], ["ev-ins"])
        self.assertEqual(attachment["citation"]["page"], 2)

    def test_assembly_rows_become_attachment_blueprint_rows(self) -> None:
        blueprint = build_form_blueprint(
            {
                "owner_ready": True,
                "opportunity_id": "RFQ-ASSEMBLY",
                "pricing_worksheet": _approved_pricing(),
                "submission_manifest_summary": {"total": 0, "required_open": 0},
                "submission_assembly": {
                    "attachments": [
                        {
                            "attachment_id": "attachment-addendum",
                            "label": "Public addendum: Addendum 1",
                            "status": "ready",
                            "filename": "addendum-1.pdf",
                            "evidence_ids": [],
                            "citation": {"source": "https://example.test/addendum-1.pdf", "snippet": "Addendum 1"},
                        }
                    ],
                    "summary": {"attachments": 1},
                },
            },
            created_at=CREATED_AT,
        )

        self.assertEqual(blueprint["attachments"][0]["attachment_id"], "attachment-addendum")
        self.assertEqual(blueprint["attachments"][0]["source"], "submission_assembly")
        self.assertEqual(blueprint["attachments"][0]["filename"], "addendum-1.pdf")
        self.assertTrue(blueprint["ready_for_form_work"])

    def test_blueprint_id_is_stable_for_same_inputs_and_created_at(self) -> None:
        payload = {
            "owner_ready": True,
            "opportunity_id": "RFQ-STABLE",
            "business_profile": {"name": "Stable Civil Ltd."},
            "buyer_contact": {"name": "Buyer", "email": "buyer@example.test"},
            "pricing_worksheet": _approved_pricing(),
            "submission_manifest_summary": {"total": 0, "required_open": 0},
            "submission_manifest": [],
        }

        first = build_form_blueprint(payload, created_at=CREATED_AT)
        second = build_form_blueprint(payload, created_at=CREATED_AT)

        self.assertEqual(first["blueprint_id"], second["blueprint_id"])


def _approved_pricing() -> dict:
    return {
        "source": "deterministic_pricing_worksheet",
        "status": "estimator_approved",
        "target_bid": 760000,
        "low_bid": 700000,
        "high_bid": 820000,
        "confidence": "Moderate",
        "estimator_approval_status": "approved",
        "can_use_for_owner_packet": True,
        "estimator_approval": {
            "approval_id": "pricing-approval-test",
            "status": "approved",
            "approved_target_bid": 760000,
            "approved_by": "Estimator",
            "approved_at": "2026-06-04T11:00:00Z",
        },
    }


if __name__ == "__main__":
    unittest.main()
