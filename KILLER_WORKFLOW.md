# Killer Workflow: 10-Minute Bid Triage

Project Bid Bot should win by helping contractors avoid bad bids before they spend estimator time.

The core workflow is not "AI writes a proposal." It is:

> Before you spend 20 hours on a bid, Project Bid Bot tells you if it is worth pursuing, what price range is realistic, and what would make you non-compliant.

## Research Signals

- Public procurement is hard for SMEs because procedures are complex, administrative burden is high, and technical or financial requirements can block access. Source: [OECD, SMEs in Public Procurement](https://www.oecd.org/en/publications/smes-in-public-procurement_9789264307476-en.html).
- Construction SMEs feel the burden most during searching, compiling formalities, and submitting offers. One IfM Bonn study found the smallest construction company studied incurred about EUR 3,070 per municipal tender, with offer preparation making up 50%-90% of monetary costs. Source: [IfM Bonn](https://www.ifm-bonn.org/en/news/meldung/participation-in-public-tenders-is-a-considerable-burden-for-small-and-medium-sized-construction-companies).
- Construction bid/no-bid decisions are driven by scope clarity, project risk, payment and cash flow, similar experience, workload, location, and probability of winning. Source: [Buildings journal bid/no-bid study](https://www.mdpi.com/2075-5309/14/10/3114).
- Proposal best practice says the compliance matrix should start at the beginning because it maps RFP requirements to response locations and helps verify all requirements are addressed. Sources: [AcqNotes compliance matrix](https://acqnotes.com/acqnote/tasks/proposal-compliance-matrix), [APMP NL compliance matrix](https://www.apmp.nl/2018/11/compliance-matrix/).
- RFP teams are becoming more selective; Loopio/APMP reported that 83% of teams use a go/no-go process. Treat this as vendor-survey evidence, not neutral academic proof. Source: [Loopio/APMP 2025 report announcement](https://loopio.com/blog/loopio-releases-sixth-annual-rfp-response-trends-and-benchmarks-report/).

## Target User

Municipal service and construction contractors who repeatedly bid on similar scopes:

- road repair, asphalt, pavement markings, curb, sidewalk;
- parks, landscaping, trails, playgrounds, fencing, arborist work;
- snow removal, salting, sweeping, seasonal maintenance;
- facilities maintenance, small renovations, signage, painting;
- civil works, catch basins, site servicing, water/sewer service connections.

The buyer is usually an owner, estimator, operations manager, or admin who does not have a dedicated capture team.

## User Promise

The app should answer five questions in one pass:

1. Should we bid?
2. What would disqualify us?
3. What price range is realistic?
4. What documents or actions are missing?
5. What should the owner approve next?

## Workflow

### 1. Intake The Contractor

Collect enough profile data to make bid/no-bid decisions:

- service categories and excluded scopes;
- geography and travel radius;
- crew size, equipment, and weekly estimator capacity;
- bonding, insurance, licenses, certifications, safety docs;
- past municipal work and preferred buyers;
- active pursuits and current workload;
- target contract size and minimum profitable job size.

Output: a contractor profile with explicit capabilities, constraints, and reusable compliance documents.

### 2. Ingest The Opportunity

The user can select a sourced opportunity or upload a solicitation package.

Required inputs:

- title, buyer, source URL, deadline, location;
- solicitation PDF or buyer document package;
- addenda, forms, drawings, schedules, pricing sheets when available;
- historical award records for similar buyer/scope/category.

Output: normalized opportunity record plus extracted document text with page/section references.

### 3. Extract Compliance Requirements

Build a compliance matrix before any proposal writing.

Each requirement row should include:

- source citation: page, section, paragraph, or nearby text;
- requirement text;
- requirement type: mandatory form, certification, insurance, bonding, license, site visit, deadline, pricing sheet, scope, safety, experience, submission instruction;
- requirement detected flag;
- evidence needed;
- whether the business appears to have the capability;
- uploaded or confirmed evidence;
- resolved state;
- owner or assignee;
- due date or trigger;
- why it matters.

Output: a traceable compliance session with citations and resolvable evidence gaps.

### 4. Run Deterministic Agent Runtime

Before scoring or packet preparation, the app should rebuild server-owned agent artifacts:

- evidence ledger: sourced facts only, with citation, source type, and confidence;
- action trace: typed actions from the allowed deterministic action list;
- bid state: uploaded, parsed, extracted, gaps open, or packet ready;
- gate results: hard stops and review gates from compliance rows;
- agent tasks: exact next actions with resolution options and citations.

Output: an auditable agent state where no unsourced fact can move the bid forward.

### 5. Score Bid/No-Bid

Use deterministic gates and learned/history-based signals.

Hard no-bid or review gates:

- unresolved mandatory license or certification evidence;
- bonding or insurance above available limits;
- mandatory site meeting already missed;
- deadline too close for current capacity;
- unresolved scope conflicts with excluded capabilities;
- location outside service area;
- contract value too large or too small to be attractive.

Soft warnings:

- unclear scope;
- weak similar experience;
- high buyer friction or poor payment history when data exists;
- crowded competitor pattern;
- unusual terms;
- high crew or equipment load;
- missing supporting documents.

Positive signals:

- similar past work;
- repeat buyer/division;
- scope matches owned equipment and crew;
- historical awards in target value band;
- deadline is manageable;
- compliance docs are mostly ready.

Output: `Pursue`, `Review`, or `Pass`, with reasons.

After the official PDF is analyzed, the deterministic compliance decision overlays the original scan label:

- hard stop open: show blocked and prevent packet preparation;
- review gate open: show review until resolved;
- capability gap: show pass unless the owner explicitly confirms capability or marks the row not applicable;
- all gates resolved: eligible to pursue and prepare bid notes.

### 6. Estimate Price Range

Use historical awards and contractor constraints to produce a realistic bid range.

Inputs:

- similar award values;
- buyer/division patterns;
- scope terms and quantities when available;
- contract type;
- estimated direct cost assumptions;
- overhead, contingency, and target margin;
- win probability or competitiveness band.

Output:

- likely low, target, and high bid;
- confidence level;
- comparable awards used;
- pricing risks and assumptions.

### 7. Produce The Owner Packet

Generate a one-page decision packet.

Packet sections:

- recommended action: pursue, review, or pass;
- short rationale;
- likely price range;
- top open compliance evidence items and capability gaps;
- deterministic agent audit summary;
- missing documents;
- required forms and deadlines;
- buyer clarification questions;
- next 3 owner actions;
- source links and citations.

Output: owner-review packet that can be exported or copied into a working bid folder.

### 7. Human Approval Gate

The app should not submit a bid automatically.

Owner decisions:

- approve pursuit;
- assign estimator;
- request missing documents;
- mark as pass;
- ask buyer clarification question;
- export packet.

Output: approved next action, not automatic submission.

## MVP Screen

The first useful screen should be a weekly bid queue:

- left: recommended bids sorted by value and urgency;
- center: selected bid triage summary;
- right: compliance matrix and owner packet;
- top metrics: bids reviewed, passes avoided, estimator hours saved, open evidence items, pricing confidence.

Avoid a generic search table as the primary experience. Search can exist, but the product should feel like a bid department already did the first pass.

## Acceptance Criteria

The workflow is successful when a contractor can:

- upload or select a bid package;
- see a traceable compliance matrix within 10 minutes;
- get a bid/no-bid recommendation with unresolved evidence items, capability gaps, and soft warnings;
- see a realistic price range grounded in similar awards;
- export or review an owner packet;
- confidently decide whether to spend estimator time.

## Next Build Step

Build document ingestion and compliance extraction first.

Minimum implementation:

1. Upload solicitation PDF.
2. Extract text by page.
3. Detect mandatory requirement phrases.
4. Classify requirements into compliance categories.
5. Store source citations.
6. Show a compliance matrix.
7. Feed unresolved evidence items and capability gaps into the existing bid/no-bid engine.
8. Add compliance rows to the approval packet.

This is the narrowest feature that makes Project Bid Bot feel less like a dashboard and more like an agentic bid department.
