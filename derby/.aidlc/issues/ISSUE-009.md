# ISSUE-009: FastAPI application — all 12 endpoints, CORS, stale-cache response envelope

**Priority**: high
**Labels**: api, phase-1
**Dependencies**: ISSUE-006, ISSUE-007, ISSUE-008
**Status**: implemented

## Description

Implement `api/main.py` with FastAPI. CORS: allow origins `http://localhost:3000` and `http://mac-mini.local:3000` and `http://localhost:8000`. Validate `day` path param as Literal['friday','saturday'] — return 422 for other values. Implement all 12 endpoints per BRAINDUMP spec. Standard response envelope: `{data, stale: bool, cached_at: str|null, source: str, errors: list[str]}`. GET /api/cards/{day}: return get_last_good_card; POST /api/cards/{day}/refresh: run Equibase fetch → normalize → validate → store_card, return result or stale fallback on failure. GET /api/odds/{day}: return get_latest_odds for all Pick 5 races; POST /api/odds/{day}/refresh: run TwinSpires odds fetch → normalize → store_odds_batch → validate → return or stale fallback. POST /api/simulate/{day}: delegate to sim engine (ISSUE-011). POST /api/tickets/{day}/build: delegate to ticket builder (ISSUE-012). All refresh endpoints: on exception, catch, log, return stale cache with error detail. GET /api/health: returns `{status: 'ok'}`.

## Acceptance Criteria

- [ ] All 12 endpoints return 200 with JSON envelope on happy path
- [ ] POST /api/cards/friday/refresh triggers Equibase fetch and returns validated card
- [ ] POST /api/odds/saturday/refresh triggers TwinSpires poll and returns latest odds
- [ ] On refresh failure, stale=true returned with cached_at timestamp and errors[] from validation
- [ ] CORS allows requests from http://localhost:3000 and http://mac-mini.local:3000
- [ ] day='monday' returns 422 Unprocessable Entity
- [ ] GET /api/health returns {status: 'ok'} with 200

## Implementation Notes


Attempt 1: Implemented FastAPI app in api/main.py with all 12 endpoints (cards/odds/simulate/tickets per friday|saturday) plus /api/health. Day path-param uses Literal['friday','saturday'] → 422 for other values. CORS allows http://localhost:3000, http://mac-mini.local:3000, http://localhost:8000 (override via API_CORS_ORIGINS). Standard {data, stale, cached_at, source, errors} envelope; refresh endpoints catch exceptions and validation failures, returning stale cache with errors. Orchestration helpers extracted to api/refresh.py for testability.