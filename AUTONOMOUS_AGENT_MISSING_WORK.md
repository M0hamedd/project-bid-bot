# Autonomous Agent Missing Work

This is the implementation handoff for finishing Project Bid Bot as an agentic bid coordinator instead of another procurement dashboard.

The product target is:

> Given a contractor profile, the agent checks real opportunities, gets or requests the official package, analyzes requirements, finds reusable evidence, estimates a defensible bid range, prepares the owner packet, and only asks the human for the few decisions or confirmations it cannot make deterministically.

## Non-Negotiables

- Keep the critical path deterministic.
- Do not add a chat agent as the control plane.
- Do not submit bids automatically.
- Do not invent missing facts, documents, prices, or capabilities.
- Every compliance blocker must trace to a requirement, citation, evidence item, profile field, or deterministic gate.
- Every pricing recommendation must expose assumptions and confidence.
- The first screen should be an action inbox, not a dashboard of charts.

## Current Baseline

Already implemented:

- Toronto open-data scan and ranking.
- Daily inbox-style priority grouping.
- Metadata-only intake for promising opportunities.
- Official package acquisition guidance.
- PDF upload and deterministic text extraction.
- Cited requirement extraction.
- Evidence ledger, typed action trace, gate results, bid state, and agent tasks.
- Server-owned compliance sessions.
- Resolve requirement workflow.
- Local evidence vault with reusable profile and uploaded evidence.
- Pricing worksheet with low/target/high range, confidence, comps, assumptions, risks, and blockers.
- Submission readiness manifest derived from package, requirements, gates, evidence, pricing, and owner approval.
- Owner packet preparation gated by server-owned `owner_packet_ready` state.
- Local persistence for sessions, evidence, scans, and packets.

Still missing:

- A persistent daily runner that reconciles tasks across runs.
- Addenda/deadline/package monitoring.
- Estimator-owned price inputs and target bid approval.
- Owner packet export and submission assembly.
- Bid outcome tracking.
- Regression fixtures that measure false packet-ready and citation coverage.
- A tighter agent-first UI that hides dashboard clutter behind "what needs doing today."

## Critical Path Build Order

1. Daily Runner With Task Reconciliation.
2. Package, Addenda, And Deadline Monitor.
3. Estimator Price Approval.
4. Submission Assembly Packet.
5. Bid Outcome Feedback Loop.
6. Trust And Evaluation Harness.
7. Agent-First UI Cleanup.

Build in this order unless a later item is needed to test an earlier one.

## Task 1: Submission Readiness Manifest

Status: implemented as the first deterministic manifest increment. Keep this section as the contract for future expansion, especially estimator approval and submission assembly.

### Goal

Create a deterministic manifest that answers: "What exactly must exist before a human can submit this bid?"

### Product Behavior

For each analyzed opportunity, the app shows a manifest above or inside the owner packet:

- official package;
- pricing form;
- bid form;
- addendum acknowledgements;
- insurance certificate;
- bonding letter;
- WSIB or safety clearance;
- licenses and certifications;
- references;
- schedule or methodology;
- portal submission steps;
- owner approval.

Each row must say `ready`, `missing`, `blocked`, `review`, or `pending_owner_approval`.

### Implementation Work

- Add `contract_radar/submission_manifest.py`.
- Build manifest items from:
  - `compliance_matrix`;
  - `gate_results`;
  - `evidence_ledger`;
  - `acquisition`;
  - `document`;
  - `pricing_worksheet`;
  - owner approval status.
- Give every manifest item:
  - `manifest_id`;
  - `item_type`;
  - `label`;
  - `required`;
  - `status`;
  - `reason`;
  - `source_requirement_id`;
  - `source_gate_id`;
  - `citation`;
  - `evidence_ids`;
  - `owner`;
  - `due_at`.
- Extend analysis and resolve responses with:
  - `submission_manifest`;
  - `submission_manifest_summary`.
- Extend `ApprovalPacket` with the manifest.
- Surface manifest summary in the packet UI.

### File Ownership

- `contract_radar/submission_manifest.py`
- `contract_radar/agent_runtime.py`
- `contract_radar/models.py`
- `contract_radar/packet.py`
- `contract_radar/service.py`
- `static/app.js`
- `static/styles.css`
- `tests/test_submission_manifest.py`
- `tests/test_agent_runtime.py`
- `tests/test_packet.py`

### Acceptance Criteria

- Implemented: resolved rows cite attached evidence or user resolution.
- Implemented: pricing form requirements create manifest rows.
- Implemented: package-only metadata sessions show an official-package manifest blocker.
- Implemented: owner packet includes the manifest.
- Implemented: `/api/approve` still rejects if server state is not `owner_packet_ready`.
- Future expansion: estimator price approval and final submission assembly should become manifest blockers when those features exist.

## Task 2: Daily Runner With Task Reconciliation

### Goal

Make Project Bid Bot progress work over time instead of making the user rerun a dashboard manually.

### Product Behavior

On launch, the app shows:

- new worthwhile bids;
- changed bids;
- tasks waiting on the user;
- tasks the agent resolved automatically;
- deadline risks;
- package/addenda updates.

The same blocker should not reappear as a new task every run.

### Implementation Work

- Add `contract_radar/daily_runner.py`.
- Add persisted run records:
  - `run_id`;
  - `started_at`;
  - `finished_at`;
  - `profile_id`;
  - `as_of`;
  - `opportunities_checked`;
  - `new_tasks`;
  - `changed_tasks`;
  - `resolved_tasks`;
  - `deadline_alerts`;
  - `package_alerts`;
  - `addenda_alerts`;
  - `errors`.
- Add stable task IDs derived from:
  - profile id;
  - opportunity id;
  - task type;
  - requirement id or gate id;
  - source citation/hash.
- Add task states:
  - `open`;
  - `waiting_on_user`;
  - `waiting_on_package`;
  - `ready_for_owner`;
  - `blocked`;
  - `done`;
  - `dismissed`.
- Reconcile new runtime `agent_tasks` with persisted task state.
- Add `/api/daily/run` or reuse `/api/inbox` with `refresh=true`.
- Persist run and task state in `state_store`.

### File Ownership

- `contract_radar/daily_runner.py`
- `contract_radar/inbox.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `app.py`
- `static/app.js`
- `tests/test_daily_runner.py`
- `tests/test_inbox.py`
- `tests/test_persistence.py`

### Acceptance Criteria

- Re-running the agent updates existing tasks instead of duplicating them.
- A resolved requirement marks its task `done`.
- A package blocker stays `waiting_on_package` until package status changes.
- A ready packet creates one `ready_for_owner` task.
- Daily run state survives app restart.

## Task 3: Package, Addenda, And Deadline Monitor

### Goal

Let the agent detect important changes after the first scan.

### Product Behavior

The app should tell the contractor:

- "This bid now has a package available."
- "An addendum appeared. Re-check compliance."
- "The deadline changed."
- "This opportunity closed or disappeared."

### Implementation Work

- Store a snapshot fingerprint per opportunity:
  - title;
  - buyer/division;
  - deadline;
  - status;
  - package candidate URLs;
  - acquisition status;
  - addenda markers if visible in metadata or package text.
- Compare latest scan against prior snapshot.
- Create deterministic change events:
  - `new_opportunity`;
  - `deadline_changed`;
  - `status_changed`;
  - `package_available`;
  - `addendum_detected`;
  - `opportunity_closed`.
- Add change events to daily runner outputs and task reconciliation.
- If a package becomes available and can be fetched, analyze it.
- If an addendum is detected, mark existing packet readiness stale until re-analysis.

### File Ownership

- `contract_radar/acquisition.py`
- `contract_radar/daily_runner.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `tests/test_acquisition.py`
- `tests/test_daily_runner.py`
- `tests/test_persistence.py`

### Acceptance Criteria

- Deadline change creates a task/update with old and new deadline.
- Package availability changes a waiting task into an analysis task.
- Addendum detection blocks stale owner packet preparation.
- Closed opportunities are removed from active next actions but preserved in history.

## Task 4: Estimator Price Approval

### Goal

Move pricing from "agent suggests a range" to "estimator approves the target bid with assumptions."

### Product Behavior

The agent should prepare the pricing worksheet, then ask an estimator for the smallest necessary inputs:

- quantity or unit count if missing;
- direct cost assumptions;
- overhead;
- contingency;
- margin;
- target bid approval.

The owner packet should separate agent-calculated guidance from estimator-approved pricing.

### Implementation Work

- Add pricing input records:
  - `pricing_input_id`;
  - `analysis_id`;
  - `input_type`;
  - `value`;
  - `unit`;
  - `source`;
  - `created_by`;
  - `created_at`.
- Add pricing approval:
  - `target_bid`;
  - `approved_by`;
  - `approved_at`;
  - `note`.
- Add deterministic worksheet status:
  - `blocked_missing_quantities`;
  - `draft_agent_estimate`;
  - `estimator_review_required`;
  - `estimator_approved`.
- Create agent tasks from missing quantity or unapproved target price.
- Keep final packet blocked from "submission ready" until estimator pricing is approved.

### File Ownership

- `contract_radar/pricing_worksheet.py`
- `contract_radar/bid_pricing.py`
- `contract_radar/service.py`
- `contract_radar/state_store.py`
- `static/app.js`
- `tests/test_pricing_worksheet.py`
- `tests/test_service_metrics.py`
- `tests/test_packet.py`

### Acceptance Criteria

- Missing quantities create pricing tasks.
- Estimator approval updates pricing worksheet status.
- Packet distinguishes agent range from approved target.
- Unapproved pricing blocks submission manifest readiness.

## Task 5: Submission Assembly Packet

### Goal

Prepare the human's submission package without pretending the app submitted it.

### Product Behavior

After owner approval, the user should get:

- a final owner packet;
- a manifest of required attachments;
- a list of portal steps;
- draft responses for internal forms where deterministic data is available;
- a final "human must submit" warning.

### Implementation Work

- Add Markdown export first.
- Add local packet file storage under ignored runtime data.
- Add packet versioning by `analysis_id` and timestamp.
- Include:
  - compliance summary;
  - manifest;
  - pricing worksheet;
  - estimator approval;
  - evidence ids;
  - citations;
  - action trace;
  - non-submission disclaimer.
- Add a packet download endpoint.

### File Ownership

- `contract_radar/packet.py`
- `contract_radar/models.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `app.py`
- `static/app.js`
- `tests/test_packet.py`
- `tests/test_persistence.py`

### Acceptance Criteria

- Approved packet can be exported as Markdown.
- Export includes citations and audit ids.
- Export states that no bid was submitted.
- Packet versions persist across restarts.

## Task 6: Bid Outcome Feedback Loop

### Goal

Let the product learn which bids were worth pursuing without adding nondeterministic decisions.

### Product Behavior

After a bid closes, the user can record:

- submitted or not submitted;
- final bid amount;
- won/lost/no award yet;
- winning amount if public;
- reason lost;
- time spent;
- margin estimate.

This should improve future ranking and pricing calibration.

### Implementation Work

- Add outcome records:
  - `outcome_id`;
  - `opportunity_id`;
  - `analysis_id`;
  - `submitted`;
  - `final_bid_amount`;
  - `award_status`;
  - `winning_amount`;
  - `winner_name`;
  - `reason_lost`;
  - `hours_spent`;
  - `created_at`;
  - `updated_at`.
- Feed outcomes into:
  - pricing comparable filters;
  - win probability calibration;
  - proof metrics;
  - "bad fit" learning.
- Keep learned changes explainable and reversible.

### File Ownership

- new `contract_radar/outcomes.py`
- `contract_radar/history.py`
- `contract_radar/bid_pricing.py`
- `contract_radar/ranker.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `tests/test_outcomes.py`
- `tests/test_bid_pricing.py`
- `tests/test_ranker.py`

### Acceptance Criteria

- Outcomes persist locally.
- Pricing worksheet can include customer historical outcomes as comps.
- Win/loss history changes ranking explanations.
- Missing outcome data does not break scans.

## Task 7: Trust And Evaluation Harness

### Goal

Make hallucination and false readiness measurable.

### Product Behavior

Before shipping changes, agents can run one command and see:

- requirement extraction precision/recall on fixtures;
- citation coverage;
- false hard-stop clearance rate;
- false packet-ready rate;
- pricing confidence sanity;
- runtime.

### Implementation Work

- Add fixture bid packages for:
  - road repair;
  - landscaping;
  - snow removal;
  - facilities maintenance;
  - signage;
  - parks/civil small works.
- Add expected output files for each fixture:
  - requirements;
  - categories;
  - citations;
  - hard stops;
  - review gates;
  - manifest items;
  - expected bid state.
- Add `scripts/evaluate_bid_flow.py`.
- Add tests that enforce:
  - no PDF-derived fact without citation;
  - unresolved hard stop cannot be packet-ready;
  - packet claims cite facts or deterministic computed fields;
  - no fixture has false packet-ready.

### File Ownership

- `tests/fixtures/`
- `scripts/evaluate_bid_flow.py`
- `tests/test_compliance.py`
- `tests/test_agent_runtime.py`
- `tests/test_submission_manifest.py`
- `tests/test_packet.py`

### Acceptance Criteria

- Evaluation reports pass/fail metrics.
- Fixture regressions fail tests.
- Each new requirement detector must include fixture coverage.

## Task 8: Agent-First UI Cleanup

### Goal

Make the app feel like an agent doing work, not a dashboard asking the user to browse data.

### Product Behavior

The first screen should answer:

1. What did the agent do since the last run?
2. What is ready for owner approval?
3. What exactly blocks the next bid?
4. What is the one action I should take now?

Charts, raw opportunity lists, and detailed matrices should be secondary drill-downs.

### Implementation Work

- Promote `daily_inbox` and reconciled agent tasks as the primary view.
- Group tasks by action:
  - approve owner packet;
  - upload official package;
  - attach evidence;
  - resolve site visit/addendum/form;
  - approve estimator pricing;
  - review changed deadline/addendum.
- Collapse the compliance matrix by default after manifest/tasks exist.
- Show the exact citation/reason in task rows.
- Keep raw scan list available as "All Opportunities".
- Remove UI copy that sounds like analytics/dashboard reporting when it should be action language.

### File Ownership

- `static/app.js`
- `static/index.html`
- `static/styles.css`
- `tests/` smoke and JS syntax checks

### Acceptance Criteria

- User can reach the next required action without scanning a large table.
- Ready packets are visibly separated from blocked bids.
- The compliance matrix is still available but no longer the main workflow.
- `node --check static/app.js` passes.

## Parallel Agent Split

Use this split if multiple agents work concurrently:

- Agent A: Submission Manifest
  - owns `submission_manifest.py`, manifest tests, packet manifest field.
- Agent B: Daily Runner
  - owns `daily_runner.py`, task reconciliation, run persistence.
- Agent C: Package Monitor
  - owns acquisition change events and addenda/deadline detection.
- Agent D: Pricing Approval
  - owns estimator inputs, pricing status, pricing tasks.
- Agent E: Packet Export
  - owns Markdown export, packet versioning, download endpoint.
- Agent F: Outcomes
  - owns bid outcome records and calibration hooks.
- Agent G: Evaluation
  - owns fixtures, evaluation script, regression gates.
- Agent H: UI Flow
  - owns task-first UI and visual simplification.

Avoid parallel edits to `contract_radar/service.py`, `contract_radar/models.py`, and `static/app.js` unless one agent is explicitly integrating.

## Integration Rules

- All public API responses must remain JSON-serializable dictionaries and lists.
- All generated IDs must be stable or explain why they are timestamped.
- Server-owned session state must remain authoritative.
- Browser-submitted rows must never override server compliance state.
- New packet readiness rules must go through server-side derived state.
- Persistence changes must include restart tests.
- UI changes must preserve the local `python app.py` workflow.

## Verification Checklist

Each agent should run the narrow tests for its work plus:

```powershell
python -m unittest
node --check static/app.js
python -m compileall app.py contract_radar tests
git diff --check
```

For UI/API changes, also run:

```powershell
python app.py
python scripts\smoke_api.py
```

## Done Definition

The missing flow is done when:

- A contractor can open the app and see today's bid actions without browsing a dashboard.
- The agent can move an opportunity from metadata to package guidance or PDF analysis.
- The agent can cite every extracted requirement.
- The agent can match reusable evidence or ask for exactly what is missing.
- The agent can produce a pricing worksheet and block when pricing data is weak.
- The agent can produce an owner packet only after deterministic gates are clear.
- The packet includes a submission manifest and exportable audit trail.
- The user only approves, supplies missing evidence/pricing inputs, or submits manually.
- Regression fixtures catch false readiness, uncited facts, and pricing overconfidence.
