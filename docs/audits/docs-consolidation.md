# Docs Consolidation Pass — 2026-04-28

Latest reconciliation of the documentation tree against current code,
running after the prior cascade (security → SSOT → error-handling →
cleanup) had each landed and after the F35 test-tightening fix moved
the suite from "375 passed, 1 skipped, 1 failed" to "376 passed, 1
skipped, 0 failed". Markdown only; no code changes.

## Repo shape (verified against current tree)

```
README.md
BRAINDUMP.md                  (customer voice; not touched)
docker-compose.yml
.env.example
.gitignore
api/                          FastAPI backend (model.py, main.py, sim.py,
                              tickets.py, refresh.py, validate.py, cache.py,
                              normalize.py + sources/{equibase,twinspires,
                              fixture,pick5}.py)
api/tests/                    conftest.py + 13 test modules
                              (incl. test_friday_e2e.py, test_stale_fallback.py)
web/                          Next.js App Router SPA
docs/audits/                  cleanup-report.md, error-handling-report.md,
                              security-report.md, ssot-report.md,
                              docs-consolidation.md (this file)
data/                         priors.json (committed) + .gitignored DBs
fixtures/pick5/               friday-card.json, friday-odds.json,
                              saturday-card.json, saturday-odds.json
```

Cross-checked: no `AIDLC_FUTURES.md`, no `kentuckyderby` adapter or
test, no `.aidlc/research/*` references in committed code, no stray
top-level docs.

## Files added

None. The audit roster (`cleanup`, `error-handling`, `security`,
`ssot`, `docs-consolidation`) already covers every distinct lens; an
"architecture overview" doc would only restate `BRAINDUMP.md` plus the
SSOT module-table.

## Files deleted

None. Each existing audit report is cited by inline comments at the
code sites it justifies (verified by grep — see inventory below); none
is redundant.

## Files rewritten in place

### `README.md`

The "Required configuration" section claimed `.env.example` "documents
every variable", then listed `DERBY_FRIDAY_DATE` /
`DERBY_SATURDAY_DATE` — which are read by `api/main.py:125-143` but
are **not** in `.env.example`. Reworded so the README matches the
shipped surface: variables that *are* in `.env.example` (`API_CORS_ORIGINS`,
`PICK5_DATA_MODE`, `API_BASE_URL`) are tagged as such, and the
`DERBY_*_DATE` overrides are tagged as "read by `api/main.py`, not in
`.env.example`". The regex anchoring claim (`^\d{4}-\d{2}-\d{2}$`) is
verified at `api/main.py:85`.

### `docs/audits/security-report.md`

The S11 verification block and the "Safe hardening implemented this
pass" footer both claimed `pytest api/tests` runs **375 passed, 1
skipped, 1 pre-existing failure**. That number was correct at
security-pass time but stale today — the error-handling pass that
followed tightened `test_403_without_fallback_raises` (F35) and the
suite is now **376 passed, 1 skipped, 0 failed**. Reworded both call
sites to give the post-cascade total and cite F35 for the chronology.
No finding text was changed.

### `docs/audits/ssot-report.md`

Same test-count drift: the report's posture line and the sanity-check
`grep` block both quoted "375 passed, 1 skipped, 1 failed". Tightened
the posture line to record the SSOT-pass-time total *and* the
post-cascade total (376 passed, 1 skipped) with a pointer to F35.
Added a one-line annotation under the sanity-check `grep` block so
the historical snapshot is preserved without contradicting current
state.

### `docs/audits/error-handling-report.md`

Three line-number drifts reconciled against current code:

- **F2** (`_safe_close`): `api/sources/twinspires.py:476` →
  `:478`. Updated in the findings table and in the per-finding detail.
- **F33** (TwinSpires 404 → None): `api/sources/twinspires.py:428` →
  `:432`. Updated in the findings table.
- **F33 detail body** range `:424–429` → `:429–434` to match the
  current `if getattr(resp, "status_code", 200) == 404:` block.

No finding semantics changed — these are pure code-position updates
after the security and cleanup passes added inline rationale comments
above each suppression site.

### `docs/audits/cleanup-report.md`

Verified accurate against current LOC (`wc -l`): `api/main.py` 820,
`api/model.py` 1374, `api/tickets.py` 812,
`api/sources/twinspires.py` 531, `api/sources/equibase.py` 501,
`web/components/TicketBuilder.tsx` 537,
`api/tests/test_probability_model.py` 1654,
`api/tests/test_main.py` 800, `api/tests/test_tickets.py` 656. The
post-pass test count `376 passed, 1 skipped` matches the current run.
No edits this pass.

## Statements removed because unverifiable

- `security-report.md` — "1 pre-existing failure" claim in the S11
  test-impact and footer (replaced with "0 failures, see F35 for the
  chronology").
- `ssot-report.md` — "375 passed, 1 skipped, 1 failed" as the *current*
  posture (kept as the SSOT-pass-time snapshot, augmented with the
  post-cascade total).
- `README.md` — ".env.example documents every variable" (it doesn't —
  the `DERBY_*_DATE` overrides are read directly by code).

## Inline-citation inventory (verified resolvable against current docs)

Every `F\d+` / `S\d+` / `error-handling-report` / `security-report`
/ `cleanup-report` / `ssot-report` cite in committed code resolves to
a section in the corresponding audit report (verified by grep across
`api/`, `web/`, `*.toml`, `*.mjs`):

| Cite                                             | Code site                                          |
| ------------------------------------------------ | -------------------------------------------------- |
| `cleanup-report.md` "Files still >500 LOC"       | `api/main.py:14`, `api/model.py:37,39`, `api/tickets.py:55`, `api/sources/twinspires.py:12`, `web/components/TicketBuilder.tsx:7` |
| `security-report.md` S2                          | `web/app/layout.tsx:11`                            |
| `security-report.md` S3                          | `api/main.py:387,549,637,685`, `api/tests/test_stale_fallback.py:9` |
| `security-report.md` S4                          | `api/main.py:573,590`                              |
| `security-report.md` S5                          | `api/sources/fixture.py:37`                        |
| `security-report.md` S11                         | `api/main.py:244`, `web/next.config.mjs:10`        |
| `security-report.md` S12                         | `api/pyproject.toml:34`                            |
| `error-handling-report.md` F1                    | `api/sources/pick5.py:96`                          |
| `error-handling-report.md` F2                    | `api/cache.py:129`, `api/sources/equibase.py:161`, `api/sources/twinspires.py:478` |
| `error-handling-report.md` F3                    | `api/main.py:386`                                  |
| `error-handling-report.md` F4                    | `api/refresh.py:59`                                |
| `error-handling-report.md` F5                    | `api/sources/twinspires.py:132`                    |
| `error-handling-report.md` F6                    | `api/cache.py:185`                                 |
| `error-handling-report.md` F8                    | `api/main.py:635,684`                              |
| `error-handling-report.md` F9                    | `api/sources/pick5.py:166`                         |
| `error-handling-report.md` F11                   | `api/normalize.py:78,86`                           |
| `error-handling-report.md` F12                   | `api/sources/pick5.py:105`                         |
| `error-handling-report.md` F13                   | `api/sources/twinspires.py:327`                    |
| `error-handling-report.md` F14                   | `api/sources/equibase.py:222`                      |
| `error-handling-report.md` F15                   | `api/sources/twinspires.py:493`                    |
| `error-handling-report.md` F16                   | `api/tickets.py:687`                               |
| `error-handling-report.md` F17                   | `api/main.py:567,579`, `web/lib/api.ts:47`         |
| `error-handling-report.md` F22                   | `api/model.py:458`                                 |
| `error-handling-report.md` F23                   | `api/model.py:715`                                 |
| `error-handling-report.md` F24                   | `api/tickets.py:639`                               |
| `error-handling-report.md` F32                   | `api/sources/fixture.py:134`                       |
| `error-handling-report.md` F33                   | `api/sources/twinspires.py:432`                    |
| `error-handling-report.md` F35                   | `api/sources/twinspires.py:268`, `api/tests/test_twinspires.py:304` |
| `ssot-report.md`                                 | `api/model.py:39`                                  |

No dangling cites surfaced. The lone broken pointer
(`api/sim.py:115` → `security-report S11`) that was carried as an
Escalation in the prior `docs-consolidation.md` revision was resolved
by the SSOT pass (the trailing clause is gone; the comment now reads
`"Bounds match the producer ranges in api.tickets."`). Verified at
`api/sim.py:115`.

## Intentional doc gaps left for future work

None. The roster is complete and every report covers a distinct lens:

- `cleanup-report.md` — code-quality (LOC budget, dead code, duplicates).
- `error-handling-report.md` — broad-catch / fallback / suppression
  contracts (F-series).
- `security-report.md` — trust boundaries, headers, redaction,
  request-bound bounds (S-series).
- `ssot-report.md` — single-source-of-truth designations and the diff
  against `b9d3ec8`.
- `docs-consolidation.md` — this file; reconciliation log between the
  reports and the code/config.

## Escalations

None. The single Escalation carried by the prior
`docs-consolidation.md` revision (`api/sim.py:115` →
`security-report S11`) was resolved by the SSOT pass; verified above.

## Verification

- `pytest api/tests` — **376 passed, 1 skipped** (current). The skip
  is the deferred `test_friday_pick5_simulate_golden_snapshot`,
  blocked on adding a `seed` parameter to `SimulateRequest`.
- `wc -l` confirms every LOC count cited in `cleanup-report.md`
  (drifts ≤3 lines are within the inline `~` approximation).
- `grep -RIn "AIDLC_FUTURES\|kentuckyderby\|KentuckyDerby\|\.aidlc/research"`
  → 0 hits in committed code; only narrative mentions inside the audit
  reports.
- Every `F\d+` / `S\d+` cite in the inline inventory above resolves to
  a section in the matching audit report.
- README.md deployment claims (`./data` mount, `next dev`,
  `uvicorn api.main:app`, `restart: unless-stopped`) verified against
  `docker-compose.yml`, `web/Dockerfile`, and `api/Dockerfile`.
- `.env.example` variables cross-checked against `docker-compose.yml`
  and code references in `api/main.py` and `api/sources/fixture.py`;
  the README's list now matches the documented surface (and flags the
  `DERBY_*_DATE` overrides as code-only).
