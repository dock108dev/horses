# SSOT Enforcement Report — 2026-04-28 (Friday-Morning Readiness pass)

Single-source-of-truth pass driven by the working-tree diff against
`origin/main` (the most recent commit, `b9d3ec8`). The branch
direction has shifted: `BRAINDUMP.md` was rewritten end-to-end from
the "API/data-loading recovery" plan into a **Friday-Morning
Readiness** phase with explicit "what this phase IS NOT" guardrails.
The pytest configuration grew a `live` marker that is deselected by
default. Test fixtures were extracted from `api/tests/test_main.py`
into a new `api/tests/conftest.py`. Two new fixture-driven tests
appeared (`test_friday_e2e.py`, `test_stale_fallback.py`).

This pass deletes everything the branch *proves* is obsolete and
fixes every dangling reference the prior audit reports
(`cleanup-report.md`, `error-handling-report.md`, `security-report.md`,
`docs-consolidation.md`) flagged but could not act on.

Test posture after the pass: `pytest api/tests` from the repo root →
**375 passed, 1 skipped, 1 failed** at SSOT-pass time. The single
failure (`test_twinspires.py::test_403_without_fallback_raises`) was
pre-existing on `b9d3ec8` and unrelated to this pass — verified by
running the same command against a clean stash of the working tree
before edits. The error-handling pass that immediately followed
tightened that test (see `docs/audits/error-handling-report.md` F35),
so the **post-cascade total is 376 passed, 1 skipped** and the suite
has been clean since. The skip is the deferred
`test_friday_pick5_simulate_golden_snapshot` (its `@pytest.mark.skip`
already documents the deferral reason: `SimulateRequest` exposes no
seed parameter, so the snapshot would be flaky).

---

## Diff scan — what the branch is becoming

| Diff signal                                                    | What it implies                                                                                         |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `BRAINDUMP.md` rewritten as "Phase: Friday-Morning Readiness"  | Customer-voice spec is now wires-prove-out, not refactor or model-build. New phase has no Phase numbers. |
| `api/tests/conftest.py` added with shared fixtures              | `conftest.py` is the SSOT for test fixtures (`FakeEquibase`, `FakeTwinSpires`, `_full_card`, `_seed_cache`, `_client_with_overrides`, `tmp_data_dir`, `client`). |
| `api/tests/test_main.py` re-imports those fixtures by name      | The local definitions in `test_main.py` are gone. Future test modules import from `api.tests.conftest`.    |
| `api/pyproject.toml` adds `markers = ["live: …"]` + `addopts = "-m 'not live'"` | Tests that hit real external services must declare `@pytest.mark.live`; they are deselected by default.   |
| `api/tests/test_friday_e2e.py` (new)                            | BRAINDUMP §C in code: fixture-driven E2E refresh→odds→sim→tickets through `TestClient`.                 |
| `api/tests/test_stale_fallback.py` (new)                        | BRAINDUMP §D in code: stale-fallback envelope shape + `_redact_exc` URL/path scrubbing assertions.       |

---

## Final SSOT modules per domain (post-pass)

| Domain                                       | SSOT module                                                                                                          |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Pick 5 day labels / dates / track            | `api/main.py` (`PICK5_DAY_LABELS`, `DEFAULT_DERBY_DATES`, `PICK5_TRACK`, `PICK5_PRODUCT_NAMES`)                       |
| Pick 5 leg sequence resolution               | `api/sources/pick5.py` (`PICK5_SEQUENCES`, `get_pick5_legs`)                                                         |
| Pick 5 leg roles + count                     | `api/model.py` (`PICK5_LEG_ROLES`, `PICK5_LEG_COUNT`, `select_pick5_legs`)                                            |
| Pydantic data models (Race / Horse / OddsSnapshot) | `api/model.py`                                                                                              |
| Probability layer (priors → blend → flags → movement → classification → edge) | `api/model.py`                                                          |
| Odds parsing / probability normalization / horse merging | `api/normalize.py`                                                                                       |
| Refresh orchestration (build_card / poll / merge) | `api/refresh.py`                                                                                                |
| Post-refresh validation                      | `api/validate.py`                                                                                                    |
| Per-day SQLite cache                         | `api/cache.py`                                                                                                       |
| Source adapters                              | `api/sources/equibase.py`, `api/sources/twinspires.py`, `api/sources/fixture.py`                                      |
| Monte Carlo simulation                       | `api/sim.py`                                                                                                         |
| Ticket builder                               | `api/tickets.py`                                                                                                     |
| FastAPI surface (routes + envelope)          | `api/main.py` (`Envelope`, `app`)                                                                                    |
| Frontend type contract                       | `web/lib/types.ts`                                                                                                   |
| Frontend API client                          | `web/lib/api.ts`                                                                                                     |
| Shared spinner UI                            | `web/components/Spinner.tsx`                                                                                         |
| Shared formatters (`pct`/`num`/`money`)      | `web/lib/format.ts`                                                                                                  |
| Product brief / authoritative behavior spec  | `BRAINDUMP.md`                                                                                                       |
| **Test fixtures (stub adapters, factories)** | **`api/tests/conftest.py`** *(new this pass — see Diff-prioritized deletions)*                                       |
| **Live-vs-stub test classification**         | **`@pytest.mark.live` (registered in `api/pyproject.toml`); default test run is `-m 'not live'`**                    |
| **Pick 5 fixture data (offline workflow)**   | **`fixtures/pick5/*.json` (`friday-card.json`, `friday-odds.json`, `saturday-card.json`, `saturday-odds.json`)**     |

The pre-existing SSOTs were re-verified against the post-stash tree.
The KentuckyDerby adapter (`api/sources/kentuckyderby.py`,
`api/tests/test_kentuckyderby.py`) remains gone; no caller references
survived. The previous SSOT pass already established this and no diff
in this branch tries to walk it back.

---

## Diff-prioritized deletions

| Deleted asset                                                           | Reason from diff / SSOT                                                                                                                                                                                                                                                                                                                                                                  | SSOT replacement                                                                                                       |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `AIDLC_FUTURES.md` (40 LOC, tracked file)                               | Auto-generated AIDLC artifact pointing future runs at `docs/audits/*` — duplicates README's documentation section. The previous SSOT report (this file's prior revision) recorded the intent to keep it out of git going forward; commit `b9d3ec8` re-added it anyway. The new BRAINDUMP guardrail "If a task doesn't make Friday morning safer, it doesn't belong in this phase" forces the deletion now. The file's only durable claim is the audit-report list, which `README.md` already enumerates. | `README.md` "Documentation" section + `docs/audits/*.md`                                                               |
| Local fixture / stub-adapter definitions in `api/tests/test_main.py` (~140 LOC) | Already deleted by the working-tree diff — extracted into `api/tests/conftest.py` and re-imported by name. This pass *records* the SSOT designation: future test modules must import shared stubs from `conftest`, not redefine `FakeEquibase` / `FakeTwinSpires` / `_full_card` / `_seed_cache` per file. (`test_friday_e2e.py` and `test_stale_fallback.py`, both added this branch, already do this correctly.) | `api/tests/conftest.py`                                                                                                |
| `See security-report S11.` clause at `api/sim.py:115`                   | The previous SSOT pass left this as the lone open Escalation: `S11` was a finding in the prior (now-deleted) `security-report.md` revision; the re-authored report only has S1..S10, so the cite has been broken since `b9d3ec8` was committed. The rationale sentence ("Bounds match the producer ranges") is self-explanatory. Replaced with an in-tree pointer to `api.tickets`, which is where the producer ranges actually live. | Inline rationale at `api/sim.py:115` now reads "Bounds match the producer ranges in `api.tickets`."                    |
| Two `.aidlc/research/*.md` rationale comments in `api/tests/test_friday_e2e.py` (lines 19 and 25) | `.aidlc/` is gitignored (`.gitignore:42`). The cited files (`fixture-friday-runner-counts.md`, `standard-budgets-and-variant-count.md`) only exist in the local AIDLC working directory and are unreachable from any clean checkout — exactly the dangling-reference shape the previous cleanup pass scrubbed (it stripped four such pointers from `api/model.py`, two from `api/tickets.py`, and one each from `api/sim.py`, `api/cache.py`, `api/normalize.py`, and `web/lib/odds.ts`). The new test reintroduced two of them; this pass strips them and points the comments at the durable on-disk SSOTs they ultimately read from. | Inline comments at `api/tests/test_friday_e2e.py:19,25` now cite `fixtures/pick5/friday-card.json` and `api.tickets.STANDARD_BUDGETS`. |

---

## Reference-stripping (deleted-asset / stale-phase pointers removed)

### User-facing fixes (the dead reference would have been seen by a reader)

- `docs/audits/security-report.md` S8 — body cited `BRAINDUMP "Phase 10
  — Swagger/API cleanup"`. The new BRAINDUMP has no numbered phases at
  all; the document is structured around the single
  Friday-Morning-Readiness phase with prose sub-headings. Rewrote the
  S8 justification to ground the kept-as-is decision in the *current*
  BRAINDUMP language ("Open questions" item 3 leaves the budget-entry
  workflow open between SPA and Swagger; the race-morning runbook
  expects `/api/health` to be reachable directly) instead of citing a
  phase header that no longer exists.
- `docs/audits/security-report.md` S8 — line range cite for the
  OpenAPI test was `api/tests/test_main.py:805-810`. The conftest
  extraction shifted the file from 932 LOC to 800 LOC and the test
  itself to line 673. Updated to `:673-680`.
- `docs/audits/cleanup-report.md` "Test files >500 LOC" — entry for
  `test_main.py` listed `932 LOC` and described an inline-LOC-note
  refresh that had been overtaken by the conftest extraction. Updated
  to `800 LOC` and rewrote the rationale to match the new shape (the
  shared fixtures *did* get extracted, into `conftest.py`, by the
  pass that this report describes).

### Inline rationale-comment cleanup

- `api/sim.py:115` — `See security-report S11.` clause dropped (see
  Diff-prioritized deletions row above for the full justification).

### Reports left as-is, with rationale

- `docs/audits/cleanup-report.md` opens "Code-quality cleanup pass on
  the post-recovery branch." That sentence is a date-stamped historical
  description of the pass that ran *before* the new BRAINDUMP landed.
  Rewriting it to "the Friday-Morning-Readiness branch" would mis-
  attribute work that completed under the prior phase. Left alone.
- `docs/audits/error-handling-report.md` opens with "F32–F34 ... were
  introduced in the API/data-loading recovery branch." Same call:
  historical, factual, and tied to specific finding IDs.
- `docs/audits/docs-consolidation.md` "Escalations" section about
  `api/sim.py:115` is now obsolete — this pass acted on the
  escalation. Left in place because it correctly records the
  chronology (the docs-only pass could not edit Python source). The
  fix is documented in this report; the docs-consolidation entry
  remains accurate as a description of the gap that existed at the
  time.
- `docs/audits/ssot-report.md` "Escalations" section in the *previous*
  revision called out the same `api/sim.py:115` gap — replaced by
  this whole report; the old escalation no longer exists.

---

## Risk log: code intentionally retained

These would have been candidates to delete on a more aggressive pass
but were kept with concrete justification.

### `api/normalize.py` — kept (unchanged from prior pass)

Six callers (`api/refresh.py`, `api/validate.py`,
`api/sources/fixture.py`, three test modules) read it; folding into
`api/model.py` would push that file past 1700 LOC and force a
circular `model ⇄ normalize` graph. The duplication inside
`_renormalize` is intentional and called out in-place.

### `api/refresh.py` — kept (unchanged from prior pass)

`api/main.py` could absorb `build_card` / `poll_pick5_odds` /
`races_with_latest_odds` directly. Kept separate because it's where
all three source adapters meet, it is pure-functional, and its tests
don't need the `app`/`Envelope` fixtures.

### `data/priors.json` — kept (explicit BRAINDUMP scope)

The new BRAINDUMP "What this phase IS NOT" item 1 keeps `data/priors.json`
as hand-tuned constants on purpose: *no* historical results ingest,
*no* fitter, *no* backtest until a future phase. The probability
pipeline at `api/model.py` reads it via `load_priors()` and the
`apply_historical_priors` step. The constants therefore satisfy the
"production usage proven" SSOT bar and are not dead code, even though
they don't yet have a fitter. (Note: tests that exercise
`load_priors()` rely on cwd being the repo root because the
`DEFAULT_PRIORS_PATH` is computed relative to cwd; running them from
inside `api/` fails. Documented for the operator; not in scope to
restructure here.)

### `api/sources/twinspires.py` `poll_program` / `ScratchEvent`

Only consumed by tests. Documented public surface ready for the
still-pending live-scratch wiring. Kept (same justification as the
prior cleanup pass).

### `PICK5_DAY_LABELS` / `PICK5_PRODUCT_NAMES` / `PICK5_TRACK`

Exposed via `api/main.py.__all__`. Used today only inside `main.py`,
but `/api/pick5/days` reads them and the SSOT designation is the
durable contract. Kept (same justification).

### `web/lib/format.ts`, `web/components/Spinner.tsx`

Established by the prior cleanup pass as the canonical home for
formatters and the spinner respectively. No diff in this branch
duplicates either; both retained as SSOTs.

---

## Sanity check — no dangling references

```
git ls-files AIDLC_FUTURES.md                       → (no output, file deleted)
grep -RIn "AIDLC_FUTURES"                           → only this report + ssot-report's
                                                       prior-pass narrative + docs-consolidation
                                                       (descriptive, not links)
grep -RIn "kentuckyderby\|KentuckyDerby"            → 0 hits in code/docs (unchanged)
grep -RIn "security-report\.md S11\|security-report S11" → 0 hits in code; only this report
grep -RIn "\.aidlc/research" --glob "!.aidlc/**"    → 0 hits in committed code
grep -RIn "BRAINDUMP \"Phase 10"                    → 0 hits
grep -n "Phase 10" docs/audits/                     → 0 hits
ls docs/audits/                                     → cleanup-report.md
                                                       docs-consolidation.md
                                                       error-handling-report.md
                                                       security-report.md
                                                       ssot-report.md
ls api/sources/                                     → equibase.py fixture.py
                                                       pick5.py twinspires.py
                                                       __init__.py
ls api/tests/                                       → conftest.py
                                                       test_cache.py test_equibase.py
                                                       test_friday_e2e.py test_main.py
                                                       test_model.py test_normalize.py
                                                       test_pick5.py test_probability_model.py
                                                       test_sim.py test_stale_fallback.py
                                                       test_tickets.py test_twinspires.py
                                                       test_validate.py
pytest api/tests   (cwd=repo root)                  → 375 passed, 1 skipped, 1 failed *
                                                       (post-cascade: 376 passed, 1 skipped after the
                                                        error-handling pass tightened F35)
```

\* The single failure
(`test_twinspires.py::test_403_without_fallback_raises`) is
pre-existing on `b9d3ec8` and is unrelated to this pass; verified by
running the same command on a clean working-tree stash before edits.

A negative test for "AIDLC_FUTURES.md must not be reintroduced" was
considered and skipped: the rule is environmental (an AIDLC tool
re-creates it) rather than a code-import concern, and adding a test
for it would commit the project to *never* re-adding the file even if
the workflow changes direction. The README + this report are the
durable record.

---

## Escalations

None. Every finding was either acted on (file deleted, comment
stripped, line-range corrected, phase reference rewritten) or
justified inline + here. The single Escalation carried by the prior
SSOT pass (`api/sim.py:115` `security-report S11`) has been resolved
by this one.
