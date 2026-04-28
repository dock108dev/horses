# Code-quality cleanup pass — derby Pick 5

**Date:** 2026-04-28 (second pass)
**Scope:** `api/` (Python FastAPI backend + tests). `web/` reviewed; nothing to act on.
**Test command:** `pytest api/tests` — **274 passed** before and after.
**Lint command:** `ruff check .` — clean before and after.

---

## Executive summary

Second cleanup pass after the sim/tickets endpoints landed (Phases 3/4 of
the BRAINDUMP). The codebase remains tight: zero `TODO`/`FIXME`/`XXX`/
`HACK` markers, no commented-out code, every broad `except` carries a
finding-ID pointer, every module has a header docstring.

This pass:

1. **Dead code:** removed an unused loop variable in `validate.py`, lifted
   one inline import to module-level in `test_main.py`.
2. **Consistency:** migrated the seven `from typing import Iterable/
   Iterator/AsyncIterator` to `collections.abc` (project requires 3.11+).
3. **Comments / style:** collapsed a 4-line `for…return True` into a one-
   line `any(...)` in `equibase.py:_detect_scratched`.
4. **Stale docstrings:** the four "LOC note" paragraphs added by the
   prior pass cited stale line counts (e.g. `main.py` said `~511 LOC`
   while the file is now 606). Refreshed each note with the current LOC
   and the extraction trigger inherited from the prior pass.
5. **>500 LOC files:** four files still over (606/559/520/577). All four
   remain *under* their per-file extraction triggers (700/400/700/800)
   from the prior pass. Justified in place; no splits this round.

No behavioral changes. Public API of the FastAPI app unchanged.

---

## Dead code removed

| Location | Removed | Why it was dead |
| --- | --- | --- |
| `api/validate.py:75` | unused enumeration counter `i` in second `for i, role in enumerate(PICK5_LEG_ROLES, start=1)` loop | Only the *first* loop on line 71 uses `i` (for the human-readable error message). The second loop just iterates the legs to validate them — `i` was never referenced in the body. Replaced with a plain `for role in PICK5_LEG_ROLES`. |
| `api/tests/test_main.py:75` | inline `from api.model import PICK5_LEG_ROLES` inside `_make_race` | Already imported at module top after this pass; the function-local import was a pre-pass artifact that no longer earned its keep. Lifted to the top-level import block alongside `Horse, Race`. |

No other dead code found. Re-searched for `TODO`/`FIXME`/`XXX`/`HACK`
(none), commented-out functions/classes/control flow (none), removed-
feature remnants (none).

---

## Files refactored / split

None. See "Files still >500 LOC" below — each file is under its
extraction trigger.

---

## Duplicates consolidated

None this pass. The duplicate inventory from the prior pass remains
accurate:

- `post_from_program_number` was already consolidated into
  `api/sources/twinspires.py` last pass.
- `_renormalize` (in `api/model.py`) vs. `normalize_probabilities` (in
  `api/normalize.py`) is still a deliberate non-duplicate — it breaks
  the circular import between the two modules. Confirmed still
  load-bearing (verified by attempting the import the other way:
  `api.normalize` continues to import from `api.model`).
- The `SOURCE_NAME` constants, `DEFAULT_USER_AGENT` strings, and
  `_HttpClient`/`_Response` Protocols are still independent per adapter;
  no new duplication introduced by the new modules (`api/sim.py`,
  `api/tickets.py`, `api/sources/pick5.py`).

The two new modules (`sim.py`, `tickets.py`) properly share types and
constants via `api.model` and `api.sim`, with no copy-paste.

---

## Files still >500 LOC

| File | LOC (now) | LOC (prior pass) | Trigger | Disposition |
| --- | --- | --- | --- | --- |
| `api/main.py` | 606 | 516 | 700 | **Justify** |
| `api/model.py` | 559 | 530 | 400 (probability layer) | **Justify** |
| `api/sources/twinspires.py` | 520 | 519 | 700 | **Justify** |
| `api/tests/test_main.py` | 577 | 578 | 800 | **Justify** |

Each file's LOC-rationale paragraph in its module docstring was refreshed
this pass to cite the current line count and the extraction trigger
(per the actionability contract: in-code reference → this section).

### `api/main.py` — 606 LOC (was 516)

**Growth source.** The +90 LOC from the prior pass landed when the
`POST /api/simulate/{day}` and `POST /api/tickets/{day}/build` endpoints
graduated from stubs to real wiring (lazy imports of `api.sim` /
`api.tickets`, blend-on-demand for un-blended cards, two `Envelope`
return paths each, request-body Pydantic models with `extra="forbid"`).

**Justification.** The growth is genuine route wiring on the same
single FastAPI `app` instance. The prior pass set the extraction trigger
at ~700 LOC; we are at 606. Splitting now (introducing a `routers/`
package with one `APIRouter` per endpoint group) would force the four
stub `Depends(...)` factories — `get_cache`, `get_equibase_adapter`,
`get_twinspires_adapter`, plus the per-test `dependency_overrides` flow
— to either duplicate across routers or move to a shared
`api/dependencies.py`, which is exactly the premature-router-refactor
the prior pass deferred.

**Extraction plan (next pass, when main.py grows past ~700 LOC):**
unchanged from the prior pass — move each endpoint group to
`api/routers/{cards,odds,simulate,tickets}.py` with `APIRouter`
instances. Keep `Envelope` + `day_to_iso_date` + the dependency
factories in `main.py`.

### `api/model.py` — 559 LOC (was 530)

**Growth source.** +29 LOC from the SSOT pass adding `select_pick5_legs`,
`PICK5_LEG_COUNT`, and `FLAG_LIKELY_SEPARATOR` so producers and consumers
share a single home (per the SSOT report).

**Justification.** Probability layer is roughly model.py:122-470 ≈ 348
LOC, still under the 400-LOC extraction trigger. Split would force every
probability import in the codebase + tests to change with no behavioral
win.

**Extraction plan (next pass, when probability layer grows past ~400
LOC):** unchanged — move from line 122 (`# Probability layer`) onward
to a new `api/probability.py`. The `_renormalize` circular-import note
moves with it, and the cycle goes away once it's no longer a sibling
of `api.model`.

### `api/sources/twinspires.py` — 520 LOC (was 519)

**Justification.** Effectively unchanged from the prior pass (+1 LOC
from the typing→collections.abc import re-flow). All internal helpers
still reach into private state on `TwinSpiresAdapter` (`_last_runners`,
`_session_seeded`, `_owns_*_client`); exporting them would force those
to become public.

**Extraction plan (next pass, only if the file grows past ~700 LOC):**
unchanged — extract `_CurlCffiClient` + `_build_curl_cffi_client` to
`api/sources/_http_compat.py` (~25 LOC of curl_cffi shim).

### `api/tests/test_main.py` — 577 LOC (was 578)

**Justification.** Effectively unchanged. Setup helpers (`_make_horses`,
`_make_race`, `_full_card`, `FakeEquibase`, `FakeTwinSpires`,
`_client_with_overrides`, `_seed_cache`) are shared by every endpoint
test in the file. Splitting at this size would either duplicate ~140
LOC of helpers or move them to a `conftest.py` that obscures setup.

**Extraction plan (next pass, when the file grows past ~800 LOC):**
unchanged — lift fakes + `_make_*` builders into
`api/tests/_fixtures.py` as a plain import (not `conftest.py`), then
split tests by endpoint family.

---

## Consistency changes made

| File | Change |
| --- | --- |
| `api/cache.py` | `from typing import Iterable` → `from collections.abc import Iterable` |
| `api/main.py` | `from typing import …, AsyncIterator, …` → `from collections.abc import AsyncIterator`; refreshed LOC note (~511 → ~606) and pointed at 700-LOC trigger |
| `api/model.py` | refreshed LOC note (~556 → ~559) and pointed at 400-LOC probability-layer trigger |
| `api/refresh.py` | `from typing import Iterable` → `from collections.abc import Iterable` |
| `api/tickets.py` | `from typing import Iterable` → `from collections.abc import Iterable` |
| `api/validate.py` | dropped unused enumerator on second loop (`for i, role …` → `for role …`) |
| `api/sources/equibase.py` | `from typing import …, Iterable, …` → `from collections.abc import Iterable`; collapsed `_detect_scratched` cell-text loop into `any(...)` |
| `api/sources/kentuckyderby.py` | `from typing import …, Iterable, …` → `from collections.abc import Iterable` |
| `api/sources/twinspires.py` | `from typing import Any, Iterable` → `from collections.abc import Iterable` + `from typing import Any`; refreshed LOC note (~513 → ~520) |
| `api/tests/test_main.py` | `from typing import Any, Iterator` → `from collections.abc import Iterator` + `from typing import Any`; lifted `PICK5_LEG_ROLES` to top-level import; refreshed LOC note (~571 → ~577) |

The typing→collections.abc migration is real consistency work: the
project requires Python 3.11, and `collections.abc` has been the
canonical home for `Iterable`/`Iterator`/`AsyncIterator` since 3.9.
The previous pass missed this because `ruff check . --select=F` (the
pyflakes family) doesn't surface `UP035`. Verified the broader rule
families (`UP`, `SIM`, `B`, `RUF`) post-edit; remaining hits are all
either (a) intentional Unicode (`×` / `–` in math comments), (b) the
standard FastAPI `Depends(...)` default-argument idiom (B008 — *not*
a bug, FastAPI documents this pattern), or (c) E501 line-too-long
(not enforced by the project's ruff config).

---

## Findings deliberately *not* acted on (justifications)

Per the actionability contract: where the right call is "leave as is,"
the justification lives both here and at the code site or in the
file's docstring.

### B008 `Depends(...)` in argument defaults — `api/main.py` (8 sites)

**Action:** none.
**Why:** This is the **documented FastAPI dependency-injection idiom**.
Moving `Depends(...)` calls into function bodies (or to module-level
singletons) defeats FastAPI's parameter introspection — it relies on
the default-value position to detect dependencies vs. body parameters
vs. query strings. Replacing the idiom with a workaround would require
either `Annotated[OddsCache, Depends(get_cache)]` everywhere (verbose
and identical at runtime) or a custom resolver (a real refactor).
Ruff's B008 is a generic Python rule; FastAPI is the exception.
**Code-site comment:** not added — the idiom is universal across
FastAPI codebases; an explanatory comment at every call site would be
noise. The justification lives here only.

### RUF002/RUF003 ambiguous Unicode (`×`, `–`) — `api/cache.py`,
`api/tests/test_sim.py`, `api/tests/test_tickets.py`,
`api/tests/test_probability_model.py`

**Action:** none.
**Why:** Every hit is in a docstring or comment using `×` for
multiplication (`~50× speedup`, `1×1×1×1×1 = $0.50 ticket`) or `–` for
ranges (`6–7 horses`). Replacing with ASCII `x` / `-` makes math
comments harder to read for the same prose. Ruff flags these because
homoglyph confusion is theoretically possible in identifiers; in
documentation prose the readability win clearly outweighs the
theoretical risk.

### E501 line-too-long (~12 hits)

**Action:** none.
**Why:** The project's `ruff` config (defaults — there is no
`ruff.toml`/`[tool.ruff]`) does not enforce `E501`. Wrapping all 12
sites would touch ~12 files for the only payoff of conforming to a
line-length budget the project hasn't opted into. If the project later
adopts `line-length = 88` enforcement, those wraps can land in a
single mechanical sweep at that point.

### RUF005 `[*list(STANDARD_BUDGETS), 60.0]` — `api/tests/test_tickets.py:300`

**Action:** none.
**Why:** Cosmetic. `list(...) + [60.0]` is one explicit step (concat),
the unpack-and-rebuild form is one implicit step (splat). Either is
fine; the existing code is already obvious in context.

### RUF022 `__all__` not sorted — `api/model.py`, `api/sim.py`,
`api/tickets.py`

**Action:** none.
**Why:** Each `__all__` is grouped *semantically* (types first,
constants next, functions last) — that is more readable than
alphabetical. The project's ruff config does not enforce RUF022.

### `_renormalize` in `api/model.py` vs. `normalize_probabilities` in `api/normalize.py`

**Action:** none.
**Why:** Same as the prior pass. Confirmed `api.normalize` still
imports from `api.model` (`PICK5_LEG_COUNT`, `Horse`, `Race`,
`SequenceRole`), so consolidating `_renormalize` into `normalize.py`
would re-introduce the cycle. The in-code comment on `_renormalize`
(model.py:478-480) already documents this.

### Three identical `DEFAULT_USER_AGENT` constants across source adapters

**Action:** none.
**Why:** Same as the prior pass. Each adapter has independent reasons
to upgrade or vary the UA (curl_cffi `impersonate=` is paired with
TwinSpires' UA only). The 4-line literal repetition is cheaper than
inverting the dependency graph for cross-adapter sharing.

---

## Verification

- `pytest api/tests` — **274 passed**, 0 failed (vs. 274 baseline; the
  +47 over the prior pass's 227 are new sim/tickets/pick5 tests added
  with their respective modules).
- `ruff check .` — clean (no findings under the project's default rule
  set).
- `ruff check . --select=F` (pyflakes family — unused imports/names/
  dead code) — clean.
- `ruff check . --select=UP035` (typing → collections.abc imports) —
  clean after this pass (was 7 hits).
- `__all__` lists hand-audited against actual exports for every file
  edited.

---

## Escalations

None. Every finding in this pass was either acted on (dead code,
consistency, stale docstrings) or justified above with a concrete
reason. No bare TODOs left in code; no "out of scope" deferrals; no
"recommend the team consider X."
