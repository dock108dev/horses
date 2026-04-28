# SSOT enforcement pass — derby Pick 5 backend

**Date:** 2026-04-28
**Scope:** `api/` (Python FastAPI backend + tests). `web/` was inspected; no
SSOT violations found there (TypeScript types in `web/lib/types.ts` are an
intentional client-side mirror of `api/model.py` for Next.js type safety).
**Test command:** `pytest api/tests` — 274 passed before and after.
**Lint:** `ruff check api/ --select=F` — clean.

---

## Diff context

The repo is not a git repository, so there is no `main...HEAD` diff. The
authoritative intent source is `BRAINDUMP.md` (referenced as the "Intent
Source" in `.aidlc/planning_index.md`). This pass treats `BRAINDUMP.md` and
the prior audits (`docs/audits/cleanup-report.md`,
`docs/audits/error-handling-report.md`) as the SSOT for what the codebase
is becoming, and deletes anything that duplicates or contradicts those.

---

## Final SSOT modules per domain

| Domain | SSOT module | Notes |
| --- | --- | --- |
| Data model + Pick 5 shape + flag/tag string constants | `api/model.py` | Pydantic `Horse`/`Race`/`OddsSnapshot`, `SequenceRole`, `PICK5_LEG_ROLES`, `PICK5_LEG_COUNT`, all `FLAG_*` constants, `select_pick5_legs`, the probability layer (priors, blend, flags). |
| Odds parsing + per-race probability normalization + source merge + sequenceRole assignment | `api/normalize.py` | `odds_to_probability`, `normalize_probabilities`, `merge_horses`, `assign_pick5_sequence_roles`. |
| SQLite cache (per-day DB, WAL) | `api/cache.py` | `OddsCache`, `OddsSnapshotRecord`, `CachedCard`. |
| Post-refresh validation | `api/validate.py` | `validate_card`, `ValidationResult`, `PROBABILITY_TOLERANCE`. |
| Refresh orchestration (build card + poll odds) | `api/refresh.py` | `build_card`, `poll_pick5_odds`, `races_with_latest_odds`. |
| Source adapters | `api/sources/{equibase,twinspires,kentuckyderby,pick5}.py` | One adapter per provider; Pick 5 leg-sequence resolution lives in `pick5.py`. |
| Monte Carlo | `api/sim.py` | `simulate`, `Ticket`, `SimulationResult`, `default_tickets_from_tags`. |
| Ticket builder | `api/tickets.py` | `build_tickets`, `build_tickets_for_budgets`, `BudgetVariant`. |
| HTTP layer | `api/main.py` | FastAPI app, `Envelope`, dependency factories. |

---

## Diff-prioritized deletions (SSOT enforcement)

### 1. Pick 5 shape constants — three copies → one home in `api/model.py`

| Removed | Reason | SSOT replacement |
| --- | --- | --- |
| `api/normalize.py:30` `PICK5_LEG_COUNT = 5` | Local copy of a domain-level constant. | `api/model.PICK5_LEG_COUNT` |
| `api/sim.py:35` `PICK5_LEG_COUNT = 5` | Same. | `api/model.PICK5_LEG_COUNT` |
| `api/sources/pick5.py:58` `PICK5_LEG_COUNT = 5` | Same. | `api/model.PICK5_LEG_COUNT` |
| `api/sim.py:36-42` hardcoded `PICK5_LEG_ROLES` 5-tuple | Re-declared what `SequenceRole` already enumerates. | `api/model.PICK5_LEG_ROLES` (derived from `get_args(SequenceRole)`) |
| `api/validate.py:37` `PICK5_LEG_ROLES = get_args(SequenceRole)` | Same derivation done twice. | `api/model.PICK5_LEG_ROLES` |

`PICK5_LEG_COUNT` is now defined once as `len(PICK5_LEG_ROLES)`, so
adding/removing a leg in `SequenceRole` would automatically propagate
without a constant-update step. All consumers updated:

- `api/normalize.py`, `api/sources/pick5.py`, `api/sim.py`,
  `api/tickets.py`, `api/validate.py`, `api/main.py`, `api/refresh.py`
  now import from `api.model`.
- Tests `test_normalize.py`, `test_sim.py`, `test_tickets.py`,
  `test_validate.py`, `test_main.py` updated to the model import path.

`PICK5_LEG_COUNT` / `PICK5_LEG_ROLES` removed from `__all__` exports of
`api/normalize.py`, `api/sim.py`, `api/sources/pick5.py`, `api/validate.py`.

### 2. `_select_pick5_legs` — duplicate function → single public helper

Removed `api/tickets.py:157-163` which was a byte-for-byte copy of
`api/sim.py:244-250`. Both selected the five Pick 5 races by
`sequenceRole`, in role order. Promoted to public
`api/model.select_pick5_legs(races)` (with a docstring covering the missing-leg
and duplicate-role behaviors). `sim.py` and `tickets.py` both import the
single canonical implementation; `sim.py` no longer carries its own
private copy either.

### 3. Flag string constants — two copies → one home in `api/model.py`

| Removed | Reason | SSOT replacement |
| --- | --- | --- |
| `api/tickets.py:45` `USEFUL_VALUE_FLAG = "useful_value"` | String literal duplicated; producer (`compute_horse_flags`) emits it via `FLAG_USEFUL_VALUE`. | `api/model.FLAG_USEFUL_VALUE` |
| `api/tickets.py:46` `CHAOS_RACE_FLAG = "chaos_race"` | Same. | `api/model.FLAG_CHAOS_RACE` |
| `api/sim.py:45` `LIKELY_SEPARATOR_FLAG = "likely_separator"` | Spec-mandated flag (BRAINDUMP "Flags": "Likely separator") that was previously consumed in sim.py but had no canonical producer location. Moved to `api/model.py` next to the other `FLAG_*` constants so a future producer (ISSUE-010, flags computation) and the existing consumer (sim.py separator-coverage metric) share one symbol. | `api/model.FLAG_LIKELY_SEPARATOR` |

Removed from `__all__`: `USEFUL_VALUE_FLAG`, `CHAOS_RACE_FLAG` in
`api/tickets.py`; `LIKELY_SEPARATOR_FLAG` in `api/sim.py`. Added
`FLAG_LIKELY_SEPARATOR` to `api/model.__all__`.

Tests `test_tickets.py` and `test_sim.py` updated to import the canonical
flag names.

### 4. Stray local cache artifact

Removed `api/data/odds_2026-05-02.db` (and the empty `api/data/`
directory). The canonical data directory per `api/main._data_dir()` and
`OddsCache(... data_dir=DEFAULT_DATA_DIR)` is the repo-root `data/` (which
is `.gitignore`d for `*.db`). The stray file was a leftover from running
something with the working directory at `api/`. The repo-root `data/`
directory still holds the SSOT `priors.json` plus its `.gitkeep`.

### 5. `__all__` cleanup

Trimmed each module's `__all__` to the symbols it actually owns:

- `api/normalize.py.__all__` lost `PICK5_LEG_COUNT`.
- `api/sim.py.__all__` lost `PICK5_LEG_COUNT`, `PICK5_LEG_ROLES`,
  `LIKELY_SEPARATOR_FLAG`.
- `api/validate.py.__all__` lost `PICK5_LEG_ROLES`.
- `api/sources/pick5.py.__all__` lost `PICK5_LEG_COUNT`.
- `api/tickets.py.__all__` lost `USEFUL_VALUE_FLAG`, `CHAOS_RACE_FLAG`.
- `api/model.py.__all__` gained `PICK5_LEG_ROLES`, `PICK5_LEG_COUNT`,
  `select_pick5_legs`, `FLAG_LIKELY_SEPARATOR`.

### 6. Stale `cast` import

`api/sim.py` no longer uses `typing.cast` (the only call site moved out
with `_select_pick5_legs`). `api/tickets.py` likewise — the `cast` import
went with the deleted helper. Both `from typing import cast` lines were
removed; ruff F401 confirms.

---

## Risk log: justified retentions

### `_renormalize` in `api/model.py:476` vs. `normalize_probabilities` in `api/normalize.py:97`

**Diff-cited rationale.** Previously surveyed and justified by the
cleanup-report under "Patterns surveyed but kept as deliberate
non-duplicates." Confirmed during this pass:

- `api/normalize.py` imports `Horse`, `Race`, `SequenceRole`,
  `PICK5_LEG_COUNT` from `api/model.py` (line 27 after this pass).
- A reverse import (`api/model.py` → `api/normalize.py`) would create a
  cycle.
- `_renormalize` is private (leading underscore) and does *not* leak
  across module boundaries; the public normalize-by-field is
  `normalize_probabilities`.

The duplication is the smaller cost than restructuring the import graph
(e.g., extracting normalization primitives into a third module). No
behavioral drift between the two implementations was observed; a future
pass can collapse them by renaming `api/model.py`'s probability section
into `api/probability.py` (already documented in `cleanup-report.md`'s
extraction plan).

### `FLAG_LIKELY_SEPARATOR` consumed in `api/sim.py` but not yet produced

`sim.py:_prepare_leg` reads `FLAG_LIKELY_SEPARATOR in h.flags` to
populate the `separator_coverage_pct` metric. No code currently *sets*
this flag on a horse, so `separator_coverage_pct` is 0.0 today. Per
BRAINDUMP "Flags" the flag is spec-mandated, and ISSUE-010 (flags
computation, phase-3) is the issue that will produce it. The flag
constant is centralized in `api/model.py` so producer + consumer share
one symbol; deleting it would silently drop a spec requirement without
moving the gap into a documented place. Acted on (consolidated); not
removed.

### Per-adapter `SOURCE_NAME` / `DEFAULT_USER_AGENT` / `_COUNTRY_SUFFIX_RE` duplications

Surveyed in the prior cleanup-report and explicitly justified there
("Patterns surveyed but kept as deliberate non-duplicates"). No new
information in this pass changes those judgments; not re-litigated here.

### Web/TS-side type mirroring (`web/lib/types.ts`)

`SequenceRole`, `Horse`, `Race`, etc. are restated in TypeScript as a
client-side mirror. This is the intended cross-language SSOT pattern for
a FastAPI ↔ Next.js boundary — Pydantic produces the JSON contract,
TypeScript redeclares the shape for type safety. Not a violation.

---

## Sanity check: dangling references

Searched for every deleted symbol and import path after the edits:

```text
grep -rn '_select_pick5_legs\|LIKELY_SEPARATOR_FLAG\b\|USEFUL_VALUE_FLAG\b\|CHAOS_RACE_FLAG\b' .
→ No matches found.
```

Imports of removed names from previous homes (e.g., `from api.sim import
PICK5_LEG_COUNT`, `from api.validate import PICK5_LEG_ROLES`) all
re-pointed to `api.model`. Verified via:

```text
ruff check api/ --select=F   →  All checks passed
pytest api/tests -q          →  274 passed in 2.27s
```

No tests deleted (none tested *removed* behavior); five tests had import
paths updated only.

---

## Escalations

None. Every finding was acted on (consolidation in-place) or justified
(`_renormalize` duplication, `FLAG_LIKELY_SEPARATOR` forward-reference,
SOURCE_NAME/UA per-adapter, web/TS mirror).
