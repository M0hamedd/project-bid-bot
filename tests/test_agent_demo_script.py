from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contract_radar.service import ContractRadarService
from scripts.run_agent_demo import DEFAULT_FIXTURE, run_agent_demo


class AgentDemoScriptTests(unittest.TestCase):
    def test_golden_demo_runs_until_owner_packet_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            document_dir = Path(tmpdir) / "documents"

            result = run_agent_demo(
                [
                    "--fixture",
                    str(DEFAULT_FIXTURE),
                    "--state-dir",
                    str(state_dir),
                    "--document-dir",
                    str(document_dir),
                ]
            )

            export_path = Path(result["approval"]["packet_export"]["storage_path"])
            self.assertTrue(export_path.exists())

        self.assertEqual(result["status"], "owner_packet_approved")
        self.assertEqual(result["analysis"]["priced_bid_state"], "owner_packet_ready")
        self.assertEqual(result["agent_loop"]["status"], "awaiting_owner_approval")
        self.assertEqual(result["rate_card_import"]["imported_count"], 3)
        self.assertEqual(result["form_blueprint"]["source"], "deterministic_form_blueprint")
        self.assertTrue(result["form_blueprint"]["ready_for_form_work"])
        self.assertEqual(result["form_blueprint_summary"]["blocker_count"], 0)
        self.assertEqual(
            result["highest_value_gap"],
            "authenticated_buyer_portal_submission_and_final_upload_remain_manual",
        )

    def test_service_golden_demo_returns_ui_ready_scan_and_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(
                document_storage_dir=Path(tmpdir) / "documents",
                local_state_dir=Path(tmpdir) / "state",
            )
            result = service.run_golden_demo({})

            export_path = Path(result["packet_export"]["storage_path"])
            self.assertTrue(export_path.exists())

        scan = result["scan"]
        self.assertEqual(result["status"], "owner_packet_approved")
        self.assertEqual(result["demo_summary"]["packet_export_ready"], True)
        self.assertEqual(scan["business_profile"]["profile_id"], "road_civil_infrastructure")
        self.assertTrue(scan["top_opportunities"])
        self.assertIn("RFQ-GOLDEN-ROAD", scan["document_analyses"])
        self.assertEqual(result["packet"]["agent_summary"]["bid_state"], "owner_packet_ready")
        self.assertTrue(result["packet_export"]["download_url"])


if __name__ == "__main__":
    unittest.main()
