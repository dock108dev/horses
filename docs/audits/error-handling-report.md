# Error-Handling & Suppression Audit — Derby Pick 5

Pass date: 2026-04-28
Scope: API backend (`api/`), Next.js frontend (`web/`), source adapters,
cache layer, fixture loader, and the post-refresh validation pipeline.

This report inventories every intentional swallow / downgrade / fallback
in the codebase, classifies each by risk lens and severity, and acts on
or justifies every finding. The legacy `docs/audits/` reports referenced
by inline comments (F1..F24, S1..S18, E1) were deleted by the SSOT pass —
this document re-establishes the rationale archive those comments point
at, and extends it with four new findings (F32–F35) for code surfaces
that have landed since the recovery branch was opened. F35 was added in
the current pass when the audit verifier observed that
`test_403_without_fallback_raises` was failing because
`TwinSpiresAdapter.__post_init__` silently auto-builds the curl_cffi
fallback. The test was tightened in this pass so it actually exercises
the F15 "no fallback configured → RuntimeError" branch.

The actionability contract: every finding here is either tightened in
the code (action recorded inline) or justified in this report **and** at
the code site. There are no bare TODOs.

---

## Executive summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 0     |
| High       | 0     |
| Medium     | 0 open (2 already tightened: F25, F27) |
| Low        | 5     |
| Note       | 26    |

**Posture verdict: Prod posture acceptable.** The app is a single-user
LAN-bound iPad tool with no auth, no money flow, no PII, and no callers
beyond the operator. Every broad catch in the request path is the
intentional implementation of the BRAINDUMP "Cache Strategy" contract:
serve the last validated cache with `stale=True` and the redacted error
attached, never a 500 on race day. Tracebacks are still logged via
`_log.exception`, so observability is preserved.

The two Medium items (Equibase HTTP-client close, OddsCache SQLite close)
are already tightened in code — both are now wrapped in try/except with
debug-level logging, matching the TwinSpires `_safe_close` pattern. They
previously could mask the real request-handler exception with a teardown
error.

There are no Critical or High findings. There is one open Escalation
(E1) covering UI-side tags / odds overrides that the backend silently
does not consume — mitigated by `extra="forbid"` on the request models,
but still a "works in UI, no effect" hazard worth fixing when the
tag-aware sim lands.

### Top issues (action taken or justified)

1. **F25 (Medium → Tightened) — EquibaseAdapter.close() did not safely close.**
   Wrapped in try/except, logs at debug. Matches F2.
2. **F27 (Medium → Tightened) — OddsCache.close() did not safely close.**
   Wrapped in try/except, logs at debug. Matches F2.
3. **F32 (Note → Justified) — fixture.py silent-skip in `load_odds_records`.**
   Inline comment added at the loop site citing this report.
4. **F33 (Note → Justified) — TwinSpires `_get_json` 404 → None downgrade.**
   Inline comment extended to cite this report.
5. **F34 (Note → Justified) — `pct`/`num` formatters degrade NaN to "—".**
   Same pattern as F29. The cleanup pass consolidated the duplicate
   formatters into `web/lib/format.ts`, where the NaN/Infinity/null guard
   is documented in the module docstring. `SimulationSummary` and
   `TicketBuilder` now import from there.
6. **F35 (Note, new this pass — Justified + test tightened).** The
   `TwinSpiresAdapter` constructor silently auto-builds a curl_cffi
   fallback when one is not passed. This is constructor-default
   behavior (not error swallowing), but it kept
   `test_403_without_fallback_raises` from actually exercising the F15
   "no fallback configured → RuntimeError" branch. The test was
   tightened to stub `_build_curl_cffi_client` and assert
   `adapter.fallback_client is None` before driving the 403, so the
   contract path now has real coverage. Inline cite added at the
   constructor site.
7. **E1 (Escalation) — UI tags / odds overrides are local-only.**
   The `tags` and `oddsOverrides` state in the SPA never reaches the
   backend; sim and ticket builds operate on the cached card only.
   `extra="forbid"` on `SimulateRequest` / `TicketsRequest` (F17)
   guarantees that if the UI ever forgets and posts these fields the
   request will 422 instead of silently dropping them.

---

## Findings table

| ID  | Location                                             | Category                  | Severity | Disposition |
| --- | ---------------------------------------------------- | ------------------------- | -------- | ----------- |
| F1  | `api/sources/pick5.py:97`                            | parser-tolerant by design | Note     | justify     |
| F2  | `api/sources/twinspires.py:478`                      | teardown silence          | Note     | justify     |
| F3  | `api/main.py:349,382,511,546`                        | cache-fallback contract   | Low      | justify     |
| F4  | `api/refresh.py:56`                                  | per-leg downgrade         | Low      | justify     |
| F5  | `api/sources/twinspires.py:129`                      | odds parse fallback       | Note     | justify     |
| F6  | `api/cache.py:183`                                   | rollback + re-raise       | Note     | justify     |
| F7  | (reserved)                                           | —                         | —        | —           |
| F8  | `api/main.py:634,683`                                | sim/tickets envelope      | Low      | justify     |
| F9  | `api/sources/pick5.py:164`                           | tier-2 verification       | Note     | justify     |
| F10 | (removed — KentuckyDerby adapter deleted by SSOT pass) | —                       | —        | —           |
| F11 | `api/normalize.py:76,85`                             | odds parse → None         | Note     | justify     |
| F12 | `api/sources/pick5.py:104,119`                       | data-race attr parse      | Note     | justify     |
| F13 | `api/sources/twinspires.py:320`                      | odds-floor in `finally`   | Note     | justify     |
| F14 | `api/sources/equibase.py:220`                        | rate-limit in `finally`   | Note     | justify     |
| F15 | `api/sources/twinspires.py:486`                      | optional dependency       | Note     | justify     |
| F16 | `api/tickets.py:697`                                 | sim fallback              | Low      | justify     |
| F17 | `api/main.py:568,580` + `web/lib/api.ts:47`          | extras=forbid contract    | Note     | justify     |
| F18 | (reserved)                                           | —                         | —        | —           |
| F19 | (reserved)                                           | —                         | —        | —           |
| F20 | (reserved)                                           | —                         | —        | —           |
| F21 | (reserved)                                           | —                         | —        | —           |
| F22 | `api/model.py:469,478`                               | priors range key parse    | Note     | justify     |
| F23 | `api/model.py:716,723` (`_compute_velocity`)         | NaN/inf guard             | Note     | justify     |
| F24 | `api/tickets.py:638`                                 | confidence neutral fallback | Note   | justify     |
| F25 | `api/sources/equibase.py:166`                        | teardown silence          | Medium   | **tightened** |
| F26 | `api/sources/twinspires.py:514`                      | curl_cffi inner close     | Note     | justify     |
| F27 | `api/cache.py:132`                                   | sqlite close silence      | Medium   | **tightened** |
| F28 | `web/components/HorseRow.tsx:134`                    | bucket lookup fallback    | Note     | justify     |
| F29 | `web/components/StaleBanner.tsx:11`, `DayHeader.tsx:23` | date format guard      | Note     | justify     |
| F30 | `web/app/sequence/[day]/page.tsx:108–230`            | catch-to-state            | Low      | justify     |
| F31 | `api/main.py:95` (`_redact_exc`)                     | error message redaction   | Note     | justify     |
| F32 | `api/sources/fixture.py:130–146`                     | fixture row silent-skip   | Note     | justify     |
| F33 | `api/sources/twinspires.py:432`                      | TwinSpires 404 → None     | Note     | justify     |
| F34 | `web/lib/format.ts:6–24`                             | formatter NaN guard       | Note     | justify     |
| F35 | `api/sources/twinspires.py:264–270` (`__post_init__`) | constructor auto-fallback | Note    | justify + **test tightened** |

Reserved IDs are kept stable so existing inline comments (`F1..F24`)
keep pointing at the right slot in case the report is re-grouped.

---

## Per-finding details

### F1 — `parse_pick5_first_leg` does not wrap `BeautifulSoup`

`api/sources/pick5.py:97`. `BeautifulSoup(card_html, "html.parser")` is
called without a try/except. **Justified**: `html.parser` is documented
as accepting arbitrary input — it produces a tree even from invalid
HTML and never raises on garbage. Wrapping it would only obscure real
import-time bugs (e.g. `bs4` missing). Risk: reliability — none.

### F2 — Teardown swallowing on HTTP clients

`api/sources/twinspires.py:478` (`_safe_close`). Close failures are
caught, logged at `DEBUG`, and dropped. **Justified**: a close failure
cannot be surfaced from `__exit__` without masking the request-side
exception that triggered cleanup. Logging at debug keeps a systemic
resource leak observable without paging on every transient teardown
blip. Same shape as the EquibaseAdapter close (F25) and OddsCache
close (F27). The KentuckyDerby adapter that previously matched this
pattern was removed by the SSOT pass.

### F3 — Cache-fallback contract on `/refresh`

`api/main.py:349` (fixture card), `:382` (live card), `:511` (fixture
odds), `:546` (live odds). Each is `except Exception as exc:` followed
by `_log.exception(...)` and a `_stale_*_envelope(..., errors=[...])`
return. **Justified**: this is the BRAINDUMP "Cache Strategy" contract
— any live ingestion failure must serve the last good cached card with
`stale=True` and `errors` populated, not a 5xx. Risk lens: reliability
positive (no race-day blank screen); observability preserved by
`_log.exception`; security: see F31 (redacted message in payload).

### F4 — Per-leg TwinSpires downgrade

`api/refresh.py:56`. A TwinSpires hiccup on a single race is logged at
`WARNING`, sets `ts_race = None`, and the merge proceeds with Equibase
data only. **Justified**: a single race failing on the live-odds source
must not blank out the rest of the card. `validate_card` downstream
still flags missing odds, so the operator sees the gap rather than
believing the card is fully fresh.

### F5 — `to_fractional_odds` malformed input

`api/sources/twinspires.py:129–135`. `Fraction(s).limit_denominator(50)`
is wrapped in a narrow `except (ValueError, ZeroDivisionError,
ArithmeticError)` that returns the original string unchanged.
**Justified**: `odds_to_probability` is the canonical parser and
returns `None` for unrecognized inputs, so passing the raw string
through is harmless. Logging this at warning would create noise on
TwinSpires "scratched" rows that send sentinel values.

### F6 — SQLite batch rollback

`api/cache.py:183`. The `executemany` insert is wrapped in `BEGIN /
COMMIT` with `except Exception: ROLLBACK; raise`. **Justified**:
rollback is necessary so a partial batch isn't visible to readers; the
exception is *not* swallowed — it re-raises so the caller's
cache-fallback path (F3) takes over.

### F8 — Sim and tickets envelope

`api/main.py:634` (simulate), `:683` (tickets). Same `_log.exception`
+ envelope contract as F3, applied to `simulate` and `build_tickets`
route handlers. **Justified**: identical reasoning. Returns
`SIM_INTERNAL_ERROR` / `TICKETS_INTERNAL_ERROR` plus a redacted
exception message; the SPA renders these in `SimulationSummary` /
`TicketBuilder` error slots.

### F9 — Tier-2 Pick 5 scrape

`api/sources/pick5.py:164`. `_scrape_first_leg` failures are logged at
`WARNING`, the function falls through to Tier 1 (hardcoded sequences)
or Tier 3 (last-five-of-card heuristic). **Justified**: the docstring
guarantees the function "never raises" — Tier 1 hardcoded data is
authoritative for 2024–2026 and was verified in research. The scrape
is purely an upgrade path for years where Churchill changes the
program.

### F10 — KentuckyDerby JSON-LD / `__NEXT_DATA__` parse (removed)

The KentuckyDerby adapter was deleted by the SSOT pass — see
`docs/audits/ssot-report.md`. Finding ID retained for stable
numbering only.

### F11 — `odds_to_probability` returns None on parse failure

`api/normalize.py:76–82`, `:85–89`. `_parse_odds_to_decimal` returns
`None` on any unparseable input rather than raising. **Justified**:
callers distinguish `None` ("no quote") from `0.0` ("zero
probability"); this contract is critical for `validate_card`'s missing
odds count and for the merge-odds flow. Tested in
`api/tests/test_normalize.py`.

### F12 — Non-numeric `data-race` attribute skip

`api/sources/pick5.py:104–106`, `:119–121`. **Justified**: scraping a
mixed wager-menu page can encounter non-numeric `data-race` values
(decoration nodes); skipping is correct — the surrounding loop
collects all valid candidates and picks the minimum.

### F13 — Odds-poll floor recorded in `finally`

`api/sources/twinspires.py:320–326`. The 30-second per-race odds poll
floor is updated in a `finally` block so a flapping source can't
bypass throttling by raising. **Justified**: rate-limit hygiene; the
exception still propagates to `poll_pick5_odds` → `refresh_odds`
which maps it to F3.

### F14 — Equibase rate-limit recorded in `finally`

`api/sources/equibase.py:220–225`. Same pattern as F13 for the
3-second Equibase floor. **Justified**: identical reasoning; protects
Equibase from being hammered if it goes flaky.

### F15 — Optional `curl_cffi` dependency

`api/sources/twinspires.py:484–489`. `ImportError` on `curl_cffi`
returns `None`, disabling the 403-fallback path but keeping the
primary `httpx` client. **Justified**: `curl_cffi` is optional for
local dev where the bot-detection path is rarely needed.
`_swap_to_fallback` raises `RuntimeError` with an actionable message
when a 403 *does* arrive without a fallback configured. See F35 for the
constructor-default behavior that meant this branch was previously
under-tested when curl_cffi was installed in the test environment.

### F16 — Sim engine fallback in tickets builder

`api/tickets.py:697–710`. `try/except` wraps the `sim.simulate` call
inside `_simulate_candidates`; on failure logs at `WARNING` and
returns `{}`. The downstream selector then falls back to
ascending-cost order. **Justified**: explicit contract — "must never
break ticket construction". Logged at warning (not debug) so a real
sim-engine bug surfaces in the operator's terminal.

### F17 — `extra="forbid"` on Pydantic request models

`api/main.py:568,580` + `web/lib/api.ts:43–47`. `SimulateRequest` and
`TicketsRequest` both set `model_config = ConfigDict(extra="forbid")`.
**Justified**: Pydantic's default is silent acceptance, which would
make the UI tag/odds-override fields look like they were applied when
they were silently dropped. `extra="forbid"` converts a hidden
ack-and-drop hazard into a 422 the SPA can surface. See Escalation E1.

### F22 — Priors range key parse

`api/model.py:469,478`. `_odds_rank_multiplier` skips malformed range
keys (`"x+"`, `"a-b"`) in `priors.json`. **Justified**: priors.json is
committed config; a malformed key would only result from a bad edit,
and falling through to the default `1.0` multiplier is a safe no-op.
The misconfiguration is visible at review time.

### F23 — NaN / inf guard in velocity computation

`api/model.py:716–724`. `_compute_velocity` rejects non-finite
probabilities at the boundary. **Justified**: drift tuples come from
SQLite rows and aren't Pydantic-validated; letting NaN propagate
would silently corrupt `finalProbability` and JSON-serialize as the
non-standard `NaN` literal that breaks strict parsers.

### F24 — Confidence neutral fallback in tickets

`api/tickets.py:638`. When the edge model has not run on a card,
`compute_ticket_confidence` returns `None`; the scorer substitutes
`1.0` so the multiplicative `score = win × payout × confidence`
doesn't collapse to zero on every candidate. **Justified**: collapsing
all scores to zero ties every candidate and makes the Balanced /
Safer / Upside selection arbitrary. Neutral 1.0 keeps `win_probability
× payout_score` as the deciding signal.

### F25 — EquibaseAdapter.close() did not safely close — **TIGHTENED**

`api/sources/equibase.py:163–168`. Previously
`self.http_client.close()` without try/except. If `httpx.Client.close()`
raised (rare but possible on socket teardown errors), the exception
propagated from `__exit__` and could mask the request-handler
exception that triggered the dependency cleanup.

**Action taken**: wrapped in `try/except Exception` with
`_log.debug(...)` to match the TwinSpires `_safe_close` pattern (F2).

### F26 — `_CurlCffiClient.close()` does not internally swallow

`api/sources/twinspires.py:514–518`. The inner `_CurlCffiClient.close`
calls `self.session.close()` directly; if it raises, propagation is
caught one frame up by `_safe_close` (F2). **Justified**: defense in
depth is already in place at the caller boundary; adding another
try/except inside `_CurlCffiClient` would be redundant and obscures
the small adapter shape.

### F27 — `OddsCache.close()` did not safely close — **TIGHTENED**

`api/cache.py:128–134`. Previously `self._conn.close()` without
try/except. SQLite connection close occasionally raises under WAL
when a request handler aborts mid-transaction; that exception would
propagate from the FastAPI `get_cache` finally block and mask the
original failure.

**Action taken**: wrapped in `try/except Exception` with
`_log.debug(...)` matching F2. The handler failure remains the
visible exception; a connection-close blip becomes a debug-level log
line.

### F28 — Defensive bucket lookup in HorseRow

`web/components/HorseRow.tsx:134`. `BUCKET_STYLES[bucket]` falls
through to `null` for unknown values. **Justified**: TypeScript
guarantees `bucket: ComputedBucket | undefined` at compile time, but
a malformed API payload (replay attack, future enum addition)
shouldn't crash with a `Cannot destructure property 'color' of
undefined`. Returning `null` degrades gracefully.

### F29 — Date format `try/catch`

`web/components/StaleBanner.tsx:11–15`,
`web/components/DayHeader.tsx:23–27`. `new Date(iso).toLocaleString()`
is wrapped in a no-op catch that returns the raw ISO string.
**Justified**: pure presentation safety against an unexpected ISO
input; never hides a real error because the fallback is the input
itself.

### F30 — Frontend page handlers catch into local state

`web/app/sequence/[day]/page.tsx:108–230`. Every async action (the file
exposes five independent `setError` / `setSimError` / `setTicketsError`
slots — `fetchCard`, `refreshCard`, `refreshOdds`, `simulate`,
`buildTickets`).
(`fetchCard`, `refreshCard`, `refreshOdds`, `simulate`,
`buildTickets`) is wrapped in `try/catch` that calls `setError(...)`
or `setSimError(...)` / `setTicketsError(...)` and updates a busy
flag. **Justified**: the error is rendered in the corresponding panel
(top-of-page banner, `SimulationSummary` error slot, `TicketBuilder`
error slot). `String(e)` is shown verbatim, which is the same payload
the backend's `_redact_exc` already sanitized; no further leak.

### F31 — `_redact_exc` strips URLs and filesystem paths

`api/main.py:95–108`. Strips `https?://...` and `/path/segments/...`
from exception strings before placing them in the response envelope.
**Justified**: scraper URLs and on-disk cache paths are not secrets
but they leak internals to the iPad browser surface. Class name is
preserved so the UI can still differentiate parse errors from HTTP
5xx. **Regression coverage**: `api/tests/test_stale_fallback.py`
(added in this pass) drives a refresh against a `_RaisingEquibase`
stub whose `RuntimeError` message embeds (a) a real HTTPS URL and
(b) a multi-segment absolute filesystem path. Both tests assert the
stale envelope's `errors[1]` starts with `"RuntimeError: "` and
contains the literal `<url>` / `<path>` token, never the original
`https://`, hostname, or cache filename. So the redaction contract is
now enforced by the test suite, not just by the code comment.

### F32 — Fixture row silent-skip in `load_odds_records`

`api/sources/fixture.py:130–146`. The per-entry loop in
`load_odds_records` falls through to `continue` on every malformed or
unmatched fixture row (non-dict entry, missing `raceId`, non-int
`post`, blank `odds`, no matching non-scratched horse, unparseable
odds string). The function returns the records that *did* parse and
match. **Justified**: fixtures live in `fixtures/pick5/*.json`,
committed config that is reviewed at edit time on a single-developer
project; a hand-edited bad row would only surface as "fewer odds in
fixture mode," which `validate_card` then flags via the
`missing odds for N horses` error. The function docstring is the
contract ("Records whose `(raceId, post)` does not match a
non-scratched horse in `races` are skipped — keeps a fixture odds
file usable across small card edits without needing to be
regenerated"). Risk lens: reliability/data-integrity low; observability
acceptable because the validate step catches missing odds downstream.
Inline comment added at the loop site citing this finding.

### F33 — TwinSpires `_get_json` 404 → None

`api/sources/twinspires.py:429–434`. After a 403 fallback retry,
`_get_json` checks for HTTP 404 and returns `None` instead of raising
via `raise_for_status()`. **Justified**: TwinSpires returns 404 for
races that have not been drawn / posted, which is a normal state
during the morning of race day before entries publish. Raising would
turn this into the F3/F4 cache-fallback path on every poll, which is
both noisier in the logs and slower (the entire refresh cycle reverts
to stale data). The downstream parsers (`_parse_program`,
`_parse_odds`) already handle a `None` payload by returning empty.
Inline comment expanded to cite this finding.

### F34 — `pct`/`num` formatter NaN guard

`web/lib/format.ts:6–24`. The shared `pct` and `num` formatters return
`"—"` for `null`, `undefined`, `NaN`, or `Infinity`. **Justified**: same
presentation-only safety as F29 — a malformed API payload field (or an
unexpected `NaN` from an in-flight sim) should render a placeholder dash
rather than `"NaN%"` or crash the panel. The fallback is purely the
displayed character; no error is swallowed because no error is being
raised in the first place. The formatters were originally duplicated in
`SimulationSummary.tsx` and `TicketBuilder.tsx`; the cleanup pass
consolidated them into `web/lib/format.ts`, whose module docstring
captures the F34 rationale ("`pct`/`num` degrade `NaN`/`Infinity`/`null`
to `\"—\"` so a single bad payload field can't crash a render pass").

### F35 — `TwinSpiresAdapter.__post_init__` silently auto-builds a curl_cffi fallback

`api/sources/twinspires.py:264–270`. When the caller passes
`fallback_client=None`, the dataclass `__post_init__` silently calls
`_build_curl_cffi_client(...)` and, if the optional dependency is
installed, attaches the resulting client to `self.fallback_client` and
flips `_owns_fallback_client = True`. **Justified**: this is
constructor-default behavior, not error swallowing. The auto-build only
suppresses `ImportError` (already covered by F15); any other failure
in `cf_requests.Session(impersonate=...)` propagates and fails adapter
construction, which is the correct fail-fast posture.

The reason this surfaced as a finding *now* is that it kept
`api/tests/test_twinspires.py::test_403_without_fallback_raises` from
actually exercising the F15 "no fallback configured → RuntimeError"
branch. In any environment where `curl_cffi` is installed (the dev
machine where this audit ran, plus production), passing
`fallback_client=None` to the constructor was overridden by the
auto-build, so the test's `pytest.raises(httpx.HTTPStatusError)`
either failed (auto-fallback hit a real network and returned
something the parser tolerated) or, with a deterministic stub,
silently took the swap-and-retry path. The contract assertion was
unverifiable.

**Action taken in this pass**: the test now stubs
`twinspires._build_curl_cffi_client` to return `None` via
`monkeypatch.setattr`, then asserts `adapter.fallback_client is None`
before driving the 403, so the F15 branch is exercised regardless of
which optional deps are installed in the test environment. The inline
comment at `__post_init__` cites this finding so future readers
understand the constructor's "silent default" is intentional and
isn't an error-handling lapse.

Risk lens: reliability **positive** (auto-bootstraps the 403-fallback
in prod where curl_cffi is installed); observability neutral
(no debug log, but it's a constructor default that runs once per
adapter instance — paging on it would be noise); data integrity
n/a; security n/a.

---

## Categorization

### Acceptable production posture (justified, no action)

F1, F2, F5, F6, F9–F15, F17, F22–F24, F26, F28–F35. Every one of
these has either an inline justification at the code site or is a
narrow exception class catch with a sentinel return — both are
enumerated above.

### Needs documentation (action: this report) ✓

F3, F4, F8, F16, F32, F33, F34, F35. F3/F4/F8/F16 had inline references
to "finding F3 / F4 / F8 / F16" that pointed at the deleted
`docs/audits/` reports. This file re-establishes those targets so the
inline comments resolve. F32 and F33 were added during the recovery
branch and carry inline comments pointing here. F34's rationale lives
in the `web/lib/format.ts` module docstring (the cleanup pass folded
the per-component duplicates into that single shared file); no inline
`F34` cite is present at the call site, but the docstring above the
formatters captures the same NaN/Infinity/null contract. F35 is new
this pass; an inline comment was added at
`TwinSpiresAdapter.__post_init__` pointing here.

### Needs telemetry (none)

No suppression site is missing the appropriate log level. The "log at
WARNING when behavior actually degrades vs. log at DEBUG for cosmetic
events" split is consistently applied:
- F4 (per-leg downgrade) → WARNING
- F9 (Pick 5 scrape failure) → WARNING
- F16 (sim fallback) → WARNING
- F2 / F25 / F27 (teardown blips) → DEBUG
- F3 / F8 (broad route catches) → `_log.exception` (full traceback)
- F32 / F33 / F34 — silent (presentation / config-input tolerance)
- F35 — silent (constructor default; runs once per adapter)

### Tighten before prod (action taken)

- F25, F27. Both fixed in a prior pass and verified in the current
  code.
- F35 (this pass). The
  `test_403_without_fallback_raises` test was tightened to actually
  exercise the F15 contract by stubbing `_build_curl_cffi_client`
  via `monkeypatch`. Before this change, the test was failing on the
  current `main` branch because `__post_init__`'s auto-fallback
  defeated the test's premise.

Re-running `pytest api/tests` shows 376 passed, 1 skipped (the
`test_friday_pick5_simulate_golden_snapshot` test is intentionally
skipped pending a `seed` parameter on `SimulateRequest`).

### Hidden failure risk (none)

There are no log-and-return-None paths that consume real data without
flagging it. F32 is the closest call (silently drops malformed fixture
rows) but the downstream `validate_card` step turns the resulting "fewer
matched odds" into a user-visible error before the response goes out.

---

## Escalations

### E1 — UI tags and odds overrides are local-only

**Blocker**: the backend has no tag-aware `/simulate` or
`/tickets/build` wiring. The SPA stores per-horse `tags` and
`oddsOverrides` in component state and intentionally **does not** post
them with the request bodies — see the comment in `web/lib/api.ts:43`
and the parallel comment in
`web/app/sequence/[day]/page.tsx:192–193`.

**Mitigation in place**: F17 (`extra="forbid"` on `SimulateRequest`
and `TicketsRequest`). If the SPA ever forgets and posts these
fields, the backend returns 422 instead of silently dropping them.

**Smallest concrete next action**: extend `SimulateRequest` /
`TicketsRequest` with optional `tags` and `oddsOverrides`, wire them
through `api.sim.default_tickets_from_tags` (which already supports
tag-driven selection) and `api.tickets.build_tickets` (already
consumes `userTag`), and remove the frontend comment + add the fields
to the request body. Tracked here rather than as a TODO in code so
future contributors aren't tempted to "just enable it" without the
wiring.

**Owner**: app maintainer (single-developer project).

---

## Verification

- `pytest api/tests` — **376 passed, 1 skipped** (post-F35
  tightening). The skipped test is the deferred golden snapshot for
  `/simulate/friday`, blocked on adding `seed` to `SimulateRequest`.
  The previous report's "373 passed, 0 failed" line was stale: this
  pass added two new test files (`test_friday_e2e.py`,
  `test_stale_fallback.py`) for **+4 tests** (3 active + 1 skipped),
  and tightened one previously-failing test. Net: every test in the
  suite now either passes or is intentionally skipped with a
  documented reason.
- New positive-verification surfaces:
  - `api/tests/test_friday_e2e.py` exercises the full Pick 5
    fixture-mode happy path (refresh card → refresh odds → simulate
    → build tickets) and asserts `errors=[] and stale=False` at
    every step. Any regression that flips a step into the F3/F4/F8
    cache-fallback path will fail here loudly.
  - `api/tests/test_stale_fallback.py` adds direct regression
    coverage for the F31 redaction contract (URL → `<url>` and
    multi-segment filesystem path → `<path>` with class-name
    preserved).
  - `api/tests/test_twinspires.py::test_403_without_fallback_raises`
    now exercises the F15 "no fallback configured → RuntimeError →
    httpx 403 propagation" branch even when curl_cffi is installed
    in the test environment (per F35).
- Broad-catch behavior unchanged in this pass; the only code edit was
  the inline comment at `__post_init__` (F35) and the test-side
  monkeypatch in `test_403_without_fallback_raises`. Line-number
  drift across F2, F3, F4, F5, F6, F8, F9, F11, F12, F13, F14, F15,
  F16, F17, F22, F23, F24, F25, F26, F27, F31, F33 was reconciled
  against the current files.
- All inline F-numbered comments at suppression sites resolve to
  sections in this report (F34 is satisfied by the
  `web/lib/format.ts` module docstring rather than an explicit cite).
- The `pyproject.toml` `live` marker added in this branch is a
  test-execution guardrail, not error-handling: tests carrying
  `@pytest.mark.live` are deselected by default so CI / pre-commit
  stays sandboxed. The inline note at the marker explicitly forbids
  applying `live` to security-regression tests, which means the F31
  redaction tests, the F3/F4/F8 cache-fallback tests, and the F32
  fixture-loader tests stay in the default selection set and gate
  every commit.
