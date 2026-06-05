from __future__ import annotations

import tempfile
import unittest

from contract_radar.daily_runner import run_daily_reconciliation
from contract_radar.state_store import SCHEMA_VERSION, LocalStateStore


class DailyRunnerTests(unittest.TestCase):
    def test_first_run_creates_stable_waiting_package_task(self) -> None:
        result = run_daily_reconciliation(_scan_result("2026-06-08"), {}, now="2026-06-03T12:00:00Z")

        run = result["daily_run"]
        tasks = result["agent_task_state"]
        task = next(iter(tasks.values()))
        inbox_item = result["daily_inbox"]["items"][0]

        self.assertEqual(run["opportunities_checked"], 1)
        self.assertEqual(len(run["new_tasks"]), 1)
        self.assertEqual(task["task_state"], "waiting_on_package")
        self.assertEqual(task["task_type"], "acquire_official_package")
        self.assertEqual(task["occurrence_count"], 1)
        self.assertEqual(inbox_item["agent_task_id"], task["task_id"])
        self.assertEqual(inbox_item["task_state"], "waiting_on_package")

    def test_second_identical_run_reuses_existing_task(self) -> None:
        first = run_daily_reconciliation(_scan_result("2026-06-08"), {}, now="2026-06-03T12:00:00Z")
        second = run_daily_reconciliation(
            _scan_result("2026-06-08"),
            {},
            previous_tasks=first["agent_task_state"],
            now="2026-06-04T12:00:00Z",
        )

        task = next(iter(second["agent_task_state"].values()))
        self.assertFalse(second["daily_run"]["new_tasks"])
        self.assertFalse(second["daily_run"]["changed_tasks"])
        self.assertEqual(task["occurrence_count"], 2)
        self.assertEqual(task["first_seen_at"], "2026-06-03T12:00:00Z")

    def test_deadline_change_is_changed_task_and_alert(self) -> None:
        first = run_daily_reconciliation(_scan_result("2026-06-08"), {}, now="2026-06-03T12:00:00Z")
        second = run_daily_reconciliation(
            _scan_result("2026-06-10"),
            {},
            previous_tasks=first["agent_task_state"],
            now="2026-06-04T12:00:00Z",
        )

        task = next(iter(second["agent_task_state"].values()))
        self.assertEqual(len(second["daily_run"]["changed_tasks"]), 1)
        self.assertEqual(second["daily_run"]["deadline_alerts"][0]["old_deadline"], "2026-06-08")
        self.assertEqual(second["daily_run"]["deadline_alerts"][0]["new_deadline"], "2026-06-10")
        self.assertEqual(task["change_reason"], "Submission deadline changed.")

    def test_resolved_old_task_is_marked_done_when_ready_task_replaces_it(self) -> None:
        first = run_daily_reconciliation(
            _scan_result("2026-06-08"),
            {
                "RFQ-123": {
                    "analysis_id": "analysis-metadata",
                    "bid_state": "metadata_intake",
                    "acquisition": {"status": "metadata_only"},
                    "agent_tasks": [{"task_id": "task-package", "task_type": "acquire_official_package"}],
                    "compliance_decision": {"label": "Review", "next_action": "Get Official Package"},
                }
            },
            now="2026-06-03T12:00:00Z",
        )
        second = run_daily_reconciliation(
            _scan_result("2026-06-08"),
            {
                "RFQ-123": {
                    "analysis_id": "analysis-ready",
                    "bid_state": "owner_packet_ready",
                    "compliance_decision": {"label": "Pursue", "next_action": "Prepare bid notes"},
                }
            },
            previous_tasks=first["agent_task_state"],
            now="2026-06-04T12:00:00Z",
        )

        states = {task["task_type"]: task["task_state"] for task in second["agent_task_state"].values()}
        self.assertEqual(states["acquire_official_package"], "done")
        self.assertEqual(states["owner_packet_approval"], "ready_for_owner")
        self.assertEqual(len(second["daily_run"]["resolved_tasks"]), 1)
        self.assertEqual(len(second["daily_run"]["new_tasks"]), 1)

    def test_daily_run_and_tasks_persist_with_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(tmpdir)
            result = run_daily_reconciliation(_scan_result("2026-06-08"), {}, now="2026-06-03T12:00:00Z")
            scan = _scan_result("2026-06-08")
            scan["daily_inbox"] = result["daily_inbox"]
            scan["daily_run"] = result["daily_run"]
            scan["agent_task_state"] = result["agent_task_state"]

            store.save_scan(scan)
            loaded = store.load()

        self.assertIn(result["daily_run"]["run_id"], loaded["daily_runs"])
        self.assertEqual(len(loaded["agent_tasks"]), 1)
        self.assertEqual(loaded["schema_version"], SCHEMA_VERSION)

    def test_monitor_events_are_folded_into_run_alerts(self) -> None:
        result = run_daily_reconciliation(
            _scan_result("2026-06-08"),
            {},
            opportunity_change_events=[
                {
                    "event_id": "change-deadline",
                    "event_type": "deadline_changed",
                    "opportunity_id": "RFQ-123",
                    "reason": "Submission deadline changed in source data.",
                    "old_value": "2026-06-08",
                    "new_value": "2026-06-10",
                    "detected_at": "2026-06-04T12:00:00Z",
                },
                {
                    "event_id": "change-package",
                    "event_type": "package_available",
                    "opportunity_id": "RFQ-123",
                    "reason": "Official package candidate became available.",
                    "old_value": "portal_login_required",
                    "new_value": "candidate_urls_found",
                    "detected_at": "2026-06-04T12:00:00Z",
                },
                {
                    "event_id": "change-addendum",
                    "event_type": "addendum_detected",
                    "opportunity_id": "RFQ-123",
                    "reason": "New addendum marker appeared in source data.",
                    "old_value": "",
                    "new_value": "Addendum 1",
                    "detected_at": "2026-06-04T12:00:00Z",
                },
            ],
            now="2026-06-04T12:00:00Z",
        )

        self.assertEqual(len(result["daily_run"]["deadline_alerts"]), 1)
        self.assertEqual(len(result["daily_run"]["package_alerts"]), 1)
        self.assertEqual(len(result["daily_run"]["addenda_alerts"]), 1)
        self.assertEqual(result["daily_inbox"]["run_summary"]["change_events"], 3)

    def test_closed_opportunity_event_marks_previous_active_task_done(self) -> None:
        first = run_daily_reconciliation(_scan_result("2026-06-08"), {}, now="2026-06-03T12:00:00Z")
        second = run_daily_reconciliation(
            _empty_scan_result(),
            {},
            previous_tasks=first["agent_task_state"],
            opportunity_change_events=[
                {
                    "event_id": "change-closed",
                    "event_type": "opportunity_closed",
                    "opportunity_id": "RFQ-123",
                    "reason": "Opportunity disappeared from the current scan result.",
                    "old_value": "Pursue",
                    "new_value": "not_in_current_scan",
                    "detected_at": "2026-06-04T12:00:00Z",
                }
            ],
            now="2026-06-04T12:00:00Z",
        )

        task = next(iter(second["agent_task_state"].values()))
        self.assertFalse(second["daily_inbox"]["items"])
        self.assertEqual(task["task_state"], "done")
        self.assertEqual(second["daily_run"]["resolved_tasks"], [task["task_id"]])
        self.assertEqual(len(second["daily_run"]["closed_opportunity_alerts"]), 1)
        self.assertEqual(second["daily_inbox"]["run_summary"]["closed_opportunities"], 1)
        self.assertEqual(task["change_reason"], "Opportunity closed or disappeared from the source data.")


def _scan_result(deadline: str) -> dict:
    return {
        "as_of": "2026-06-03",
        "priority_mode": "best_win_chance",
        "business_profile": {"profile_id": "road_civil_infrastructure"},
        "top_opportunities": [
            {
                "label": "Pursue",
                "days_until_deadline": 5,
                "solicitation": {
                    "document_number": "RFQ-123",
                    "description": "Road repair and sidewalk restoration",
                    "submission_deadline": deadline,
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


def _empty_scan_result() -> dict:
    return {
        "as_of": "2026-06-04",
        "priority_mode": "best_win_chance",
        "business_profile": {"profile_id": "road_civil_infrastructure"},
        "top_opportunities": [],
        "watchlist": [],
        "all_evaluated": [],
        "skipped": [],
    }


if __name__ == "__main__":
    unittest.main()
