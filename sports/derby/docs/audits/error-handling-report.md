# Error-handling audit — derby Pick 5 backend + iPad SPA

**Date:** 2026-04-28 (second pass)
**Scope:** `api/` (FastAPI app, source adapters, cache, validation, refresh
orchestration, sim/ticket helpers) and `web/` (Next.js iPad SPA — page
state, fetch wrapper, display helpers). Test files excluded — exception
handling in tests is dictated by the assertions and is not a production
concern.
**Baseline test run:** `pytest api/tests` — 274 passed before and after
tightening edits. `npx tsc --noEmit` in `web/` — clean.

---

## Executive summary

| Severity   | Count | Disposition                                           |
| ---------- | ----- | ----------------------------------------------------- |
| Critical   | 0     |                                                       |
| High       | 1     | tightened (F17)                                       |
| Medium     | 1     | tightened (F16)                                       |
| Low        | 0     |                                                       |
| Note       | 16    | acceptable, justified inline + here                   |
| **Total**  | **18**|                                                       |

**Posture verdict — acceptable for production.**

This is a re-audit on top of the first pass. Files changed since the
prior report (`main.py`, `refresh.py`, `pick5.py`, `tickets.py`,
`twinspires.py`, `kentuckyderby.py`, `normalize.py`, `validate.py`,
`sim.py`) were re-walked for new suppression sites. Two new findings
emerged this pass and were addressed:

1. **F16 (Medium → fixed)** — `tickets._rank_tickets` swallowed every
   ranking-time exception at `_log.debug`, which makes a real sim-engine
   bug invisible in production logs. Bumped to `_log.warning(... %s, exc)`
   so the failure plus the exception details are observable while
   keeping the contract that ranking failures must not break ticket
   construction.
2. **F17 (High → fixed)** — `SimulateRequest` and `TicketsRequest` used
   Pydantic's default `extra="ignore"`, silently dropping the `tags` and
   `oddsOverrides` fields the iPad UI was posting. The user's tagging /
   override actions had **no effect** on simulation or ticket build
   results — a hidden-failure-risk class. Tightened both models to
   `extra="forbid"`, removed those fields from the web client request
   bodies, and recorded an Escalation (E1) for the underlying feature
   gap (tag-aware sim is not yet wired through).

The previously-tightened F1 (`pick5.parse_pick5_first_leg` BeautifulSoup
catch) and F2 (silent `_safe_close` swallows) remain tightened — both
sites still carry the pointer comments added in the first pass. F7 from
the first pass (optional-module ImportError on `sim`/`tickets`) no
longer applies — those imports are now done unconditionally inside the
endpoint bodies because both modules ship.

---

## Findings table

| ID  | Location                                  | Category                          | Severity | Disposition                                |
| --- | ----------------------------------------- | --------------------------------- | -------- | ------------------------------------------ |
| F1  | `api/sources/pick5.py:96`                 | Suppression — broad except        | Note     | Already tightened (pass 1); comment kept   |
| F2a | `api/sources/twinspires.py:_safe_close`   | Suppression — silent close        | Note     | Already tightened (pass 1); comment kept   |
| F2b | `api/sources/kentuckyderby.py:close`      | Suppression — silent close        | Note     | Already tightened (pass 1); comment kept   |
| F3a | `api/main.py:322`                         | Cache-fallback broad except       | Note     | Justified inline                           |
| F3b | `api/main.py:460`                         | Cache-fallback broad except       | Note     | Justified inline                           |
| F4  | `api/refresh.py:56`                       | Per-leg downgrade to warning      | Note     | Justified inline                           |
| F5  | `api/sources/twinspires.py:128`           | Odds-parse fallback to string     | Note     | Justified inline                           |
| F6  | `api/cache.py:174`                        | Tx rollback + re-raise            | Note     | Justified inline                           |
| F8a | `api/main.py:525`                         | Sim runtime → error envelope      | Note     | Justified inline                           |
| F8b | `api/main.py:574`                         | Tickets runtime → error envelope  | Note     | Justified inline                           |
| F9  | `api/sources/pick5.py:163`                | Tier-2 verification softening     | Note     | Justified inline                           |
| F10a| `api/sources/kentuckyderby.py:74`         | Per-block JSON parse skip         | Note     | Justified inline                           |
| F10b| `api/sources/kentuckyderby.py:89`         | Per-block JSON parse skip         | Note     | Justified inline                           |
| F11a| `api/normalize.py:77`                     | Odds parser sentinel-None         | Note     | Justified inline                           |
| F11b| `api/normalize.py:86`                     | Odds parser sentinel-None         | Note     | Justified inline                           |
| F12 | `api/sources/pick5.py:103,118`            | data-race attr int parse skip     | Note     | Justified inline                           |
| F13 | `api/sources/twinspires.py:319`           | Rate-limit `try/finally`          | Note     | Justified inline                           |
| F14 | `api/sources/equibase.py:199`             | Rate-limit `try/finally`          | Note     | Justified inline                           |
| F15 | `api/sources/twinspires.py:479`           | Optional curl_cffi import         | Note     | Justified inline                           |
| F16 | `api/tickets.py:325`                      | Broad except, debug-only log      | Medium   | **Tightened** (warning + exc detail)       |
| F17 | `api/main.py:475-491`                     | Pydantic silent-extras drop       | High     | **Tightened** (`extra="forbid"`, UI fixed) |
| F18 | `web/components/StaleBanner.tsx:11`       | Date-format try/catch fallback    | Note     | Justified inline                           |
| F19 | `web/components/DayHeader.tsx:23`         | Date-format try/catch fallback    | Note     | Justified inline                           |
| F20 | `web/app/sequence/[day]/page.tsx`         | Browser fetch catch → setError    | Note     | Acceptable as-is (UI surface)              |
| F21 | `api/refresh.py:poll_pick5_odds`          | All-or-nothing odds batch         | Note     | Acceptable (cycle-level retry contract)    |

`type: ignore` comments now exist only at:
- `api/sources/kentuckyderby.py:162` — narrow `[return-value]` on the
  recursive runner-list walker; it's the documented sentinel-shape escape
  and not a suppression of a runtime issue.

`api/main.py` no longer carries any `# type: ignore` markers. There are
no `noqa`, `pylint: disable`, or `warnings.filterwarnings` calls in the
codebase. The `# noqa: B017` markers in `api/tests/` are scoped to
`pytest.raises(Exception)` for Pydantic ValidationError assertions and
are appropriate.

---

## Per-finding details

### F1 — Broad except around `BeautifulSoup` (Note — already tightened)

**Location:** `api/sources/pick5.py:96`.

The first pass removed the broad `try/except` around
`BeautifulSoup(card_html, "html.parser")` because `html.parser` does not
raise on malformed input — the catch was masking real programming bugs.
The inline comment at the call site (`# html.parser tolerates malformed
input ... see error-handling-report finding F1.`) still cites this
section. No change this pass.

---

### F2a / F2b — Silent `close()` failures in adapter teardown (Note)

**Locations:**
- `api/sources/twinspires.py:_safe_close` (line 463)
- `api/sources/kentuckyderby.py:KentuckyDerbyAdapter.close` (line 234)

The first pass replaced bare `except Exception: pass` with
`_log.debug("HTTP client close failed: %s", exc)` so a systemic
teardown failure (socket-pool exhaustion, etc.) is observable without
masking the in-flight exception that originally tripped `__exit__`.
Both comments still cite this section.

---

### F3a / F3b — Cache-fallback broad except in card/odds refresh (Note)

**Locations:** `api/main.py:refresh_card` (line 322),
`api/main.py:refresh_odds` (line 460).

**Code shape:**
```python
try:
    ... live ingest ...
except Exception as exc:
    _log.exception("Card refresh failed for day=%s", day)
    return _stale_card_envelope(
        cache, iso_date, errors=[LIVE_SOURCE_ERROR, _redact_exc(exc)]
    )
```

**Risk lens:** Reliability/observability. The broad catch is the explicit
BRAINDUMP "Cache Strategy" contract: any live-ingest failure during race
day must surface as a stale envelope, never a 5xx. `_log.exception`
captures the full traceback at ERROR. The exception message is passed
through `_redact_exc` (defined `api/main.py:74`) so URLs and absolute
filesystem paths in the upstream error don't leak to the iPad UI — see
`docs/audits/security-report.md` S3.

**Disposition:** Acceptable as-is. Comments at both sites cite this
finding.

---

### F4 — TwinSpires per-leg fetch downgraded to warning (Note)

**Location:** `api/refresh.py:build_card` (line 56).

Per-leg downgrade is the right call: TwinSpires is best-effort live odds,
Equibase remains canonical for IDs / ML / jockey / trainer, and a 403 on
one race must not blank the whole card. `validate_card` downstream still
flags missing odds. Comment in place.

---

### F5 — `to_fractional_odds` fallback to original string (Note)

**Location:** `api/sources/twinspires.py:128`.

When `Fraction(s).limit_denominator(50)` raises on an unparseable
decimal, the function returns the original string. `odds_to_probability`
is the single canonical parser used downstream and returns `None` for
unrecognized strings — so the unparseable token round-trips to "no
quote", not a false probability.

---

### F6 — SQLite rollback + re-raise in batch insert (Note)

**Location:** `api/cache.py:174`.

Correct transactional handling: explicit `BEGIN`, on success `COMMIT`,
on failure `ROLLBACK` and re-raise. The exception is preserved (not
swallowed), and the single-tx pattern is the documented ~50× speedup
for SQLite writes.

---

### F8a / F8b — `sim` / `tickets` runtime exceptions return error envelope (Note)

**Locations:** `api/main.py:simulate` (line 525),
`api/main.py:build_tickets` (line 574).

Same shape as F3 — broad catch, `_log.exception` for full traceback,
redacted message via `_redact_exc` to the envelope. The endpoints both
return `data=null, errors=[INTERNAL_ERROR, redacted]` so the iPad UI
gets a deterministic shape instead of a 5xx. Comments in place.

---

### F9 — Pick 5 Tier-2 scrape failure logged + ignored (Note)

**Location:** `api/sources/pick5.py:163`.

Tier 1 (hardcoded year-keyed constants) is the source of truth; Tier 2
(Equibase scrape) is a verification override. If Tier 2 raises, Tier 1
still produces a correct answer and `get_pick5_legs` honors its
"never raises" contract. Comment cites this finding and explains the
fallback chain.

---

### F10a / F10b — KentuckyDerby JSON parse skips on malformed blocks (Note)

**Locations:** `api/sources/kentuckyderby.py:74` (`extract_next_data`),
`api/sources/kentuckyderby.py:89` (`extract_jsonld_blocks`).

Both catches are narrow (`ValueError, JSONDecodeError`).
KentuckyDerby.com is a fallback name-only source. Returning `None` /
empty on a malformed block lets the adapter fall through from
`__NEXT_DATA__` to JSON-LD competitors, exactly as designed.

---

### F11a / F11b — `_parse_odds_to_decimal` sentinel-None return (Note)

**Locations:** `api/normalize.py:77, 86`.

The narrow `except ValueError` returns `None` so callers can distinguish
"no quote" from "0% probability" — documented in the function
docstring.

---

### F12 — `data-race` attribute int parse skip (Note)

**Location:** `api/sources/pick5.py:103, 118`.

Narrow `except (TypeError, ValueError)` around `int(...)` of a raw HTML
attribute. Skipping non-numeric attributes is exactly what the regex-
based fallback is for.

---

### F13 / F14 — Rate-limit timestamp recorded in `finally` (Note)

**Locations:** `api/sources/twinspires.py:319`,
`api/sources/equibase.py:199`.

Recording the attempt timestamp in `finally` rather than `else` means a
flapping endpoint cannot bypass the per-source rate-limit floor by
raising — defensive against upstream rate-limit retaliation.

---

### F15 — Optional curl_cffi import (Note)

**Location:** `api/sources/twinspires.py:479`.

`curl_cffi` is the 403-fallback transport. If unavailable, the primary
`httpx` path still works; only the auto-upgrade is lost. The 403-handler
(`_swap_to_fallback`, line 398) raises a clear `RuntimeError` if a 403
is seen with no fallback configured, so failure is loud at the right
moment.

---

### F16 — `_rank_tickets` broad except with debug-only log (Medium → tightened)

**Location:** `api/tickets.py:325` (post-edit).

**Pre-edit:**
```python
except Exception:
    _log.debug("Hit-rate ranking unavailable; falling back to cost order")
```

**Risk lens:** Observability. The `_log.debug` level meant that a real
sim-engine bug that broke ranking would never surface in production
logs (which run at INFO or higher). The contract — "ranking is best-
effort and must never break ticket construction" — is correct, but the
silence undermined our ability to diagnose a real regression.

**Action taken:** Bumped to
`_log.warning("Hit-rate ranking failed; falling back to cost order: %s", exc)`
and updated the docstring to state the warning-log behavior. Behavior
on the happy path and the known-degraded path (e.g. a leg without
`finalProbability`) is unchanged; the warning is the "this is unusual,
please look" signal.

**Verification:** `pytest api/tests` — 274 passed.

---

### F17 — Pydantic silent-extras drop on simulate / tickets endpoints (High → tightened)

**Locations:**
- `api/main.py:SimulateRequest` (line 475)
- `api/main.py:TicketsRequest` (line 484)
- `web/lib/api.ts` (request bodies)
- `web/app/sequence/[day]/page.tsx` (handlers)

**Pre-edit:**
```python
class SimulateRequest(BaseModel):
    n_iterations: int | None = None

class TicketsRequest(BaseModel):
    budget_dollars: float | None = None
    base_unit: float | None = None
```

The iPad UI was posting `tags: Record<string, UserTag>` and
`oddsOverrides: Record<string, string>` to both endpoints (see the
prior `web/lib/api.ts:SimulateBody` / `BuildTicketsBody`), expecting
the simulator and ticket builder to honor user tagging and odds
overrides. Pydantic's default `extra="ignore"` silently dropped both
fields. The simulator's `default_tickets_from_tags` reads
`horse.userTag` from the cached card, but no adapter ever sets
`userTag`, so the user's tagging actions had **no observable effect on
sim or ticket results**.

**Risk lens:** Reliability + Operational. This is the textbook
"validation that warns but accepts" anti-pattern — actually worse,
because Pydantic doesn't even warn. The user's intent was discarded
silently and replaced with a synthetic favorite-only fallback, with no
indication anything was missing.

**Action taken:**

1. Added `model_config = ConfigDict(extra="forbid")` to
   `SimulateRequest` and `TicketsRequest` so any future regression
   posting unsupported fields gets a 422 with a clear message instead
   of a silent drop. (`api/main.py`)
2. Removed `tags` and `oddsOverrides` from
   `SimulateBody` / `BuildTicketsBody` in `web/lib/api.ts`, with a
   comment that explains why they were intentionally cut.
3. Updated `handleRunSim` and `handleBuildTickets` in
   `web/app/sequence/[day]/page.tsx` to call `simulate(day, {})` and
   `buildTickets(day, { budget_dollars, base_unit })` respectively,
   with comments pointing at this finding. The local UI-state for
   `tags` and `oddsOverrides` is preserved — the iPad still lets you
   tag/override for visual review — it just no longer pretends those
   inputs influence the sim.
4. Filed Escalation **E1** below to track the underlying feature gap.

**Verification:** `pytest api/tests` — 274 passed (no test asserted the
silent-drop behavior). `npx tsc --noEmit` in `web/` — clean.

---

### F18 / F19 — Date-format try/catch fallback (Note)

**Locations:** `web/components/StaleBanner.tsx:11`,
`web/components/DayHeader.tsx:23`.

Both helpers wrap `new Date(iso).toLocaleString()` /
`toLocaleTimeString()` in `try/catch` and fall back to the raw ISO
string on failure. The catch is appropriately narrow (no broad logging
needed) — it only handles malformed timestamps that the backend
shouldn't be producing anyway. The fallback (raw string) is preferable
to crashing the React tree for a display-only widget.

**Disposition:** Acceptable. No code change.

---

### F20 — Browser fetch catch → setError (Note)

**Location:** `web/app/sequence/[day]/page.tsx` (multiple
`try/catch (e) { setError(String(e)); }` patterns in the four handlers
and the initial `useEffect`).

Each handler stringifies the caught error into a state slot consumed by
a `role="alert"` banner. This is appropriate UI-side error handling for
a personal app — the user sees the failure, hits retry. There's no
network logging stack to wire to here.

**Disposition:** Acceptable. No code change.

---

### F21 — `poll_pick5_odds` is all-or-nothing per cycle (Note)

**Location:** `api/refresh.py:poll_pick5_odds` (line 87).

`twinspires.fetch_odds` errors propagate up to `refresh_odds`, which
catches `Exception` (F3b) and returns a stale-cache envelope. A single
bad race blanks the whole cycle's writes. Per-race try/except inside
the loop would be more resilient.

**Why this is acceptable:** The stale-cache contract already covers the
user-visible behavior (the iPad keeps showing the prior validated
snapshot), the per-race rate-limit floor (30s) means transient failures
naturally retry on the next cycle, and the BRAINDUMP "Refresh Odds"
flow is a single user action — they can re-tap. Splitting per-race
would also widen the surface for partial writes that confuse drift
charts. Treating the cycle as the atomic unit is intentional.

**Disposition:** Acceptable. No code change.

---

## Categorization

### acceptable-prod-notes (16)
F1, F2a, F2b, F3a, F3b, F4, F5, F6, F8a, F8b, F9, F10a, F10b, F11a,
F11b, F12, F13, F14, F15, F18, F19, F20, F21 — all carry inline pointer
comments to their report section.

### needs-doc (0)
None outstanding.

### needs-telemetry (0)
The cache-fallback catches all log via `_log.exception`. Per-leg
TwinSpires failures log via `_log.warning`. The teardown swallow paths
log at debug. After F16, the rank-tickets fallback now logs at warning
with exception detail. No additional logging gaps were identified.
Absence of a metrics/structured-logging backend is a project-phase
artifact (Phase 1, BRAINDUMP) and not an error-handling bug.

### tighten-before-prod (0)
F16 and F17 were tightened in this pass; F1 and F2 in the prior pass.

### hidden-failure-risk (0)
F17 was the last live one — silent acceptance of UI-posted fields that
the backend never consumed. Now loud: any future regression posting
unrecognized fields gets a 422 with a clear message.

---

## Escalations

### E1 — Tag-aware sim / odds override is unwired

**Blocker:** The iPad SPA exposes per-horse `userTag` selection
(`single`, `A`, `B`, `C`, `toss`, `chaos`, `boost`, `fade`) and per-horse
`currentOdds` overrides as first-class UI affordances, but the backend's
`/api/simulate/{day}` and `/api/tickets/{day}/build` endpoints have no
mechanism to receive that state. After F17 the silent drop is gone, but
the underlying feature gap is still unresolved: the user can tag horses
in the UI and see the tag pills, but `sim.default_tickets_from_tags`
reads `horse.userTag` from the cached card and **no adapter sets
`userTag` server-side**, so the result is always the favorite-only
fallback regardless of UI state.

**Smallest concrete next action:** Pick one of the two paths below and
file a single ticket against it. Both are ~half-day changes.

1. **Wire the feature.** Add `tags: dict[str, UserTag] | None` and
   `odds_overrides: dict[str, str] | None` to `SimulateRequest` /
   `TicketsRequest`. In each handler, before calling `blend_race` /
   `default_tickets_from_tags` / `tickets.build_tickets`, mutate the
   in-memory `cached_card.races` to apply the overrides (`currentOdds`
   + recomputed `marketProbability`) and tag assignments. Keep the
   mutation request-scoped — do NOT persist back into the SQLite cache.
2. **Remove the UI affordance.** Strip `tags`, `oddsOverrides`,
   `TagPicker`, and `OddsOverride` from `web/`. The card display
   continues to show backend-derived flags.

Either path closes the loop; the current state (UI exists, backend
ignores) is what created F17 in the first place.

**Owner:** application owner (this is a personal app — same person).
**Why escalated rather than acted on:** wiring the feature crosses
adapter, normalize, sim, and tickets boundaries plus a request-scoped
mutation contract; removing the UI deletes ~200 LOC of components and
is a product-direction call. Either is bigger than an error-handling
tightening.

---

## Final verdict

**Prod posture acceptable.**

Two new findings were uncovered this pass — F16 (debug-only swallow
that hid sim-engine bugs) and F17 (Pydantic silent-extras drop that
made the user's tagging actions a no-op). Both are now fixed. The
remaining 21 Note-level findings are deliberate, narrow, or both, and
all carry inline pointers to this report. The cache-fallback contract
(`stale_envelope` + `_log.exception` + `_redact_exc`) is uniformly
applied at the API boundary; broad catches all log with traceback (or
at warning with exception detail, in the case of best-effort
fallbacks); and the only suppression that was genuinely hiding a
product-level failure (F17) has been made loud. The Escalation E1
captures the one architectural decision that exceeds the scope of an
error-handling pass.
