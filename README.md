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
