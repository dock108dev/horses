# ISSUE-005: Pick 5 sequence identification (`api/sources/pick5.py`)

**Priority**: high
**Labels**: data-source, phase-1
**Dependencies**: ISSUE-003
**Status**: implemented

## Description

Implement `get_pick5_legs(year: int, day: str) -> list[int]` per the three-tier strategy from pick5-sequence-identification.md. Tier 1 (primary): hardcoded year-keyed constants for Churchill Downs Derby week — 5-year historical pattern is stable: Oaks day (Friday) = races 8–12; Derby day (Saturday) = races 9–13. Constants for 2024 and 2025 verified from research; 2026 values use same pattern. Tier 2 (verification): parse Equibase full-card HTML wager-type list per race; find first race with 'Pick 5' in its wager menu, return range(start, start+5). Apply sanity check: first leg must be >= 7. If scraped differs from hardcoded, emit warning log and return scraped value. Tier 3 (last resort heuristic): return last 5 races of the day if both Tier 1 and Tier 2 fail. Function should never raise — always return a list of 5 integers.

## Acceptance Criteria

- [ ] get_pick5_legs(2026, 'friday') returns [8, 9, 10, 11, 12] from hardcoded constants
- [ ] get_pick5_legs(2026, 'saturday') returns [9, 10, 11, 12, 13] from hardcoded constants
- [ ] If Equibase parse returns different first leg, warning is logged and scraped value is returned
- [ ] Function returns list of exactly 5 integers in all code paths including error paths
- [ ] Tier-3 heuristic returns last 5 races when total_races is provided

## Implementation Notes


Attempt 1: Implemented three-tier Pick 5 leg resolver in api/sources/pick5.py: hardcoded year-keyed constants for 2024-2026 (Fri=8-12, Sat=9-13), Equibase full-card scrape with MIN_FIRST_LEG=7 sanity floor and warning-on-mismatch override, last-5-races heuristic. get_pick5_legs never raises and always returns 5 ints. 21 new tests in tests/test_pick5.py covering all tiers, error paths, and invariants. Full suite 84/84 passing.