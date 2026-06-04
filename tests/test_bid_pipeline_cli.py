from __future__ import annotations

import unittest

from scripts.run_bid_pipeline import run_bid_pipeline_cli


class BidPipelineCliTests(unittest.TestCase):
    def test_cli_builds_agent_pipeline_payload(self) -> None:
        result = run_bid_pipeline_cli(
            [
                "--profile-id",
                "road_civil_infrastructure",
                "--max-steps",
                "3",
                "--approval-request-id",
                "approval-request-1",
                "--approved-by",
                "Owner",
                "--note",
                "Approved.",
                "--state-dir",
                "demo-state",
            ],
            service_factory=FakePipelineService,
        )

        payload = result["payload"]
        self.assertEqual(result["state_dir"], "demo-state")
        self.assertEqual(payload["profile_id"], "road_civil_infrastructure")
        self.assertEqual(payload["max_steps"], 3)
        self.assertEqual(payload["approval_request_ids"], ["approval-request-1"])
        self.assertEqual(payload["approved_by"], "Owner")
        self.assertEqual(payload["note"], "Approved.")


class FakePipelineService:
    def __init__(self, local_state_dir: str | None = None) -> None:
        self.local_state_dir = local_state_dir

    def run_agent_pipeline(self, payload: dict) -> dict:
        return {
            "payload": payload,
            "state_dir": self.local_state_dir,
        }


if __name__ == "__main__":
    unittest.main()
