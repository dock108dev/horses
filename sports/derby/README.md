# Derby Pick 5

Personal iPad browser app for analyzing the Friday (Oaks) and Saturday (Derby)
Pick 5 sequences at Churchill Downs. Pulls race cards, morning-line, and live
odds from public sources, runs Monte Carlo simulations, and builds budget-bound
A/B/chaos tickets. The app does not place bets. See `BRAINDUMP.md` for the
product brief.

The codebase is two services wired together by Docker Compose:

- `api/` — FastAPI backend. Source adapters (Equibase, TwinSpires,
  KentuckyDerby), per-day SQLite cache for stale-fallback, post-refresh
  validation, blend/flag probability layer, Monte Carlo sim, ticket builder.
- `web/` — Next.js (App Router) frontend. iPad-targeted UI for refreshing
  the card, tagging horses, running simulations, and viewing tickets. Calls
  the backend through a `/api/:path*` rewrite.

## Run locally

```sh
cp .env.example .env
docker compose up
```

Open `http://localhost:3000` (or `http://mac-mini.local:3000` from the iPad
on the same LAN). The backend is reachable directly at port 8000; the SPA
proxies `/api/*` through Next.js.

`pytest api/tests` runs the backend test suite. `npx tsc --noEmit` from
`web/` typechecks the frontend.

### Required configuration

`.env.example` documents every variable. The two that matter most:

- `API_CORS_ORIGINS` — explicit comma-separated origin allow-list.
  `*` is rejected at startup (see `docs/audits/security-report.md` S1).
- `DERBY_FRIDAY_DATE` / `DERBY_SATURDAY_DATE` — override the defaults
  (`2026-05-01` / `2026-05-02`) when targeting a different year. Must
  match `YYYY-MM-DD`.

## Deploy

The intended deployment is a Mac mini on the user's LAN, optionally exposed
over Tailscale. Both Docker images run with `restart: unless-stopped` and a
mounted `./data` volume that persists per-day SQLite snapshots.

The `web` Dockerfile runs `next dev` for the operator's HMR ergonomics; the
`api` Dockerfile runs `uvicorn` against `api.main:app`. There is no auth, no
PII, no money flow — the trust boundary is the LAN/Tailscale perimeter.
Wider exposure requires the steps in `docs/audits/security-report.md`
"Remediation roadmap".

## Documentation

- `BRAINDUMP.md` — product brief, customer voice. Authoritative source
  for what the app must do.
- `docs/audits/` — code-quality, error-handling, security, and SSOT
  audit reports. Each one is cited by inline comments at the code sites
  they justify; treat them as the rationale archive for non-obvious
  decisions in the codebase.
- `docs/audits/docs-consolidation.md` — most recent docs review.
