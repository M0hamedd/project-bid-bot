from __future__ import annotations

import unittest

from contract_radar.owner_approval_reports import owner_approval_actions


class OwnerApprovalReportTests(unittest.TestCase):
    def test_builds_bounded_owner_approval_action(self) -> None:
        actions = owner_approval_actions(
            {
                "source": "owner_approval_decision_report",
                "approval_request_id": "approval-request-1",
                "approved": True,
                "approved_by": "Owner",
                "note": "Approved.",
                "analysis_id": "fake-analysis",
                "compliance_rows": [{"requirement_id": "fake"}],
            }
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["endpoint"], "/api/owner-approval/approve")
        self.assertEqual(
            actions[0]["payload"],
            {
                "approval_request_id": "approval-request-1",
                "approved": True,
                "approved_by": "Owner",
                "note": "Approved.",
            },
        )

    def test_skips_unfilled_templates_when_requested(self) -> None:
        self.assertEqual(
            owner_approval_actions(
                {
                    "source": "owner_approval_decision_report",
                    "template": True,
                    "approval_request_id": "approval-request-1",
                    "approved": False,
                },
                skip_templates=True,
            ),
            [],
        )

    def test_rejects_unapproved_report(self) -> None:
        with self.assertRaisesRegex(ValueError, "approved=true"):
            owner_approval_actions(
                {
                    "source": "owner_approval_decision_report",
                    "approval_request_id": "approval-request-1",
                    "approved": False,
                }
            )


if __name__ == "__main__":
    unittest.main()
