from __future__ import annotations

import unittest

from contract_radar.opportunity_monitor import (
    EVENT_ADDENDUM_DETECTED,
    EVENT_DEADLINE_CHANGED,
    EVENT_NEW_OPPORTUNITY,
    EVENT_OPPORTUNITY_CLOSED,
    EVENT_PACKAGE_AVAILABLE,
    build_opportunity_snapshots,
    detect_opportunity_changes,
    monitor_scan_changes,
)


class OpportunityMonitorTests(unittest.TestCase):
    def test_first_sighting_records_new_opportunity_and_package_candidate(self) -> None:
        scan = _scan_result(_opportunity(source_links={"package_url": "https://example.test/rfq.pdf"}))

        result = monitor_scan_changes(scan, now="2026-06-03T12:00:00Z")
        event_types = [event["event_type"] for event in result["opportunity_change_events"]]

        self.assertIn(EVENT_NEW_OPPORTUNITY, event_types)
        self.assertIn(EVENT_PACKAGE_AVAILABLE, event_types)
        self.assertEqual(result["monitor_summary"][EVENT_PACKAGE_AVAILABLE], 1)
        snapshot = result["opportunity_snapshots"]["RFQ-123"]
        self.assertEqual(snapshot["candidate_public_package_urls"], ["https://example.test/rfq.pdf"])

    def test_deadline_change_is_detected_from_snapshots(self) -> None:
        previous = build_opportunity_snapshots(_scan_result(_opportunity(deadline="2026-06-08")))
        current = build_opportunity_snapshots(_scan_result(_opportunity(deadline="2026-06-10")))

        events = detect_opportunity_changes(current, previous, now="2026-06-04T12:00:00Z")
        deadline = next(event for event in events if event["event_type"] == EVENT_DEADLINE_CHANGED)

        self.assertEqual(deadline["old_value"], "2026-06-08")
        self.assertEqual(deadline["new_value"], "2026-06-10")

    def test_addendum_marker_is_detected_when_it_appears(self) -> None:
        previous = build_opportunity_snapshots(_scan_result(_opportunity()))
        current = build_opportunity_snapshots(
            _scan_result(
                _opportunity(extra={"buyer_note": "Addendum 1 posted with revised quantities."})
            )
        )

        events = detect_opportunity_changes(current, previous, now="2026-06-04T12:00:00Z")
        addendum = next(event for event in events if event["event_type"] == EVENT_ADDENDUM_DETECTED)

        self.assertIn("Addendum 1", addendum["new_value"])

    def test_missing_current_opportunity_is_marked_closed(self) -> None:
        previous = build_opportunity_snapshots(_scan_result(_opportunity()))
        current = build_opportunity_snapshots(_scan_result())

        events = detect_opportunity_changes(current, previous, now="2026-06-04T12:00:00Z")

        self.assertEqual(events[0]["event_type"], EVENT_OPPORTUNITY_CLOSED)
        self.assertEqual(events[0]["opportunity_id"], "RFQ-123")


def _scan_result(*opportunities: dict) -> dict:
    return {
        "as_of": "2026-06-03",
        "business_profile": {"profile_id": "road_civil_infrastructure"},
        "top_opportunities": list(opportunities),
        "watchlist": [],
        "all_evaluated": [],
        "skipped": [],
    }


def _opportunity(
    *,
    deadline: str = "2026-06-08",
    source_links: dict | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "label": "Pursue",
        "solicitation": {
            "document_number": "RFQ-123",
            "description": "Road repair and sidewalk restoration",
            "submission_deadline": deadline,
            "division": "Transportation Services",
            "buyer_name": "City Buyer",
            "source_links": source_links or {"source_label": "Open Data"},
        },
    }
    if extra:
        payload.update(extra)
    return payload


if __name__ == "__main__":
    unittest.main()
