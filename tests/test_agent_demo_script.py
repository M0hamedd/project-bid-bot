from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
