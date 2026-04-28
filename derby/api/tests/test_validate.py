"""Tests for the post-refresh card validation layer."""

from __future__ import annotations

from api.model import PICK5_LEG_ROLES, Horse, Race
from api.validate import (
    PROBABILITY_TOLERANCE,
    ValidationResult,
    validate_card,
)


DAY = "saturday"
LEG_RACE_NUMBERS = (9, 10, 11, 12, 13)


def _race_id(num: int) -> str:
    return f"CD-2026-05-02-R{num:02d}"


def _horse(
    race_num: int,
    post: int,
    name: str,
    *,
    ml: str | None = "5/2",
    current: str | None = "3/1",
    scratched: bool = False,
    market_prob: float | None = None,
    ml_prob: float | None = None,
    suffix: str = "",
) -> Horse:
    return Horse(
        id=f"{_race_id(race_num)}-p{post:02d}{suffix}",
        raceId=_race_id(race_num),
        post=post,
        name=name,
        morningLineOdds=ml,
        currentOdds=current,
        scratched=scratched,
        marketProbability=market_prob,
        morningLineProbability=ml_prob,
    )


def _race(
    race_num: int,
    leg_index: int,
    horses: list[Horse],
) -> Race:
    return Race(
        id=_race_id(race_num),
        day=DAY,
        raceNumber=race_num,
        sequenceRole=PICK5_LEG_ROLES[leg_index],
        horses=horses,
    )


def _balanced_horses(race_num: int, n: int = 4) -> list[Horse]:
    """Build ``n`` horses whose marketProbability sums to exactly 1.0."""
    each = 1.0 / n
    return [
        _horse(race_num, post, f"Horse {race_num}-{post}", market_prob=each)
        for post in range(1, n + 1)
    ]


def _full_card() -> list[Race]:
    return [
        _race(num, i, _balanced_horses(num))
        for i, num in enumerate(LEG_RACE_NUMBERS)
    ]


# ---------- valid card ----------


def test_valid_complete_card_returns_valid_true_no_errors() -> None:
    result = validate_card(_full_card(), DAY)
    assert isinstance(result, ValidationResult)
    assert result.valid is True
    assert result.errors == []


def test_valid_card_accepts_morning_line_only_horses() -> None:
    races = _full_card()
    for h in races[0].horses:
        h.currentOdds = None
    result = validate_card(races, DAY)
    assert result.valid is True


def test_valid_card_accepts_scratched_horse_without_odds() -> None:
    races = _full_card()
    races[0].horses.append(
        _horse(
            LEG_RACE_NUMBERS[0],
            5,
            "Scratched Star",
            ml=None,
            current=None,
            scratched=True,
            suffix="-scr",
        )
    )
    result = validate_card(races, DAY)
    assert result.valid is True


# ---------- AC: missing odds ----------


def test_missing_odds_reports_count_and_race_number() -> None:
    races = _full_card()
    races[0].horses[0].morningLineOdds = None
    races[0].horses[0].currentOdds = None
    races[0].horses[0].marketProbability = None
    races[0].horses[0].morningLineProbability = None
    races[0].horses[1].morningLineOdds = None
    races[0].horses[1].currentOdds = None
    races[0].horses[1].marketProbability = None
    races[0].horses[1].morningLineProbability = None
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any(
        f"Race {LEG_RACE_NUMBERS[0]} missing odds for 2 horses" in e
        for e in result.errors
    )


def test_missing_odds_singular_horse_uses_horse_not_horses() -> None:
    races = _full_card()
    races[0].horses[0].morningLineOdds = None
    races[0].horses[0].currentOdds = None
    races[0].horses[0].marketProbability = None
    races[0].horses[0].morningLineProbability = None
    result = validate_card(races, DAY)
    assert any(
        f"Race {LEG_RACE_NUMBERS[0]} missing odds for 1 horse" in e
        for e in result.errors
    )


def test_unparseable_odds_count_as_missing() -> None:
    races = _full_card()
    races[0].horses[0].morningLineOdds = "SCR"
    races[0].horses[0].currentOdds = "--"
    races[0].horses[0].marketProbability = None
    races[0].horses[0].morningLineProbability = None
    result = validate_card(races, DAY)
    assert any("missing odds for 1 horse" in e for e in result.errors)


# ---------- AC: missing Pick 5 leg ----------


def test_fewer_than_five_legs_reports_each_missing_leg() -> None:
    races = _full_card()[:3]  # only legs 1, 2, 3 present
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any("Pick 5 leg 4 not found" in e for e in result.errors)
    assert any("Pick 5 leg 5 not found" in e for e in result.errors)


def test_no_pick5_legs_reports_all_five() -> None:
    result = validate_card([], DAY)
    assert result.valid is False
    for n in range(1, 6):
        assert any(f"Pick 5 leg {n} not found" in e for e in result.errors)


# ---------- AC: duplicate (raceId, post) ----------


def test_duplicate_post_in_same_race_flagged() -> None:
    races = _full_card()
    races[0].horses.append(
        _horse(
            LEG_RACE_NUMBERS[0],
            1,
            "Doppel Ganger",
            market_prob=0.0,
            suffix="-dup",
        )
    )
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any(
        f"Race {LEG_RACE_NUMBERS[0]} has duplicate horses at post 1" in e
        for e in result.errors
    )


def test_same_post_in_different_races_is_not_duplicate() -> None:
    races = _full_card()  # every race uses posts 1..4 — that is fine
    result = validate_card(races, DAY)
    assert result.valid is True


# ---------- AC: probability sum tolerance ----------


def test_probability_sum_above_tolerance_flagged() -> None:
    races = _full_card()
    for h in races[0].horses:
        h.marketProbability = 0.30  # 4 * 0.30 = 1.20
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any(
        f"Race {LEG_RACE_NUMBERS[0]} marketProbability sum" in e
        for e in result.errors
    )


def test_probability_sum_below_tolerance_flagged() -> None:
    races = _full_card()
    for h in races[0].horses:
        h.marketProbability = 0.20  # 4 * 0.20 = 0.80
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any("marketProbability sum 0.800" in e for e in result.errors)


def test_probability_sum_within_tolerance_passes() -> None:
    races = _full_card()
    # 4 * 0.252 = 1.008, well inside the ±0.01 tolerance
    for h in races[0].horses:
        h.marketProbability = 0.252
    result = validate_card(races, DAY)
    assert result.valid is True


def test_scratched_horse_excluded_from_probability_sum() -> None:
    races = _full_card()
    races[0].horses.append(
        _horse(
            LEG_RACE_NUMBERS[0],
            5,
            "Scratched Star",
            ml=None,
            current=None,
            scratched=True,
            market_prob=0.5,  # would push the sum to 1.5
            suffix="-scr",
        )
    )
    result = validate_card(races, DAY)
    assert result.valid is True


def test_morning_line_probability_sum_also_checked() -> None:
    races = _full_card()
    # Replace marketProbability with morningLineProbability so the
    # market check is skipped (no values) but the ML check fires.
    for h in races[0].horses:
        h.marketProbability = None
        h.morningLineProbability = 0.30  # sum 1.20
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any(
        "morningLineProbability sum" in e for e in result.errors
    )


# ---------- AC: errors non-empty whenever valid is False ----------


def test_errors_non_empty_whenever_invalid() -> None:
    result = validate_card([], DAY)
    assert result.valid is False
    assert len(result.errors) > 0


# ---------- supplemental: name and day handling ----------


def test_empty_horse_name_flagged() -> None:
    races = _full_card()
    races[0].horses[0].name = "   "
    result = validate_card(races, DAY)
    assert result.valid is False
    assert any(
        f"Race {LEG_RACE_NUMBERS[0]} missing name" in e
        for e in result.errors
    )


def test_day_filter_excludes_other_day_races() -> None:
    saturday = _full_card()
    friday_extra = Race(
        id="CD-2026-05-01-R09",
        day="friday",
        raceNumber=9,
        sequenceRole="pick5-leg-1",
        horses=[],
    )
    result = validate_card([friday_extra, *saturday], DAY)
    assert result.valid is True


def test_validation_result_is_immutable() -> None:
    result = validate_card([], DAY)
    try:
        result.valid = True  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ValidationResult should be frozen")


def test_probability_tolerance_constant() -> None:
    assert PROBABILITY_TOLERANCE == 0.01
