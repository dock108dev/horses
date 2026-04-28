# Docs Consolidation Pass — 2026-04-28

Reconciled the documentation tree with current code after the SSOT,
security, error-handling, and cleanup passes had each finished.
Markdown only; no code changes.

## Repo shape (verified)

- Root: `README.md`, `BRAINDUMP.md` (customer-voice; not touched).
- `/docs/audits/`: `cleanup-report.md`, `error-handling-report.md`,
  `security-report.md`, `ssot-report.md`, plus this file.
- Two services in `api/` and `web/` wired by `docker-compose.yml`; data
  fixtures in `fixtures/pick5/`.
- No stray top-level docs, no `AIDLC_FUTURES.md`, no
  `kentuckyderby` adapter or test.

## Files added

- `docs/audits/docs-consolidation.md` (this file).

## Files deleted

None this pass. The four existing audit reports each cover a distinct
lens (cleanup, error-handling, security, SSOT) and are cited by inline
comments at the code sites they justify; none is redundant.

## Files rewritten in place

### `README.md`

- Required-configuration list said "the two that matter most" but
  enumerated three; reworded and added `API_BASE_URL` (which `.env.example`
  documents and `docker-compose.yml` consumes) so the README matches the
  shipped variable surface.
- Documentation section listed only "code-quality, error-handling, and
  SSOT" reports — `security-report.md` exists on disk but was missing
  from the README. Added it, plus a pointer to this consolidation log.

### `docs/audits/ssot-report.md`

- "Reference-stripping" section claimed `security-report.md` and
  `docs-consolidation.md` were deleted from the repo. That was true at
  SSOT-pass time (17:30) but a follow-up security pass at 17:38
  re-authored `security-report.md`, and this pass re-creates the
  consolidation log. Rewrote the section to record the chronology and
  to flag that the security pass's inline citations (`security-report
  S1..S5` from `api/main.py`, `api/sources/fixture.py`) are valid
  against the current file, not dangling.
- Sanity-check `grep` block claimed zero hits for `security-report.md`
  and `docs-consolidation.md`. That snapshot is no longer current
  (pointers exist again now that the files exist again). Added a note
  below the grep block clarifying the historical scope so the report
  stays internally consistent.
- Inline-comment-cleanup entry for `api/sim.py:96` (`security-report
  S11`) said the reference was "removed". A short-form
  `security-report S11` reference still exists at `api/sim.py:115`
  inside the `TicketSimulationResult` bounds comment. Tightened the
  entry to describe what was dropped vs. what remained, and added an
  Escalation (below) for the surviving stale pointer.
- Added `## Escalations` entry for `api/sim.py:115`.

### `docs/audits/error-handling-report.md`

- F34 cited `web/components/SimulationSummary.tsx:25–37` and
  `TicketBuilder.tsx:52–67` for the formatter NaN guard. The cleanup
  pass moved the formatters to `web/lib/format.ts`; the cited line
  ranges no longer house formatters and the claimed inline comments
  were never present at those sites. Re-pointed F34 at
  `web/lib/format.ts:6–24` and rewrote the prose so the rationale is
  attributed to the shared module's docstring (which already captures
  the NaN/Infinity/null contract), not to per-component cites.
- Top-of-report summary item, "Categorization → Needs documentation"
  section, and "Verification" section all had to be tightened to match
  the new F34 location and to stop claiming inline F34 cites that
  don't exist.

### `docs/audits/cleanup-report.md`

- "Files still >500 LOC" entry for `TicketBuilder.tsx` listed `553
  LOC`; current file is `537 LOC` (the formatter extraction trimmed it
  after the inline `~553` note was written). Updated the headline LOC
  and added a one-sentence note acknowledging the inline drift so the
  inline approximation `~553` and the report's `537` no longer look
  like they contradict each other.
- "Consistency changes made" entry for the same file noted the LOC
  refresh as `544 → 553`; appended `, since drifted to 537 after the
  formatter extraction` so the post-pass count is documented.

## Statements removed because unverifiable

- `ssot-report.md` "Reference-stripping" header copy implying the
  `security-report.md` deletion was permanent — it isn't, the file is
  back. Replaced with a chronological description.
- `ssot-report.md` sanity-check `grep` hits of `0` for
  `security-report.md` and `docs-consolidation.md` — both files now
  exist and are referenced; left the grep block as a snapshot but
  added a clarifying note.
- `error-handling-report.md` F34 line ranges
  (`SimulationSummary.tsx:25–37`, `TicketBuilder.tsx:52–67`) — those
  lines no longer house formatters.
- `error-handling-report.md` claim that "inline comments were added at
  the F32 / F33 / F34 sites" — verified: F32 comment exists at
  `api/sources/fixture.py:134`, F33 comment exists at
  `api/sources/twinspires.py:427`, but no F34 comment exists in the
  components or in `web/lib/format.ts`. Restricted the claim to F32
  and F33; described F34's documentation home (the format.ts module
  docstring) explicitly.

## Intentional doc gaps left for future work

None. Every report covers a single lens and the audit roster is small
enough that a separate "architecture overview" doc would only
duplicate what `BRAINDUMP.md` and the audit reports already say.

## Escalations

### `api/sim.py:115` — broken inline reference to `security-report S11`

The `TicketSimulationResult` bounds comment cites `security-report
S11`. The current `docs/audits/security-report.md` only contains
S1..S10; S11 lived in the prior (deleted) revision and was about
Pass-2 score-field bounds — the re-authored report does not have an
equivalent finding ID. The rationale sentence in the comment ("Bounds
match the producer ranges") is self-explanatory and remains correct;
only the trailing pointer is broken.

The SSOT report (now updated) records the chronology — an earlier
removal pass dropped the full-path version of the same pointer from
`api/sim.py` and `api/model.py:99`, but a short-form variant at
`api/sim.py:115` survived. The docs-only pass cannot edit Python
source.

**Smallest concrete next action**: in `api/sim.py:115`, drop the
trailing `See security-report S11.` clause. The surrounding rationale
already documents the constraint.

**Owner**: app maintainer (single-developer project).

## Verification

- `wc -l` confirmed the LOC counts for every file referenced in the
  cleanup report. Drifts ≤3 lines (`api/main.py`: 815 vs. 816,
  `api/model.py`: 1374 vs. 1377, `api/tickets.py`: 810 vs. 812,
  `api/tests/test_main.py`: 931 vs. 932) are within the inline `~`
  approximation and were not edited. The one meaningful drift
  (`TicketBuilder.tsx`: 537 vs. 553) was reconciled in the cleanup
  report.
- `grep` confirmed every inline `S{n}` / `F{n}` cite in `api/`,
  `web/`, `.env.example`, `docker-compose.yml` resolves to a section
  in the corresponding audit report — except `api/sim.py:115`, which
  is now tracked under Escalations.
- Every audit report's date / test-count line (`373 passed`) was
  verified consistent across `cleanup-report.md`, `security-report.md`,
  `ssot-report.md`, and `error-handling-report.md`.
- `README.md` deployment claims (`./data` mount, `next dev`,
  `uvicorn api.main:app`) verified against `docker-compose.yml`,
  `web/Dockerfile`, and `api/Dockerfile`.
- `.env.example` variables verified against
  `docker-compose.yml` and code references in `api/main.py` and
  `api/sources/fixture.py`.
