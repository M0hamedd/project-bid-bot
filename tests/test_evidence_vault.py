from __future__ import annotations

import base64
import tempfile
import unittest

import fitz

from contract_radar.evidence_vault import evidence_inventory_for_profile
from contract_radar.service import ContractRadarService


class EvidenceVaultTests(unittest.TestCase):
    def test_profile_seeded_vault_contains_core_company_evidence(self) -> None:
        inventory = evidence_inventory_for_profile(
            {
                "profile_id": "road_civil_infrastructure",
                "insurance_coverage": "$5M CGL and automobile liability",
                "bonding_single_job_limit": 2_000_000,
                "ready_documents": ["WSIB clearance", "traffic control plan"],
                "certifications": ["Book 7 traffic control supervisors"],
                "recent_municipal_work": ["sidewalk bay replacements"],
            },
            now="2026-06-03T12:00:00Z",
        )

        evidence_types = {record["evidence_type"] for record in inventory["records"]}
        self.assertIn("insurance_certificate", evidence_types)
        self.assertIn("bonding_capacity", evidence_types)
        self.assertIn("safety_document", evidence_types)
        self.assertIn("certification", evidence_types)
        self.assertIn("reference_project", evidence_types)
        self.assertTrue(all(record["evidence_id"].startswith("EVD-") for record in inventory["records"]))

    def test_uploaded_pdf_uses_profile_vault_to_resolve_known_evidence(self) -> None:
        pdf_bytes = _pdf_bytes(
            [
                "Bidders must provide proof of commercial general liability insurance.",
                "Bidders must provide WSIB clearance and a traffic control plan.",
                "Bidders shall submit the completed pricing form with unit prices.",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ContractRadarService(document_storage_dir=tmpdir).analyze_document(
                {
                    "filename": "road-rfq.pdf",
                    "opportunity_id": "RFQ-EVD",
                    "profile_id": "road_civil_infrastructure",
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        by_category = {row["category"]: row for row in result["compliance_matrix"]}
        self.assertTrue(by_category["insurance"]["resolved"])
        self.assertTrue(by_category["safety"]["resolved"])
        self.assertFalse(by_category["pricing_sheet"]["resolved"])
        self.assertEqual(result["bid_state"], "evidence_gaps_open")
        self.assertIn("evidence_vault", {fact["source_type"] for fact in result["evidence_ledger"]})
        vault_facts = [fact for fact in result["evidence_ledger"] if fact["source_type"] == "evidence_vault"]
        self.assertTrue(all(fact["value"]["evidence_id"] for fact in vault_facts))

    def test_expired_persisted_vault_record_does_not_resolve_requirement(self) -> None:
        pdf_bytes = _pdf_bytes(["Bidders must provide a municipal contractor license."])
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(document_storage_dir=tmpdir)
            service._evidence_vault_records = {
                "expired-license": {
                    "evidence_id": "EVD-EXPIRED",
                    "profile_id": "custom",
                    "evidence_type": "license",
                    "label": "Expired municipal contractor license",
                    "capability_tags": ["license", "permit"],
                    "verified_status": "user_confirmed",
                    "expires_at": "2000-01-01",
                }
            }
            result = service.analyze_document(
                {
                    "filename": "custom-rfq.pdf",
                    "opportunity_id": "RFQ-OLD",
                    "business_profile": {
                        "profile_id": "custom",
                        "name": "Custom Contractor",
                        "insurance_coverage": "",
                        "bonding_single_job_limit": 0,
                        "ready_documents": [],
                        "certifications": [],
                        "recent_municipal_work": [],
                    },
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        row = result["compliance_matrix"][0]
        self.assertFalse(row["resolved"])
        self.assertEqual(row["uploaded_evidence"], [])
        self.assertNotIn("evidence_vault", {fact["source_type"] for fact in result["evidence_ledger"]})

    def test_upload_and_attach_evidence_resolves_server_requirement(self) -> None:
        pdf_bytes = _pdf_bytes(["Bidders must provide a municipal contractor license."])
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(document_storage_dir=tmpdir, local_state_dir=tmpdir)
            analysis = service.analyze_document(
                {
                    "filename": "license-rfq.pdf",
                    "opportunity_id": "RFQ-LIC",
                    "business_profile": _custom_profile(),
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )
            row = analysis["compliance_matrix"][0]
            self.assertFalse(row["resolved"])

            uploaded = service.upload_evidence(
                {
                    "business_profile": _custom_profile(),
                    "filename": "municipal-license.txt",
                    "label": "Municipal contractor license",
                    "evidence_type": "license",
                    "capability_tags": ["license", "municipal contractor license"],
                    "content_base64": base64.b64encode(b"municipal license evidence").decode("ascii"),
                }
            )
            updated = service.attach_evidence_to_requirement(
                {
                    "analysis_id": analysis["analysis_id"],
                    "requirement_id": row["requirement_id"],
                    "evidence_id": uploaded["evidence"]["evidence_id"],
                }
            )

        self.assertEqual(updated["bid_state"], "owner_packet_ready")
        self.assertTrue(updated["compliance_summary"]["ready_to_prepare"])
        self.assertFalse(updated["agent_tasks"])
        attached = updated["compliance_matrix"][0]["uploaded_evidence"][0]
        self.assertEqual(attached["type"], "vault_evidence")
        self.assertEqual(attached["evidence_id"], uploaded["evidence"]["evidence_id"])
        self.assertIn("evidence_vault", {fact["source_type"] for fact in updated["evidence_ledger"]})

    def test_uploaded_evidence_is_reused_by_later_analysis(self) -> None:
        pdf_bytes = _pdf_bytes(["Bidders must provide a municipal contractor license."])
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(document_storage_dir=tmpdir, local_state_dir=tmpdir)
            uploaded = service.upload_evidence(
                {
                    "business_profile": _custom_profile(),
                    "filename": "municipal-license.txt",
                    "label": "Municipal contractor license",
                    "evidence_type": "license",
                    "capability_tags": ["license", "municipal contractor license"],
                    "content_base64": base64.b64encode(b"municipal license evidence").decode("ascii"),
                }
            )

            reloaded = ContractRadarService(document_storage_dir=tmpdir, local_state_dir=tmpdir)
            result = reloaded.analyze_document(
                {
                    "filename": "license-rfq.pdf",
                    "opportunity_id": "RFQ-LIC-2",
                    "business_profile": _custom_profile(),
                    "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            )

        row = result["compliance_matrix"][0]
        self.assertTrue(row["resolved"])
        self.assertEqual(row["uploaded_evidence"][0]["evidence_id"], uploaded["evidence"]["evidence_id"])
        self.assertEqual(result["bid_state"], "owner_packet_ready")


def _pdf_bytes(pages: list[str]) -> bytes:
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page(width=420, height=160)
            page.insert_text((36, 48), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def _custom_profile() -> dict:
    return {
        "profile_id": "custom",
        "name": "Custom Contractor",
        "business_type": "municipal services contractor",
        "ready_documents": [],
        "certifications": [],
        "recent_municipal_work": [],
    }


if __name__ == "__main__":
    unittest.main()
