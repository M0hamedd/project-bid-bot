from __future__ import annotations

import contextlib
import io
import json
import unittest
from typing import Any

from scripts.approve_owner_request import approve_owner_request_cli, main


class OwnerApprovalCliTests(unittest.TestCase):
    def test_payload_shape_uses_only_request_id_approved_by_and_note(self) -> None:
        approvals: list[dict[str, Any]] = []

        def service_factory() -> _FakeOwnerApprovalService:
            return _FakeOwnerApprovalService(approvals)

        result = approve_owner_request_cli(
            [
                "--approval-request-id",
                "approval-request-123",
                "--approved-by",
                "Casey Owner",
                "--note",
                "Approved target bid.",
            ],
            service_factory=service_factory,
        )

        self.assertEqual(result["status"], "approved")
        self.assertEqual(
            approvals,
            [
                {
                    "approval_request_id": "approval-request-123",
                    "approved_by": "Casey Owner",
                    "note": "Approved target bid.",
                }
            ],
        )
        self.assertEqual(set(approvals[0]), {"approval_request_id", "approved_by", "note"})

    def test_state_dir_is_passed_to_factory_when_supported(self) -> None:
        calls: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []

        def service_factory(local_state_dir: str | None = None) -> _FakeOwnerApprovalService:
            calls.append({"local_state_dir": local_state_dir})
            return _FakeOwnerApprovalService(approvals)

        approve_owner_request_cli(
            [
                "--approval-request-id",
                "approval-request-state",
                "--state-dir",
                "C:\\tmp\\owner-approval-state",
            ],
            service_factory=service_factory,
        )

        self.assertEqual(calls, [{"local_state_dir": "C:\\tmp\\owner-approval-state"}])

    def test_state_dir_is_ignored_when_factory_does_not_support_it(self) -> None:
        approvals: list[dict[str, Any]] = []

        def service_factory() -> _FakeOwnerApprovalService:
            return _FakeOwnerApprovalService(approvals)

        result = approve_owner_request_cli(
            [
                "--approval-request-id",
                "approval-request-no-state",
                "--state-dir",
                "C:\\tmp\\unused-state",
            ],
            service_factory=service_factory,
        )

        self.assertEqual(result["approval_request_id"], "approval-request-no-state")

    def test_missing_approval_request_id_raises_system_exit(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                approve_owner_request_cli([], service_factory=_unused_service_factory)

        self.assertNotEqual(raised.exception.code, 0)

    def test_unrecognized_analysis_or_compliance_args_raise_system_exit(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                approve_owner_request_cli(
                    [
                        "--approval-request-id",
                        "approval-request-123",
                        "--analysis-rows",
                        "[]",
                    ],
                    service_factory=_unused_service_factory,
                )
            with self.assertRaises(SystemExit):
                approve_owner_request_cli(
                    [
                        "--approval-request-id",
                        "approval-request-123",
                        "--compliance-rows",
                        "[]",
                    ],
                    service_factory=_unused_service_factory,
                )

    def test_main_returns_nonzero_and_writes_value_error_to_stderr(self) -> None:
        def service_factory() -> _FailingOwnerApprovalService:
            return _FailingOwnerApprovalService("Owner approval request fake is not pending.")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--approval-request-id", "fake"], service_factory=service_factory)

        self.assertEqual(exit_code, 1)
        self.assertIn("not pending", stderr.getvalue())

    def test_main_prints_json_result(self) -> None:
        approvals: list[dict[str, Any]] = []

        def service_factory() -> _FakeOwnerApprovalService:
            return _FakeOwnerApprovalService(approvals)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                ["--approval-request-id", "approval-request-json", "--json"],
                service_factory=service_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("\n  ", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["approval_request_id"], "approval-request-json")


class _FakeOwnerApprovalService:
    def __init__(self, approvals: list[dict[str, Any]]) -> None:
        self._approvals = approvals

    def approve_owner_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._approvals.append(dict(payload))
        return {
            "status": "approved",
            "approval_request_id": payload["approval_request_id"],
            "owner_approval_request": dict(payload),
        }


class _FailingOwnerApprovalService:
    def __init__(self, message: str) -> None:
        self._message = message

    def approve_owner_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(self._message)


def _unused_service_factory() -> _FakeOwnerApprovalService:
    raise AssertionError("service factory should not be called")


if __name__ == "__main__":
    unittest.main()
