# Project Bid Bot

Project Bid Bot is an early bid-procurement agent for small public-sector contractors. It scans Toronto procurement data, filters out bad-fit opportunities, estimates likely bid ranges from historical awards, explains compliance risks, and prepares an owner-review packet before anyone wastes a day on a weak bid.

The current repo is deliberately simple and local-first. It is not a hardware showcase and it does not submit bids automatically. The reusable core is the procurement workflow:

- business profile and capability matching;
- historical award retrieval and market-fit scoring;
- bid/no-bid labels: `Pursue`, `Review`, `Monitor`, `Skip`;
- pricing worksheet and recommended bid range;
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
python scripts\benchmark_pipeline.py --offline --repeat 2 --json
python -m unittest
```

## API

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/health` | GET | Runtime status, supported business profiles, ranker/value-model status |
| `/api/scan` | POST | Load procurement data, score opportunities, price bids, generate briefs |
| `/api/simulate` | POST | Run a short opportunity timeline simulation |
| `/api/approve` | POST | Create an owner-review packet for a selected opportunity |

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
scripts/precompute_scan_cache.py precomputed scan replay helper
tests/                         unit and integration tests
```

## Product Direction

The reusable idea is an agentic bid department, not another search dashboard. The next useful product steps are:

- narrow the first customer wedge by contractor type and data source;
- add deeper compliance extraction from solicitation PDFs/addenda;
- improve bid amount calibration by segment, buyer, and scope;
- track submitted bids and outcomes so the model learns from real customer history;
- build human approval checkpoints before any buyer-facing action.
