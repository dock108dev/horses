"""Tests for the probability blending, priors, flags, and boost/fade layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.model import (
    BLEND_WEIGHT_MARKET,
    BLEND_WEIGHT_MARKET_FALLBACK,
    BLEND_WEIGHT_ML,
    BLEND_WEIGHT_ML_FALLBACK,
    BLEND_WEIGHT_MODEL,
    DEFAULT_PRIORS_PATH,
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
    Horse,
    Race,
    apply_flags,
    apply_model_priors_to_race,
    apply_user_boost_fade,
    blend_probabilities,
    blend_race,
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
    assert "large_field_dirt_route" in priors["race_type_priors"]
    assert "small_field_chalk" in priors["race_type_priors"]
    assert set(priors["field_size_priors"].keys()) == {"6-7", "8-10", "11-14", "15+"}


def test_load_priors_handles_missing_top_level_keys(tmp_path: Path) -> None:
    p = tmp_path / "priors.json"
    p.write_text(json.dumps({}))
    priors = load_priors(p)
    assert priors == {"race_type_priors": {}, "field_size_priors": {}}


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
# User boost / fade
# ---------------------------------------------------------------------------


def test_apply_user_boost_fade_renormalizes_after_scaling() -> None:
    horses = [
        _horse(1, market=0.40, user_tag="boost"),
        _horse(2, market=0.30),
        _horse(3, market=0.20, user_tag="fade"),
        _horse(4, market=0.10),
    ]
    for h in horses:
        h.finalProbability = h.marketProbability
    race = _race(horses)
    apply_user_boost_fade(race)
    total = sum(h.finalProbability for h in horses if h.finalProbability is not None)
    assert total == pytest.approx(1.0)
    # boost lifted horse 1's relative share, fade dropped horse 3's.
    assert horses[0].finalProbability is not None and horses[0].finalProbability > 0.40
    assert horses[2].finalProbability is not None and horses[2].finalProbability < 0.20


def test_apply_user_boost_fade_no_op_without_tags() -> None:
    horses = [_horse(1, market=0.50), _horse(2, market=0.50)]
    for h in horses:
        h.finalProbability = h.marketProbability
    race = _race(horses)
    apply_user_boost_fade(race)
    assert horses[0].finalProbability == pytest.approx(0.50)
    assert horses[1].finalProbability == pytest.approx(0.50)


def test_apply_user_boost_fade_skips_horses_without_final_probability() -> None:
    horses = [_horse(1, market=0.60, user_tag="boost"), _horse(2, market=0.40)]
    horses[0].finalProbability = 0.60
    # horse 2 has no finalProbability — function must not crash.
    race = _race(horses)
    apply_user_boost_fade(race)
    assert horses[0].finalProbability == pytest.approx(1.0)
    assert horses[1].finalProbability is None
