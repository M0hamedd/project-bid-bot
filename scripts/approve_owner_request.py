from __future__ import annotations

import argparse
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_radar.service import ContractRadarService


ServiceFactory = Callable[..., Any]


@dataclass(frozen=True)
class _CliRun:
    result: dict[str, Any]
    pretty_json: bool


def approve_owner_request_cli(
    argv: Sequence[str] | None = None,
    service_factory: ServiceFactory = ContractRadarService,
) -> dict[str, Any]:
    """Approve a server-owned owner approval request by request id."""
    return _run(argv, service_factory).result


def main(
    argv: Sequence[str] | None = None,
    service_factory: ServiceFactory = ContractRadarService,
) -> int:
    try:
        run = _run(argv, service_factory)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(_format_json(run.result, pretty=run.pretty_json))
    return 0


def _run(argv: Sequence[str] | None, service_factory: ServiceFactory) -> _CliRun:
    args = _parser().parse_args(argv)
    service = _build_service(service_factory, args.state_dir)
    payload = {
        "approval_request_id": args.approval_request_id,
        "approved_by": args.approved_by,
        "note": args.note,
    }
    return _CliRun(
        result=service.approve_owner_request(payload),
        pretty_json=bool(args.json),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Approve a pending owner approval request by server-generated request id."
    )
    parser.add_argument(
        "--approval-request-id",
        required=True,
        help="Server-generated owner approval request id.",
    )
    parser.add_argument(
        "--approved-by",
        default="Owner",
        help="Approver name recorded on the owner approval. Default: Owner",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional approval note. Default: empty",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Optional local state directory passed to the service factory when supported.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Pretty print the JSON result.",
    )
    return parser


def _build_service(service_factory: ServiceFactory, state_dir: str | None) -> Any:
    kwargs: dict[str, Any] = {}
    if state_dir and _supports_local_state_dir(service_factory):
        kwargs["local_state_dir"] = state_dir
    return service_factory(**kwargs)


def _supports_local_state_dir(service_factory: ServiceFactory) -> bool:
    try:
        parameters = inspect.signature(service_factory).parameters.values()
    except (TypeError, ValueError):
        return True

    for parameter in parameters:
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == "local_state_dir" and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return True
    return False


def _format_json(payload: dict[str, Any], pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, indent=2, sort_keys=True)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
