from __future__ import annotations

import unittest

from contract_radar.inbox import build_daily_bid_inbox


class DailyBidInboxTests(unittest.TestCase):
    def test_scan_opportunity_without_package_becomes_get_package_task(self) -> None:
        inbox = build_daily_bid_inbox(_scan_result("Pursue"))

        self.assertEqual(inbox["summary"]["total"], 1)
        self.assertEqual(inbox["summary"]["needs_package"], 1)
        self.assertEqual(inbox["items"][0]["status"], "get_package")
        self.assertIn("official package", inbox["items"][0]["next_action"].lower())

    def test_server_analysis_state_promotes_ready_packet_items(self) -> None:
        inbox = build_daily_bid_inbox(
            _scan_result("Pursue"),
            {
                "RFQ-123": {
                    "analysis_id": "analysis-ready",
                    "bid_state": "owner_packet_ready",
                    "compliance_decision": {
                        "label": "Pursue",
                        "next_action": "Prepare bid notes",
                    },
                }
            },
        )

        self.assertEqual(inbox["summary"]["ready_for_packet"], 1)
        self.assertEqual(inbox["items"][0]["status"], "ready_for_packet")
        self.assertEqual(inbox["items"][0]["next_action"], "Prepare bid notes")

    def test_metadata_intake_stays_blocked_on_package(self) -> None:
        inbox = build_daily_bid_inbox(
            _scan_result("Pursue"),
            {
                "RFQ-123": {
                    "analysis_id": "analysis-metadata",
                    "bid_state": "metadata_intake",
                    "acquisition": {"status": "metadata_only"},
                    "agent_tasks": [{"title": "Get Official Package"}],
                    "compliance_decision": {
                        "label": "Review",
                        "next_action": "Get Official Package",
                    },
                }
            },
        )

        self.assertEqual(inbox["items"][0]["status"], "get_package")
        self.assertEqual(inbox["items"][0]["acquisition_status"], "metadata_only")
        self.assertEqual(inbox["summary"]["needs_action"], 1)

    def test_blocked_analysis_with_agent_task_stays_actionable(self) -> None:
        inbox = build_daily_bid_inbox(
            _scan_result("Pursue"),
            {
                "RFQ-123": {
                    "analysis_id": "analysis-stale",
                    "bid_state": "evidence_gaps_open",
                    "agent_tasks": [
                        {
                            "task_id": "task-source-change",
                            "task_type": "reanalyze_official_package",
                            "title": "Recheck Changed Source",
                        }
                    ],
                    "compliance_decision": {
                        "label": "Blocked",
                        "next_action": "Recheck Changed Source",
                        "reason": "An addendum marker appeared after this package was analyzed.",
                    },
                }
            },
        )

        self.assertEqual(inbox["items"][0]["status"], "resolve_gates")
        self.assertEqual(inbox["items"][0]["task_type"], "reanalyze_official_package")
        self.assertEqual(inbox["summary"]["needs_action"], 1)


def _scan_result(label: str) -> dict:
    return {
        "as_of": "2026-06-03",
        "business_profile": {"profile_id": "road_civil_infrastructure"},
        "top_opportunities": [
            {
                "label": label,
                "days_until_deadline": 5,
                "predicted_bid": 750000,
                "solicitation": {
                    "document_number": "RFQ-123",
                    "description": "Road repair and sidewalk restoration",
                    "submission_deadline": "2026-06-08",
                    "division": "Transportation Services",
                    "buyer_name": "City Buyer",
                },
                "pricing_breakdown": {
                    "recommended_bid": 760000,
                    "expected_profit": 90000,
                    "win_probability": 0.42,
                },
            }
        ],
        "watchlist": [],
        "all_evaluated": [],
        "skipped": [],
    }


if __name__ == "__main__":
    unittest.main()
