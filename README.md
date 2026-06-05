# Project Bid Bot

Project Bid Bot is an early bid-procurement agent for small public-sector contractors. It scans Toronto procurement data, filters out bad-fit opportunities, estimates likely bid ranges from historical awards, explains compliance risks, and prepares an owner-review packet before anyone wastes a day on a weak bid.

The current repo is deliberately simple and local-first. It is not a hardware showcase and it does not submit bids automatically. The reusable core is the procurement workflow:

- business profile and capability matching;
- historical award retrieval and market-fit scoring;
- bid/no-bid labels: `Pursue`, `Review`, `Monitor`, `Skip`;
- pricing worksheet and recommended bid range;
- estimator approval gate before owner packet readiness;
- revenue and capacity planning;
- deterministic bid brief and approval packet generation;
- proof metrics for data source status, shortlist reduction, pricing coverage, and model performance.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8080`.

To run the finished local deterministic demo from the terminal:

```powershell
python scripts\run_agent_demo.py --reset
```

To run the same demo in the browser, start `python app.py` and click **Run Local Demo**. The demo creates a road-repair opportunity, imports a company rate card, analyzes the generated solicitation PDF, resolves deterministic requirements, approves estimator pricing, prepares the owner packet, exports Markdown, and stops with a clear warning that human buyer-portal submission is still manual.

To run the agent-facing deal-to-approval pipeline:

```powershell
python scripts\run_bid_pipeline.py --profile-id road_civil_infrastructure
```

That command scans for current deal work, executes only safe automatic tasks, and returns `next_agent_actions` with exact endpoints, payload templates, `completed_action_template` JSON, approval commands, package download filenames, or packet download links. When packages are needed, `package_directory_manifest` gives the deterministic `OPPORTUNITY_ID__anything.pdf` names and the `--package-dir` resume command. When a packet is generated, `generated_bid_packages` contains the structured export, pricing, manifest, form fields, attachments, portal steps, and final human-submission guardrails. It also returns `portal_submission_requests` so a browser/portal agent can prepare fields and attachments while stopping before final submit/certify controls.

For compact terminal-agent handoff files instead of one large JSON blob:

```powershell
python scripts\run_bid_pipeline.py --agent-work-dir .\agent-work
python scripts\run_bid_pipeline.py --resume-agent-work-dir .\agent-work --agent-work-dir .\agent-work
```

The handoff directory includes `owner-approval-requests.json`, `portal-package-requests.json`, plus one file per request under matching subfolders. It also writes fillable report templates under `reports\` and indexes them in `report-templates.json`; unfilled templates are ignored by `--resume-agent-work-dir` until an agent or human fills them. Owner approval request files contain an `approval_report_template`; setting `approved: true` in a report lets `--resume-agent-work-dir` generate the owner packet from the current server-owned request id. Each portal package request is a browser/portal-agent contract with the portal URL, search hint, expected documents, target filename, validation rules, guardrails, exact resume commands, and a `completion_report_template`. If the portal requires credentials, payment, or terms acceptance, the package request must remain human-required. When bid packages are generated, the handoff also writes `portal-submission-requests.json` plus per-request files under `portal-submission-requests\`; these are preparation-only contracts that copy known fields and prepare/upload attachments but explicitly stop before final submission. `--resume-agent-work-dir` lets a terminal agent rerun from the same folder after it adds owner approval reports, completed action JSON, portal package reports, portal submission reports, or downloaded `OPPORTUNITY_ID__anything.pdf` packages.

The same single-directory resume is available through the local API for browser/desktop agents:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/agent/workdir-resume -ContentType "application/json" -Body '{"agent_work_dir": ".\\agent-work", "profile_id": "road_civil_infrastructure"}'
```

After a browser or portal agent prepares fields/attachments from a `portal-submission-requests\*.json` file, it can save a filled preparation report and record it for audit. Reports that claim final submission are rejected:

```powershell
python scripts\run_bid_pipeline.py --portal-submission-report-file .\agent-work\reports\portal-submission-report.json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/agent/submission-report -ContentType "application/json" -Body (Get-Content .\agent-work\reports\portal-submission-report.json -Raw)
```

After a browser or terminal agent downloads an official package, it can fill the request's `completion_report_template` with the local PDF path and resume without hand-building base64.

To apply the report through the running local API and immediately get the resumed pipeline state back, include `resume_pipeline: true` in the report payload:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/agent/package-report -ContentType "application/json" -Body (Get-Content .\agent-work\package-report.json -Raw)
```

Or resume through the CLI:

```powershell
python scripts\run_bid_pipeline.py --portal-package-report-file .\agent-work\package-report.json
```

For multiple package reports:

```powershell
python scripts\run_bid_pipeline.py --portal-package-report-dir .\agent-work\package-reports
```

After an owner approves a specific current request id, generate the packet with:

```powershell
python scripts\run_bid_pipeline.py --approval-request-id <approval-request-id> --approved-by Owner
```

To resume after a human or another agent completes a required payload, save the completed action JSON and run:

```powershell
python scripts\run_bid_pipeline.py --completed-action-file completed-action.json
```

Or POST the completed action template to the running local API and get the resumed pipeline state back:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/agent/completed-actions -ContentType "application/json" -Body (Get-Content .\agent-work\completed-action.json -Raw)
```

To resume from a filled agent handoff directory, point the pipeline at the directory or its `completed-action-templates` subfolder:

```powershell
python scripts\run_bid_pipeline.py --completed-action-dir .\agent-work
```

If an agent or human has already downloaded the official package PDF locally, resume without hand-building base64 JSON:

```powershell
python scripts\run_bid_pipeline.py --package-file <opportunity-id>=C:\path\to\official-package.pdf
```

For a batch of downloaded packages, name each PDF `OPPORTUNITY_ID__anything.pdf` and run:

```powershell
python scripts\run_bid_pipeline.py --package-dir C:\path\to\downloaded-packages
```

Owner approval can also be resumed through the same completed-action path by saving the owner `completed_action_template` returned in `next_agent_actions`. Only known bid workflow endpoints are accepted as completed actions; this is not a generic endpoint executor.

Useful checks:

```powershell
python scripts\smoke_api.py
python scripts\evaluate_bid_flow.py
python scripts\benchmark_pipeline.py --offline --repeat 2 --json
python -m unittest
```

## API

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/health` | GET | Runtime status, supported business profiles, ranker/value-model status |
| `/api/agent/pipeline` | POST | Run deal discovery through owner approval handoff, apply bounded completed action payloads, and generate packets only for supplied or completed current approval request ids |
| `/api/agent/package-report` | POST | Apply a browser/portal package completion report by verifying the local PDF and analyzing it through the bounded document path |
| `/api/agent/completed-actions` | POST | Apply bounded completed action templates through the pipeline whitelist and return the resumed pipeline state |
| `/api/agent/owner-approval-report` | POST | Apply an explicit owner approval decision report through the server-owned approval request pipeline |
| `/api/agent/submission-report` | POST | Record a portal preparation report for copied fields/attachments/blockers while rejecting final-submit claims |
| `/api/agent/workdir-resume` | POST | Load one local agent handoff directory, apply completed reports/downloaded PDFs through the deterministic pipeline, and return the resumed next actions |
| `/api/agent/run` | POST | Run the local autonomous-safe agent over current opportunities |
| `/api/agent/run-until-approval` | POST | Execute safe current tasks until owner approval, human input, error, or max steps |
| `/api/agent/task/execute` | POST | Execute one current server-owned safe task or return the required human payload |
| `/api/daily/run` | POST | Run the local daily bid agent and reconcile persistent task state |
| `/api/scan` | POST | Load procurement data, score opportunities, price bids, generate briefs |
| `/api/simulate` | POST | Run a short opportunity timeline simulation |
| `/api/documents/acquire` | POST | Start official-package acquisition or metadata-only intake |
| `/api/documents/analyze` | POST | Analyze an uploaded solicitation PDF with cited compliance extraction |
| `/api/evidence/upload` | POST | Store local company evidence for reuse across bids |
| `/api/compliance/attach-evidence` | POST | Attach vault evidence to a server-owned requirement |
| `/api/compliance/resolve` | POST | Resolve a deterministic compliance requirement |
| `/api/pricing/input` | POST | Record typed estimator pricing inputs on a server-owned analysis |
| `/api/pricing/approve` | POST | Approve the server-owned target bid before packet readiness |
| `/api/packets/export` | POST | Return saved Markdown export metadata for an approved packet |
| `/api/packets/export/{export_id}` | GET | Download a saved packet Markdown export |
| `/api/outcomes/record` | POST | Record submitted/won/lost bid outcomes for local ranking and pricing feedback |
| `/api/approve` | POST | Create an owner-review packet for a selected packet-ready opportunity |

## Data

The app prefers cached or live Toronto Open Data procurement records. Bundled sample records are only for local testing and require:

```powershell
$env:CONTRACT_RADAR_ALLOW_SAMPLE_DATA="1"
```

Offline mode uses `data/cache`:

```powershell
$env:CONTRACT_RADAR_OFFLINE="1"
```

## Repo Map

```text
app.py                         local HTTP server
contract_radar/                procurement engine, scoring, pricing, briefs, packets
static/                        browser UI
scripts/benchmark_pipeline.py  local pipeline benchmark
scripts/smoke_api.py           API smoke test
scripts/evaluate_bid_flow.py   deterministic fixture evaluation for bid-flow safety
scripts/run_bid_pipeline.py    agent-facing deal-to-approval pipeline runner
scripts/precompute_scan_cache.py precomputed scan replay helper
tests/                         unit and integration tests
```

## Product Direction

The current wedge is documented in [PRODUCT_WEDGE.md](PRODUCT_WEDGE.md).
The next workflow spec is documented in [KILLER_WORKFLOW.md](KILLER_WORKFLOW.md).
The implementation workstreams are documented in [FEATURE_WORKSTREAMS.md](FEATURE_WORKSTREAMS.md).
The remaining product-completion gaps are documented in [FLOW_COMPLETION_PLAN.md](FLOW_COMPLETION_PLAN.md).
The agent handoff for missing autonomous-workflow pieces is documented in [AUTONOMOUS_AGENT_MISSING_WORK.md](AUTONOMOUS_AGENT_MISSING_WORK.md).

The reusable idea is an agentic bid department, not another search dashboard. The next useful product steps are:

- narrow the first customer wedge by contractor type and data source;
- add deeper compliance extraction from solicitation PDFs/addenda;
- improve bid amount calibration by segment, buyer, and scope;
- expand submitted-bid outcome learning with richer win/loss calibration and bad-fit feedback;
- build human approval checkpoints before any buyer-facing action.
