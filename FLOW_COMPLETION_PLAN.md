# Flow Completion Plan

This document defines what remains before Project Bid Bot feels like a complete autonomous bid coordinator instead of a task-focused demo.

Current implemented flow:

1. Run the bid agent against Toronto open data.
2. Rank opportunities into actionable tasks.
3. Auto-start metadata intake for top pursue/review opportunities.
4. Ask for the official package when the agent cannot fetch one.
5. Analyze uploaded PDFs with cited requirement extraction.
6. Build deterministic evidence, gates, tasks, and bid state.
7. Let the user resolve compliance blockers.
8. Prepare owner bid notes only when the server-owned state is packet-ready.

This is a valid v1 skeleton. It is not product-complete yet.

## Product Completion Target

The finished flow should let a contractor open the app and see:

> These are the bids worth touching today, these are blocked, this is the missing evidence, this is the defensible price range, and this is the owner packet ready for approval.

The agent must remain deterministic by default:

- no unsourced facts;
- no automatic submission;
- no fake portal access;
- no hidden LLM decisions in the critical compliance path;
- every blocker, price assumption, and packet claim must trace to a source.

## Workstream 1: Official Package Acquisition

**Goal:** Reduce manual PDF upload by finding, fetching, or guiding the user to the official solicitation package.

**Why it matters:** The current flow can start intake from open-data metadata, but the real compliance workflow still depends on an uploaded PDF. The agent should do as much package acquisition as possible before asking the user.

**Current increment implemented:**

- deterministic acquisition status classifier;
- direct public PDF candidate detection;
- portal-login-required detection;
- manual-download-required detection;
- fetch-failed status with reason;
- package-fetched and package-uploaded statuses;
- acquisition guidance with portal URL, search hint, expected documents, and next step;
- guidance surfaced in the official-package panel and agent task details.

Remaining work in this stream is authenticated portal automation, addenda monitoring, multi-file package grouping, and automatic analysis of fetched package bundles beyond direct PDFs.

**Build:**

- Add an acquisition status model:
  - `not_checked`
  - `metadata_only`
  - `candidate_urls_found`
  - `package_fetched`
  - `portal_login_required`
  - `manual_download_required`
  - `fetch_failed`
  - `package_uploaded`
- Store candidate package URLs with source labels and timestamps.
- Detect whether a buyer portal page points to documents, addenda, forms, drawings, pricing sheets, or login-gated pages.
- Add deterministic portal guidance:
  - buyer portal name;
  - exact opportunity id;
  - expected document names;
  - download instructions;
  - reason automation could not fetch it.
- Preserve current local-only behavior. Do not add credentials or portal automation yet.
- When a package is fetched or uploaded, rerun the same analysis session lifecycle.

**Likely files:**

- `contract_radar/acquisition.py`
- `contract_radar/service.py`
- `contract_radar/documents.py`
- `contract_radar/agent_runtime.py`
- `static/app.js`
- `static/styles.css`
- `tests/test_acquisition.py`
- `tests/test_document_analysis.py`

**Acceptance criteria:**

- The agent can distinguish "no public package found" from "manual portal download required."
- Task queue shows the exact acquisition blocker and source.
- Fetched PDFs and manually uploaded PDFs produce the same downstream analysis shape.
- Existing metadata-only intake remains blocked until a real package is fetched or uploaded.
- Tests prove `/api/approve` rejects metadata-only sessions.

## Workstream 2: Evidence Vault

**Goal:** Let the business reuse verified company evidence across bids.

**Why it matters:** Today, resolving a requirement is mostly a click. A real contractor needs the agent to know which certificates, insurance docs, bonding letters, licenses, safety policies, references, and equipment evidence already exist.

**Current increment implemented:**

- profile-seeded local evidence inventory;
- deterministic evidence ids;
- profile-derived evidence for insurance, bonding, ready documents, certifications, references, equipment, and crew capacity;
- requirement matching against unexpired vault evidence;
- local user-uploaded evidence storage;
- persisted evidence records that survive service restarts;
- requirement-level evidence attachment through server-owned analysis sessions;
- `evidence_vault` facts in the agent evidence ledger;
- UI display of matched evidence on resolved compliance rows.

Remaining work in this stream is full vault management: expiry editing, evidence review/removal, reusable evidence search, and richer evidence upload forms.

**Build:**

- Add local evidence records:
  - `evidence_id`
  - `evidence_type`
  - `label`
  - `filename`
  - `content_hash`
  - `source`
  - `issued_at`
  - `expires_at`
  - `profile_id`
  - `capability_tags`
  - `verified_status`
  - `created_at`
  - `updated_at`
- Supported evidence types:
  - insurance certificate;
  - WSIB clearance;
  - bonding capacity letter;
  - license;
  - certification;
  - safety policy;
  - site visit confirmation;
  - addendum acknowledgement;
  - pricing form;
  - reference project;
  - equipment list;
  - crew/capacity proof.
- Add upload/storage for evidence files.
- Match compliance rows to existing evidence by deterministic tags and expiry dates.
- Convert matched vault items into evidence ledger facts.
- Show missing, expired, and available evidence in the UI.
- Allow user to attach a vault item to a requirement.

**Likely files:**

- new `contract_radar/evidence_vault.py`
- `contract_radar/state_store.py`
- `contract_radar/compliance.py`
- `contract_radar/agent_runtime.py`
- `contract_radar/service.py`
- `static/app.js`
- `static/index.html`
- `static/styles.css`
- `tests/test_evidence_vault.py`
- `tests/test_agent_runtime.py`

**Acceptance criteria:**

- A known insurance/bonding/license requirement can resolve from an unexpired vault item.
- Expired evidence does not resolve a requirement.
- Evidence facts cite the vault item and linked requirement.
- The UI shows "available evidence" separately from "needs human confirmation."
- Re-running scan/analysis does not lose attached evidence.

## Workstream 3: Pricing Worksheet

**Goal:** Produce a defensible bid range, not just a broad score or estimated value.

**Why it matters:** Contractors will not trust a bid agent unless it explains the pricing basis. The agent should say when the data is weak instead of pretending precision.

**Current increment implemented:**

- deterministic pricing worksheet builder;
- low/target/high bid range from pricing candidates or recommendation range;
- confidence rating from comparable awards, win probability, and blockers;
- comparable award list from historical/RAG evidence;
- cost stack, rates, assumptions, risks, and evidence;
- pricing blockers for unresolved official pricing/form requirements;
- worksheet included in scan results, selected-bid UI, and owner packet.

Remaining work in this stream is quantity extraction, line-item pricing forms, customer-specific cost inputs, and final estimator override/approval of the target bid.

**Build:**

- Add a pricing worksheet per opportunity:
  - comparable awards;
  - included/excluded comps;
  - scope similarity;
  - buyer/division similarity;
  - contract type;
  - estimated direct cost assumptions;
  - overhead;
  - contingency;
  - target margin;
  - low/target/high bid range;
  - confidence;
  - pricing risks;
  - missing quantity data.
- Improve comparable filtering by:
  - buyer/division;
  - category;
  - scope keywords;
  - work type;
  - location;
  - contract size band;
  - recency.
- Add deterministic confidence rules:
  - enough close comps;
  - weak comps;
  - no comps;
  - scope too unclear;
  - quantity sheet missing.
- Add "do not price yet" state when required quantity/pricing forms are missing.

**Likely files:**

- `contract_radar/bid_pricing.py`
- `contract_radar/history.py`
- `contract_radar/rag.py`
- `contract_radar/ranker.py`
- `contract_radar/packet.py`
- `static/app.js`
- `tests/test_bid_pricing.py`
- `tests/test_history.py`
- `tests/test_packet.py`

**Acceptance criteria:**

- Every recommended opportunity has either a pricing worksheet or a deterministic reason pricing is blocked.
- The worksheet names which comps were used and why.
- Weak comps reduce confidence.
- Missing pricing forms or quantities create an agent task.
- Owner packet includes the pricing range, confidence, and assumptions.

## Workstream 4: Owner Packet V2

**Goal:** Turn "bid notes" into a usable owner-review artifact.

**Why it matters:** The current packet is useful internally, but the product promise is that the owner can decide whether to spend estimator time. The packet should be exportable and audit-ready.

**Build packet sections:**

- Recommendation:
  - pursue, review, blocked, or pass;
  - one-line reason;
  - confidence.
- Opportunity summary:
  - buyer;
  - title;
  - deadline;
  - source;
  - estimated value;
  - fit summary.
- Compliance status:
  - hard stops;
  - review gates;
  - resolved requirements;
  - missing evidence;
  - capability gaps.
- Evidence manifest:
  - attached vault evidence;
  - uploaded package;
  - user confirmations;
  - expired/missing evidence.
- Pricing worksheet:
  - low/target/high;
  - comps;
  - assumptions;
  - risks.
- Owner actions:
  - approve pursuit;
  - assign estimator;
  - upload/attach evidence;
  - pass;
  - ask buyer clarification.
- Deterministic audit:
  - bid state;
  - gate ids;
  - evidence fact ids;
  - action trace.

**Export targets:**

- Markdown first.
- PDF later.
- DOCX later.

**Likely files:**

- `contract_radar/packet.py`
- `contract_radar/models.py`
- `contract_radar/service.py`
- `static/app.js`
- `static/styles.css`
- `tests/test_packet.py`

**Acceptance criteria:**

- Packet cannot be prepared unless bid state is `owner_packet_ready`.
- Packet includes source citations and audit ids.
- Packet clearly says the app did not submit the bid.
- Packet can be copied or exported as Markdown.
- Packet includes open blockers when generated in non-approved preview mode.

## Workstream 5: Autonomous Daily Runner

**Goal:** Make the agent progress work over time instead of waiting for manual reruns.

**Why it matters:** A dashboard waits. An agent comes back with work done and a short list of human decisions.

**Current increment implemented:**

- deterministic daily-run reconciliation module;
- stable agent task ids across runs;
- persisted daily run records and agent task state in local state;
- task states: `open`, `waiting_on_user`, `waiting_on_package`, `ready_for_owner`, `blocked`, `done`, and `dismissed`;
- run summaries for new, changed, resolved, deadline-alert, and package-alert counts;
- `/api/daily/run` endpoint plus scan/inbox responses carrying `daily_run` and `agent_task_state`;
- UI consumes server-owned daily inbox and shows task change summaries.

Remaining work in this stream is a real local scheduler/automation trigger and richer change detection from package/addenda monitoring.

**Build:**

- Add local daily run state:
  - `run_id`
  - `started_at`
  - `finished_at`
  - `profile_id`
  - `as_of`
  - `opportunities_checked`
  - `new_tasks`
  - `changed_tasks`
  - `deadline_alerts`
  - `addenda_alerts`
  - `errors`
- Add deterministic task state:
  - `open`
  - `waiting_on_user`
  - `waiting_on_package`
  - `ready_for_owner`
  - `blocked`
  - `done`
  - `dismissed`
- Reconcile tasks across runs so the same blocker does not appear as a new task every day.
- Detect changes:
  - new opportunity;
  - deadline changed;
  - status changed;
  - package appeared;
  - addendum appeared;
  - opportunity closed.
- Add a "Today" summary:
  - new bids worth reviewing;
  - tasks requiring human action;
  - blockers resolved automatically;
  - deadlines at risk.
- Keep this local-first. Do not add a cloud scheduler yet.

**Likely files:**

- new `contract_radar/daily_runner.py`
- `contract_radar/inbox.py`
- `contract_radar/state_store.py`
- `contract_radar/service.py`
- `static/app.js`
- `tests/test_daily_runner.py`
- `tests/test_inbox.py`

**Acceptance criteria:**

- Re-running the agent updates existing tasks instead of duplicating them.
- A deadline change creates a clear task/update.
- A package becoming available changes a `waiting_on_package` task into an analysis task.
- The first screen shows today's action list, not historical clutter.
- State persists across app restarts.

## Workstream 6: Submission Readiness Manifest

**Goal:** Know exactly what files, forms, confirmations, and approvals are needed before a human submits.

**Why it matters:** We should not submit bids automatically, but we can prepare a deterministic checklist that prevents non-compliance.

**Current increment implemented:**

- deterministic `submission_manifest` and `submission_manifest_summary` on analysis and resolve responses;
- manifest items for official package, extracted compliance requirements, pricing worksheet, and owner approval;
- manifest status model: `ready`, `missing`, `blocked`, `review`, and `pending_owner_approval`;
- source requirement ids, gate ids, citations, evidence ids, owners, and due dates on manifest rows;
- owner packet serialization with the submission manifest included;
- compact submission-readiness UI in the document analysis panel and owner packet.

Remaining work in this stream is connecting estimator price approval and final submission assembly to manifest blockers once those features exist.

**Build:**

- Add submission manifest items:
  - official bid form;
  - pricing form;
  - signed declarations;
  - addendum acknowledgements;
  - insurance certificate;
  - bonding letter;
  - WSIB;
  - licenses/certifications;
  - references;
  - schedule;
  - methodology;
  - health and safety plan;
  - portal submission steps.
- Track each item:
  - required;
  - optional;
  - source citation;
  - evidence/file attached;
  - owner;
  - status;
  - due date.
- Generate from compliance rows, pricing worksheet, and evidence vault.
- Include in packet and task queue.

**Likely files:**

- new `contract_radar/submission_manifest.py`
- `contract_radar/compliance.py`
- `contract_radar/agent_runtime.py`
- `contract_radar/packet.py`
- `static/app.js`
- `tests/test_submission_manifest.py`

**Acceptance criteria:**

- Every required form/document has a manifest row.
- Missing required manifest items block packet readiness.
- Resolved manifest items cite the uploaded/vault evidence.
- Owner packet includes the manifest.

## Workstream 7: Trust And Evaluation Harness

**Goal:** Prevent regressions in requirement extraction, gates, pricing confidence, and packet claims.

**Why it matters:** This product dies if it hallucinates compliance or overstates pricing confidence.

**Build:**

- Add fixture packages for common municipal bid types:
  - road repair;
  - landscaping;
  - snow removal;
  - facility maintenance;
  - signage;
  - parks/civil small works.
- For each fixture, define expected:
  - requirements;
  - hard stops;
  - review gates;
  - evidence needs;
  - citation coverage;
  - expected task count;
  - expected bid state.
- Add benchmark script:
  - extraction precision;
  - extraction recall;
  - citation coverage;
  - runtime;
  - false packet-ready rate.
- Add packet claim audit:
  - every packet claim must trace to fact ids or deterministic computed fields.

**Likely files:**

- `tests/fixtures/`
- `tests/test_compliance.py`
- `tests/test_agent_runtime.py`
- `tests/test_packet.py`
- new `scripts/evaluate_bid_flow.py`

**Acceptance criteria:**

- CI/local tests fail if uncited PDF-derived facts enter the evidence ledger.
- CI/local tests fail if unresolved hard stops become packet-ready.
- Evaluation output reports false positives and missing requirements.
- New requirement detectors must include fixture coverage.

## Recommended Agent Split

Run these in parallel only when write scopes are separated.

### Agent A: Acquisition

Owns:

- `contract_radar/acquisition.py`
- acquisition-related service methods;
- package status tests.

Deliverable:

- richer acquisition statuses and UI task language.

### Agent B: Evidence Vault

Owns:

- `contract_radar/evidence_vault.py`
- state-store persistence for evidence;
- evidence matching tests.

Deliverable:

- reusable contractor evidence records and deterministic requirement matching.

### Agent C: Pricing Worksheet

Owns:

- `contract_radar/bid_pricing.py`
- history/comparable selection;
- pricing worksheet tests.

Deliverable:

- low/target/high pricing worksheet with confidence and blocked-pricing reasons.

### Agent D: Packet V2

Owns:

- `contract_radar/packet.py`
- packet export;
- packet tests.

Deliverable:

- owner packet artifact with compliance, evidence, pricing, actions, and audit trace.

### Agent E: Daily Runner

Owns:

- `contract_radar/daily_runner.py`
- inbox/task reconciliation;
- daily runner tests.

Deliverable:

- persistent daily run summaries and non-duplicating task state.

### Agent F: Submission Manifest

Owns:

- `contract_radar/submission_manifest.py`
- manifest integration into gates/tasks/packet.

Deliverable:

- required submission files and forms tracked as deterministic blockers.

### Agent G: Evaluation Harness

Owns:

- `tests/fixtures/`
- `scripts/evaluate_bid_flow.py`
- regression tests.

Deliverable:

- measurable trust harness for extraction, gates, pricing, and packet readiness.

## Build Order

Do these first:

1. Evidence Vault.
2. Official Package Acquisition.
3. Pricing Worksheet.
4. Owner Packet V2.

Then:

5. Submission Readiness Manifest.
6. Autonomous Daily Runner.
7. Trust And Evaluation Harness.

Reasoning:

- Evidence Vault makes resolution real instead of click-based.
- Acquisition reduces upload friction.
- Pricing and Packet V2 complete the owner decision loop.
- Manifest and Daily Runner make it operational.
- Evaluation keeps the deterministic agent trustworthy.

## Definition Of Flow Complete

The flow is complete when all of these are true:

- The agent can find or guide the user to the official package.
- The agent can analyze the package and cite every requirement.
- The agent can reuse company evidence instead of asking for the same confirmations every bid.
- The agent blocks packet prep on unresolved hard stops, missing forms, missing pricing data, expired evidence, and capability gaps.
- The agent creates a defensible price worksheet or clearly refuses to price.
- The owner packet includes compliance, evidence, pricing, next actions, and audit trace.
- Daily reruns update the queue without duplicating tasks.
- Local tests prove no unresolved bid can become packet-ready through browser-submitted state.
