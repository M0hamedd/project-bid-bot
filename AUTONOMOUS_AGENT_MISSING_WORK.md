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
- Terminal/API-friendly `/api/agent/run` orchestration that intakes company facts, scans, runs safe automatic package acquisition/recheck actions, and returns approval queue plus human-required blockers.
- Single-task agent execution: `/api/agent/task/execute` executes only current server-owned task ids, runs safe package acquisition/recheck actions, surfaces owner approval requests, and returns required payload schemas for tasks that need human facts or approval.
- Deterministic company intake that saves supplied services, documents, evidence facts, rate cards, and missing profile facts.
- Missing company profile facts now become sourced ledger facts, gate results, and `complete_company_profile` tasks before packet prep.
- Profile-completion tasks are actionable: supplied facts refresh the saved profile, evidence vault, open analyses, gates, and daily inbox state.
- Local evidence vault with reusable profile and uploaded evidence.
- Pricing worksheet with low/target/high range, confidence, comps, assumptions, risks, and blockers.
- Local company profile persistence for saved business details, pricing rate cards, and pricing policy facts.
- Submission readiness manifest derived from package, requirements, gates, evidence, pricing, and owner approval.
- Deterministic submission assembly artifact with prefilled profile/opportunity/pricing fields, attachment upload list, portal steps, final checks, and a human-submission warning.
- Deterministic owner approval requests: ready analyses now produce a server-owned approval request with target bid, manifest state, citations, guardrails, and the server approval payload needed to prepare a packet, without approving or submitting anything.
- Agent-friendly owner approval execution: `/api/owner-approval/approve` accepts a current `approval_request_id`, rejects fake or stale ids, and prepares the owner packet from server-owned analysis state.
- Persistent daily runner with stable task reconciliation, new/changed/resolved task tracking, and local run history.
- Deterministic opportunity snapshot monitor for package availability, deadline changes, status changes, visible addenda markers, and closed listings.
- Closed opportunities are removed from active next actions while closure events and reconciled task history are preserved.
- Source-change invalidation: addendum, deadline, status, package, or closure changes mark existing analyzed packets stale until recheck.
- Source-change recheck tasks are actionable: the server tries current direct public PDF candidates and re-analyzes the official package when fetch succeeds, while preserving the stale-source gate when it cannot.
- Public source-page package discovery: acquisition/recheck can inspect public buyer/source HTML pages, rank discovered PDF package/addendum links, and fetch/analyze the best public candidate without a manual upload.
- Public package document inventory: discovered PDFs are classified as solicitation package, addendum, pricing form, drawings/specifications, required form, or excluded award/notice artifacts, then surfaced in submission assembly attachments.
- Supporting package PDF storage: after the primary public package is fetched, public addenda/pricing/supporting PDFs are fetched when allowed, stored locally, and attached to the analysis/assembly audit bundle.
- Supporting package text merge: extractable public addenda/pricing/supporting PDF text is merged into cited requirement extraction and pricing-form detection before gates/tasks are rebuilt.
- Estimator target-bid approval gate: resolved requirements now wait for server-owned pricing approval before `owner_packet_ready`.
- Estimator pricing input records for quantity/cost facts and target-bid overrides.
- Deterministic PDF pricing-form and line-item quantity extraction with citations.
- Deterministic profile-rate-card cost rollups for extracted PDF line items.
- Business-profile pricing rate cards and policy rates that override generic rollup defaults when supplied.
- Project-specific PDF line-item unit costs can be recorded as estimator inputs and refresh pricing gates/tasks.
- Owner packet preparation gated by server-owned `owner_packet_ready` state.
- Markdown packet export with manifest, pricing approval, citations, evidence ids, action trace, and a non-submission warning.
- Bid outcome feedback loop with local outcome records, summary metrics, ranking feedback, and pricing comps.
- Deterministic bid-flow evaluation harness with six fixtures, citation coverage, and false packet-ready checks.
- Local persistence for sessions, evidence, scans, and packets.

Still missing:

- Authenticated portal/package automation and addendum-aware package fetching beyond direct public PDF candidates.
- Non-deterministic tool agents for broader web/package discovery, document interpretation, drafting, portal navigation, and buyer communication, bounded by sourced facts and approval gates.
- Richer rate-card management/import and richer estimator override review.
- Richer guided onboarding for profile/evidence/rate imports beyond deterministic intake and profile-completion prompts.
- Buyer-specific form filling and attachment bundling beyond the first deterministic submission assembly.
- Richer owner approval surfaces such as email/Slack/mobile approval delivery.
- Expanded bid outcome analytics beyond the first local feedback loop.
- Broader regression fixture coverage beyond the first deterministic trust harness.
- A tighter agent-first UI that hides dashboard clutter behind "what needs doing today."

## Critical Path Build Order

1. Finish portal/package automation and addendum-aware package re-analysis beyond public unauthenticated PDF/page candidates.
2. Add the non-deterministic tool-agent layer for discovery, drafting, and portal workflows with audit constraints.
3. Editable Line-Item Pricing And Rate Cards.
4. Buyer-Specific Form Filling And Attachment Bundling.
5. Bid Outcome Feedback Expansion.
6. Trust And Evaluation Harness Expansion.
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

Status: implemented as the first persistent local daily-run increment. Keep this section as the contract for future scheduler/change-monitor expansion.

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

- Implemented: `contract_radar/daily_runner.py`.
- Implemented persisted run records:
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
- Implemented stable task IDs derived from:
  - profile id;
  - opportunity id;
  - task type;
  - requirement id or gate id;
  - source citation/hash.
- Implemented task states:
  - `open`;
  - `waiting_on_user`;
  - `waiting_on_package`;
  - `ready_for_owner`;
  - `blocked`;
  - `done`;
  - `dismissed`.
- Implemented: reconcile new runtime tasks with persisted task state.
- Implemented: add `/api/daily/run` and include run summaries in scan/inbox responses.
- Implemented: persist run and task state in `state_store`.

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

- Implemented: re-running the agent updates existing tasks instead of duplicating them.
- Implemented: a resolved or replaced task is marked `done`.
- Implemented: a package blocker stays `waiting_on_package`.
- Implemented: a ready packet creates one `ready_for_owner` task.
- Implemented: daily run state survives app restart.
- Future expansion: automatic scheduler wakeups and richer addenda/package monitoring.

## Task 3: Package, Addenda, And Deadline Monitor

Status: deterministic source-snapshot monitoring, stale-readiness invalidation, direct public PDF recheck, public source-page PDF discovery, package document classification, supporting-PDF storage, and first supporting-text merge are implemented. Keep this section as the contract for future authenticated portal/package automation and richer addendum-aware package re-analysis.

### Goal

Let the agent detect important changes after the first scan.

### Product Behavior

The app should tell the contractor:

- "This bid now has a package available."
- "An addendum appeared. Re-check compliance."
- "The deadline changed."
- "This opportunity closed or disappeared."

### Implementation Work

- Implemented: `contract_radar/opportunity_monitor.py`.
- Implemented: store a snapshot fingerprint per opportunity:
  - title;
  - buyer/division;
  - deadline;
  - status;
  - package candidate URLs;
  - acquisition status;
  - addenda markers if visible in metadata or package text.
- Implemented: compare latest scan against prior snapshot.
- Implemented: create deterministic change events:
  - `new_opportunity`;
  - `deadline_changed`;
  - `status_changed`;
  - `package_available`;
  - `addendum_detected`;
  - `opportunity_closed`.
- Implemented: add change events to daily runner outputs, scan/inbox API responses, run summaries, persistence, and UI summary text.
- Implemented: source-change tasks call a server-owned recheck endpoint that tries direct public PDF candidates, analyzes the fetched package, and clears stale source gates only after successful re-analysis.
- Implemented: if addendum, deadline, status, package, or closure changes are detected, mark existing analyzed packet readiness stale until recheck.

### File Ownership

- `contract_radar/acquisition.py`
- `contract_radar/opportunity_monitor.py`
- `contract_radar/daily_runner.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `static/app.js`
- `tests/test_acquisition.py`
- `tests/test_opportunity_monitor.py`
- `tests/test_daily_runner.py`
- `tests/test_persistence.py`

### Acceptance Criteria

- Implemented: deadline change creates a run alert/update with old and new deadline.
- Implemented: package availability creates a package alert and source change event.
- Implemented: addendum marker detection creates an addenda alert and source change event.
- Implemented: closed opportunity detection creates a source change event.
- Implemented: package availability or source-change recheck can fetch/analyze current direct public PDF candidates where permitted.
- Implemented: package acquisition/recheck can inspect public source pages, rank discovered PDF package/addendum links, and fetch/analyze the best public PDF candidate where permitted.
- Implemented: discovered public PDFs are classified, award/result/notice artifacts are excluded from analysis candidates, and addenda/pricing/supporting documents appear in submission assembly attachments.
- Implemented: after fetching the primary package PDF, supporting public package PDFs are stored locally and carried into the analysis/assembly audit metadata.
- Implemented: extractable supporting public package PDFs are merged into deterministic requirement/pricing extraction with their own citations before agent gates/tasks are rebuilt.
- Implemented: addendum/source-change detection blocks stale owner packet preparation through a runtime gate and recheck task.
- Implemented: closed/disappeared opportunities mark previous active tasks done and disappear from active next actions while preserving change-event history.
- Remaining: authenticated portal/package automation, richer multi-PDF conflict/version handling, OCR/scanned supporting PDFs, and portal-specific package selection.

## Task 4: Estimator Price Approval

Status: deterministic target-bid approval, server-owned pricing inputs, first PDF quantity extraction, profile-rate-card cost rollups, business-profile rate-card overrides, and project-specific line-item unit-cost edits implemented. Keep this section as the contract for richer rate-card editing/import and override review.

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

- Implemented: add pricing input records:
  - `pricing_input_id`;
  - `analysis_id`;
  - `input_type`;
  - `value`;
  - `unit`;
  - `source`;
  - `created_by`;
  - `created_at`.
- Implemented: add pricing approval:
  - `target_bid`;
  - `approved_by`;
  - `approved_at`;
  - `note`.
- Implemented: deterministic worksheet approval fields:
  - `estimator_approval_status`;
  - `approval_required`;
  - `can_use_for_owner_packet`.
- Implemented: richer deterministic worksheet status:
  - `blocked_missing_pricing_inputs`;
  - `draft_agent_estimate`;
  - `estimator_review_required`;
  - `estimator_approved`.
- Implemented: create an agent task from missing required estimator inputs and from an unapproved target price after PDF compliance gates are resolved.
- Implemented: keep final packet blocked from `owner_packet_ready` until estimator pricing is approved.
- Implemented: `/api/pricing/input` records server-owned estimator inputs and rebuilds gates/tasks/state.
- Implemented: `/api/pricing/approve` updates the server-owned analysis session and typed action trace.
- Implemented: deterministic PDF pricing extraction creates cited `pricing_line_items`, satisfies required quantity inputs when quantities are found, and creates a quantity task when pricing form language has no extractable quantities.
- Implemented: deterministic profile rate card converts extracted quantities into a line-item direct-cost rollup, contingency, overhead, margin, and rollup target bid.
- Implemented: business profiles can carry and locally persist `pricing_rate_card` and `pricing_policy` facts that override supported-lane pricing defaults and appear in the evidence ledger.
- Implemented: unpriced extracted PDF line items block pricing approval until an estimator records a cited project unit cost.
- Implemented: `/api/pricing/line-item-rate` records server-owned line-item unit-cost inputs and recomputes pricing gates/tasks/state.

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

- Implemented: missing required quantity/cost inputs create pricing tasks when the pricing context declares them.
- Implemented: estimator approval updates pricing worksheet approval status.
- Implemented: packet distinguishes agent range from estimator-approved target.
- Implemented: unapproved pricing blocks submission manifest readiness and `/api/approve`.
- Implemented: extract first-pass required quantities and line items from buyer pricing forms automatically.
- Implemented: deterministic cost rollups from extracted line items.
- Remaining: richer rate-card editing/import and richer override policy.

## Task 5: Submission Assembly Packet

Status: first Markdown export, versioned packet-storage, and deterministic submission assembly increments implemented. Keep this section as the contract for future buyer-specific form filling, attachment bundling, and richer downloadable formats.

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

- Implemented: add Markdown export first.
- Implemented: add local packet file storage under ignored runtime data.
- Implemented: add packet versioning by `analysis_id` and timestamp.
- Implemented: add deterministic `submission_assembly` with:
  - prefilled business/opportunity/buyer/pricing fields;
  - attachment rows derived from the submission manifest;
  - public package/addendum/pricing document attachment rows derived from acquisition inventory and local storage metadata;
  - portal action steps;
  - final human checks;
  - explicit non-submission warning.
- Implemented: include:
  - compliance summary;
  - manifest;
  - submission assembly;
  - pricing worksheet;
  - estimator approval;
  - evidence ids;
  - citations;
  - action trace;
  - non-submission disclaimer.
- Implemented: add a packet download endpoint.
- Remaining: buyer-specific form-field mapping where deterministic profile data is available.
- Remaining: package attachment bundling and portal-specific submission assembly.

### File Ownership

- `contract_radar/packet_export.py`
- `contract_radar/packet.py`
- `contract_radar/models.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `app.py`
- `static/app.js`
- `tests/test_packet.py`
- `tests/test_packet_export.py`
- `tests/test_persistence.py`

### Acceptance Criteria

- Implemented: approved packet can be exported as Markdown.
- Implemented: export includes citations and audit ids.
- Implemented: export includes submission assembly fields, attachments, portal steps, and final checks.
- Implemented: export states that no bid was submitted.
- Implemented: packet versions persist across restarts.
- Implemented: ready analyses expose owner approval request artifacts before `/api/approve` is called.

## Task 6: Bid Outcome Feedback Loop

Status: first deterministic outcome-record increment implemented. Keep this section as the contract for richer calibration and bad-fit learning.

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

This improves future ranking explanations and pricing comparables without adding nondeterministic decisions. Remaining work is deeper probability calibration, proof metrics, and reversible bad-fit learning.

### Implementation Work

- Implemented: add outcome records:
  - `outcome_id`;
  - `opportunity_id`;
  - `analysis_id`;
  - `profile_id`;
  - `submitted`;
  - `final_bid_amount`;
  - `award_status`;
  - `winning_amount`;
  - `winner_name`;
  - `reason_lost`;
  - `hours_spent`;
  - `margin_estimate`;
  - `created_at`;
  - `updated_at`.
- Implemented: persist outcomes in local state through `/api/outcomes/record`.
- Implemented: feed similar outcomes into ranking explanations and bounded score changes.
- Implemented: include customer outcome matches as first-party pricing comparables.
- Remaining: win probability calibration.
- Remaining: proof metrics.
- Remaining: reversible "bad fit" learning beyond bounded score deltas.
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

- Implemented: outcomes persist locally.
- Implemented: pricing worksheet can include customer historical outcomes as comps.
- Implemented: win/loss history changes ranking explanations.
- Implemented: missing outcome data does not break scans.
- Remaining: richer calibrated win-probability and proof metric reporting.

## Task 7: Trust And Evaluation Harness

Status: first deterministic fixture harness implemented. Keep this section as the contract for expanding precision/recall depth and packet-claim auditing.

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

- Implemented: add text fixture bid packages for:
  - road repair;
  - landscaping;
  - snow removal;
  - facilities maintenance;
  - signage;
  - parks/civil small works.
- Implemented: add expected output fields for:
  - requirement categories;
  - hard stops;
  - review gates;
  - expected bid state;
  - packet-ready allowance.
- Implemented: add `scripts/evaluate_bid_flow.py`.
- Implemented: add tests that enforce:
  - no uploaded-PDF-derived fact without citation;
  - no fixture with unresolved blockers becomes packet-ready;
  - expected hard-stop gates stay present;
  - pricing confidence sanity.
- Remaining:
  - requirement extraction precision metrics beyond category recall;
  - manifest item expectations;
  - packet claims cite facts or deterministic computed fields;
  - fixture binary PDFs or OCR/scanned-document cases.

### File Ownership

- `tests/fixtures/`
- `scripts/evaluate_bid_flow.py`
- `tests/test_compliance.py`
- `tests/test_agent_runtime.py`
- `tests/test_submission_manifest.py`
- `tests/test_packet.py`

### Acceptance Criteria

- Implemented: evaluation reports pass/fail metrics.
- Implemented: fixture regressions fail tests.
- Future expectation: each new requirement detector must include fixture coverage.

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
