# ISSUE-010: Probability blending model, JSON priors, and flags computation (`api/model.py`)

**Priority**: medium
**Labels**: model, phase-3
**Dependencies**: ISSUE-006
**Status**: implemented

## Description

Implement `api/model.py`. (1) Load `data/priors.json` at startup with `race_type_priors` (keys: 'large_field_dirt_route', 'small_field_chalk'; values: favorite_soften, mid_price_boost, longshot_boost multipliers) and `field_size_priors` (keys: '6-7', '8-10', '11-14', '15+'; values: favoriteWinRate). (2) `compute_model_prior(horse, race, priors)`: determine field-size bucket from len(non-scratched horses); determine race type from surface/distance/field-size; apply multiplier to marketProbability then re-normalize. (3) `blend_probabilities(horse, has_model_prior)`: `final = current*0.70 + ml*0.20 + model*0.10` or `current*0.80 + ml*0.20` fallback. Set `modelProbability` and `finalProbability` on Horse. (4) Flags per BRAINDUMP: overbet_favorite (currentOdds implied > ml_implied * 1.15); useful_value (currentOdds implied < ml_implied * 0.85); public_single (market_prob > 0.40); good_single (0.28–0.40 + value flag); bad_single (market_prob > 0.45); chaos_race (field≥10 and no horse > 0.20); spread_race (top-4 within 5% of each other); taking_money (latest odds < prior odds — requires drift series); cold_on_board (latest odds > prior odds); scratch (horse.scratched=True); missing_odds. (5) `apply_user_boost_fade(horse)`: if userTag='boost' multiply finalProbability by 1.15; 'fade' by 0.85; re-normalize race.

## Acceptance Criteria

- [ ] With marketProbability=0.35, morningLineProbability=0.28, modelProbability=0.30: finalProbability = 0.35*0.70 + 0.28*0.20 + 0.30*0.10 = 0.332
- [ ] Missing model prior uses 0.80/0.20 blend: finalProbability = 0.35*0.80 + 0.28*0.20 = 0.336
- [ ] overbet_favorite flag set when market implied is 15%+ above ML implied
- [ ] chaos_race flag set on a 12-horse race where no horse exceeds 0.20 market probability
- [ ] taking_money flag set when current odds shorter than prior snapshot odds
- [ ] priors.json loaded and race_type multipliers applied to modelProbability

## Implementation Notes


Attempt 1: Added the probability layer to api/model.py: load_priors, field_size_bucket, determine_race_type, compute_model_prior + apply_model_priors_to_race (race-type multipliers + re-normalize), blend_probabilities/blend_race (0.70/0.20/0.10 with 0.80/0.20 fallback), compute_horse_flags + compute_race_flags + apply_flags (overbet/value/single/chaos/spread/drift/scratch/missing-odds), and apply_user_boost_fade (1.15/0.85 + race re-normalize). Populated data/priors.json with the BRAINDUMP example priors. 45 new tests in api/tests/test_probability_model.py; full suite 227/227.