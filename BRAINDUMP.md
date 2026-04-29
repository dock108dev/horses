# BRAINDUMP.md — Phase: Friday-Morning Readiness

Today is **2026-04-28 (Tuesday)**.
Oaks is **2026-05-01 (Friday)**. Derby is **2026-05-02 (Saturday)**.
We have **~3 days** before live entries publish on Equibase, and **~3 days** to
prove the entire pipeline runs cleanly so race-morning is just "click the
button and get tickets."

---

## What this phase IS NOT

- Not building a real model. Priors are still hand-tuned constants in
  `data/priors.json`. No historical results ingest, no fitter, no backtest.
  That is a future phase.
- Not adding new endpoints, new UI screens, or new ticket strategies.
- Not refactoring. The wires work — we're proving they hold under realistic
  inputs.

If a task doesn't make Friday morning safer, it doesn't belong in this phase.

---

## Definition of "ready" (exit criteria)

By **Thursday night 2026-04-30** all of these must be green:

1. **Fixture E2E** — full workflow runs against fixtures, produces non-empty
   data, and matches a checked-in golden snapshot:
   `refresh card → refresh odds → simulate → build tickets`.
2. **Live E2E** — same workflow runs against real Equibase + TwinSpires for
   Friday's card, validates clean, and stores a real `last_good_card` in
   `data/odds_2026-05-01.db`.
3. **Stale-fallback proven** — after a successful live refresh, simulate
   Equibase being down (block the host or stub the adapter to raise) and
   confirm the API still returns the cached card with `stale=true` and a
   redacted error.
4. **Pre-warmed cache** — Friday's card committed to SQLite, so race morning
   is a re-fetch, not a cold start.
5. **iPad reachable** — the iPad on the LAN can hit `/api/health`,
   `/api/cards/friday`, and the SPA at `:3000` with no CORS errors.
6. **Runbook printed/saved** — race-morning steps fit on one screen and the
   operator does not have to think.

If any of these are red on Thursday night, fixture mode is the fallback —
the app must still produce tickets from the fixture card.

---

## Pre-flight test plan (runnable TODAY, no live data needed)

Everything in this section can run right now in fixture mode. Goal: prove
shape, behavior, and timing before Equibase publishes.

### A. Smoke (5 min)

```bash
# Bring up the stack in fixture mode.
PICK5_DATA_MODE=fixture docker compose up -d --force-recreate api web

# Health.
curl -fsS http://localhost:8000/api/health

# Both days, full workflow.
for day in friday saturday; do
  curl -fsS -X POST   "http://localhost:8000/api/cards/$day/refresh?source=fixture" | jq '.errors,.stale,(.data|length)'
  curl -fsS -X POST   "http://localhost:8000/api/odds/$day/refresh?source=fixture"  | jq '.errors,.stale,(.data|length)'
  curl -fsS -X POST   "http://localhost:8000/api/simulate/$day"                     | jq '.errors,.stale,(.data.tickets|length)'
  curl -fsS -X POST   "http://localhost:8000/api/tickets/$day/build"                | jq '.errors,.stale,(.data.variants|length)'
done
```

Expected for every line: `errors=[]`, `stale=false`, length > 0.

### B. Unit + integration suite

```bash
docker compose exec api pytest -q
```

Currently 12 test files under `api/tests/`. Must stay green. If any test
references live network, mark it `@pytest.mark.live` and skip by default.

### C. Golden snapshot test (NEW — write this)

Add `api/tests/test_friday_e2e.py` (or similar):

- Calls `load_card("friday")` + `load_odds_records("friday", ...)` + simulate
  + build_tickets via the in-process app (no HTTP, no docker) using the
  FastAPI `TestClient`.
- Asserts the response envelope shape, `errors=[]`, race count = 5, runner
  counts per leg, that `finalProbability` per race sums to 1.0 ± 0.01, and
  that `tickets.variants` is non-empty across `STANDARD_BUDGETS`.
- Optionally pickles a checked-in JSON of the simulate result so a future
  refactor that silently changes blend math fails this test loudly.

This is the single most important test we don't have yet.

### D. Stale-fallback test (NEW)

Add `api/tests/test_stale_fallback.py`:

- Pre-populate the SQLite cache with a known `last_good_card`.
- Replace `EquibaseAdapter.fetch_race` with a stub that raises.
- Assert `POST /api/cards/friday/refresh` returns `stale=true`,
  `source=cache`, `errors` non-empty, and `data` is the pre-populated card.
- Assert the redaction strips URLs and absolute paths from the error string.

### E. Timing dry run

```bash
PICK5_DATA_MODE=fixture time curl -fsS -X POST \
  "http://localhost:8000/api/simulate/friday" -d '{"n_iterations":50000}' \
  -H 'content-type: application/json' >/dev/null
```

Expected: well under 10s for 50k iterations on the Mac mini. If sim is
slower than that, file it but do not optimize this phase — fixture data is
synthetic and a real card may differ.

### F. iPad reachability (do this from the iPad, not the host)

- Open Safari → `http://mac-mini.local:3000` → confirm SPA loads.
- DevTools/console: hit `http://mac-mini.local:8000/api/health`.
- If CORS blocks, set `API_CORS_ORIGINS` in `.env` to include the actual
  origin Safari uses. The wildcard `*` is rejected at startup
  (`api/main.py:221`).

---

## Live cutover plan (when Equibase publishes — likely Wed 4/29 or Thu 4/30)

You'll know entries are up when `curl -fsS -I "https://www.equibase.com/static/entry/CD050126R08-EQB.html"` returns 200 with a body that doesn't contain "no data found" / "entries are not available".

### Step 1 — switch off fixture mode

Drop `PICK5_DATA_MODE=fixture` from the env (or leave the var unset). Restart
the api container. Fixture files stay mounted; they're the fallback if live
parsing breaks.

### Step 2 — refresh both days, capture output

```bash
for day in friday saturday; do
  curl -fsS -X POST "http://localhost:8000/api/cards/$day/refresh" | tee /tmp/card-$day.json | jq '.errors,.stale,(.data|length)'
done
```

Expected: `errors=[]`, `stale=false`, length=5 for each day.

If `errors` is non-empty, **diff against the fixture**. The most likely
failure modes (in order of probability):

1. **Equibase HTML shape drift** — `_find_entries_table` selector misses,
   `_parse_entries` returns empty horse list. Fix in
   `api/sources/equibase.py`. Re-run.
2. **TwinSpires program JSON shape drift** — affects odds, not card
   structure; per-leg failure is downgraded to a warning at
   `api/refresh.py:60`, so the card should still validate.
3. **Pick 5 sequence wrong** — `get_pick5_legs(2026, "friday")` returns
   `[8,9,10,11,12]` from the hardcoded table (`api/sources/pick5.py:44`).
   If Churchill changed the program, the scraper override at
   `pick5.py` step 2 catches it and logs a warning; verify the warning
   matches the actual track program.
4. **Pre-publication soft-404** on a single race — wait an hour, retry.

### Step 3 — refresh odds, sim, tickets against live card

Same loop as the fixture smoke, minus `?source=fixture`. Confirm:

- `/api/odds/friday/refresh` → `data` has 5 races, each with non-empty
  `runners`, `cached_at` is recent, `source=twinspires`.
- `/api/simulate/friday` with default iterations → `tickets` array is
  non-empty.
- `/api/tickets/friday/build` → `variants` covers STANDARD_BUDGETS.

### Step 4 — store the warm card

The successful refresh writes to `data/odds_2026-05-01.db`. Confirm:

```bash
docker compose exec api sqlite3 /data/odds_2026-05-01.db \
  "SELECT count(*) FROM cards WHERE validated=1;"
```

Should return ≥ 1. Now even if Equibase or TwinSpires goes down Friday
morning, we serve the cached card with `stale=true`.

### Step 5 — repeat Step 2–4 for Saturday

Same exact steps, `day=saturday`. Saturday's card may publish later than
Friday's; if so, leave it for Thursday night.

---

## Race-morning runbook (Friday 2026-05-01)

One-screen checklist. Operator is on the iPad; Mac mini is on and on the LAN.

```
1. Open SPA on iPad → http://mac-mini.local:3000
2. Tap Friday tab.
3. Tap "Refresh Card."          → expect green check, "Source: equibase+twinspires"
4. Tap "Refresh Odds."          → expect green check, runner odds visible
5. Tap "Run Sim."               → expect win-rate column populated
6. Enter budget + base unit.
7. Tap "Build Tickets."         → expect tickets with explanations
8. (As scratches happen) Tap "Refresh Odds" again before each leg's MTP < 2.
```

If anything goes red:

- `stale=true` with `errors` mentioning a leg → odds for that leg failed,
  the card is still cached. Tap Refresh Odds again in 60s.
- `data=[]` → live source has fully fallen over AND no cached card exists.
  This should not happen if Thursday-night warm-cache was done. Recovery:
  `ssh mac-mini`, `PICK5_DATA_MODE=fixture docker compose up -d
  --force-recreate api`, accept that you're betting on yesterday's
  fixture-shaped card. (This is the "we are screwed but not blank" path.)
- iPad shows nothing → `/api/health` from Safari devtools tells you whether
  it's the API, the network, or the SPA.

Phone numbers for the operator if shit breaks: N/A — this is a one-person
operation; the runbook above is the recovery plan.

---

## Things we are explicitly NOT doing this phase

- Real probabilistic model from past results. Priors stay as
  `data/priors.json` constants; the so-called "modelProbability" remains a
  re-labeled `currentOdds × race_type multiplier` (`api/model.py:332`).
- Beyer / pace / class / workouts / horse history — none of these are in
  the schema and we are not adding them this week.
- New scrapers (results pages, charts, BRIS).
- New ticket strategies. STANDARD_BUDGETS + Safer/Upside is what we run on
  Friday.
- LOC reduction or refactor of `api/main.py` (815 LOC) and `api/model.py`
  (1374 LOC). They work. Touch only if a bug forces it.

---

## Open questions to resolve BEFORE Thursday

1. Has the operator (Mike) actually opened the SPA on the iPad on the LAN
   yet? If not, do that today — discovering CORS / hostname problems
   Friday morning is not acceptable.
2. Is `data/` on the host the same volume the container writes to? Verify
   by checking `data/odds_2026-05-01.db` exists on the host after a live
   refresh. If not, the warm cache won't survive a container restart.
3. Where does the operator type the budget on race morning — directly in
   the SPA, or in Swagger? If SPA, has every numeric input been clicked
   on the iPad and not just the desktop browser?
4. What's the plan if the Mac mini reboots Friday morning? `docker compose`
   should `restart: unless-stopped` (already configured), but verify the
   actual auto-start by `sudo reboot` Wednesday.

---

## Suggested order of work for this phase

1. **Today (Tue 4/28)** — write the golden-snapshot test (C) and
   stale-fallback test (D). Run smoke (A), unit (B), timing (E).
2. **Wed 4/29** — verify iPad reachability (F). Reboot test the Mac mini.
   Check Equibase hourly; if entries publish, run Step 2 of Live Cutover.
3. **Thu 4/30** — if not done Wednesday, do live cutover for both days,
   confirm warm cache persists, walk the runbook on the iPad with the
   real card data.
4. **Fri 5/01 morning** — execute the runbook. Don't touch code.

Friday is for clicking buttons, not for fixing bugs.
