from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_radar.demo import DEFAULT_DOCUMENT_DIR, DEFAULT_FIXTURE, DEFAULT_STATE_DIR, run_golden_demo
from contract_radar.service import ContractRadarService


def run_agent_demo(
    argv: Sequence[str] | None = None,
    *,
    service_factory=ContractRadarService,
) -> dict:
    args = _parser().parse_args(argv)
    return run_golden_demo(
        fixture=args.fixture,
        state_dir=args.state_dir,
        document_dir=args.document_dir,
        reset=bool(args.reset),
        max_steps=int(args.max_steps),
        estimator=str(args.estimator or "Demo Estimator"),
        approved_by=str(args.approved_by or ""),
        note=args.note,
        skip_owner_approval=bool(args.skip_owner_approval),
        service_factory=service_factory,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run_agent_demo(argv)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic golden Project Bid Bot agent demo.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Path to the golden demo fixture JSON.")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Local state directory for the demo run.")
    parser.add_argument("--document-dir", default=str(DEFAULT_DOCUMENT_DIR), help="Document storage directory for the demo run.")
    parser.add_argument("--reset", action="store_true", help="Delete the demo state/document dirs before running.")
    parser.add_argument("--max-steps", type=int, default=4, help="Maximum safe task executions in the agent loop.")
    parser.add_argument("--estimator", default="Demo Estimator", help="Estimator name for pricing approval.")
    parser.add_argument("--approved-by", default="", help="Owner name for owner approval.")
    parser.add_argument("--note", default=None, help="Owner approval note.")
    parser.add_argument("--skip-owner-approval", action="store_true", help="Stop after generating the owner approval request.")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
