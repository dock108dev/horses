# ISSUE-001: Project scaffold — Python backend, Next.js frontend, Docker Compose

**Priority**: high
**Labels**: infra, phase-1
**Dependencies**: none
**Status**: implemented

## Description

Bootstrap the full project from zero (findings.md: every file must be created). Create `api/` Python package with `pyproject.toml` declaring FastAPI, httpx, curl-cffi, beautifulsoup4, pydantic, aiosqlite, uvicorn. Create `web/` Next.js 14 App Router project with `package.json`. Create `docker-compose.yml` with `api` service (port 8000) and `web` service (port 3000) on a shared Docker network so the frontend can reach the backend at `http://api:8000` and iPad can access at `http://mac-mini.local:3000`. Create `.env.example` documenting environment variables. Create skeleton `data/priors.json` with empty `race_type_priors` and `field_size_priors` objects (BRAINDUMP model v1 spec). Create `data/` directory for SQLite DB files.

## Acceptance Criteria

- [ ] `docker compose up` builds both services without error
- [ ] Next.js dev server accessible at http://localhost:3000
- [ ] Backend health endpoint GET /api/health returns 200 JSON
- [ ] `data/priors.json` exists with `race_type_priors` and `field_size_priors` keys
- [ ] `.env.example` documents all env vars needed by both services

## Implementation Notes


Attempt 1: Bootstrapped repo from zero: api/ FastAPI package (pyproject.toml with FastAPI/httpx/curl-cffi/bs4/pydantic/aiosqlite/uvicorn, main.py with GET /api/health, Dockerfile, .dockerignore), web/ Next.js 14 App Router scaffold (package.json, tsconfig, next.config.mjs, app/layout.tsx, app/page.tsx, Dockerfile, .dockerignore), docker-compose.yml wiring api:8000 + web:3000 on a shared bridge network with web reaching api at http://api:8000, .env.example documenting all vars for both services, data/priors.json skeleton with race_type_priors and field_size_priors, data/.gitkeep, expanded .gitignore.