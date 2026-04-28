
# BRAINDUMP.md — Derby Pick 5 API/Data Loading Recovery

## Current state

The Derby Pick 5 app shell is up, navigation works, and the Friday/Saturday routes render.

But the actual workflow is dead:


## Important correction

There are multiple Pick 5 sequences across the cards both days.

So the app model cannot be:

```text
Friday = Kentucky Oaks Pick 5
Saturday = Kentucky Derby Pick 5
```

- Friday opens.
- Saturday opens.
- `Refresh Card` does not load a card.
- `Refresh Odds` does not load odds.
- `Run Sim` has nothing to run against.
- `Build Tickets` has no usable card/odds/sim state.
- UI still says:
  - `Last card refresh: never`
  - `Last odds refresh: never`
  - `Source: —`
  - `No card loaded yet — tap Refresh Card.`
- Swagger/API is either blank or hanging on most options.

This should be handled as a backend/API/data contract problem first. Do not start polishing the UI until the data path is proven end-to-end.

---

# Goal

Get one complete day working end-to-end:

1. App opens Friday or Saturday.
2. User clicks `Refresh Card`.
3. Card data appears.
4. User clicks `Refresh Odds`.
5. Odds appear and are associated to the right horses/races.
6. User clicks `Run Sim`.
7. Sim results are visible and tied to the loaded card.
8. User enters budget/base unit.
9. User clicks `Build Tickets`.
10. Tickets are produced, priced correctly, and explain why they were built.

This pass is about making the wires correct. Not adding new features.

---

# Main suspicion

The frontend is probably doing what it can, but the backend/API layer is not returning valid, timely data.

The biggest red flags:

- Swagger hangs or returns blank.
- App buttons never update timestamps.
- Source stays `—`.
- Empty state never clears.
- Both Friday and Saturday behave the same way.
- No visible difference between “not clicked yet”, “loading”, “failed”, and “loaded empty”.

That means we need to prove the system from the bottom up:

```text
external/source data
→ backend service
→ API route
→ Swagger response
→ frontend fetch
→ frontend state update
→ rendered card/odds/sim/tickets
````

Right now that chain is broken somewhere before or at the API layer.

---

# Phase 1 — Stop guessing and map the actual API contract

## Find every frontend API call

Search the frontend for every call related to:

* card refresh
* odds refresh
* run sim
* build tickets
* Friday route
* Saturday route
* day selection
* Derby/Oaks config
* Pick 5 sequence

Things to search:

```text
fetch(
axios
Refresh Card
Refresh Odds
Run Sim
Build Tickets
pick5
derby
oaks
card
odds
simulate
tickets
api/
```

Create a small table in the repo notes:

| UI action     | frontend file | API endpoint | method | expected request | expected response |
| ------------- | ------------- | ------------ | ------ | ---------------- | ----------------- |
| Refresh Card  | TBD           | TBD          | TBD    | TBD              | TBD               |
| Refresh Odds  | TBD           | TBD          | TBD    | TBD              | TBD               |
| Run Sim       | TBD           | TBD          | TBD    | TBD              | TBD               |
| Build Tickets | TBD           | TBD          | TBD    | TBD              | TBD               |

Do not continue until this is known.

---

# Phase 2 — Test the backend directly

For each endpoint found above, test with curl or Swagger.

We need to know which category each endpoint falls into:

## Possible states

### 1. Route does not exist

Symptoms:

* 404
* frontend silently catches it
* Swagger missing route

Fix:

* add route
* update frontend to correct route
* add integration test

### 2. Route exists but hangs

Symptoms:

* Swagger spinner forever
* curl never finishes
* no frontend error except empty screen

Likely causes:

* external API call has no timeout
* scraper request is blocking
* async function is waiting forever
* DB query is locked or too broad
* app is trying to scrape live data during the request
* missing source config causing retry loop

Fix:

* every external call needs a hard timeout
* route should return a real error payload
* long-running work should not block the request unless intentionally synchronous
* log where the hang happens

### 3. Route returns blank but 200

Symptoms:

```json
[]
```

or

```json
{}
```

or

```json
{ "races": [] }
```

Likely causes:

* no data seeded
* wrong date
* wrong day key
* wrong track key
* wrong race numbers
* Friday/Saturday mismatch
* backend returns empty success instead of data failure

Fix:

* distinguish “loaded zero races” from “failed to load”
* validate date/day/track/race sequence before returning success
* return structured warning/error

### 4. Route returns data but frontend does not render

Symptoms:

* Swagger/curl look good
* app remains empty

Likely causes:

* response shape mismatch
* camelCase vs snake_case mismatch
* frontend expects `races`, backend returns `card`
* frontend expects `horses`, backend returns `entries`
* frontend state update not firing
* failed JSON parse
* CORS/proxy/env URL issue

Fix:

* align response contract
* add frontend console logging temporarily
* add typed response validation
* render API error state

---

# Phase 3 — Add brutal but useful request logging

For this recovery pass, every workflow endpoint should log:

```text
[Pick5] request started
[Pick5] day=Friday/Saturday
[Pick5] date=...
[Pick5] track=...
[Pick5] source=...
[Pick5] external call started
[Pick5] external call completed in Xms
[Pick5] parsed races=N
[Pick5] parsed runners=N
[Pick5] response returned
```

If it fails:

```text
[Pick5] request failed
endpoint=...
day=...
date=...
source=...
error_type=...
error_message=...
```

If it returns empty:

```text
[Pick5] empty card returned
day=...
date=...
track=...
source=...
reason=...
```

Swagger hanging without logs is unacceptable. The backend needs to say exactly where it gets stuck.

---

# Phase 4 — Add timeouts everywhere

No API route should hang forever.

For every source call:

* set a timeout
* catch timeout separately
* return a structured error
* do not let the UI sit in permanent nothingness

Example response shape:

```json
{
  "ok": false,
  "status": "source_timeout",
  "message": "Card source timed out while loading Saturday.",
  "day": "Saturday",
  "source": "TBD",
  "data": null
}
```

For empty but successful:

```json
{
  "ok": false,
  "status": "empty_card",
  "message": "No races were returned for Saturday.",
  "day": "Saturday",
  "source": "TBD",
  "data": {
    "races": []
  }
}
```

For success:

```json
{
  "ok": true,
  "status": "loaded",
  "message": "Loaded Saturday card.",
  "day": "Saturday",
  "source": "TBD",
  "data": {
    "races": []
  }
}
```

Even if the current app does not use this exact shape, the important part is that success, empty, and failure must not all look the same.

---

# Phase 5 — Verify the day/date/track assumptions

This app has two explicit products:

* Friday = Kentucky Oaks Pick 5
* Saturday = Kentucky Derby Pick 5

The backend should not be guessing loosely.

Add/verify one single source of truth like:

```ts
const PICK5_DAYS = {
  friday: {
    label: "Friday",
    productName: "Kentucky Oaks Pick 5",
    track: "Churchill Downs",
    date: "YYYY-MM-DD",
    sequence: [/* race numbers */]
  },
  saturday: {
    label: "Saturday",
    productName: "Kentucky Derby Pick 5",
    track: "Churchill Downs",
    date: "YYYY-MM-DD",
    sequence: [/* race numbers */]
  }
}
```

Or equivalent backend config.

Need to confirm:

* Friday route passes Friday key.
* Saturday route passes Saturday key.
* API receives the right key.
* Backend maps key to the correct date.
* Backend maps key to the correct track.
* Backend maps key to the correct race sequence.
* Odds loader uses the same race/horse identifiers as card loader.
* Sim uses the loaded card, not a stale hardcoded card.
* Ticket builder uses the latest sim and odds state.

No duplicate Friday/Saturday logic scattered across frontend and backend.

---

# Phase 6 — Prove the backend can return fixture data

Before fighting live source data, add a fixture/fallback mode.

Create a known-good local fixture for each day:

```text
fixtures/pick5/friday-card.json
fixtures/pick5/saturday-card.json
fixtures/pick5/friday-odds.json
fixtures/pick5/saturday-odds.json
```

Then add either:

```text
?source=fixture
```

or an env flag:

```text
PICK5_DATA_MODE=fixture
```

Acceptance test:

* Swagger returns Friday fixture card.
* Swagger returns Saturday fixture card.
* Frontend can render Friday fixture card.
* Frontend can render Saturday fixture card.
* Sim can run against fixture card.
* Ticket builder can build against fixture odds.

This is critical because it separates:

```text
frontend/backend contract bugs
```

from:

```text
live data source bugs
```

Right now everything is blended together.

---

# Phase 7 — Frontend needs visible operational states

Current UI says nothing useful beyond “No card loaded yet.”

That is okay before first click, but after a click it needs to show what happened.

For each button, add state:

* idle
* loading
* success
* empty
* failed
* timed out

Examples:

```text
Loading Saturday card...
```

```text
Card source timed out. Check API logs or try fixture mode.
```

```text
Card endpoint returned 0 races for Saturday.
```

```text
Loaded 5 races / 58 horses from Churchill Downs.
```

For debugging, render a small dev-only diagnostics panel:

```text
Day: Saturday
Card endpoint: /api/...
Card status: failed
HTTP status: 504
Last error: source timeout
Last attempted: 3:54 PM
```

This app is currently too silent. Silent failure is making it impossible to tell whether the UI is broken, the API is broken, or the source data is empty.

---

# Phase 8 — Button behavior rules

## Refresh Card

Must:

* call the card endpoint
* set loading state
* clear prior error
* receive card response
* validate races exist
* update card state
* update `Last card refresh`
* update `Source`
* render races

Must not:

* silently do nothing
* leave timestamp as `never` after successful load
* call odds/sim/ticket endpoints before card exists unless explicitly designed to

## Refresh Odds

Must:

* require loaded card first, or clearly explain that no card is loaded
* call odds endpoint with day/card identifiers
* validate odds returned
* attach odds to known horses
* show unmatched odds/horses if any
* update `Last odds refresh`
* update source if relevant

Must not:

* overwrite card
* silently accept odds for unknown horses
* return success with no matched odds

## Run Sim

Must:

* require loaded card
* preferably use odds if available, but should say whether it used odds, morning line, or default priors
* produce race-level probabilities
* produce sequence-level outputs
* show timestamp/status

Must not:

* run against empty card
* pretend sim succeeded with no runners

## Build Tickets

Must:

* require loaded card
* require sim output
* preferably require odds/value output
* use budget and base unit
* show ticket count
* show total cost
* show unused budget
* explain keys/spreads/value decisions

Must not:

* build empty tickets
* exceed budget
* ignore base unit
* silently fail

---

# Phase 9 — Data model sanity checks

Each race needs at minimum:

```json
{
  "raceNumber": 8,
  "track": "Churchill Downs",
  "postTime": "...",
  "distance": "...",
  "surface": "...",
  "runners": [
    {
      "programNumber": "1",
      "horseName": "...",
      "morningLine": "...",
      "scratched": false
    }
  ]
}
```

Odds need to match by stable identifiers:

```json
{
  "raceNumber": 8,
  "programNumber": "1",
  "horseName": "...",
  "winOdds": "...",
  "impliedProbability": 0.12,
  "source": "...",
  "observedAt": "..."
}
```

Potential matching problems to watch:

* horse names with punctuation differences
* program number changes
* coupled entries like `1` and `1A`
* scratches
* race number mismatch
* Friday/Saturday date mismatch
* stale odds from previous day
* odds source using a different track/date key

The app should show unmatched odds instead of dropping them silently.

---

# Phase 10 — Swagger/API cleanup

Swagger being blank or hanging is a blocker.

Fix priorities:

1. Swagger page loads reliably.
2. Endpoint list is visible.
3. Each Pick 5 endpoint has a clear description.
4. Each endpoint has a sample request.
5. Each endpoint has a sample success response.
6. Each endpoint has a sample error response.
7. Long-running endpoints have timeout behavior.
8. Routes do not perform unbounded external work during schema generation.

If Swagger itself hangs because route imports trigger source calls, that needs to be fixed immediately. Importing API modules should not fetch live data.

---

# Phase 11 — Backend route design

Prefer explicit workflow routes while debugging:

```text
GET  /api/pick5/days
POST /api/pick5/{day}/refresh-card
POST /api/pick5/{day}/refresh-odds
POST /api/pick5/{day}/run-sim
POST /api/pick5/{day}/build-tickets
GET  /api/pick5/{day}/state
```

The frontend can then hydrate from state and each action can update state.

A route like this is very useful:

```text
GET /api/pick5/{day}/debug
```

It should return:

```json
{
  "day": "Saturday",
  "config": {
    "date": "...",
    "track": "Churchill Downs",
    "sequence": [8, 9, 10, 11, 12]
  },
  "card": {
    "loaded": false,
    "raceCount": 0,
    "runnerCount": 0,
    "lastRefresh": null,
    "lastError": null
  },
  "odds": {
    "loaded": false,
    "matchedRunnerCount": 0,
    "unmatchedOddsCount": 0,
    "lastRefresh": null,
    "lastError": null
  },
  "sim": {
    "loaded": false,
    "lastRun": null,
    "lastError": null
  },
  "tickets": {
    "loaded": false,
    "lastBuild": null,
    "lastError": null
  }
}
```

This would make the app much easier to debug.

---

# Phase 12 — Do not let live scraping block the UI forever

If `Refresh Card` is doing a live scrape, reconsider that design.

Better pattern:

```text
Refresh Card
→ request backend
→ backend tries source with timeout
→ backend stores result/state
→ backend returns loaded/failed/empty response
```

For anything slow:

```text
request starts job
→ returns job id
→ UI polls job status
→ UI renders result when done
```

But for this version, a synchronous request is fine only if it has strict timeouts and clear errors.

---

# Phase 13 — Acceptance criteria

## API acceptance

* Swagger loads.
* `/days` or equivalent returns Friday/Saturday.
* Friday card endpoint returns either:

  * valid card data, or
  * structured failure in under the timeout limit.
* Saturday card endpoint returns either:

  * valid card data, or
  * structured failure in under the timeout limit.
* No endpoint hangs indefinitely.
* Empty data is not treated as success unless intentionally marked as empty.
* Logs identify where failure happens.

## Frontend acceptance

* Friday page shows loading state after clicking `Refresh Card`.
* Saturday page shows loading state after clicking `Refresh Card`.
* Failed API call renders visible error.
* Empty API response renders visible empty state with reason.
* Successful card response renders races and runners.
* Successful odds response updates odds timestamp and odds display.
* Sim cannot run without card.
* Tickets cannot build without sim/card.
* No button click silently does nothing.

## End-to-end acceptance

Using fixture mode:

* Friday card loads.
* Saturday card loads.
* Odds load.
* Sim runs.
* Tickets build.
* Budget/base unit are respected.
* Total ticket cost is visible.
* App can be used for one full fake day without touching live data.

Using live mode:

* API either loads real data or returns a useful reason why it cannot.
* No hanging Swagger.
* No infinite frontend loading.
* No permanent `never` timestamps after successful actions.

---

# Phase 14 — First debugging order

Do this in order:

1. Open browser devtools.
2. Click `Refresh Card`.
3. Capture the exact network request.
4. Record:

   * URL
   * method
   * status
   * response body
   * timing
   * console error
5. Test that same URL in curl.
6. Test the same route in Swagger.
7. Add backend logging around that route.
8. Determine whether the issue is:

   * route missing
   * route hanging
   * route returning empty
   * frontend not rendering response
9. Fix only that path first.
10. Repeat for odds, sim, tickets.

No broad rewrites until the first broken link is identified.

---

# Phase 15 — Likely actual fixes

Based on the screenshots and Swagger behavior, likely fixes are:

* Add hard timeouts to source calls.
* Stop route imports from triggering source work.
* Fix date/day/track config.
* Add fixture mode.
* Fix frontend API base URL or proxy route.
* Align response shapes between frontend and backend.
* Add visible frontend error states.
* Make Swagger return structured errors instead of hanging.
* Ensure backend returns non-empty race data before frontend tries odds/sim/tickets.

---

# Final target

At the end of this pass, the app should not be “smart” yet.

It just needs to be honest and wired:

* If data loads, show it.
* If data is empty, say exactly what is empty.
* If the source fails, say exactly what failed.
* If an endpoint hangs today, make it timeout and report.
* If the frontend and backend disagree on shape, fix the contract.
* If live data is unreliable, fixture mode must still let the app prove the workflow.

The first win is not a perfect Derby model.

The first win is clicking `Refresh Card` and no longer staring at `never`.

```
