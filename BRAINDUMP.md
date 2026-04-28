# BRAINDUMP.md — PASS 2 (EDGE ENGINE w/ HISTORICAL PRIORS + ODDS MOVEMENT)
---
# 0. PASS 2 GOAL
PASS 1 = functional  
PASS 2 = **structural edge vs the betting pool**
PASS 2 upgrades the system from:
> “build valid tickets”
to:
> **“build tickets that exploit market bias, public behavior, and race context”**
---
# 1. CORE SHIFT (DO NOT MISS THIS)
PASS 1 assumed:
```text
odds ≈ truth

PASS 2 assumes:

odds ≈ starting point
historical + context ≠ priced correctly

So:

final_prob =
  odds_prob
  + historical_adjustments
  + odds_movement_signal
  + chaos_context

⸻

2. PASS 2 ARCHITECTURE ADDITIONS

Add 3 new modules:

historical_priors/
odds_tracker/
edge_model/

Updated flow:

Scraped Odds
  ↓
Normalize
  ↓
Apply Historical Priors
  ↓
Apply Odds Movement Adjustments
  ↓
Final Probability Model
  ↓
Race Classification
  ↓
Budget Allocation Engine
  ↓
Ticket Builder

⸻

3. HISTORICAL PRIORS (THE MOST IMPORTANT ADD)

3.1 Philosophy

We are NOT training a model.

We are injecting:

known structural biases in horse racing markets

⸻

3.2 historical_priors.json

{
  "field_size": {
    "6-7": { "favorite_win_rate": 0.38 },
    "8-10": { "favorite_win_rate": 0.32 },
    "11-14": { "favorite_win_rate": 0.26 },
    "15+": { "favorite_win_rate": 0.22 }
  },
  "odds_rank": {
    "1": { "multiplier": 0.94 },
    "2": { "multiplier": 1.00 },
    "3": { "multiplier": 1.02 },
    "4-6": { "multiplier": 1.08 },
    "7+": { "multiplier": 0.90 }
  },
  "race_type": {
    "turf_sprint": { "chaos": 1.20 },
    "maiden": { "chaos": 1.25 },
    "derby": { "chaos": 1.35 },
    "default": { "chaos": 1.00 }
  }
}

⸻

3.3 Applying Historical Adjustments

Step 1 — Convert odds → probability

Step 2 — Apply rank multiplier

adjusted_prob = odds_prob × odds_rank_multiplier

Step 3 — Apply field size adjustment

Instead of raw favorite strength:

if field_size >= 14:
  compress top probabilities
  expand mid-tier probabilities

Step 4 — Apply race-type chaos

flatten_distribution(chaos_factor)

Step 5 — Normalize

⸻

3.4 What This Actually Does

* slightly depresses favorites in big fields
* boosts mid-tier horses (your B tier)
* flattens chaotic races
* forces spreads where needed
* protects you from false singles

⸻

4. ODDS MOVEMENT ENGINE (PROJECTED CLOSING LINE)

4.1 Store Snapshots

OddsSnapshot {
  timestamp
  race
  horse
  odds
}

Track:

T-120 min
T-60 min
T-30 min
Current

⸻

4.2 Compute Velocity

velocity = change in implied probability over time

⸻

4.3 Movement Rules

if favorite shortens:
  weak signal (expected)
if mid-tier (5-1 to 12-1) shortens:
  strong signal → BOOST
if longshot shortens:
  chaos signal → CONDITIONAL BOOST
if drifting:
  reduce confidence

⸻

4.4 Apply Adjustment

movement_adjustment =
  velocity × movement_weight

Then:

final_prob += movement_adjustment

Normalize again.

⸻

5. HORSE EDGE MODEL

Each horse gets:

true_prob (after adjustments)
market_prob (from odds)
ownership_proxy
edge_score
confidence_score

⸻

5.1 Ownership Proxy

Approximate:

ownership =
  function(odds rank + favorite bias)

Rules:

* rank 1 = very high ownership
* rank 2–3 = high
* rank 4–6 = medium (sweet spot)
* longshots = low but noisy

⸻

5.2 Edge Score

edge = true_prob - market_prob

Then adjust:

edge_score =
  edge
  + ownership_discount
  + chaos_bonus

⸻

5.3 Horse Buckets (Upgraded)

CORE (A)
VALUE (B)
CHAOS (C)
TRAP (overbet favorite)
DEAD (toss)

⸻

6. RACE CLASSIFICATION (UPDATED)

Use adjusted probabilities:

Compute:

top_prob
second_prob
entropy

Classify:

KEY
TIGHT
MID
CHAOS

Now more accurate because:

* favorites already adjusted
* chaos already modeled

⸻

7. BUDGET ALLOCATION ENGINE (UNCHANGED CORE, BETTER INPUT)

Still:

KEY → 1
TIGHT → 2
MID → 3
CHAOS → 5–7

But now classification is smarter.

⸻

8. SPEND EFFICIENCY MODEL (NEW)

For each horse:

marginal_value =
  increase in race win probability
  ÷ increase in ticket cost

For each race:

best_spend_target =
  race with highest marginal_value

Use this to:

* decide where to add horses
* decide where to cut

⸻

9. TICKET OPTIMIZATION (UPGRADED)

Now maximize:

score =
  win_probability
  × payout_score
  × confidence

⸻

9.1 Payout Score

Proxy:

payout_score =
  inverse(chalkiness)

Chalkiness:

* number of high-ownership horses
* number of favorites

⸻

9.2 Confidence

From:

* probability strength
* odds movement
* race stability

⸻

10. FINAL TICKET OUTPUT

Return:

Ticket A — Balanced
Ticket B — Safer
Ticket C — Upside

Each includes:

Cost
Hit Rate
Edge Score
Confidence
Chalk Exposure
Notes

⸻

11. STRATEGY OUTPUT (NEW — IMPORTANT)

Show:

Race Strategy
R8: SINGLE (strong, low chaos)
R9: 2-DEEP (clear top 2)
R10: CHAOS SPREAD (value concentrated)
R11: MID
R12: MAX CHAOS (Derby)

⸻

12. FLAGS (EXPANDED)

Overbet favorite
Value horse
Separator candidate
Public single
Steam horse
Cold horse
Chaos race
Spread race
Trap favorite

⸻

13. VALIDATION LOOP (UPDATED)

13.1 Historical Adjustment

* probabilities still sum to 100%
* no horse inflated unrealistically

13.2 Movement

* velocity reasonable
* no extreme spikes

13.3 Tickets

* structures differ meaningfully
* not all chalk-heavy
* not all chaos-heavy

⸻

14. PASS 2 ACCEPTANCE CRITERIA

System must:

✅ adjust probabilities beyond raw odds
✅ identify value vs overbet horses
✅ incorporate odds movement
✅ classify races correctly
✅ allocate budget intelligently
✅ generate differentiated tickets
✅ show confidence + edge

⸻

15. FINAL MENTAL MODEL

PASS 1:

build tickets that work

PASS 2:

build tickets that beat how people bet

⸻

16. FINAL TRUTH

Your edge comes from:

1. Using favorites to reduce cost
2. Using historical priors to avoid bad singles
3. Using odds movement to find live horses
4. Using budget to maximize chaos coverage
5. Capturing 1–2 key upsets

NOT from:

perfectly predicting race winners

⸻

17. END STATE

When this is working, you can:

* open app on iPad
* auto-load Derby weekend races
* see adjusted probabilities
* see value + traps
* see odds movement
* enter $96
* get 3 strong tickets

That’s the product.

---
If you want, next I can:
- turn this into actual code (Python + React)
- or give you exact formulas + functions ready to drop in
This version is now *actually sharp*, not just functional.