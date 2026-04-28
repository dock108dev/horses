# AIDLC Planning Index

## Intent Source (authoritative)
- BRAINDUMP.md

## Discovery (pre-built — current repo state)
- .aidlc/discovery/findings.md
- .aidlc/discovery/topics.json

## Research (pre-built — answers to discovery topics)
- .aidlc/research/alternative-data-sources.md
- .aidlc/research/equibase-data-access.md
- .aidlc/research/kentuckyderby-odds-endpoint.md
- .aidlc/research/live-odds-timing-and-frequency.md
- .aidlc/research/odds-snapshot-storage-backend.md
- .aidlc/research/pick5-sequence-identification.md
- .aidlc/research/scratch-detection-source.md
- .aidlc/research/twinspires-scraper-feasibility.md

## Existing Issues (14 files in .aidlc/issues/)
Read individual issue files for full specs:
- .aidlc/issues/ISSUE-001.md
- .aidlc/issues/ISSUE-002.md
- .aidlc/issues/ISSUE-003.md
- .aidlc/issues/ISSUE-004.md
- .aidlc/issues/ISSUE-005.md
- .aidlc/issues/ISSUE-006.md
- .aidlc/issues/ISSUE-007.md
- .aidlc/issues/ISSUE-008.md
- .aidlc/issues/ISSUE-009.md
- .aidlc/issues/ISSUE-010.md
- .aidlc/issues/ISSUE-011.md
- .aidlc/issues/ISSUE-012.md
- .aidlc/issues/ISSUE-013.md
- .aidlc/issues/ISSUE-014.md

## Issue Backlog Summary
- Total issues: 14
- Completion: 0/14 (0.0%)
- Priority totals: high=9, medium=5, low=0
- Status totals: pending=14

### Category Rollup (Labels)
- phase-1: 9
- data-source: 3
- frontend: 2
- phase-2: 2
- phase-3: 2
- phase-4: 2
- api: 1
- cache: 1
- infra: 1
- model: 1
- models: 1
- normalization: 1
- simulation: 1
- storage: 1
- tickets: 1
- validation: 1

### Active Issues
- ISSUE-001 [pending] [high] — Project scaffold — Python backend, Next.js frontend, Docker Compose labels: infra, phase-1
- ISSUE-002 [pending] [high] — Shared data models — Pydantic (Python) and TypeScript types labels: models, phase-1
- ISSUE-003 [pending] [high] — Equibase source adapter — race cards, entries, morning line odds, scratches labels: data-source, phase-1
- ISSUE-004 [pending] [high] — TwinSpires + KentuckyDerby source adapters — live odds, program data, scratch detection labels: data-source, phase-1
- ISSUE-005 [pending] [high] — Pick 5 sequence identification (`api/sources/pick5.py`) labels: data-source, phase-1
- ISSUE-006 [pending] [high] — Normalization layer — odds-to-probability, source merging, sequenceRole assignment labels: normalization, phase-1
- ISSUE-007 [pending] [high] — SQLite odds snapshot cache (`api/cache.py`) — persistence, drift series, stale fallback labels: cache, storage, phase-1
- ISSUE-008 [pending] [high] — Scraper validation layer (`api/validate.py`) — post-refresh checks and stale fallback labels: validation, phase-1
- ISSUE-009 [pending] [high] — FastAPI application — all 12 endpoints, CORS, stale-cache response envelope labels: api, phase-1
- ISSUE-010 [pending] [medium] — Probability blending model, JSON priors, and flags computation (`api/model.py`) labels: model, phase-3
- ISSUE-011 [pending] [medium] — Monte Carlo simulation engine (`api/sim.py`) — Pick 5 hit rate estimation labels: simulation, phase-3
- ISSUE-012 [pending] [medium] — Ticket builder (`api/tickets.py`) — A/B/chaos tickets, budget variants labels: tickets, phase-4
- ISSUE-013 [pending] [medium] — Next.js frontend — iPad-optimized day pages, race card UI, horse tagging, manual overrides labels: frontend, phase-2
- ISSUE-014 [pending] [medium] — Simulation + ticket UI components — SimulationSummary and TicketBuilder labels: frontend, phase-2, phase-4

### Completed Issues
- none

## Other Project Docs
- BRAINDUMP.md
