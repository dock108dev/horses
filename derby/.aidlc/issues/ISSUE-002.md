# ISSUE-002: Shared data models — Pydantic (Python) and TypeScript types

**Priority**: high
**Labels**: models, phase-1
**Dependencies**: ISSUE-001
**Status**: implemented

## Description

Implement the canonical data models specified in BRAINDUMP. Python side (`api/model.py`): Pydantic v2 models for `Race`, `Horse`, `OddsSnapshot`. TypeScript side (`web/lib/types.ts`): matching interfaces exported for frontend use. All field names must match BRAINDUMP exactly: `Race` fields include `id`, `day`, `track`, `raceNumber`, `postTime`, `name`, `surface`, `distance`, `sequenceRole` (enum pick5-leg-1..5), `horses[]`. `Horse` fields include `id`, `raceId`, `post`, `name`, `jockey`, `trainer`, `morningLineOdds`, `currentOdds`, `scratched`, `source`, `marketProbability`, `morningLineProbability`, `modelProbability`, `finalProbability`, `userTag` (enum single/A/B/C/toss/chaos/boost/fade), `flags[]`. `OddsSnapshot`: `timestamp`, `day`, `raceNumber`, `horseId`, `odds`, `impliedProbability`, `source`.

## Acceptance Criteria

- [ ] Python `Race` and `Horse` Pydantic models include all BRAINDUMP-specified fields with correct types
- [ ] Python `OddsSnapshot` model includes all 7 BRAINDUMP fields
- [ ] TypeScript `Race`, `Horse`, `OddsSnapshot` interfaces export correctly with no TS errors
- [ ] `UserTag` and `SequenceRole` TypeScript union types defined
- [ ] Python models round-trip to/from JSON without data loss

## Implementation Notes


Attempt 1: Added canonical data models: api/model.py (Pydantic v2 Race, Horse, OddsSnapshot + Day/Track/SequenceRole/UserTag literal types with probability range checks and extra='forbid'), matching web/lib/types.ts interfaces and union aliases, and api/tests/test_model.py covering JSON round-trip and validation rejection cases. All 9 pytest tests pass; tsc --noEmit clean.