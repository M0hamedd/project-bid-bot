from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_bid_flow import evaluate_fixture_directory


class BidFlowEvaluationTests(unittest.TestCase):
    def test_bid_flow_fixtures_pass_trust_metrics(self) -> None:
        report = evaluate_fixture_directory()
        summary = report["summary"]

        self.assertTrue(summary["passed"], report["failures"])
        self.assertEqual(summary["fixture_count"], 6)
        self.assertEqual(summary["category_recall"], 1.0)
        self.assertEqual(summary["citation_coverage"], 1.0)
        self.assertEqual(summary["false_packet_ready_count"], 0)
        self.assertEqual(summary["uncited_pdf_fact_count"], 0)
        self.assertEqual(summary["false_hard_stop_clearance_count"], 0)
        self.assertEqual(summary["pricing_sanity_failure_count"], 0)

    def test_evaluation_fails_when_expected_hard_stop_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "fixture_id": "broken",
                        "profile_id": "road_civil_infrastructure",
                        "chunks": [
                            {
                                "source": "broken.pdf",
                                "page_number": 1,
                                "chunk_id": "p1",
                                "text": "Bidders must provide proof of commercial general liability insurance.",
                            }
                        ],
                        "expected": {
                            "categories": ["site_visit"],
                            "hard_stop_categories": ["site_visit"],
                            "bid_state": "evidence_gaps_open",
                            "allow_packet_ready": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_fixture_directory(path.parent)

        self.assertFalse(report["summary"]["passed"])
        self.assertTrue(any("missing expected requirement category site_visit" in item for item in report["failures"]))
        self.assertTrue(any("missing expected hard-stop gate for site_visit" in item for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
