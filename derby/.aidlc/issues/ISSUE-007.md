# ISSUE-007: SQLite odds snapshot cache (`api/cache.py`) — persistence, drift series, stale fallback

**Priority**: high
**Labels**: cache, storage, phase-1
**Dependencies**: ISSUE-002
**Status**: implemented

## Description

Implement `api/cache.py` using SQLite with WAL mode per odds-snapshot-storage-backend.md recommendation. Per-day DB file at `data/odds_{YYYY-MM-DD}.db`. WAL + NORMAL sync pragma on connection open. Two tables: (1) `odds_snapshots(id, race_id, horse_id, horse_name, odds, implied_probability, source, captured_at_ms)` with composite index on (race_id, horse_id, captured_at_ms); (2) `card_snapshots(id, day, card_json, captured_at_ms, validated)` for full Race object blobs. Key operations: `store_odds_batch(snapshots)` — insert all in single transaction (critical for performance per research); `get_latest_odds(race_id)` — latest per-horse snapshot using MAX(captured_at_ms) GROUP BY horse_id; `get_drift_series(race_id, horse_id)` — chronological list of (timestamp, odds, implied_probability) for drift chart display; `store_card(day, races, validated)` — serialize Race list to JSON blob; `get_last_good_card(day)` — return most recent card where validated=true plus its timestamp. On process restart, open existing DB file — all prior-session data immediately queryable.

## Acceptance Criteria

- [ ] After storing snapshots and restarting the process, get_latest_odds returns correct data without re-fetching
- [ ] get_drift_series returns list in ascending captured_at order
- [ ] 50-horse batch insert in single transaction completes in <100ms
- [ ] get_last_good_card returns card JSON + captured_at timestamp when a validated card exists
- [ ] get_last_good_card returns None when no validated card has been stored for that day
- [ ] DB file created at data/odds_{YYYY-MM-DD}.db on first write

## Implementation Notes


Attempt 1: Added api/cache.py — per-day SQLite WAL cache (data/odds_{day}.db) with odds_snapshots and card_snapshots tables. OddsCache exposes store_odds_batch (single-tx insert), get_latest_odds (MAX-per-horse), get_drift_series (chronological), store_card (Race[] → JSON), get_last_good_card (latest validated). Frozen dataclasses OddsSnapshotRecord and CachedCard. 16 new tests, all 132 pass.