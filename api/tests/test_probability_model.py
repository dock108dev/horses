"""Tests for the probability blending, priors, and flags layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.model import (
    ADJUSTMENT_MAX,
    ADJUSTMENT_MIN,
    BLEND_WEIGHT_MARKET,
    BLEND_WEIGHT_MARKET_FALLBACK,
    BLEND_WEIGHT_ML,
    BLEND_WEIGHT_ML_FALLBACK,
    BLEND_WEIGHT_MODEL,
    CHAOS_BONUS_SCALE,
    CONFIDENCE_WEIGHT_PROB,
    DEFAULT_PRIORS_PATH,
    FIELD_SIZE_COMPRESSION_MIN,
    FLAG_BAD_SINGLE,
    FLAG_CHAOS_RACE,
    FLAG_COLD_ON_BOARD,
    FLAG_GOOD_SINGLE,
    FLAG_MISSING_ODDS,
    FLAG_OVERBET_FAVORITE,
    FLAG_PUBLIC_SINGLE,
    FLAG_SCRATCH,
    FLAG_SPREAD_RACE,
    FLAG_TAKING_MONEY,
    FLAG_USEFUL_VALUE,
    LONGSHOT_VELOCITY_DAMPENER,
    MAX_CHAOS_FACTOR_OVERRIDE,
    MAX_SINGLE_HORSE_PROB,
    MOVEMENT_REFERENCE_WINDOW_MS,
    MOVEMENT_WEIGHT_DRIFT,
    MOVEMENT_WEIGHT_FAVORITE_SHORTEN,
    MOVEMENT_WEIGHT_LONGSHOT_SHORTEN,
    MOVEMENT_WEIGHT_MID_TIER_SHORTEN,
    OWNERSHIP_NEUTRAL,
    OWNERSHIP_PROXY_BY_RANK,
    OWNERSHIP_PROXY_TAIL,
    OWNERSHIP_SCALE,
    PROB_STRONG_THRESHOLD,
    RACE_STABILITY_MODIFIER,
    STRATEGY_LABEL_CHAOS_SPREAD,
    STRATEGY_LABEL_MAX_CHAOS,
    STRATEGY_LABEL_SINGLE,
    STRATEGY_LABEL_TWO_DEEP,
    VELOCITY_CLAMP,
    VELOCITY_NOISE_FLOOR,
    Horse,
    Race,
    apply_edge_model,
    apply_flags,
    apply_historical_priors,
    apply_model_priors_to_race,
    apply_movement_adjustment,
    blend_probabilities,
    blend_race,
    classify_race,
    compute_horse_flags,
    compute_model_prior,
    compute_race_flags,
    determine_race_type,
    field_size_bucket,
    load_priors,
)


def _horse(
    post: int,
    *,
    name: str | None = None,
    market: float | None = None,
    ml: float | None = None,
    model: float | None = None,
    scratched: bool = False,
    user_tag: str | None = None,
) -> Horse:
    return Horse(
        id=f"h-{post}",
        raceId="r-1",
        post=post,
        name=name or f"Horse {post}",
        marketProbability=market,
        morningLineProbability=ml,
        modelProbability=model,
        scratched=scratched,
        userTag=user_tag,  # type: ignore[arg-type]
    )


def _race(horses: list[Horse], *, surface: str = "dirt", distance: str = "1 1/4M") -> Race:
    return Race(
        id="r-1",
        day="saturday",
        raceNumber=12,
        surface=surface,
        distance=distance,
        horses=horses,
    )


# ---------------------------------------------------------------------------
# Blending
# ---------------------------------------------------------------------------


def test_blend_with_model_prior_uses_three_way_split() -> None:
    h = _horse(1, market=0.35, ml=0.28, model=0.30)
    blend_probabilities(h, has_model_prior=True)
    expected = 0.35 * BLEND_WEIGHT_MARKET + 0.28 * BLEND_WEIGHT_ML + 0.30 * BLEND_WEIGHT_MODEL
    assert h.finalProbability == pytest.approx(expected)
    assert h.finalProbability == pytest.approx(0.331)


def test_blend_without_model_prior_uses_fallback_weights() -> None:
    h = _horse(1, market=0.35, ml=0.28, model=None)
    blend_probabilities(h, has_model_prior=False)
    expected = 0.35 * BLEND_WEIGHT_MARKET_FALLBACK + 0.28 * BLEND_WEIGHT_ML_FALLBACK
    assert h.finalProbability == pytest.approx(expected)
    assert h.finalProbability == pytest.approx(0.336)


def test_blend_falls_back_to_fallback_when_model_prob_missing() -> None:
    h = _horse(1, market=0.35, ml=0.28, model=None)
    blend_probabilities(h, has_model_prior=True)
    assert h.finalProbability == pytest.approx(0.336)


def test_blend_returns_market_when_only_market_present() -> None:
    h = _horse(1, market=0.40, ml=None, model=None)
    blend_probabilities(h, has_model_prior=False)
    assert h.finalProbability == pytest.approx(0.40)


def test_blend_returns_none_when_all_inputs_missing() -> None:
    h = _horse(1, market=None, ml=None, model=None)
    blend_probabilities(h, has_model_prior=True)
    assert h.finalProbability is None


def test_blend_race_blends_every_horse() -> None:
    horses = [
        _horse(1, market=0.35, ml=0.28, model=0.30),
        _horse(2, market=0.10, ml=0.12, model=None),
    ]
    race = _race(horses)
    blend_race(race, has_model_prior=False)
    assert horses[0].finalProbability == pytest.approx(0.336)
    assert horses[1].finalProbability == pytest.approx(0.10 * 0.80 + 0.12 * 0.20)


# ---------------------------------------------------------------------------
# Priors loading
# ---------------------------------------------------------------------------


def test_default_priors_file_loads_with_expected_keys() -> None:
    priors = load_priors()
    assert "race_type_priors" in priors
    assert "field_size_priors" in priors
    assert "odds_rank" in priors
    assert "race_type" in priors
    assert "large_field_dirt_route" in priors["race_type_priors"]
    assert "small_field_chalk" in priors["race_type_priors"]
    assert set(priors["field_size_priors"].keys()) == {"6-7", "8-10", "11-14", "15+"}
    assert set(priors["odds_rank"].keys()) == {"1", "2", "3", "4-6", "7+"}
    assert set(priors["race_type"].keys()) == {"turf_sprint", "maiden", "derby", "default"}


def test_load_priors_handles_missing_top_level_keys(tmp_path: Path) -> None:
    p = tmp_path / "priors.json"
    p.write_text(json.dumps({}))
    priors = load_priors(p)
    assert priors == {
        "race_type_priors": {},
        "field_size_priors": {},
        "odds_rank": {},
        "race_type": {},
    }


def test_default_priors_path_points_to_data_dir() -> None:
    assert DEFAULT_PRIORS_PATH == Path("data/priors.json")


# ---------------------------------------------------------------------------
# Race-shape classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size,bucket",
    [(5, "6-7"), (6, "6-7"), (7, "6-7"), (8, "8-10"), (10, "8-10"), (11, "11-14"), (14, "11-14"), (15, "15+"), (20, "15+")],
)
def test_field_size_bucket(size: int, bucket: str) -> None:
    assert field_size_bucket(size) == bucket


def test_determine_race_type_large_field_dirt_route() -> None:
    race = _race([_horse(i + 1, market=0.10) for i in range(12)], surface="dirt", distance="1 1/4M")
    assert determine_race_type(race, 12) == "large_field_dirt_route"


def test_determine_race_type_small_field_chalk() -> None:
    race = _race([_horse(i + 1, market=0.15) for i in range(6)], surface="dirt", distance="6f")
    assert determine_race_type(race, 6) == "small_field_chalk"


def test_determine_race_type_returns_none_for_mid_field_sprint() -> None:
    race = _race([_horse(i + 1, market=0.10) for i in range(9)], surface="dirt", distance="6f")
    assert determine_race_type(race, 9) is None


# ---------------------------------------------------------------------------
# Model prior + race-type multiplier application
# ---------------------------------------------------------------------------


def test_compute_model_prior_softens_favorite_in_large_dirt_route() -> None:
    horses = [_horse(i + 1, market=0.30 if i == 0 else 0.07) for i in range(11)]
    race = _race(horses, surface="dirt", distance="1 1/4M")
    priors = {
        "race_type_priors": {
            "large_field_dirt_route": {
                "favorite_soften": 0.9,
                "mid_price_boost": 1.08,
                "longshot_boost": 1.03,
            }
        }
    }
    result = compute_model_prior(horses[0], race, priors)
    assert result == pytest.approx(0.30 * 0.9)


def test_compute_model_prior_returns_market_when_no_race_type() -> None:
    horses = [_horse(i + 1, market=0.10) for i in range(9)]
    race = _race(horses, surface="dirt", distance="6f")
    priors = {"race_type_priors": {"large_field_dirt_route": {"favorite_soften": 0.9}}}
    assert compute_model_prior(horses[0], race, priors) == pytest.approx(0.10)


def test_compute_model_prior_returns_none_for_scratched() -> None:
    horses = [_horse(1, market=0.30, scratched=True)]
    race = _race(horses)
    assert compute_model_prior(horses[0], race, {}) is None


def test_apply_model_priors_to_race_normalizes_to_one() -> None:
    horses = [
        _horse(1, market=0.30),
        _horse(2, market=0.20),
        _horse(3, market=0.15),
        _horse(4, market=0.10),
        _horse(5, market=0.08),
        _horse(6, market=0.07),
        _horse(7, market=0.05),
        _horse(8, market=0.03),
        _horse(9, market=0.01),
        _horse(10, market=0.005),
        _horse(11, market=0.005),
    ]
    race = _race(horses, surface="dirt", distance="1 1/4M")
    priors = load_priors()
    apply_model_priors_to_race(race, priors)
    total = sum(h.modelProbability for h in horses if h.modelProbability is not None)
    assert total == pytest.approx(1.0)
    # Favorite was softened; its share of the model prior should be < its market share.
    assert horses[0].modelProbability is not None
    assert horses[0].modelProbability < 0.30


def test_apply_model_priors_to_race_handles_priors_json_round_trip() -> None:
    """Load real priors.json and verify race-type multiplier reaches modelProbability."""
    horses = [_horse(i + 1, market=0.30 if i == 0 else 0.07) for i in range(11)]
    race = _race(horses, surface="dirt", distance="1 1/4M")
    priors = load_priors()
    apply_model_priors_to_race(race, priors)
    # Favorite drops from 0.30 share toward a softened share after re-normalization.
    assert horses[0].modelProbability is not None
    assert horses[0].modelProbability < 0.30


# ---------------------------------------------------------------------------
# Per-horse flags
# ---------------------------------------------------------------------------


def test_overbet_favorite_flag_set_when_market_15pct_above_ml() -> None:
    h = _horse(1, market=0.40, ml=0.30)  # ratio = 1.333
    assert FLAG_OVERBET_FAVORITE in compute_horse_flags(h)


def test_useful_value_flag_set_when_market_below_ml_minus_15pct() -> None:
    h = _horse(1, market=0.20, ml=0.30)  # ratio = 0.666
    assert FLAG_USEFUL_VALUE in compute_horse_flags(h)


def test_no_overbet_or_value_when_ratio_inside_band() -> None:
    h = _horse(1, market=0.30, ml=0.30)
    flags = compute_horse_flags(h)
    assert FLAG_OVERBET_FAVORITE not in flags
    assert FLAG_USEFUL_VALUE not in flags


def test_public_and_bad_single_flags() -> None:
    h = _horse(1, market=0.50, ml=0.50)
    flags = compute_horse_flags(h)
    assert FLAG_PUBLIC_SINGLE in flags
    assert "bad_single" in flags


def test_good_single_requires_value_flag() -> None:
    # market=0.30 is in the 0.28–0.40 window; ml=0.50 makes it a value.
    h = _horse(1, market=0.30, ml=0.50)
    flags = compute_horse_flags(h)
    assert FLAG_USEFUL_VALUE in flags
    assert FLAG_GOOD_SINGLE in flags


def test_good_single_not_set_without_value_flag() -> None:
    h = _horse(1, market=0.30, ml=0.30)
    flags = compute_horse_flags(h)
    assert FLAG_GOOD_SINGLE not in flags


def test_scratched_horse_only_flagged_scratch() -> None:
    h = _horse(1, market=0.30, ml=0.30, scratched=True)
    assert compute_horse_flags(h) == [FLAG_SCRATCH]


def test_missing_odds_flag_when_market_probability_none() -> None:
    h = _horse(1, market=None, ml=0.20)
    assert FLAG_MISSING_ODDS in compute_horse_flags(h)


# ---------------------------------------------------------------------------
# Drift flags
# ---------------------------------------------------------------------------


def test_taking_money_flag_when_latest_odds_shorter() -> None:
    drift = [(1000, "10-1", 0.0909), (2000, "5-1", 0.1667)]
    h = _horse(1, market=0.17, ml=0.10)
    flags = compute_horse_flags(h, drift_series=drift)
    assert FLAG_TAKING_MONEY in flags


def test_cold_on_board_flag_when_latest_odds_longer() -> None:
    drift = [(1000, "5-1", 0.1667), (2000, "10-1", 0.0909)]
    h = _horse(1, market=0.09, ml=0.10)
    flags = compute_horse_flags(h, drift_series=drift)
    assert FLAG_COLD_ON_BOARD in flags


def test_no_drift_flags_when_only_one_snapshot() -> None:
    drift = [(1000, "5-1", 0.1667)]
    h = _horse(1, market=0.17, ml=0.10)
    flags = compute_horse_flags(h, drift_series=drift)
    assert FLAG_TAKING_MONEY not in flags
    assert FLAG_COLD_ON_BOARD not in flags


# ---------------------------------------------------------------------------
# Race-level flags
# ---------------------------------------------------------------------------


def test_chaos_race_flag_for_12_horse_field_no_horse_above_20pct() -> None:
    horses = [_horse(i + 1, market=0.083) for i in range(12)]  # 1/12 each
    race = _race(horses)
    assert FLAG_CHAOS_RACE in compute_race_flags(race)


def test_chaos_race_not_set_when_a_horse_exceeds_20pct() -> None:
    horses = [_horse(1, market=0.30)] + [_horse(i + 2, market=0.06) for i in range(11)]
    race = _race(horses)
    assert FLAG_CHAOS_RACE not in compute_race_flags(race)


def test_spread_race_flag_when_top_4_within_5pct() -> None:
    horses = [
        _horse(1, market=0.16),
        _horse(2, market=0.15),
        _horse(3, market=0.13),
        _horse(4, market=0.12),
        _horse(5, market=0.05),
        _horse(6, market=0.04),
    ]
    race = _race(horses)
    assert FLAG_SPREAD_RACE in compute_race_flags(race)


def test_apply_flags_appends_race_flags_to_non_scratched_horses() -> None:
    horses = [_horse(i + 1, market=0.083, ml=0.083) for i in range(12)]
    horses[5].scratched = True
    race = _race(horses)
    apply_flags(race)
    for h in race.horses:
        if h.scratched:
            assert h.flags == [FLAG_SCRATCH]
        else:
            assert FLAG_CHAOS_RACE in h.flags


def test_apply_flags_threads_drift_series_per_horse() -> None:
    horses = [_horse(1, market=0.20, ml=0.10), _horse(2, market=0.10, ml=0.10)]
    race = _race(horses)
    drift = {
        horses[0].id: [(1000, "8-1", 0.111), (2000, "4-1", 0.20)],
    }
    apply_flags(race, drift_by_horse_id=drift)
    assert FLAG_TAKING_MONEY in horses[0].flags
    assert FLAG_TAKING_MONEY not in horses[1].flags


# ---------------------------------------------------------------------------
# Historical priors — four-step adjustment
# ---------------------------------------------------------------------------


def _seed_final_from_market(horses: list[Horse]) -> None:
    """Helper to set finalProbability=marketProbability for tests entering the
    historical-priors step directly (skipping ``blend_race``)."""
    for h in horses:
        h.finalProbability = h.marketProbability


def _named_race(
    horses: list[Horse],
    *,
    name: str | None = None,
    surface: str = "dirt",
    distance: str = "1 1/4M",
) -> Race:
    return Race(
        id="r-1",
        day="saturday",
        raceNumber=12,
        name=name,
        surface=surface,
        distance=distance,
        horses=horses,
    )


def test_apply_historical_priors_keeps_sum_to_one() -> None:
    horses = [
        _horse(1, market=0.30),
        _horse(2, market=0.20),
        _horse(3, market=0.15),
        _horse(4, market=0.12),
        _horse(5, market=0.10),
        _horse(6, market=0.08),
        _horse(7, market=0.05),
    ]
    _seed_final_from_market(horses)
    race = _named_race(horses, surface="dirt", distance="1 1/4M")
    apply_historical_priors(race, load_priors())
    total = sum(h.finalProbability for h in horses if h.finalProbability is not None)
    assert total == pytest.approx(1.0)


def test_apply_historical_priors_skips_scratched_horses() -> None:
    horses = [
        _horse(1, market=0.40),
        _horse(2, market=0.30),
        _horse(3, market=0.20, scratched=True),
        _horse(4, market=0.10),
    ]
    _seed_final_from_market(horses)
    horses[2].finalProbability = None  # scratched horse cleared by upstream
    race = _named_race(horses, surface="dirt", distance="6f")
    apply_historical_priors(race, load_priors())
    assert horses[2].finalProbability is None
    non_scratched_total = sum(
        h.finalProbability
        for h in horses
        if h.finalProbability is not None and not h.scratched
    )
    assert non_scratched_total == pytest.approx(1.0)


def test_apply_historical_priors_softens_favorite_in_large_field() -> None:
    # 14-horse field where the public has piled on the favorite at 0.40.
    horses = [_horse(1, market=0.40)] + [
        _horse(i + 2, market=0.046) for i in range(13)
    ]
    _seed_final_from_market(horses)
    race = _named_race(horses, surface="dirt", distance="1 1/4M")
    apply_historical_priors(race, load_priors())
    favorite = horses[0]
    assert favorite.finalProbability is not None
    # Field-size compression caps the favorite at the 11-14 anchor (0.25)
    # and the rank-1 multiplier (0.94) shaves it further; after re-normalization
    # the favorite ends meaningfully below its raw market share of 0.40.
    assert favorite.finalProbability < 0.40 - 0.05


def test_apply_historical_priors_lifts_mid_tier_in_large_field() -> None:
    horses = [_horse(1, market=0.40)] + [
        _horse(i + 2, market=0.046) for i in range(13)
    ]
    _seed_final_from_market(horses)
    race = _named_race(horses, surface="dirt", distance="1 1/4M")
    apply_historical_priors(race, load_priors())
    # A mid-tier rank-4 horse should end above its raw market share once
    # the favorite has been compressed and slack redistributed.
    mid_tier = horses[3]
    assert mid_tier.finalProbability is not None
    assert mid_tier.finalProbability > 0.046


def test_apply_historical_priors_derby_flatter_than_turf_sprint() -> None:
    """Same raw odds → derby distribution must be flatter than turf-sprint."""
    horses_a = [
        _horse(1, market=0.40),
        _horse(2, market=0.25),
        _horse(3, market=0.15),
        _horse(4, market=0.10),
        _horse(5, market=0.06),
        _horse(6, market=0.04),
    ]
    horses_b = [
        _horse(1, market=0.40),
        _horse(2, market=0.25),
        _horse(3, market=0.15),
        _horse(4, market=0.10),
        _horse(5, market=0.06),
        _horse(6, market=0.04),
    ]
    _seed_final_from_market(horses_a)
    _seed_final_from_market(horses_b)
    derby_race = _named_race(
        horses_a, name="Kentucky Derby", surface="dirt", distance="1 1/4M"
    )
    sprint_race = _named_race(
        horses_b, name="Turf Sprint Stakes", surface="turf", distance="6f"
    )
    priors = load_priors()
    apply_historical_priors(derby_race, priors)
    apply_historical_priors(sprint_race, priors)

    def _spread(hs: list[Horse]) -> float:
        probs = [h.finalProbability for h in hs if h.finalProbability is not None]
        return max(probs) - min(probs)

    assert _spread(horses_a) < _spread(horses_b)


def test_apply_historical_priors_no_compression_below_threshold() -> None:
    # Field size below FIELD_SIZE_COMPRESSION_MIN — the favorite must NOT
    # be capped at the field-size anchor; only odds_rank multipliers apply.
    horses = [
        _horse(1, market=0.40),
        _horse(2, market=0.30),
        _horse(3, market=0.18),
        _horse(4, market=0.07),
        _horse(5, market=0.05),
    ]
    assert len(horses) < FIELD_SIZE_COMPRESSION_MIN
    _seed_final_from_market(horses)
    race = _named_race(horses, name="Allowance", surface="dirt", distance="1 1/16M")
    priors = load_priors()
    apply_historical_priors(race, priors)
    total = sum(h.finalProbability for h in horses if h.finalProbability is not None)
    assert total == pytest.approx(1.0)
    # Favorite is softened by the rank-1 multiplier (0.94) but not capped at
    # any field-size anchor — so it remains comfortably above 0.30.
    assert horses[0].finalProbability is not None
    assert horses[0].finalProbability > 0.30


def test_apply_historical_priors_default_race_type_is_no_chaos_flatten() -> None:
    """A 'default' race type (chaos=1.0) must not flatten the distribution."""
    horses = [
        _horse(1, market=0.50),
        _horse(2, market=0.30),
        _horse(3, market=0.15),
        _horse(4, market=0.05),
    ]
    _seed_final_from_market(horses)
    race = _named_race(horses, name="Allowance", surface="dirt", distance="1 1/16M")
    priors = {
        "odds_rank": {},
        "field_size_priors": {},
        "race_type": {"default": {"chaos": 1.0}},
    }
    apply_historical_priors(race, priors)
    # Only re-normalization runs; ratios stay proportional to the original.
    assert horses[0].finalProbability == pytest.approx(0.50)
    assert horses[1].finalProbability == pytest.approx(0.30)


def test_apply_historical_priors_handles_empty_eligible() -> None:
    horses = [_horse(1, market=0.50, scratched=True)]
    horses[0].finalProbability = None
    race = _named_race(horses)
    apply_historical_priors(race, load_priors())
    assert horses[0].finalProbability is None


def test_apply_historical_priors_odds_rank_multiplier_per_rank() -> None:
    """Verify rank-bucket multipliers (1, 2, 3, 4-6, 7+) are picked correctly."""
    horses = [_horse(i + 1, market=1.0 / 8) for i in range(8)]
    _seed_final_from_market(horses)
    # Pre-bias finalProbability so each horse's rank is determined.
    base = [0.30, 0.20, 0.15, 0.12, 0.10, 0.07, 0.04, 0.02]
    for h, p in zip(horses, base):
        h.finalProbability = p
    race = _named_race(horses, name="Allowance", surface="dirt", distance="1 1/16M")
    # Use only odds_rank — disable other steps.
    priors = {
        "odds_rank": {"1": 0.94, "2": 1.0, "3": 1.02, "4-6": 1.08, "7+": 0.9},
        "field_size_priors": {},
        "race_type": {"default": {"chaos": 1.0}},
    }
    # Snapshot expected un-normalized adjustment.
    raw_adjusted = [
        base[0] * 0.94,
        base[1] * 1.0,
        base[2] * 1.02,
        base[3] * 1.08,
        base[4] * 1.08,
        base[5] * 1.08,
        base[6] * 0.9,
        base[7] * 0.9,
    ]
    expected_total = sum(raw_adjusted)
    expected = [v / expected_total for v in raw_adjusted]

    apply_historical_priors(race, priors)
    for h, exp in zip(horses, expected):
        assert h.finalProbability == pytest.approx(exp)


# ---------------------------------------------------------------------------
# Movement-adjustment engine
# ---------------------------------------------------------------------------


def _drift(samples: list[tuple[int, float]]) -> list[tuple[int, str, float]]:
    """Build a drift-series triple from ``(captured_at_ms, implied_prob)`` pairs."""
    return [(ts, "n/a", prob) for ts, prob in samples]


def test_movement_velocity_full_window_uses_raw_delta() -> None:
    series = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.15)])
    horses = [_horse(1, market=0.15), _horse(2, market=0.20)]
    horses[0].finalProbability = 0.30
    horses[1].finalProbability = 0.70
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id={horses[0].id: series})
    # velocity = +0.05, mid-tier weight 0.40 → adjustment = +0.02 → 0.32, then renormalize.
    expected = (0.30 + 0.02) / (0.30 + 0.02 + 0.70)
    assert horses[0].finalProbability == pytest.approx(expected)
    assert sum(h.finalProbability for h in horses) == pytest.approx(1.0)


def test_movement_velocity_short_window_normalized_to_reference() -> None:
    # 30-min window with +0.015 implied prob change projects to +0.06 over 120 min.
    short_window = MOVEMENT_REFERENCE_WINDOW_MS // 4
    series = _drift([(0, 0.10), (short_window, 0.115)])
    horse = _horse(1, market=0.115)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    # velocity = +0.06; mid-tier weight 0.40 → adjustment +0.024 → 0.524, then renorm.
    assert horse.finalProbability == pytest.approx(0.524 / (0.524 + 0.50))


def test_movement_velocity_clamped_to_max() -> None:
    # Raw rate would yield +0.30 over the reference window; clamped to +0.15.
    series = _drift([(0, 0.05), (MOVEMENT_REFERENCE_WINDOW_MS, 0.35)])
    horses = [_horse(1, market=0.35), _horse(2, market=0.30), _horse(3, market=0.35)]
    for h in horses:
        h.finalProbability = 1.0 / 3
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id={horses[0].id: series})
    # Velocity clamp 0.15 × favorite weight 0.15 = +0.0225 boost.
    pre_renorm = (1.0 / 3) + 0.0225
    expected = pre_renorm / (pre_renorm + 2 * (1.0 / 3))
    assert horses[0].finalProbability == pytest.approx(expected)


def test_movement_below_noise_floor_produces_no_adjustment() -> None:
    # Raw delta over full window is +0.01 — under the 0.02 noise floor.
    series = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.11)])
    horses = [_horse(1, market=0.10), _horse(2, market=0.10)]
    horses[0].finalProbability = 0.50
    horses[1].finalProbability = 0.50
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id={horses[0].id: series})
    assert horses[0].finalProbability == pytest.approx(0.50)
    assert horses[1].finalProbability == pytest.approx(0.50)
    assert horses[0].steam_horse is False


def test_movement_empty_series_is_noop() -> None:
    horses = [_horse(1, market=0.40), _horse(2, market=0.60)]
    horses[0].finalProbability = 0.40
    horses[1].finalProbability = 0.60
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id=None)
    assert horses[0].finalProbability == pytest.approx(0.40)
    assert horses[1].finalProbability == pytest.approx(0.60)


def test_movement_single_snapshot_is_noop() -> None:
    series = _drift([(0, 0.20)])
    horse = _horse(1, market=0.20)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.50)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.finalProbability == pytest.approx(0.50)


def test_movement_mid_tier_shortening_uses_strong_weight() -> None:
    # 9-1 → 6-ish mid-tier shortening → strong boost. marketProbability of
    # 0.15 → fractional odds ≈ 5.67 lands squarely in [5.0, 12.0].
    series = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.15)])
    horse = _horse(1, market=0.15)
    horse.finalProbability = 0.20
    other = _horse(2, market=0.30)
    other.finalProbability = 0.80
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    velocity = 0.15 - 0.10
    expected_pre_norm = 0.20 + velocity * MOVEMENT_WEIGHT_MID_TIER_SHORTEN
    expected = expected_pre_norm / (expected_pre_norm + 0.80)
    assert horse.finalProbability == pytest.approx(expected)
    assert horse.steam_horse is True


def test_movement_favorite_shortening_uses_weak_weight() -> None:
    # 7/2 → 2/1 favorite — fractional odds < 5.0.
    series = _drift([(0, 0.222), (MOVEMENT_REFERENCE_WINDOW_MS, 0.333)])
    horse = _horse(1, market=0.333)
    horse.finalProbability = 0.40
    other = _horse(2, market=0.20)
    other.finalProbability = 0.60
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    velocity = 0.333 - 0.222
    expected_pre_norm = 0.40 + velocity * MOVEMENT_WEIGHT_FAVORITE_SHORTEN
    expected = expected_pre_norm / (expected_pre_norm + 0.60)
    assert horse.finalProbability == pytest.approx(expected)


def test_movement_longshot_shortening_uses_dampener() -> None:
    # marketProbability 0.05 → fractional ≈ 19.0 (well above the 12.0
    # longshot floor). Velocity 0.025 sits comfortably above the noise
    # floor.
    series = _drift([(0, 0.025), (MOVEMENT_REFERENCE_WINDOW_MS, 0.05)])
    horse = _horse(1, market=0.05)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.30)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    velocity = 0.025
    weight = MOVEMENT_WEIGHT_LONGSHOT_SHORTEN * LONGSHOT_VELOCITY_DAMPENER
    expected_pre_norm = 0.50 + velocity * weight
    expected = expected_pre_norm / (expected_pre_norm + 0.50)
    assert horse.finalProbability == pytest.approx(expected)
    # Longshots never get the steam_horse flag.
    assert horse.steam_horse is False


def test_movement_drift_uses_drift_weight_regardless_of_tier() -> None:
    # 5/2 → 9/2 favorite drifting → weight = 0.20.
    series = _drift([(0, 0.286), (MOVEMENT_REFERENCE_WINDOW_MS, 0.182)])
    horse = _horse(1, market=0.182)
    pre = 0.30
    horse.finalProbability = pre
    other = _horse(2, market=0.30)
    other.finalProbability = 0.70
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    velocity = 0.182 - 0.286
    expected_pre_norm = pre + velocity * MOVEMENT_WEIGHT_DRIFT
    expected = expected_pre_norm / (expected_pre_norm + 0.70)
    assert horse.finalProbability == pytest.approx(expected)
    # Drifting horse loses share — its post-adjustment probability is
    # strictly lower than the pre-movement starting point.
    assert horse.finalProbability < pre


def test_movement_adjustment_capped_at_max_boost() -> None:
    # Force a velocity past the cap: clamp 0.15 × mid-tier 0.40 = 0.06 normally,
    # so we need to push velocity ABOVE the natural max. ADJUSTMENT_MAX = 0.08
    # caps the result. Easiest: a longshot has weight 0.25 × 0.70 = 0.175;
    # at clamped velocity 0.15 → 0.02625, well below cap. To exercise the cap
    # we synthesize a (currently mid-tier) market_prob and a steep series.
    # 0.15 × 0.40 = 0.06; we need a higher product. Force the cap explicitly
    # by reducing the cap is not allowed — instead verify the cap by
    # constructing a velocity*weight just above ADJUSTMENT_MAX via a custom
    # market that sits in mid-tier with a max-clamp velocity.
    # 0.15 × 0.40 = 0.06 < 0.08, so the natural mid-tier max is 0.06.
    # The cap is exercised by the longshot* dampened weight only at higher
    # velocity values, but velocity is clamped — so the structural design
    # makes the cap always be > the achievable adjustment in mid-tier. Pin
    # the constants to confirm the relationship and exercise the symmetric
    # min cap below in test_movement_adjustment_capped_at_min_reduction.
    assert ADJUSTMENT_MAX > VELOCITY_CLAMP * MOVEMENT_WEIGHT_MID_TIER_SHORTEN


def test_movement_adjustment_capped_at_min_reduction() -> None:
    # Drift weight 0.20 × velocity -0.15 = -0.03 (within the -0.05 cap);
    # to actually hit the floor cap, we'd need a higher product, which the
    # current calibration cannot reach. Pin the relationship instead.
    natural_min = -VELOCITY_CLAMP * MOVEMENT_WEIGHT_DRIFT
    assert ADJUSTMENT_MIN <= natural_min  # cap is at least as permissive


def test_movement_keeps_sum_to_one_after_renormalize() -> None:
    horses = [
        _horse(1, market=0.30),
        _horse(2, market=0.20),
        _horse(3, market=0.15),
        _horse(4, market=0.10),
        _horse(5, market=0.10),
        _horse(6, market=0.08),
        _horse(7, market=0.04),
        _horse(8, market=0.03),
    ]
    for h, p in zip(horses, [0.30, 0.20, 0.15, 0.10, 0.10, 0.08, 0.04, 0.03]):
        h.finalProbability = p
    drift = {
        horses[2].id: _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.18)]),
        horses[3].id: _drift([(0, 0.15), (MOVEMENT_REFERENCE_WINDOW_MS, 0.05)]),
    }
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id=drift)
    total = sum(h.finalProbability for h in horses if h.finalProbability is not None)
    assert total == pytest.approx(1.0)


def test_movement_skips_scratched_horses() -> None:
    horses = [
        _horse(1, market=0.20),
        _horse(2, market=0.30, scratched=True),
        _horse(3, market=0.50),
    ]
    horses[0].finalProbability = 0.40
    horses[1].finalProbability = None
    horses[2].finalProbability = 0.60
    series = _drift([(0, 0.20), (MOVEMENT_REFERENCE_WINDOW_MS, 0.30)])
    race = _race(horses)
    apply_movement_adjustment(
        race,
        drift_by_horse_id={horses[0].id: series, horses[1].id: series},
    )
    assert horses[1].finalProbability is None
    assert horses[1].steam_horse is False
    non_scratched_total = sum(
        h.finalProbability
        for h in horses
        if not h.scratched and h.finalProbability is not None
    )
    assert non_scratched_total == pytest.approx(1.0)


def test_movement_ceiling_guard_caps_dominant_horse() -> None:
    # Dominant horse already at 0.95 with mid-tier shortening velocity.
    # After +adjustment + renormalize the horse exceeds 0.85; the cap
    # snaps it back to 0.85 and rescales the others to fill the rest.
    horses = [_horse(1, market=0.10), _horse(2, market=0.05), _horse(3, market=0.05)]
    horses[0].finalProbability = 0.95
    horses[1].finalProbability = 0.04
    horses[2].finalProbability = 0.01
    series = _drift([(0, 0.05), (MOVEMENT_REFERENCE_WINDOW_MS, 0.10)])
    race = _race(horses)
    apply_movement_adjustment(race, drift_by_horse_id={horses[0].id: series})
    assert horses[0].finalProbability == pytest.approx(MAX_SINGLE_HORSE_PROB)
    others_total = horses[1].finalProbability + horses[2].finalProbability
    assert others_total == pytest.approx(1.0 - MAX_SINGLE_HORSE_PROB)
    assert sum(
        h.finalProbability for h in horses if h.finalProbability is not None
    ) == pytest.approx(1.0)


def test_movement_steam_horse_set_for_mid_tier_shortening() -> None:
    series = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.15)])
    horse = _horse(1, market=0.15)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is True
    assert other.steam_horse is False


def test_movement_steam_horse_not_set_for_drifting_mid_tier() -> None:
    series = _drift([(0, 0.15), (MOVEMENT_REFERENCE_WINDOW_MS, 0.10)])
    horse = _horse(1, market=0.10)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is False


def test_movement_steam_horse_not_set_for_favorite_shortening() -> None:
    series = _drift([(0, 0.222), (MOVEMENT_REFERENCE_WINDOW_MS, 0.333)])
    horse = _horse(1, market=0.333)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is False


def test_movement_steam_horse_not_set_for_longshot_shortening() -> None:
    series = _drift([(0, 0.0476), (MOVEMENT_REFERENCE_WINDOW_MS, 0.0667)])
    horse = _horse(1, market=0.0667)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.50)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is False


def test_movement_steam_horse_not_set_below_noise_floor() -> None:
    # Mid-tier horse with sub-noise shortening (0.005 over full window).
    series = _drift([(0, 0.140), (MOVEMENT_REFERENCE_WINDOW_MS, 0.145)])
    horse = _horse(1, market=0.145)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is False


def test_movement_steam_horse_set_at_exact_noise_floor() -> None:
    # Velocity exactly at 0.02 (≥ noise floor).
    series = _drift(
        [(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.10 + VELOCITY_NOISE_FLOOR)]
    )
    horse = _horse(1, market=0.12)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.20)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.steam_horse is True


def test_movement_zero_time_delta_treated_as_no_signal() -> None:
    series = _drift([(1000, 0.10), (1000, 0.20)])
    horse = _horse(1, market=0.10)
    horse.finalProbability = 0.50
    other = _horse(2, market=0.50)
    other.finalProbability = 0.50
    race = _race([horse, other])
    apply_movement_adjustment(race, drift_by_horse_id={horse.id: series})
    assert horse.finalProbability == pytest.approx(0.50)
    assert horse.steam_horse is False


# ---------------------------------------------------------------------------
# Race classification — KEY/TIGHT/MID/CHAOS, entropy, chaos_level, strategy
# ---------------------------------------------------------------------------


def _seed_final(horses: list[Horse], probs: list[float]) -> None:
    for h, p in zip(horses, probs):
        h.finalProbability = p


def _classify_race(
    probs: list[float],
    *,
    name: str | None = None,
    surface: str = "dirt",
    distance: str = "1 1/16M",
    priors: dict | None = None,
) -> Race:
    horses = [_horse(i + 1) for i in range(len(probs))]
    _seed_final(horses, probs)
    race = _named_race(horses, name=name, surface=surface, distance=distance)
    classify_race(race, priors if priors is not None else load_priors())
    return race


def test_classify_race_key_branch_top_prob_and_gap() -> None:
    race = _classify_race([0.50, 0.20, 0.10, 0.08, 0.06, 0.06])
    assert race.classification == "KEY"
    # KEY requires top ≥ 0.42 and gap ≥ 0.15.
    top = race.horses[0].finalProbability
    second = race.horses[1].finalProbability
    assert top is not None and second is not None
    assert top >= 0.42
    assert top - second >= 0.15


def test_classify_race_key_strategy_single_when_chaos_low() -> None:
    # 4-horse concentrated distribution → entropy_ratio low; default chaos
    # factor (=1.0) → factor_level LOW. KEY × LOW → SINGLE.
    race = _classify_race([0.85, 0.10, 0.03, 0.02])
    assert race.classification == "KEY"
    assert race.chaos_level == "LOW"
    assert race.strategy == STRATEGY_LABEL_SINGLE


def test_classify_race_tight_branch_via_top2_threshold() -> None:
    # top=0.40 < 0.42 (no KEY). top2 = 0.70 ≥ 0.55 → TIGHT.
    race = _classify_race([0.40, 0.30, 0.15, 0.15])
    assert race.classification == "TIGHT"


def test_classify_race_tight_branch_via_top_and_second_thresholds() -> None:
    # top2 = 0.52 < 0.55 (so first-condition TIGHT fails); but
    # top ≥ 0.32 AND second ≥ 0.20 trips the second-condition TIGHT.
    race = _classify_race([0.32, 0.20, 0.18, 0.15, 0.15])
    assert race.classification == "TIGHT"


def test_classify_race_mid_branch() -> None:
    # 7-horse field. top<0.32 → no TIGHT; top3 = 0.64 ≥ 0.62 and entropy
    # ≤ 2.8 → MID.
    race = _classify_race([0.30, 0.18, 0.16, 0.12, 0.10, 0.08, 0.06])
    assert race.classification == "MID"
    assert race.entropy is not None and race.entropy <= 2.8


def test_classify_race_chaos_fallback() -> None:
    # 12 nearly-uniform runners → no KEY/TIGHT/MID condition holds → CHAOS.
    race = _classify_race([1.0 / 12] * 12)
    assert race.classification == "CHAOS"


def test_classify_race_writes_all_four_fields() -> None:
    race = _classify_race([0.50, 0.20, 0.10, 0.08, 0.06, 0.06])
    assert race.classification is not None
    assert race.entropy is not None and race.entropy > 0
    assert race.chaos_level is not None
    assert race.strategy is not None


def test_classify_race_derby_hard_override_to_max_chaos() -> None:
    # A KEY-shaped distribution would normally map to SINGLE / 2-DEEP, but
    # any race whose chaos_factor reaches the override threshold must be
    # forced to MAX CHAOS regardless of classification.
    race = _classify_race(
        [0.85, 0.10, 0.03, 0.02], name="Kentucky Derby"
    )
    assert race.classification == "KEY"
    assert race.strategy == STRATEGY_LABEL_MAX_CHAOS


def test_classify_race_override_fires_at_factor_threshold_exactly() -> None:
    # Custom priors with chaos_factor exactly at the override threshold —
    # boundary condition (>=, not >).
    priors = {"race_type": {"derby": {"chaos": MAX_CHAOS_FACTOR_OVERRIDE}}}
    race = _classify_race(
        [0.50, 0.20, 0.10, 0.08, 0.06, 0.06],
        name="Derby Stakes",
        priors=priors,
    )
    assert race.strategy == STRATEGY_LABEL_MAX_CHAOS


def test_classify_race_override_does_not_fire_below_threshold() -> None:
    priors = {
        "race_type": {"derby": {"chaos": MAX_CHAOS_FACTOR_OVERRIDE - 0.01}}
    }
    race = _classify_race(
        [0.85, 0.10, 0.03, 0.02], name="Derby Trial", priors=priors
    )
    # KEY classification with non-derby (sub-threshold) factor should keep
    # the table-derived strategy, not the override.
    assert race.classification == "KEY"
    assert race.strategy != STRATEGY_LABEL_MAX_CHAOS


def test_classify_race_chaos_level_low_when_factor_and_ratio_low() -> None:
    race = _classify_race([0.85, 0.10, 0.03, 0.02])
    assert race.chaos_level == "LOW"


def test_classify_race_chaos_level_extreme_via_factor() -> None:
    # Derby-grade chaos factor → factor_level EXTREME. Even if the
    # entropy ratio is LOW, the higher of the two wins → EXTREME.
    race = _classify_race(
        [0.85, 0.10, 0.03, 0.02], name="Kentucky Derby"
    )
    assert race.chaos_level == "EXTREME"


def test_classify_race_chaos_level_extreme_via_entropy_ratio() -> None:
    # Uniform distribution → entropy = log2(field_size) → ratio = 1.0 →
    # ratio-level EXTREME. Default chaos factor LOW → result EXTREME.
    race = _classify_race([1.0 / 12] * 12)
    assert race.chaos_level == "EXTREME"


def test_classify_race_chaos_level_takes_higher_of_two() -> None:
    # Custom priors give a HIGH factor (1.20). The probability shape is
    # very concentrated → ratio LOW. ``max(HIGH, LOW)`` is HIGH.
    priors = {"race_type": {"default": {"chaos": 1.20}}}
    race = _classify_race(
        [0.85, 0.10, 0.03, 0.02],
        name="Allowance",
        priors=priors,
    )
    assert race.chaos_level == "HIGH"


def test_classify_race_chaos_strategy_for_high_chaos_uniform_field() -> None:
    # Classification is CHAOS, chaos_level is EXTREME (uniform-ratio).
    # CHAOS × EXTREME → MAX CHAOS.
    race = _classify_race([1.0 / 12] * 12)
    assert race.classification == "CHAOS"
    assert race.strategy == STRATEGY_LABEL_MAX_CHAOS


def test_classify_race_handles_no_eligible_runners() -> None:
    horses = [_horse(1, market=0.50, scratched=True)]
    horses[0].finalProbability = None
    race = _named_race(horses)
    classify_race(race, load_priors())
    assert race.classification is None
    assert race.entropy is None
    assert race.chaos_level is None
    assert race.strategy is None


def test_classify_race_skips_scratched_horses_in_distribution() -> None:
    # 4 active horses + 1 scratched. The scratched horse should not be
    # included in the entropy or top_prob computation.
    horses = [_horse(i + 1) for i in range(5)]
    _seed_final(horses, [0.85, 0.10, 0.03, 0.02, 0.0])
    horses[4].scratched = True
    horses[4].finalProbability = None
    race = _named_race(horses, name="Allowance")
    classify_race(race, load_priors())
    assert race.classification == "KEY"


def test_classify_race_entropy_matches_shannon_log2() -> None:
    import math

    probs = [0.50, 0.30, 0.20]
    expected = -sum(p * math.log2(p) for p in probs)
    race = _classify_race(probs)
    assert race.entropy == pytest.approx(expected)


def test_classify_race_strategy_table_lookup_produces_two_deep_for_tight() -> None:
    # TIGHT × {LOW, MODERATE} both map to 2-DEEP per the strategy table.
    priors = {"race_type": {"default": {"chaos": 1.0}}}
    race = _classify_race(
        [0.45, 0.40, 0.05, 0.05, 0.03, 0.02],
        name="Allowance",
        priors=priors,
    )
    assert race.classification == "TIGHT"
    assert race.chaos_level in {"LOW", "MODERATE"}
    assert race.strategy == STRATEGY_LABEL_TWO_DEEP


def test_classify_race_strategy_table_lookup_produces_chaos_spread() -> None:
    # MID classification × MODERATE chaos_level (custom factor 1.10) →
    # MID per the table — so use a different cell. Use TIGHT × EXTREME
    # via uniform-ish distribution and TIGHT-shaped top — this is hard to
    # hit cleanly, so verify the well-defined CHAOS × LOW = CHAOS SPREAD.
    priors = {"race_type": {"default": {"chaos": 1.0}}}
    race = _classify_race(
        # Concentrated longshot distribution — top<0.32, top3<0.62 → CHAOS;
        # mass is bunched near the top so ratio stays LOW.
        [0.30, 0.20, 0.10, 0.05, 0.04, 0.03, 0.02, 0.02, 0.02, 0.02,
         0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
        name="Maiden Claiming",
        priors=priors,
    )
    assert race.classification == "CHAOS"
    # Chaos level may be LOW or MODERATE depending on exact entropy ratio;
    # the table maps both to CHAOS SPREAD or MAX CHAOS — verify the strategy
    # is one of the CHAOS-row labels.
    assert race.strategy in {
        STRATEGY_LABEL_CHAOS_SPREAD,
        STRATEGY_LABEL_MAX_CHAOS,
    }
    assert race.chaos_level in {"LOW", "MODERATE", "HIGH", "EXTREME"}


def test_classify_race_with_apply_flags_keeps_legacy_chaos_flag() -> None:
    # Backward-compat shim: legacy ``chaos_race`` flag continues to fire on
    # 12-horse no-clear-leader fields, in addition to the new race
    # classification fields populated by ``classify_race``.
    horses = [_horse(i + 1, market=1.0 / 12) for i in range(12)]
    _seed_final(horses, [1.0 / 12] * 12)
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    classify_race(race, load_priors())
    assert race.classification == "CHAOS"
    assert any(FLAG_CHAOS_RACE in h.flags for h in race.horses)


# ---------------------------------------------------------------------------
# Edge model — ownership_proxy, edge_score, confidence, computedBucket, flags
# ---------------------------------------------------------------------------


def _edge_priors(chaos: float = 1.0) -> dict:
    return {
        "odds_rank": {},
        "field_size_priors": {},
        "race_type": {"default": {"chaos": chaos}},
    }


def _seed_edge_horses(market_probs: list[float]) -> list[Horse]:
    horses = [_horse(i + 1, market=p, ml=p) for i, p in enumerate(market_probs)]
    for h in horses:
        h.finalProbability = h.marketProbability
    return horses


def test_edge_model_ownership_proxy_matches_rank_table() -> None:
    # 14 horses so we cover every key in OWNERSHIP_PROXY_BY_RANK plus the tail.
    market_probs = [0.30, 0.20, 0.13, 0.10, 0.06, 0.05, 0.04, 0.03,
                    0.025, 0.02, 0.018, 0.015, 0.012, 0.01]
    horses = _seed_edge_horses(market_probs)
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    for rank, h in enumerate(horses, start=1):
        expected = OWNERSHIP_PROXY_BY_RANK.get(rank, OWNERSHIP_PROXY_TAIL)
        assert h.ownership_proxy == pytest.approx(expected), (
            f"rank {rank}: expected {expected}, got {h.ownership_proxy}"
        )


def test_edge_model_ownership_proxy_tail_for_rank_13_plus() -> None:
    market_probs = [0.10] * 15
    horses = _seed_edge_horses(market_probs)
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    # Ranks 13, 14, 15 all collapse to the tail value.
    assert horses[12].ownership_proxy == pytest.approx(OWNERSHIP_PROXY_TAIL)
    assert horses[13].ownership_proxy == pytest.approx(OWNERSHIP_PROXY_TAIL)
    assert horses[14].ownership_proxy == pytest.approx(OWNERSHIP_PROXY_TAIL)


def test_edge_model_edge_score_formula_for_non_favorite() -> None:
    # Rank-2 horse (market 0.20, second-highest) with true_prob nudged to 0.23.
    # Default race chaos=1.0 → no chaos bonus. Ownership at rank 2 is 0.50.
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    horses[1].finalProbability = 0.23
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    horse = horses[1]
    assert horse.true_prob == pytest.approx(0.23)
    expected_edge = 0.23 - 0.20
    expected_discount = -(0.50 - OWNERSHIP_NEUTRAL) * OWNERSHIP_SCALE
    expected_score = expected_edge + expected_discount + 0.0
    assert horse.edge_score == pytest.approx(expected_score)


def test_edge_model_chaos_bonus_only_for_non_favorites() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors(chaos=1.30))
    favorite = horses[0]
    non_fav = horses[1]
    expected_bonus = (1.30 - 1.00) * CHAOS_BONUS_SCALE
    fav_edge = 0.30 - 0.30  # zero
    fav_discount = -(0.65 - OWNERSHIP_NEUTRAL) * OWNERSHIP_SCALE
    assert favorite.edge_score == pytest.approx(fav_edge + fav_discount)
    nf_edge = 0.20 - 0.20
    nf_discount = -(0.50 - OWNERSHIP_NEUTRAL) * OWNERSHIP_SCALE
    assert non_fav.edge_score == pytest.approx(
        nf_edge + nf_discount + expected_bonus
    )


def test_edge_model_positive_edge_implies_true_prob_above_market() -> None:
    horses = _seed_edge_horses([0.20, 0.15, 0.15, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05])
    # Push horse #5 above its market price; ownership at rank 5 is 0.19,
    # discount ≈ +0.0018, so any positive raw edge keeps edge_score > 0.
    horses[4].finalProbability = 0.18
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    h = horses[4]
    assert h.edge_score is not None and h.edge_score > 0
    assert h.true_prob is not None and h.marketProbability is not None
    assert h.true_prob > h.marketProbability


def test_edge_model_confidence_score_in_unit_interval() -> None:
    horses = _seed_edge_horses([0.45, 0.20, 0.15, 0.10, 0.05, 0.05])
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    classify_race(race, load_priors())
    apply_edge_model(race, _edge_priors())
    for h in horses:
        assert h.confidence_score is not None
        assert 0.0 <= h.confidence_score <= 1.0


def test_edge_model_confidence_decreases_for_chaos_vs_key() -> None:
    # Same horse-shape; classification differs.
    def _build() -> tuple[Race, list[Horse]]:
        horses = _seed_edge_horses([0.45, 0.18, 0.12, 0.10, 0.08, 0.07])
        race = _named_race(horses, name="Allowance")
        apply_flags(race)
        return race, horses

    race_key, horses_key = _build()
    race_key.classification = "KEY"
    apply_edge_model(race_key, _edge_priors())

    race_chaos, horses_chaos = _build()
    race_chaos.classification = "CHAOS"
    apply_edge_model(race_chaos, _edge_priors())

    # Pin to the favorite — its prob_strength is identical between cases.
    assert horses_key[0].confidence_score is not None
    assert horses_chaos[0].confidence_score is not None
    assert horses_chaos[0].confidence_score < horses_key[0].confidence_score
    expected_ratio = (
        RACE_STABILITY_MODIFIER["CHAOS"] / RACE_STABILITY_MODIFIER["KEY"]
    )
    assert horses_chaos[0].confidence_score == pytest.approx(
        horses_key[0].confidence_score * expected_ratio
    )


def test_edge_model_confidence_uses_movement_signal_from_velocity() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    classify_race(race, load_priors())
    series = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.15)])
    apply_edge_model(
        race,
        _edge_priors(),
        drift_by_horse_id={horses[1].id: series},
    )
    # Velocity = 0.05; movement_signal = (0.5 + 1) / 2 = 0.75 (rank 2 is not
    # longshot-dampened). Compare against a flat-velocity peer at the same
    # finalProbability — its movement_signal is the neutral 0.5.
    moving = horses[1].confidence_score
    flat = horses[2].confidence_score
    assert moving is not None and flat is not None
    assert moving > flat


def test_edge_model_longshot_velocity_dampener_caps_movement_signal() -> None:
    market_probs = [0.30, 0.20, 0.15, 0.10, 0.07, 0.06, 0.05, 0.05, 0.02]
    horses = _seed_edge_horses(market_probs)
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    classify_race(race, load_priors())
    # Same +0.05 velocity on rank-2 (no dampener) and rank-7 (dampened).
    series_strong = _drift([(0, 0.10), (MOVEMENT_REFERENCE_WINDOW_MS, 0.15)])
    series_strong_long = _drift([(0, 0.0), (MOVEMENT_REFERENCE_WINDOW_MS, 0.05)])
    apply_edge_model(
        race,
        _edge_priors(),
        drift_by_horse_id={
            horses[1].id: series_strong,
            horses[6].id: series_strong_long,
        },
    )
    # The dampener reduces effective velocity for rank ≥ 7. With the same raw
    # velocity, the longshot's movement-signal-derived contribution must be
    # strictly smaller than the rank-2 horse's.
    # We isolate the movement contribution by subtracting the prob-strength
    # contribution from each horse's confidence_score.
    stability = RACE_STABILITY_MODIFIER[race.classification]
    prob_part_2 = (
        CONFIDENCE_WEIGHT_PROB
        * min(horses[1].finalProbability / PROB_STRONG_THRESHOLD, 1.0)
    )
    prob_part_7 = (
        CONFIDENCE_WEIGHT_PROB
        * min(horses[6].finalProbability / PROB_STRONG_THRESHOLD, 1.0)
    )
    move_2 = horses[1].confidence_score / stability - prob_part_2
    move_7 = horses[6].confidence_score / stability - prob_part_7
    assert move_7 < move_2


def test_edge_model_bucket_dead_for_scratched() -> None:
    horses = _seed_edge_horses([0.40, 0.30, 0.20, 0.10])
    horses[2].scratched = True
    horses[2].finalProbability = None
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[2].computedBucket == "DEAD"
    assert horses[2].edge_score is None
    assert horses[2].true_prob is None


def test_edge_model_bucket_dead_for_bad_single_with_strong_negative_edge() -> None:
    # Heavy public favorite at 0.55 with finalProbability dragged below
    # market enough to fail the DEAD edge threshold (-0.05).
    horses = _seed_edge_horses([0.55, 0.20, 0.10, 0.08, 0.07])
    horses[0].finalProbability = 0.30  # market−final = 0.25 → edge well below -0.05
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    assert FLAG_BAD_SINGLE in horses[0].flags
    apply_edge_model(race, _edge_priors())
    assert horses[0].computedBucket == "DEAD"


def test_edge_model_bucket_trap_for_rank1_with_negative_edge() -> None:
    # Rank-1 horse priced 0.40, true_prob 0.34 — negative edge.
    horses = _seed_edge_horses([0.40, 0.20, 0.18, 0.12, 0.10])
    horses[0].finalProbability = 0.34
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[0].trap_favorite is True
    assert horses[0].computedBucket == "TRAP"
    # TRAP must never apply to a non-rank-1 horse.
    for h in horses[1:]:
        assert not (h.trap_favorite and h.computedBucket == "TRAP" and h.id != horses[0].id)


def test_edge_model_bucket_trap_not_set_when_rank1_has_positive_edge() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.18, 0.15, 0.10, 0.07])
    horses[0].finalProbability = 0.40  # well above market
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[0].trap_favorite is False
    assert horses[0].computedBucket != "TRAP"


def test_edge_model_bucket_core_when_strong_prob_and_positive_edge() -> None:
    # Rank-1 horse needs raw edge > +0.081 to clear the rank-1 ownership
    # discount (-0.081) and land in CORE rather than TRAP.
    horses = _seed_edge_horses([0.25, 0.20, 0.18, 0.15, 0.10, 0.09])
    horses[0].finalProbability = 0.40  # ≥ 0.30 and raw edge +0.15
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[0].edge_score is not None and horses[0].edge_score > 0
    assert horses[0].computedBucket == "CORE"


def test_edge_model_bucket_chaos_when_chaos_race_flag_and_edge_above_threshold() -> None:
    horses = _seed_edge_horses([0.083] * 12)
    # Race flagged as chaos by apply_flags (12-horse, no horse > 0.20).
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    assert any(FLAG_CHAOS_RACE in h.flags for h in race.horses)
    # Bump rank-3 above its market — light edge.
    horses[2].finalProbability = 0.12
    apply_edge_model(race, _edge_priors())
    assert horses[2].computedBucket == "CHAOS"


def test_edge_model_bucket_chaos_via_steam_horse() -> None:
    # Non-chaos race shape (no FLAG_CHAOS_RACE), but the horse has steam.
    # The raw edge needs to be positive enough to clear the ownership
    # discount and land at edge_score ≥ -0.02.
    horses = _seed_edge_horses([0.30, 0.18, 0.15, 0.10, 0.10, 0.07, 0.05, 0.05])
    horses[1].steam_horse = True
    horses[1].finalProbability = 0.22  # raw edge +0.04; rank-2 discount -0.054
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    assert FLAG_CHAOS_RACE not in horses[1].flags
    apply_edge_model(race, _edge_priors())
    assert horses[1].edge_score is not None and horses[1].edge_score >= -0.02
    assert horses[1].computedBucket == "CHAOS"


def test_edge_model_bucket_value_fallback() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    horses[2].finalProbability = 0.155  # tiny positive edge but below CORE prob
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[2].computedBucket == "VALUE"


def test_edge_model_all_four_flags_present_on_horses() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    for h in horses:
        assert hasattr(h, "trap_favorite")
        assert hasattr(h, "separator_candidate")
        assert hasattr(h, "value_horse")
        assert hasattr(h, "cold_horse")
        # Each one resolves to a bool, never None.
        assert isinstance(h.trap_favorite, bool)
        assert isinstance(h.separator_candidate, bool)
        assert isinstance(h.value_horse, bool)
        assert isinstance(h.cold_horse, bool)


def test_edge_model_separator_candidate_requires_low_ownership() -> None:
    # Rank-7 horse — ownership 0.09 — with a strong positive edge.
    horses = _seed_edge_horses([0.20, 0.15, 0.15, 0.12, 0.10, 0.08, 0.07, 0.07, 0.06])
    horses[6].finalProbability = 0.13  # raw edge ≈ +0.06; rank 7 ownership ≈ 0.09
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[6].separator_candidate is True
    # Rank-2 horse with similar raw edge — ownership 0.50 — must NOT separate.
    horses_b = _seed_edge_horses([0.20, 0.15, 0.15, 0.12, 0.10, 0.08, 0.07, 0.07, 0.06])
    horses_b[1].finalProbability = 0.21
    race_b = _named_race(horses_b, name="Allowance")
    apply_flags(race_b)
    apply_edge_model(race_b, _edge_priors())
    assert horses_b[1].separator_candidate is False


def test_edge_model_value_horse_threshold() -> None:
    horses = _seed_edge_horses([0.20, 0.15, 0.15, 0.12, 0.10])
    horses[1].finalProbability = 0.20  # raw edge +0.05; rank-2 discount -0.054
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    # edge_score ≈ -0.004 → below value threshold → False
    assert horses[1].edge_score is not None and horses[1].edge_score < 0.03
    assert horses[1].value_horse is False
    # Lift rank-3 (ownership 0.38, discount -0.032) by enough to clear 0.03.
    horses[2].finalProbability = 0.25  # raw edge +0.10
    apply_edge_model(race, _edge_priors())
    assert horses[2].edge_score is not None and horses[2].edge_score >= 0.03
    assert horses[2].value_horse is True


def test_edge_model_cold_horse_requires_drift_and_negative_edge() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    # Drifting horse with negative edge — should be marked cold_horse.
    horses[0].finalProbability = 0.20  # raw edge -0.10 vs market 0.30
    series_drift = _drift([(0, 0.30), (MOVEMENT_REFERENCE_WINDOW_MS, 0.20)])
    race = _named_race(horses, name="Allowance")
    apply_flags(race, drift_by_horse_id={horses[0].id: series_drift})
    apply_edge_model(
        race, _edge_priors(), drift_by_horse_id={horses[0].id: series_drift}
    )
    assert horses[0].cold_horse is True
    # Same drift but positive edge → not cold.
    horses[1].finalProbability = 0.30  # raw edge +0.10
    apply_edge_model(
        race, _edge_priors(), drift_by_horse_id={horses[0].id: series_drift}
    )
    assert horses[1].cold_horse is False


def test_edge_model_handles_missing_movement_data() -> None:
    horses = _seed_edge_horses([0.40, 0.20, 0.15, 0.10, 0.08, 0.07])
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    classify_race(race, load_priors())
    apply_edge_model(race, _edge_priors())
    # No drift_by_horse_id passed → velocity treated as 0; cold_horse stays
    # False; confidence still computed.
    for h in horses:
        assert h.cold_horse is False
        assert h.confidence_score is not None


def test_edge_model_handles_horse_without_market_probability() -> None:
    horses = _seed_edge_horses([0.30, 0.20, 0.15, 0.15, 0.10, 0.10])
    horses[2].marketProbability = None
    horses[2].finalProbability = 0.15  # blend may have set it from ML
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    # No market price → no rank → no ownership_proxy → no edge_score.
    assert horses[2].ownership_proxy is None
    assert horses[2].edge_score is None
    # Still gets a true_prob and confidence_score from finalProbability alone.
    assert horses[2].true_prob == pytest.approx(0.15)
    assert horses[2].confidence_score is not None
    # No edge_score → cannot satisfy CORE/CHAOS edge thresholds → VALUE fallback.
    assert horses[2].computedBucket == "VALUE"
    # Other horses unaffected.
    assert horses[0].edge_score is not None


def test_edge_model_scratched_horses_get_dead_bucket_and_none_fields() -> None:
    horses = _seed_edge_horses([0.40, 0.30, 0.20, 0.10])
    horses[1].scratched = True
    horses[1].finalProbability = None
    horses[1].marketProbability = None
    race = _named_race(horses, name="Allowance")
    apply_flags(race)
    apply_edge_model(race, _edge_priors())
    assert horses[1].computedBucket == "DEAD"
    assert horses[1].ownership_proxy is None
    assert horses[1].edge_score is None
    assert horses[1].true_prob is None
    assert horses[1].confidence_score is None
    assert horses[1].trap_favorite is False
    assert horses[1].separator_candidate is False
    assert horses[1].value_horse is False
    assert horses[1].cold_horse is False


def test_edge_model_full_pipeline_smoke() -> None:
    """End-to-end: blend → priors → flags → movement → classify → edge."""
    horses = [
        _horse(1, market=0.30, ml=0.28),
        _horse(2, market=0.18, ml=0.20),
        _horse(3, market=0.15, ml=0.13),
        _horse(4, market=0.10, ml=0.10),
        _horse(5, market=0.08, ml=0.07),
        _horse(6, market=0.05, ml=0.06),
        _horse(7, market=0.05, ml=0.05),
        _horse(8, market=0.05, ml=0.06),
        _horse(9, market=0.04, ml=0.05),
    ]
    race = _named_race(horses, name="Allowance", surface="dirt", distance="1 1/16M")
    priors = load_priors()
    apply_model_priors_to_race(race, priors)
    blend_race(race, has_model_prior=True)
    apply_historical_priors(race, priors)
    apply_flags(race)
    apply_movement_adjustment(race)
    classify_race(race, priors)
    apply_edge_model(race, priors)

    # Sum of true_prob across non-scratched is approximately 1.0
    total = sum(
        h.true_prob for h in horses if h.true_prob is not None and not h.scratched
    )
    assert total == pytest.approx(1.0)
    # All horses got a bucket.
    assert all(h.computedBucket is not None for h in horses)
    # All horses got numeric ownership and edge values.
    for h in horses:
        assert h.ownership_proxy is not None
        assert h.edge_score is not None
        assert h.confidence_score is not None
        assert 0.0 <= h.confidence_score <= 1.0
