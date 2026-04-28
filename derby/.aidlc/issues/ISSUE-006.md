# ISSUE-006: Normalization layer — odds-to-probability, source merging, sequenceRole assignment

**Priority**: high
**Labels**: normalization, phase-1
**Dependencies**: ISSUE-003, ISSUE-004, ISSUE-005
**Status**: implemented

## Description

Implement `api/normalize.py`. (1) Odds-to-probability: parse fractional ('5/2'), integer-to-1 ('4-1'), and decimal odds strings → `prob = 1 / (decimal_equivalent + 1)`. Fractional '5/2' → 2.5 decimal → 0.2857. Handle '1/2' (odds-on), 'EVS', and missing/null odds gracefully. (2) Per-race normalization: divide each implied prob by the sum across all non-scratched horses to normalize to exactly 1.0 (pari-mutuel overround removal). (3) Source merging: given Equibase `Horse` list and TwinSpires odds list for the same race, match horses by programNumber where possible; fall back to name normalization (strip punctuation/country suffixes, lowercase, compare) then `difflib.get_close_matches(cutoff=0.85)` per alternative-data-sources.md. Populate `morningLineProbability` from Equibase ML odds; `marketProbability` from TwinSpires live odds. (4) Set `sequenceRole` on each Race in the Pick 5 sequence: 'pick5-leg-1' through 'pick5-leg-5' based on get_pick5_legs output.

## Acceptance Criteria

- [ ] '5/2' parses to 0.2857 (±0.0001); '3-1' to 0.25; '10/1' to 0.0909; 'EVS' to 0.5
- [ ] After per-race normalization, sum of all non-scratched horse probabilities equals 1.0 (±0.001)
- [ ] Horse with Equibase name 'HORSE NAME (IRE)' correctly merges with TwinSpires name 'HORSE NAME'
- [ ] sequenceRole set to 'pick5-leg-1' through 'pick5-leg-5' on correct Race objects
- [ ] Scratched horses excluded from probability normalization denominator
- [ ] Missing live odds handled: horse keeps morningLineProbability with missing odds flag

## Implementation Notes


Attempt 1: Added api/normalize.py with odds_to_probability (fractional/integer-to-1/decimal/EVS), normalize_probabilities (overround removal, scratched-aware), merge_horses (Equibase+TwinSpires by post then normalized-name with difflib cutoff 0.85), and assign_pick5_sequence_roles. 32 tests added in api/tests/test_normalize.py; full suite (116) green.