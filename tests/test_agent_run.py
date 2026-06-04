from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from contract_radar.service import ContractRadarService
from tests.test_persistence import _approval_scan


class AgentRunTests(unittest.TestCase):
    def test_agent_run_intakes_company_scans_and_returns_human_required_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)

            def fake_scan(payload: dict) -> dict:
                scan = _approval_scan("RFQ-AGENT")
                if isinstance(payload.get("business_profile"), dict):
                    scan["business_profile"] = copy.deepcopy(payload["business_profile"])
                service._auto_start_intake_sessions(scan, scan["business_profile"])
                hydrated = service._scan_with_runtime_state(scan)
                service._last_scan = copy.deepcopy(hydrated)
                return hydrated

            with patch.object(service, "scan", side_effect=fake_scan):
                result = service.run_agent(
                    {
                        "company": {
                            "name": "Agent Civil Ltd.",
                            "services": ["road repair", "sidewalk repair"],
                            "ready_documents": ["insurance", "WSIB"],
                            "insurance_coverage": "$5M CGL",
                            "bonding_single_job_limit": 1_500_000,
                            "owned_equipment": ["dump truck"],
                            "recent_municipal_work": ["curb repairs"],
                            "team_size": 12,
                            "max_contract_value": 1_200_000,
                            "pricing_rate_card": [
                                {
                                    "label": "Asphalt milling",
                                    "keywords": ["asphalt", "milling"],
                                    "unit": "m2",
                                    "unit_direct_cost": 18,
                                }
                            ],
                        },
                        "max_auto_actions": 0,
                    }
                )

        run = result["agent_run"]
        self.assertEqual(run["status"], "waiting_on_human_input")
        self.assertEqual(result["business_profile"]["name"], "Agent Civil Ltd.")
        self.assertIn("No bid was submitted.", run["guardrails"])
        self.assertEqual(run["approval_required_count"], 0)
        self.assertGreaterEqual(run["human_action_count"], 1)
        self.assertEqual(run["human_required_actions"][0]["task_type"], "acquire_official_package")
        self.assertIn("company_intake_completed", [action["action_type"] for action in run["automatic_actions"]])
        self.assertIn("scan_completed", [action["action_type"] for action in run["automatic_actions"]])

    def test_agent_run_acquires_direct_public_package_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            acquired_payloads: list[dict] = []

            def fake_scan(payload: dict) -> dict:
                scan = _approval_scan("RFQ-DIRECT")
                for item in [*scan["top_opportunities"], *scan["all_evaluated"]]:
                    item["solicitation"]["source_links"]["package_pdf_url"] = "https://example.test/rfq-direct.pdf"
                service._auto_start_intake_sessions(scan, scan["business_profile"])
                hydrated = service._scan_with_runtime_state(scan)
                service._last_scan = copy.deepcopy(hydrated)
                return hydrated

            def fake_acquire(payload: dict) -> dict:
                acquired_payloads.append(copy.deepcopy(payload))
                return {
                    "analysis_id": "analysis-direct",
                    "opportunity_id": payload["opportunity_id"],
                    "business_profile": {"profile_id": "road_civil_infrastructure"},
                    "bid_state": "evidence_gaps_open",
                    "document": {"filename": "rfq-direct.pdf"},
                    "acquisition": {
                        "status": "package_fetched",
                        "message": "Official package was fetched from a direct public PDF URL.",
                    },
                }

            with patch.object(service, "scan", side_effect=fake_scan):
                with patch.object(service, "acquire_document", side_effect=fake_acquire):
                    result = service.run_agent(
                        {
                            "profile_id": "road_civil_infrastructure",
                            "max_auto_actions": 2,
                        }
                    )

        run = result["agent_run"]
        self.assertEqual(len(acquired_payloads), 1)
        self.assertEqual(acquired_payloads[0]["opportunity_id"], "RFQ-DIRECT")
        self.assertIn("official_package_acquisition_checked", [action["action_type"] for action in run["automatic_actions"]])
        acquisition_action = next(
            action for action in run["automatic_actions"]
            if action["action_type"] == "official_package_acquisition_checked"
        )
        self.assertEqual(acquisition_action["status"], "package_fetched")

    def test_agent_run_rechecks_stale_source_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ContractRadarService(local_state_dir=tmpdir)
            rechecked_payloads: list[dict] = []

            def fake_scan(payload: dict) -> dict:
                scan = _approval_scan("RFQ-STALE-RUN")
                analysis = {
                    "analysis_id": "analysis-stale-run",
                    "opportunity_id": "RFQ-STALE-RUN",
                    "bid_state": "evidence_gaps_open",
                    "source_stale": True,
                    "source_change_events": [{"event_id": "evt-1"}],
                    "agent_tasks": [
                        {
                            "task_id": "task-recheck",
                            "task_type": "reanalyze_official_package",
                            "title": "Recheck Changed Source",
                            "detail": "Addendum changed.",
                        }
                    ],
                    "acquisition": {"status": "package_uploaded"},
                    "compliance_decision": {"label": "Pursue", "next_action": "Recheck Changed Source"},
                }
                service._document_analysis_sessions["analysis-stale-run"] = copy.deepcopy(analysis)
                service._latest_document_analysis_by_opportunity["RFQ-STALE-RUN"] = "analysis-stale-run"
                hydrated = service._scan_with_runtime_state(scan)
                service._last_scan = copy.deepcopy(hydrated)
                return hydrated

            def fake_recheck(payload: dict) -> dict:
                rechecked_payloads.append(copy.deepcopy(payload))
                return {
                    "analysis_id": "analysis-stale-run",
                    "opportunity_id": payload["opportunity_id"],
                    "business_profile": {"profile_id": "road_civil_infrastructure"},
                    "bid_state": "evidence_gaps_open",
                    "acquisition": {"status": "portal_login_required", "message": "Portal still requires manual package review."},
                }

            with patch.object(service, "scan", side_effect=fake_scan):
                with patch.object(service, "recheck_document", side_effect=fake_recheck):
                    result = service.run_agent({"profile_id": "road_civil_infrastructure"})

        run = result["agent_run"]
        self.assertEqual(len(rechecked_payloads), 1)
        self.assertEqual(rechecked_payloads[0]["analysis_id"], "analysis-stale-run")
        self.assertIn("changed_source_rechecked", [action["action_type"] for action in run["automatic_actions"]])


if __name__ == "__main__":
    unittest.main()
