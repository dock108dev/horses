# ISSUE-008: Scraper validation layer (`api/validate.py`) — post-refresh checks and stale fallback

**Priority**: high
**Labels**: validation, phase-1
**Dependencies**: ISSUE-006, ISSUE-007
**Status**: implemented

## Description

Implement `api/validate.py` with `validate_card(races: list[Race], day: str) -> ValidationResult`. After each refresh cycle, check: (1) all 5 Pick 5 legs present by sequenceRole; (2) every horse in every Pick 5 leg has non-empty name and post > 0; (3) at least one odds value (ML or current) parsed per horse; (4) no duplicate horses by (raceId, post) pair; (5) scratched horses are flagged not silently removed; (6) per-race probabilities sum to 1.0 ±0.01 for non-scratched horses. Return `ValidationResult(valid: bool, errors: list[str])` with human-readable error strings like 'Race 9 missing odds for 2 horses' and 'Pick 5 leg 3 (Race 11) not found in card'. API callers (ISSUE-009) must use this: on valid=False, fall back to `get_last_good_card` from cache and return it with `stale=True` plus the error list in the response. This satisfies the BRAINDUMP requirement: 'If validation fails, use cached snapshot or retry.'

## Acceptance Criteria

- [ ] Returns valid=True for a complete 5-leg card where all horses have post, name, and at least one odds value
- [ ] Returns valid=False with error 'Race N missing odds for X horses' when horses lack odds
- [ ] Returns valid=False with error 'Pick 5 leg N not found' when fewer than 5 legs present
- [ ] Returns valid=False when duplicate (raceId, post) entries detected
- [ ] Returns valid=False when any Pick 5 race has non-scratched horse probability sum outside [0.99, 1.01]
- [ ] Validation errors array is non-empty whenever valid=False

## Implementation Notes


Attempt 1: Added api/validate.py with ValidationResult dataclass and validate_card(races, day) covering all 6 BRAINDUMP checks: 5 Pick 5 legs by sequenceRole, non-empty names, parseable odds (or probability) for non-scratched horses, no duplicate (raceId, post), scratched-horse exclusion, and per-race probability sum within 1.0 ± 0.01 for both marketProbability and morningLineProbability. 20 tests added in api/tests/test_validate.py.