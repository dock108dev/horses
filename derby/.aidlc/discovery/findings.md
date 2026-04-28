# Findings

## Repository State

The repository contains **zero implementation code**. Every file listed in BRAINDUMP.md must be built from scratch.

### Files That Exist

| File | Status |
|------|--------|
| `BRAINDUMP.md` | Complete design spec — 558-line authoritative document |
| `.gitignore` | Minimal — ignores `.aidlc/runs/` and `.aidlc/reports/` |
| `.aidlc/config.json` | AIDLC harness config (budget: 4h, checkpoints: 15m, provider: Claude) |
| `.aidlc/runs/aidlc_20260428_034742/state.json` | Current run state (phase: discovery, 0 files created) |
| `.aidlc/runs/aidlc_20260428_034742/*.log` | Harness execution log |

### Files That Do Not Exist (per BRAINDUMP spec)

**Backend (`api/`)**
- `api/main.py` — FastAPI/Flask app with all routes
- `api/sources/twinspires.py` — TwinSpires adapter
- `api/sources/kentuckyderby.py` — KentuckyDerby.com adapter
- `api/sources/equibase.py` — Equibase adapter
- `api/normalize.py` — Odds-to-probability conversion, normalization
- `api/cache.py` — Snapshot cache
- `api/model.py` — Probability blending + JSON priors
- `api/sim.py` — Monte Carlo simulation engine
- `api/tickets.py` — Ticket builder/optimizer

**Frontend (`web/`)**
- `web/app/page.tsx` — Main page
- `web/app/sequence/[day]/page.tsx` — Friday/Saturday day pages (Next.js App Router convention)
- `web/components/RaceCard.tsx`
- `web/components/HorseRow.tsx`
- `web/components/OddsBadge.tsx`
- `web/components/TicketBuilder.tsx`
- `web/components/SimulationSummary.tsx`

**Config/infra**
- `docker-compose.yml` — Not created
- `Dockerfile` (backend) — Not created
- `requirements.txt` / `pyproject.toml` — Not created
- `package.json` — Not created
- `.env.example` — Not created

**Data files**
- Model priors JSON (`race_type_priors`, `field_size_priors`) — Not created
- Any test fixtures or cached snapshots — Not created

---

## What BRAINDUMP Already Fully Specifies (No Research Needed)

### Data Models
`Race` and `Horse` TypeScript types fully defined in BRAINDUMP — all fields named including `sequenceRole`, `userTag`, `marketProbability`, `morningLineProbability`, `modelProbability`, `finalProbability`.

`OddsSnapshot` type fully defined: `{timestamp, day, raceNumber, horseId, odds, impliedProbability, source}`.

### API Contracts
All 12 endpoints defined:
```
GET /api/cards/{friday|saturday}
POST /api/cards/{friday|saturday}/refresh
GET /api/odds/{friday|saturday}
POST /api/odds/{friday|saturday}/refresh
POST /api/simulate/{friday|saturday}
POST /api/tickets/{friday|saturday}/build
```

### Probability Blending Formula
```
final = current_odds_prob * 0.70 + morning_line_prob * 0.20 + model_prior * 0.10
# fallback if no model prior:
final = current_odds_prob * 0.80 + morning_line_prob * 0.20
```

### Odds-to-Probability Conversion
Standard: `prob = 1 / (odds + 1)` for fractional odds. Normalize per race to 100%.

### Ticket Structure
- Main: A/A/A/A/A
- Backups: one B per leg × 5
- Chaos: value/separator horses
- Budgets: $48, $96, $144, $192, custom
- Base unit: $0.50

### Simulation
25,000–100,000 Monte Carlo iterations in the backend. Output: hit rate estimate, chalkiness, chaos/separator coverage.

### Model v1 Format
JSON priors file with `race_type_priors` (field: `large_field_dirt_route`, `small_field_chalk`) and `field_size_priors` (key: field size bucket, value: `favoriteWinRate`).

### Flags System
Full list in BRAINDUMP: overbet favorite, useful value, public single, good/bad single, chaos race, spread race, likely separator, taking money, cold on board, scratch, missing odds.

### Validation Rules
After refresh: all 5 legs loaded, every horse has post/name, odds parsed, no duplicates, scratches flagged, probabilities sum to 100%.

### Cache Strategy
Always cache last good snapshot; show staleness timestamp on failure. Never go blank on race day.

### Frontend Framework (Implied)
`app/page.tsx` and `app/sequence/[day]/page.tsx` conventions match **Next.js App Router**. iPad access via `http://mac-mini.local:3000` (mDNS on local network).

### Build Order
Phase 1: data pipeline → Phase 2: browser UI → Phase 3: simulation → Phase 4: ticket builder.

---

## Systems with Real Unknowns

### Data Sources (the critical unknown)
BRAINDUMP names three sources but provides no URL specifics, page structure, auth requirements, or feasibility assessment. This is the highest-risk area — BRAINDUMP explicitly says "the app lives or dies on automated data."

### Pick 5 Sequence Identification
BRAINDUMP assumes the adapter can identify which race numbers are Pick 5 legs for Friday (Kentucky Oaks day) and Saturday (Derby day). It does not specify how this determination is made programmatically.

### Snapshot Storage Backend
BRAINDUMP specifies the `OddsSnapshot` type but does not specify the storage mechanism (SQLite, JSON files, Redis, etc.).

### Simulation Placement
BRAINDUMP says "run 25,000–100,000 simulations" but does not specify whether the Monte Carlo engine runs in the Python backend (returning JSON results) or in the browser (WASM or JS worker). Given the backend-first architecture, Python is implied, but it affects API design.

---
