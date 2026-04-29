# Cleanup Report — 2026-04-28

Code-quality cleanup pass on the post-recovery branch. Tests stay green
(`pytest api/tests` → 376 passed, 1 skipped) and the frontend
typechecks (`npx tsc --noEmit` exits 0; the only frontend change in
this pass is a comment-only LOC-note refresh). No public API call
signatures changed; no behavioral changes.

This pass was a follow-up sweep after the SSOT, security, error-
handling, and prior cleanup pass had each landed. It picks up the
residual stale references that the previous pass's "Consistency
changes" list claimed to strip but had only stripped from module-level
docstrings, and refreshes the inline LOC notes to match the current
files (the previous numbers had drifted again as the audits added
inline rationale comments).

## Dead code removed

This pass turned up **no removable dead code** — every public symbol in
`api/`, `api/sources/`, and `web/` is wired to either a production
caller or a passing test (verified by `pyflakes api/` returning clean
and by grep across the frontend). No unused imports, commented-out
blocks, or stale experiments surfaced.

What did surface was one residual rationale-comment that pointed at a
research file no longer on disk — see "Consistency changes" below. It
is a dead reference, not dead code, and was rewritten in place to keep
the actual rationale.

## Files refactored / split

None this pass. The previous pass's `web/lib/format.ts` extraction is
still the canonical home for `pct` / `num` / `money`; nothing else
crossed the bar where extraction would be a clean split rather than a
shuffle of imports.

## Duplicates consolidated

No new duplicates surfaced. Spot-checked candidates that turned out to
be **non-duplicates** and are intentionally kept distinct:

| Candidate                                  | Why it's not a duplicate                                                                                                          |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `web/lib/odds.ts:formatPercent` vs<br>`web/lib/format.ts:pct` | `formatPercent(p, digits)` takes a fractional `[0, 1]` value and multiplies by 100 before formatting; `pct(value, digits)` takes an already-percent value (e.g. `chalkiness_pct`) and formats directly. The probability fields and the percent fields flow through different layers, so unifying would force every caller to remember which scale it has. |
| `StaleBanner.tsx:fmt` vs<br>`DayHeader.tsx:fmt`              | Same name, different surface contracts: `StaleBanner` shows the full `toLocaleString()` for a cached-at warning and renders `"—"` when null; `DayHeader` shows only `toLocaleTimeString()` for the page header and renders `"never"` when null. The placeholder strings and the date/time precision are deliberately surface-specific.            |

## Files still >500 LOC

Each is justified inline at the file head and re-stated here. LOC
counts were refreshed in this pass — most had drifted by 2-5 lines as
the security and error-handling passes added inline rationale comments
on top of the previous cleanup pass's docstring tightening. The
"extraction trigger" sub-clauses remain dropped because the files are
already past every previous trigger; carrying the trigger language
forward would still be misleading.

### `api/main.py` — 820 LOC (justify, inline note refreshed)

Every section is FastAPI route wiring on the single `app` instance.
Splitting into `routers/` would fragment the `Envelope`
request/response contract — every route returns the same shape and
shares the `get_cache` / `get_equibase_adapter` /
`get_twinspires_adapter` dependencies — for no behavioral win.
Module-docstring LOC note refreshed `816 → 820` this pass.

### `api/model.py` — 1374 LOC (justify, inline note refreshed)

Pydantic `Horse` / `Race` / `OddsSnapshot` types + the entire
probability layer (priors → blend → historical priors → flags →
movement → classification → edge model) live in one module on purpose.
The probability functions read and mutate the Pydantic models defined
at the top, and every consumer (`api.sim`, `api.tickets`, `api.main`,
`api.tests.*`) imports the model and pipeline functions from
`api.model`.

A `api/probability.py` split was considered. It would force a circular
import (probability needs `Horse`/`Race`; the models need to be
re-exported for backwards compat) or a from-scratch rename of every
existing import. **Concrete extraction plan if the file grows further:**
move the edge-model section (`apply_edge_model` + `OWNERSHIP_PROXY_*`
+ `RACE_STABILITY_*` + the bucket constants, ~225 LOC starting around
the `# ---- edge model` divider) into `api/edge_model.py` because that
section reads `Horse.flags` / `Horse.steam_horse` after every other
pipeline step has run — so the import direction stays clean
(`edge_model` → `model`, never the other way). Defer until model.py
crosses 1500 LOC or the edge model gets a second consumer.
Module-docstring LOC note refreshed `1377 → 1374` this pass.

### `api/tickets.py` — 812 LOC (justify, inline note refreshed)

Candidate-pool construction (`_build_main_selections_classified`,
`_build_main_selections`, `_build_backup_selections`,
`_build_chaos_selections`), budget fitting (`_fit_to_budget`,
`_efficiency_ratio`), and Balanced/Safer/Upside scoring (`_Scored`,
`_score_and_select`, `_simulate_candidates`, `_compute_ticket_edge`,
`_generate_ticket_notes`, `_build_labeled_ticket`) all share the same
`legs: list[Race]`, `horse_index`, and `Ticket` plumbing. A
scoring-only split would force every internal helper to thread the
candidate pool through a new module boundary for no behavioral win.
Module-docstring LOC note refreshed `810 → 812` this pass after the
`_efficiency_ratio` docstring grew by two lines (see "Consistency
changes").

### `api/sources/twinspires.py` — 531 LOC (justify, inline note refreshed)

Adapter construction, JSON parsing, scratch diffing, the curl_cffi 403
fallback wrapper, and HTTP plumbing all read/write the same private
state (`_session_seeded`, `_owns_*_client`, `_last_odds_at`,
`_last_runners`) on the dataclass. Module-docstring LOC note refreshed
`526 → 531` this pass — the security pass added a five-line rationale
comment on the `__post_init__` curl_cffi auto-build branch.

### `api/sources/equibase.py` — 501 LOC (justify, no inline note)

Unchanged at 501 LOC. Adapter (`EquibaseAdapter`) and parsing
helpers (`parse_race_html` + the half-dozen `_parse_*` / `_find_*`
helpers) all share the soft-404 markers, the country-suffix regex, and
the `_table_header_cells` index. A parser-only split would force every
parser to take a `_table_header_cells` arg or recompute it; the marker
constants would have to be re-exported. Not worth the churn at 501
LOC.

### `web/components/TicketBuilder.tsx` — 537 LOC (justify, inline note refreshed)

The `TicketBuilder` → `BudgetPanel` → `TicketCard` tree shares
`legs`, `horsesById`, `dispositions`, and `simResultsById` props. The
sub-components are private to the file (only `TicketBuilder` is
exported); splitting them out would only shuffle imports without
changing the data flow. Inline LOC note refreshed `~553 → ~537` this
pass to match the actual current count after the prior pass's shared-
formatter extraction.

### Test files >500 LOC (justify)

- `api/tests/test_probability_model.py` — 1654 LOC. Mirrors
  `api/model.py`'s probability layer; one large file means the priors,
  blend, flags, movement, classification, and edge-model tests share
  one fixture set. A per-stage split would either duplicate fixtures or
  introduce a `conftest.py` indirection.
- `api/tests/test_main.py` — 800 LOC. The shared fixtures
  (`FakeEquibase`, `FakeTwinSpires`, `_client_with_overrides`,
  `_seed_cache`) were already extracted to `api/tests/conftest.py` by
  the prior pass; the remaining 800 LOC is per-route assertion code
  that shares no further structure with the smaller per-domain test
  files. Inline LOC note was already removed by the prior pass — no
  change this pass.
- `api/tests/test_tickets.py` — 656 LOC. Mirrors `api/tickets.py`;
  per-rule splits (selection / fit / scoring) would duplicate the
  shared `_build_legs` / `_make_horse` factories.

## Consistency changes made

- `api/tickets.py` — module-docstring LOC note refreshed
  `810 → 812`. The `_efficiency_ratio` function docstring previously
  read `Ranking-equivalent of ΔP/ΔCost — see ``spend-efficiency-formula.md``.`
  The cited research note does not exist on disk; the prior pass had
  stripped two `.aidlc/research/*.md` references from the
  module-level docstring but missed this one in the function-level
  docstring. Rewritten in place to spell out the rationale that the
  reference was standing in for ("within a single leg this is monotone
  in `fp`; the `n_leg / p_leg` factor lets the trim/add loops compare
  candidates across legs of different width").
- `api/main.py` — module-docstring LOC note refreshed `816 → 820`
  to match the current file after the security pass added the
  Cross-Origin-Resource-Policy rationale block.
- `api/model.py` — module-docstring LOC note refreshed `1377 → 1374`
  (the file lost three lines as the security pass tightened a comment
  block).
- `api/sources/twinspires.py` — module-docstring LOC note refreshed
  `526 → 531`.
- `web/components/TicketBuilder.tsx` — top-of-file LOC note
  refreshed `~553 → ~537` to match the current file. The previous
  cleanup-report explicitly noted this drift but left the comment
  unchanged; this pass acted on it.

## Things deliberately not touched (and why)

- `api/sources/twinspires.py` `poll_program` / `ScratchEvent` — only
  consumed by tests, no production caller. They are exposed in
  `__all__` and have full test coverage as a documented adapter API
  ready for the still-pending live-scratch wiring; deletion would
  silently drop tested behavior. Leave as documented public surface.
- `PICK5_DAY_LABELS` / `PICK5_PRODUCT_NAMES` / `PICK5_TRACK` exposed
  via `api/main.py.__all__` — only used inside `main.py` today, but
  the SSOT report explicitly designates them as the single source of
  truth for day-config and the `/api/pick5/days` self-describe route
  reads them. Removing from `__all__` would semantically downgrade them
  to internal config and silently un-document the SSOT designation.
- `web/lib/odds.ts:formatPercent` next to `web/lib/format.ts:pct` —
  they look like duplicates but are not. See "Duplicates consolidated"
  above for the kept-distinct rationale.
- `StaleBanner.tsx:fmt` next to `DayHeader.tsx:fmt` — same. See
  "Duplicates consolidated".

## Escalations

None. Every finding was either acted on (LOC notes refreshed, the
stale `_efficiency_ratio` reference rewritten) or justified inline + in
this report.
