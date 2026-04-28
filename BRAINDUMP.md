100% — then revise the whole thing:

# BRAINDUMP.md — Derby Weekend Pick 5 Browser App, Data-First Version
## Hard Requirement
Manual data entry is not acceptable.
This app only works if it can automatically pull or refresh:
- Churchill / Kentucky Derby weekend race cards
- Friday Pick 5 sequence
- Saturday Pick 5 sequence
- horses
- post positions
- jockeys
- trainers
- morning line odds
- current/live odds
- race number
- race time
- surface/distance if available
Manual override is allowed.
Manual entry as the main workflow is not.
---
## Goal
Build a personal iPad browser app for Derby weekend.
Primary use case:
> I open the app during Friday/Saturday Derby weekend, hit refresh, and it updates the Pick 5 races and odds. Then I run simulations and build tickets.
This is for me only.
It should not place bets.
It should not require me to type in every horse.
---
## Data Sources
### Preferred Source 1 — TwinSpires / KentuckyDerby pages
TwinSpires and KentuckyDerby.com publish official Derby odds, race info, post positions, jockeys, trainers, and live odds pages around Derby weekend. KentuckyDerby.com says morning line odds shift to near-time live odds once advance wagering opens. TwinSpires has official Kentucky Derby odds pages with horse, jockey, trainer, post, race, and odds data.  [oai_citation:0‡Kentucky Derby](https://www.kentuckyderby.com/wager/live-odds/?utm_source=chatgpt.com)
### Preferred Source 2 — Equibase
Equibase is the official source for racing entries, results, statistics, and mobile racing data. Use it for race cards / entries / results where possible.  [oai_citation:1‡Equibase](https://www.equibase.com/?utm_source=chatgpt.com)
### Source 3 — Public odds / article fallback
Use public pages only as backup for Derby/Oaks headline races or sanity checks. Not ideal for full Pick 5 cards.
---
## Important Data Reality
The hardest part is not the simulation.
The hardest part is getting reliable race-card and odds data without manual work.
So v1 should be designed like this:
```text
Browser app
  ↓
Local backend scraper/API
  ↓
Source adapters
  - TwinSpires adapter
  - KentuckyDerby adapter
  - Equibase adapter
  ↓
Normalized race card + odds snapshot
  ↓
Simulation + ticket builder

Do not scrape directly from the browser.

Use a tiny local backend so CORS and parsing do not wreck the app.

⸻

Minimal Architecture

derby-p5/
  api/
    main.py
    sources/
      twinspires.py
      kentuckyderby.py
      equibase.py
    normalize.py
    cache.py
    model.py
    sim.py
    tickets.py
  web/
    app/
      page.tsx
      sequence/[day]/page.tsx
    components/
      RaceCard.tsx
      HorseRow.tsx
      OddsBadge.tsx
      TicketBuilder.tsx
      SimulationSummary.tsx

Run locally:

docker compose up

Open on iPad:

http://mac-mini.local:3000

Or through Tailscale.

⸻

Backend Endpoints

GET /api/cards/friday
GET /api/cards/saturday
POST /api/cards/friday/refresh
POST /api/cards/saturday/refresh
GET /api/odds/friday
GET /api/odds/saturday
POST /api/odds/friday/refresh
POST /api/odds/saturday/refresh
POST /api/simulate/friday
POST /api/simulate/saturday
POST /api/tickets/friday/build
POST /api/tickets/saturday/build

⸻

Normalized Data Model

type Race = {
  id: string
  day: "friday" | "saturday"
  track: "Churchill Downs"
  raceNumber: number
  postTime?: string
  name?: string
  surface?: string
  distance?: string
  sequenceRole?: "pick5-leg-1" | "pick5-leg-2" | "pick5-leg-3" | "pick5-leg-4" | "pick5-leg-5"
  horses: Horse[]
}
type Horse = {
  id: string
  raceId: string
  post: number
  name: string
  jockey?: string
  trainer?: string
  morningLineOdds?: string
  currentOdds?: string
  scratched?: boolean
  source?: string
  marketProbability?: number
  morningLineProbability?: number
  modelProbability?: number
  finalProbability?: number
  userTag?: "single" | "A" | "B" | "C" | "toss" | "chaos" | "boost" | "fade"
}

⸻

The App Flow

Step 1 — Refresh Data

I open Friday or Saturday.

Tap:

Refresh Card + Odds

The backend pulls:

* race list
* Pick 5 sequence
* entries
* post positions
* ML odds
* live/current odds
* scratches if available

Then stores a local snapshot.

⸻

Step 2 — Normalize Odds

Convert odds to implied probability.

Examples:

3-1 = 25%
5-2 = 28.57%
10-1 = 9.09%

Then normalize inside each race.

Because pari-mutuel odds include takeout/pool effects, the race probabilities need to sum to 100%.

⸻

Step 3 — Blend With Model

Default:

final_probability =
  current_odds_probability * 0.70
+ morning_line_probability * 0.20
+ model_prior_probability * 0.10

If model prior is missing:

final_probability =
  current_odds_probability * 0.80
+ morning_line_probability * 0.20

Then apply my tags.

⸻

Model v1

The model does not need to be fancy.

It can be a local JSON prior file produced before Derby weekend.

Example:

{
  "race_type_priors": {
    "large_field_dirt_route": {
      "favorite_soften": 0.9,
      "mid_price_boost": 1.08,
      "longshot_boost": 1.03
    },
    "small_field_chalk": {
      "favorite_soften": 1.0,
      "mid_price_boost": 1.0
    }
  },
  "field_size_priors": {
    "6-7": { "favoriteWinRate": 0.38 },
    "8-10": { "favoriteWinRate": 0.32 },
    "11-14": { "favoriteWinRate": 0.25 },
    "15+": { "favoriteWinRate": 0.18 }
  }
}

This is enough for v1.

Actual ML can come later.

⸻

What “Trained Model” Means For v1

For this first build, trained model means:

historical priors + odds calibration + race shape modifiers

Not a giant ML system.

Inputs:

* field size
* current odds rank
* morning line rank
* race type
* distance/surface
* Derby/Oaks/high-chaos flag
* odds drift if multiple snapshots exist

Outputs:

* model prior probability
* chaos score
* overbet/value flag

⸻

Odds Snapshot Tracking

This matters.

The app should save odds snapshots over time:

type OddsSnapshot = {
  timestamp: string
  day: "friday" | "saturday"
  raceNumber: number
  horseId: string
  odds: string
  impliedProbability: number
  source: string
}

Why:

* odds movement can matter
* late money matters
* I want to see if a horse is getting crushed
* I want to know if a favorite is getting overbet

UI:

Horse A
ML: 8-1
9am: 10-1
11am: 7-1
Current: 4-1
Flag: taking money

⸻

Required UI

Each day page:

Friday Pick 5
[Refresh Card]
[Refresh Odds]
[Run Sim]
[Build Tickets]
Last card refresh: 10:42 AM
Last odds refresh: 11:08 AM
Source: TwinSpires / KentuckyDerby / Equibase
Budget: $96
Base Unit: $0.50

Each race:

Race 8 — Leg 1
Surface/Distance
Post Time
Post | Horse | ML | Current | Drift | Market % | Final % | Tag | Flags

⸻

Manual Override, But Not Manual Entry

I can manually override:

* tag
* toss
* single
* boost/fade
* current odds if scraper fails for one horse
* scratch status

But I should not be typing the entire card.

Manual override is a safety valve only.

⸻

Ticket Builder

Primary output:

* $48 ticket
* $96 ticket
* $144 ticket
* $192 ticket
* custom

Ticket construction should use:

* A/B/C tags
* final probabilities
* chaos score
* budget
* single candidates
* overbet favorite flags
* separator horses

⸻

Ticket Logic

Generate:

Main Ticket

Mostly A horses.

A / A / A / A / A

Backup Tickets

One B allowed.

B / A / A / A / A
A / B / A / A / A
A / A / B / A / A
A / A / A / B / A
A / A / A / A / B

Chaos Ticket

Uses value/separator horses.

Good for:

* Derby leg
* Oaks leg
* turf chaos
* big field races

⸻

Simulation

Run 25,000–100,000 simulations per sequence.

For each sim:

for each leg:
  pick winner using final probabilities
combine 5 winners
evaluate generated tickets

Output:

Ticket A
Cost: $72
Estimated hit rate: 2.4%
Chalkiness: Medium
Chaos coverage: Medium
Separator coverage: Good

⸻

Flags

The app should flag:

Overbet favorite
Useful value
Possible public single
Good single candidate
Bad single candidate
Chaos race
Spread race
Likely separator
Taking money
Cold on board
Scratch
Missing odds

⸻

Scraper Validation

This is critical.

After refresh:

* confirm every race has horses
* confirm each horse has post/name
* confirm odds parsed
* confirm no duplicate horses
* confirm scratched horses are handled
* confirm probabilities normalize to 100%
* confirm all 5 Pick 5 legs are loaded

If validation fails:

Data incomplete: Race 9 missing odds for 2 horses
Use cached snapshot or retry

⸻

Cache Strategy

Always cache last good snapshot.

If refresh fails, app should not go blank.

It should say:

Showing cached odds from 11:02 AM
Refresh failed at 11:14 AM

This is very important for race day.

⸻

Build Order

Phase 1 — Data Pipeline

Build source adapters first.

Success means:

* app can load Friday card
* app can load Saturday card
* app can refresh odds
* app saves snapshots
* app validates data

Do not build the sim until this works.

Phase 2 — Browser UI

Build iPad-friendly view.

Success means:

* open on iPad
* refresh data
* view all Pick 5 legs
* see odds and probabilities
* tag horses

Phase 3 — Simulation

Add probability blend and Monte Carlo.

Success means:

* run sims
* see race winner probabilities
* see fragile/spread/single races

Phase 4 — Ticket Builder

Add budgeted tickets.

Success means:

* generate tickets under $48/$96/$144/$192
* compare tickets
* show cost and hit-rate estimates

⸻

Acceptance Criteria

This is done when:

* I can open it on my iPad
* tap refresh
* automatically load Friday Pick 5
* automatically load Saturday Pick 5
* see current odds
* see morning line odds
* see odds movement
* tag horses
* run simulations
* build tickets under budget
* rely on cached data if refresh fails

No manual race-card entry.

No manual full-card CSV work.

Manual override only.

⸻

Final Principle

The app lives or dies on automated data.

If the data ingestion is weak, the sim does not matter.

Build the data adapter, cache, and validation first.

Then build the Pick 5 model.