# Docs consolidation pass — derby Pick 5

**Date:** 2026-04-28
**Scope:** every Markdown file outside `.aidlc/` (which is AIDLC tool state,
not project docs).

## Pre-pass inventory

| Path                                | Disposition |
| ----------------------------------- | ----------- |
| `BRAINDUMP.md` (root)               | **Kept untouched.** Customer voice; the contract for what the app must do. |
| `AIDLC_FUTURES.md` (root)           | **Deleted.** See below. |
| `docs/audits/cleanup-report.md`     | **Kept.** Cited from code. |
| `docs/audits/error-handling-report.md` | **Kept.** Cited from code. |
| `docs/audits/security-report.md`    | **Kept.** Cited from code and from `web/next.config.mjs`. |
| `docs/audits/ssot-report.md`        | **Kept.** Cited from `api/model.py` docstring. |
| `README.md`                         | **Added.** Root entry point did not exist. |

## Files added

### `README.md`

Root entry point. One paragraph on what the repo is, a `docker compose up`
quickstart with the env-var pointers, deployment basics (Mac mini on LAN /
Tailscale), and a pointer to `docs/`. Every claim is grounded in
`docker-compose.yml`, `.env.example`, the `Dockerfile`s, and
`api/main.py` (CORS reject, `DERBY_*_DATE` validation).

## Files deleted

### `AIDLC_FUTURES.md`

Auto-generated tooling artifact. Three reasons it had to go:

1. **Structure violation.** Lived at the repo root despite not being a
   customer-voice document or a `README`. The pass rules require the root
   to hold only `README.md` plus untouched product-vision files like
   `BRAINDUMP.md`.
2. **Unverifiable / contradictory claims.** Stated "Issues planned: 14;
   Issues implemented: 10" while `.aidlc/planning_index.md` reports
   "Completion: 0/14 (0.0%)". One of the two had to be wrong, and neither
   is needed at the root.
3. **Pointers to nonexistent files.** Recommended reviewing
   `ARCHITECTURE.md`, `DESIGN.md`, and an "optional `ROADMAP.md`" — none
   of which exist in the repo. That is the textbook "no placeholder
   docs" violation.

The information that was load-bearing (audit-report pointers) is captured
in the new `README.md` "Documentation" section.

## Files consolidated

None. The four `docs/audits/*.md` reports are non-overlapping (cleanup,
error-handling, security, SSOT) and each is referenced by inline comments
at distinct code sites. Merging them would break those pointers and
flatten the cleanly separated lenses.

## Statements removed because unverifiable

This pass removed the entirety of `AIDLC_FUTURES.md`. Specific claims
that could not be verified from the codebase or that contradicted other
authoritative sources:

- "Issues planned: 14, implemented: 10, verified: 0, failed: 0." Could
  not be reconciled with `.aidlc/planning_index.md` ("Completion: 0/14").
- "Branch: unknown / Project type: unknown." `docker-compose.yml`,
  `pyproject.toml`, and `package.json` clearly identify this as a
  FastAPI + Next.js repo; the "unknown" placeholders are AIDLC default
  output, not facts about the project.
- Recommendations to "Review and update supporting docs (`README.md`,
  `ARCHITECTURE.md`, `DESIGN.md`, optional `ROADMAP.md`)." Three of the
  four files do not exist; the recommendation is generic AIDLC
  boilerplate rather than project-specific guidance.

The four audit reports were read end-to-end against current code.
Spot-checks done this pass:

- `api/main.py` (608 lines) ↔ cleanup-report "606 LOC" claim — within
  rounding of the report's own "~" qualifier; the docstring at
  `api/main.py:11` and the cleanup-report section refresh together.
- `api/model.py` (561 lines) ↔ cleanup-report "559 LOC" — same.
- `api/sources/twinspires.py` (521 lines) ↔ cleanup-report "520 LOC" —
  same.
- All `docs/audits/...` paths cited from code resolve to the actual
  files at the cited sections (`security-report.md` S1/S2/S3,
  `error-handling-report.md` F1–F21 / E1, `cleanup-report.md` "Files
  still >500 LOC", `ssot-report.md`).
- `_redact_exc` in `api/main.py:76` matches the `security-report.md` S3
  "URL/path stripping" description.
- The CORS wildcard reject at `api/main.py:196` matches
  `security-report.md` S1.
- The `extra="forbid"` Pydantic configs on `SimulateRequest` /
  `TicketsRequest` (`api/main.py:476, 484`) match
  `error-handling-report.md` F17.

No statements removed from the four audit reports — they are
code-grounded as written.

## Intentional doc gaps

### No `ARCHITECTURE.md` / `DESIGN.md`

**Reason:** module docstrings already carry the rationale. `api/main.py`,
`api/model.py`, `api/cache.py`, `api/normalize.py`, `api/refresh.py`,
`api/validate.py`, `api/sim.py`, `api/tickets.py`, `api/sources/*.py`,
and the four web `lib/`/`components/` files each open with a header
docstring that explains responsibility and non-obvious choices. A
separate architecture doc would either restate those (drift risk) or be
strictly more abstract (no marginal value for a personal app of this
size). The README points at `BRAINDUMP.md` for product intent and
`docs/audits/` for design rationale, which together cover what an
ARCHITECTURE doc would.

**What would bring this back into scope:** a second contributor joining,
or the codebase doubling in size such that the audit reports stop being
sufficient to onboard. Until then, no doc gap.

### No `ROADMAP.md`

**Reason:** `BRAINDUMP.md` already contains the phased build order
("Phase 1 — Data Pipeline" through "Phase 4 — Ticket Builder") with
acceptance criteria per phase. The state of those phases is observable
from the code (Phases 1–4 have shipped per the audit reports' "274
passing tests" baseline). A separate ROADMAP would duplicate
`BRAINDUMP.md` and rot first.

**What would bring this back into scope:** a public-facing release
beyond personal use, where outsiders need to know what's planned without
reading the customer-voice brief.

### No frontend-specific README

**Reason:** `web/package.json` scripts are conventional Next.js
(`dev`/`build`/`start`/`lint`); `next.config.mjs` is commented inline
(rewrite + security headers); component files carry their own purpose
in their JSX. The root README's "Run locally" covers the only commands
an operator needs.

## Verification

- `ls` of repo root after this pass:
  `README.md`, `BRAINDUMP.md`, `api/`, `data/`, `docker-compose.yml`,
  `docs/`, `web/` — plus the dotfiles `.env.example`, `.gitignore`,
  `.aidlc/`, `.pytest_cache/`, `.ruff_cache/`. No stray `.md` files.
- `docs/` contains only `audits/` (4 reports + this consolidation
  report).
- Every inline comment in code that points at `docs/audits/*` still
  resolves: spot-checked `S1`/`S2`/`S3` in `security-report.md`, `F1`–
  `F21` plus `E1` in `error-handling-report.md`, "Files still >500 LOC"
  in `cleanup-report.md`, and the SSOT report header anchor.
- README claims verified against `docker-compose.yml`,
  `.env.example`, `api/main.py`, `api/Dockerfile`, `web/Dockerfile`,
  and `web/next.config.mjs`.

## Escalations

None. Every finding in this pass was either acted on (`README.md` added,
`AIDLC_FUTURES.md` deleted) or justified above with the concrete trigger
that would bring it back into scope. No bare TODOs left in code; no
"out of scope" deferrals.
