# Feature Workstreams

This splits the 10-Minute Bid Triage workflow into agent-sized feature tracks.

The north star:

> Select or upload a public bid package, get a cited compliance matrix, receive a bid/no-bid recommendation, see a realistic price range, and produce an owner-review packet.

## Workstream 1: Contractor Profile Readiness

**Goal:** Make the contractor profile detailed enough to drive compliance and bid/no-bid decisions.

**Build:**

- profile fields for licenses, certifications, insurance, bonding, safety docs, service radius, crew/equipment, active pursuits, preferred buyers, excluded scopes;
- profile completeness score;
- reusable document inventory: evidence needed, uploaded evidence, expiry, resolved state;
- profile API validation.

**Likely files:**

- `contract_radar/models.py`
- `contract_radar/profiles.py`
- `contract_radar/service.py`
- `static/app.js`
- `static/index.html`
- `tests/test_profiles.py`

**Acceptance criteria:**

- user can see which compliance docs the contractor already has;
- bid engine can reference bonding, insurance, licenses, certifications, and capacity;
- missing profile requirements can become capability gaps or unresolved evidence items.

**Dependencies:** none.

## Workstream 2: Solicitation Package Upload

**Goal:** Let a user upload bid documents instead of relying only on sourced open-data listings.

**Build:**

- upload endpoint for PDFs and supporting documents;
- local document storage under ignored runtime/cache path;
- document metadata model: filename, source, page count, hash, uploaded time, linked opportunity id;
- UI upload action on selected opportunity;
- error handling for unsupported files.

**Likely files:**

- `app.py`
- `contract_radar/service.py`
- new `contract_radar/documents.py`
- `contract_radar/models.py`
- `static/app.js`
- `static/index.html`
- `tests/test_documents.py`

**Acceptance criteria:**

- user can upload a PDF from the UI;
- backend stores metadata and links it to an opportunity;
- repeated uploads of the same file are de-duplicated by hash.

**Dependencies:** none.

## Workstream 3: PDF Text Extraction With Citations

**Goal:** Extract text with page-level citations so every requirement can point back to source.

**Build:**

- PDF text extraction service;
- page text chunks with page number, character offsets, and source filename;
- fallback message for scanned/image-only PDFs;
- citation object model;
- tests with a small fixture PDF.

**Likely files:**

- new `contract_radar/document_text.py`
- `contract_radar/models.py`
- `requirements.txt`
- `tests/test_document_text.py`

**Acceptance criteria:**

- extracting a text PDF returns page chunks;
- each chunk has page/source metadata;
- image-only PDFs fail clearly instead of silently producing fake requirements.

**Dependencies:** Workstream 2 helps, but extraction can be built with local fixtures first.

## Workstream 4: Requirement Extraction And Classification

**Goal:** Convert solicitation text into structured compliance requirements.

**Build:**

- deterministic requirement phrase detector for `shall`, `must`, `mandatory`, `required`, `submit`, `provide`, `attend`, `bond`, `insurance`, `WSIB`, `license`, `certificate`, `addendum`;
- classifier categories: form, certification, insurance, bonding, license, safety, site visit, deadline, pricing sheet, scope, experience, submission instruction, addendum, other;
- evidence model: requirement_detected, evidence_needed, business_has_capability, uploaded_evidence, resolved;
- citations back to extracted text;
- confidence and false-positive controls.

**Likely files:**

- new `contract_radar/compliance.py`
- `contract_radar/models.py`
- `contract_radar/packet.py`
- `tests/test_compliance.py`

**Acceptance criteria:**

- requirement extraction produces structured rows with citation, category, evidence needs, capability signal, uploaded evidence, and resolved state;
- mandatory unresolved items remain open until evidence is recorded or the row is marked not applicable;
- extracted requirements are stable and deterministic on fixture text.

**Dependencies:** Workstream 3.

## Workstream 5: Compliance Matrix API And UI

**Goal:** Show a usable compliance matrix tied to the selected opportunity.

**Build:**

- API endpoint creates a server-side compliance analysis session for an opportunity;
- UI table with category, requirement, resolution state, assignee, citation, evidence needed;
- filters for unresolved evidence, capability gaps, needs review, and resolved rows;
- citation preview panel;
- ability to mark site visits attended, addenda acknowledged, certificates available, pricing forms assigned, rows resolved, or rows not applicable.

**Likely files:**

- `app.py`
- `contract_radar/service.py`
- `static/app.js`
- `static/index.html`
- `static/styles.css`
- `tests/test_service_metrics.py`

**Acceptance criteria:**

- user can inspect all compliance rows for a bid;
- open evidence items and capability gaps are obvious without scrolling through the whole document;
- citation opens or displays the source page/text snippet.

**Dependencies:** Workstreams 2, 3, 4.

## Workstream 6: Bid/No-Bid Engine Integration

**Goal:** Feed compliance findings into the existing recommendation engine.

**Build:**

- hard review/pass rules from unresolved evidence and capability gaps;
- soft warning rules from uncertain requirements;
- score impact for deadline, bonding, insurance, license, capacity, missing mandatory forms;
- updated `BidFitnessTrace` entries;
- explainable final rationale.

**Likely files:**

- `contract_radar/matcher.py`
- `contract_radar/models.py`
- `contract_radar/service.py`
- `contract_radar/briefs.py`
- `tests/test_matcher.py`
- `tests/test_service_metrics.py`

**Acceptance criteria:**

- unresolved mandatory compliance evidence can downgrade `Pursue` to `Review` or `Pass`;
- final rationale names the exact open item and citation;
- existing bid/no-bid tests still pass.

**Dependencies:** Workstream 4.

## Workstream 7: Price Range And Comparable Awards Upgrade

**Goal:** Make price guidance feel credible for municipal contractors.

**Build:**

- improve comparable-award selection by scope, buyer/division, category, contract type, location, deadline period;
- show low/target/high range;
- expose assumptions: direct cost, overhead, contingency, target margin, confidence;
- flag when historical data is too weak for confident pricing.

**Likely files:**

- `contract_radar/bid_pricing.py`
- `contract_radar/history.py`
- `contract_radar/rag.py`
- `contract_radar/ranker.py`
- `static/app.js`
- `tests/test_bid_pricing.py`
- `tests/test_history.py`

**Acceptance criteria:**

- every recommended bid shows comparable awards or says why it cannot;
- price range includes confidence and assumptions;
- weak comps reduce confidence instead of pretending precision.

**Dependencies:** none, but benefits from Workstream 6.

## Workstream 8: Owner Packet V2

**Goal:** Produce a one-page owner-review packet that combines decision, compliance, pricing, and next actions.

**Build:**

- packet sections: recommendation, rationale, price range, open evidence items, unresolved documents, requirements checklist, buyer questions, next actions, citations;
- markdown export;
- later: PDF/DOCX export;
- packet status: draft, ready for owner, blocked, approved.

**Likely files:**

- `contract_radar/packet.py`
- `contract_radar/models.py`
- `contract_radar/service.py`
- `static/app.js`
- `tests/test_packet.py`

**Acceptance criteria:**

- packet includes open compliance evidence items, capability gaps, and source citations;
- approved packet never implies the app submitted the bid;
- markdown export is readable and can be sent to an owner.

**Dependencies:** Workstreams 4, 6, 7.

## Workstream 9: Workflow State And Task Tracking

**Goal:** Track a bid from triage to owner decision without becoming a CRM.

**Build:**

- opportunity workflow states: new, triaged, blocked, review, pursuing, passed, packet ready, approved;
- task list for missing docs, pricing review, buyer question, owner approval;
- local persistence for current workspace;
- simple audit log.

**Likely files:**

- new `contract_radar/workflow.py`
- `contract_radar/models.py`
- `contract_radar/service.py`
- `static/app.js`
- `tests/test_workflow.py`

**Acceptance criteria:**

- user can mark a bid as pass/pursue/review;
- missing compliance rows create tasks;
- state survives page refresh in local mode.

**Dependencies:** Workstreams 4, 5, 8.

## Workstream 10: Trust, Evaluation, And QA Harness

**Goal:** Make the agent trustworthy by measuring extraction quality and preventing hallucinated compliance.

**Build:**

- fixture solicitation documents with expected requirement rows;
- extraction precision/recall checks;
- citation coverage metric;
- benchmark output for triage time, requirements extracted, open evidence items found, price confidence;
- tests that fail if uncited requirements enter the compliance matrix.

**Likely files:**

- `tests/fixtures/`
- `tests/test_compliance.py`
- `tests/test_document_text.py`
- `scripts/benchmark_pipeline.py`
- new `scripts/evaluate_compliance_extraction.py`

**Acceptance criteria:**

- every compliance row must have a source citation or explicit fallback reason;
- benchmark reports triage pipeline metrics;
- test fixtures catch regressions in requirement extraction.

**Dependencies:** Workstreams 3, 4.

## Workstream 11: Weekly Bid Queue UX

**Goal:** Make the app feel like a bid department already did the first pass.

**Build:**

- queue grouped by `Pursue`, `Review`, `Pass`;
- top metrics: bids reviewed, hours saved, open evidence items found, pricing confidence;
- selected-bid detail with decision proof, compliance matrix, price range, owner packet;
- reduce generic dashboard feel.

**Likely files:**

- `static/index.html`
- `static/app.js`
- `static/styles.css`

**Acceptance criteria:**

- first screen shows what to act on, not a generic search table;
- user can go from queue item to open compliance evidence to owner packet in one flow;
- mobile and desktop layouts do not overlap.

**Dependencies:** Workstreams 5, 6, 8.

## Workstream 12: Customer Discovery Instrumentation

**Goal:** Capture whether the workflow actually saves contractor time.

**Build:**

- fields for estimated hours saved;
- pass reason tracking;
- owner decision outcome tracking;
- exportable discovery notes after each triage;
- lightweight feedback buttons: useful, wrong, missing requirement, pricing off.

**Likely files:**

- `contract_radar/models.py`
- `contract_radar/service.py`
- `static/app.js`
- `tests/test_backtest.py`

**Acceptance criteria:**

- app records why bids were passed;
- owner can mark whether recommendation was useful;
- data can support customer discovery conversations.

**Dependencies:** Workstreams 6, 8.

## Suggested Parallel Plan

Phase 1 can run in parallel:

- Agent A: Workstream 2, solicitation upload.
- Agent B: Workstream 3, PDF extraction with citations.
- Agent C: Workstream 4, requirement extraction.
- Agent D: Workstream 7, pricing/comparable awards upgrade.

Phase 2 follows:

- Agent E: Workstream 5, compliance matrix UI/API.
- Agent F: Workstream 6, bid/no-bid integration.
- Agent G: Workstream 10, QA/evaluation harness.

Phase 3 polishes the product:

- Agent H: Workstream 8, owner packet V2.
- Agent I: Workstream 9, workflow state.
- Agent J: Workstream 11, weekly bid queue UX.
- Agent K: Workstream 12, customer discovery instrumentation.

## Critical Path

The shortest path to the killer workflow is:

1. Workstream 2: upload documents.
2. Workstream 3: extract text with citations.
3. Workstream 4: extract requirements.
4. Workstream 5: show compliance matrix.
5. Workstream 6: feed unresolved evidence and capability gaps into bid/no-bid.
6. Workstream 8: produce owner packet.

Everything else improves trust, pricing, UX, or learning, but this path proves the core product.
