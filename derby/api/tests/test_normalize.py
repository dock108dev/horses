"""Tests for the normalization layer (odds parsing, merging, leg tagging)."""

from __future__ import annotations

import math

import pytest

from api.model import PICK5_LEG_COUNT, Horse, Race
from api.normalize import (
    MISSING_LIVE_ODDS_FLAG,
    NAME_MATCH_CUTOFF,
    assign_pick5_sequence_roles,
    merge_horses,
    normalize_horse_name,
    normalize_probabilities,
    odds_to_probability,
)


RACE_ID = "CD-2026-05-02-R09"


def _eq_horse(
    post: int,
    name: str,
    *,
    ml: str | None = None,
    scratched: bool = False,
    flags: list[str] | None = None,
) -> Horse:
    return Horse(
        id=f"{RACE_ID}-p{post:02d}",
        raceId=RACE_ID,
        post=post,
        name=name,
        morningLineOdds=ml,
        scratched=scratched,
        source="equibase",
        flags=list(flags or []),
    )


def _ts_horse(
    post: int,
    name: str,
    *,
    pn: str | None = None,
    current: str | None = None,
    scratched: bool = False,
) -> Horse:
    pn = pn or str(post)
    return Horse(
        id=f"{RACE_ID}-{pn}",
        raceId=RACE_ID,
        post=post,
        name=name,
        currentOdds=current,
        scratched=scratched,
        source="twinspires",
    )


# ---------- odds_to_probability ----------


def test_fractional_5_2_parses_to_0_2857() -> None:
    assert odds_to_probability("5/2") == pytest.approx(0.2857, abs=1e-4)


def test_integer_to_one_3_1_parses_to_0_25() -> None:
    assert odds_to_probability("3-1") == pytest.approx(0.25, abs=1e-9)


def test_integer_to_one_10_1_parses_to_0_0909() -> None:
    assert odds_to_probability("10/1") == pytest.approx(0.0909, abs=1e-4)


def test_evs_token_parses_to_0_5() -> None:
    assert odds_to_probability("EVS") == 0.5
    assert odds_to_probability("evs") == 0.5
    assert odds_to_probability("Even") == 0.5


def test_odds_on_1_2_parses_to_0_6667() -> None:
    # 1/2 → decimal 0.5 → 1/(0.5+1) = 0.6667
    assert odds_to_probability("1/2") == pytest.approx(0.6667, abs=1e-4)


def test_decimal_string_parses_via_payout_ratio() -> None:
    # "4.80" treated as 4.80-to-1 → 1/(4.80+1) = 1/5.80 ≈ 0.1724
    assert odds_to_probability("4.80") == pytest.approx(1 / 5.80, abs=1e-6)


def test_dash_separator_normalizes_like_slash() -> None:
    assert odds_to_probability("5-2") == odds_to_probability("5/2")


def test_handles_none_blank_and_garbage_gracefully() -> None:
    assert odds_to_probability(None) is None
    assert odds_to_probability("") is None
    assert odds_to_probability("   ") is None
    assert odds_to_probability("SCR") is None
    assert odds_to_probability("--") is None


def test_zero_denominator_returns_none() -> None:
    assert odds_to_probability("5/0") is None


def test_accepts_numeric_input() -> None:
    assert odds_to_probability(3) == pytest.approx(0.25, abs=1e-9)
    assert odds_to_probability(2.5) == pytest.approx(0.2857, abs=1e-4)


# ---------- normalize_probabilities ----------


def test_market_probabilities_sum_to_one_after_normalization() -> None:
    horses = [
        _eq_horse(1, "Alpha"),
        _eq_horse(2, "Bravo"),
        _eq_horse(3, "Charlie"),
    ]
    horses[0].marketProbability = 0.40  # raw = 0.40 + overround
    horses[1].marketProbability = 0.35
    horses[2].marketProbability = 0.30  # sum 1.05 → 5% overround

    normalize_probabilities(horses, field="marketProbability")
    total = sum(h.marketProbability or 0.0 for h in horses)
    assert math.isclose(total, 1.0, abs_tol=1e-3)


def test_scratched_horses_excluded_from_normalization_denominator() -> None:
    horses = [
        _eq_horse(1, "Alpha"),
        _eq_horse(2, "Bravo"),
        _eq_horse(3, "Scratched", scratched=True),
    ]
    horses[0].marketProbability = 0.6
    horses[1].marketProbability = 0.4
    horses[2].marketProbability = 0.5  # should be cleared

    normalize_probabilities(horses, field="marketProbability")
    assert horses[0].marketProbability == pytest.approx(0.6, abs=1e-9)
    assert horses[1].marketProbability == pytest.approx(0.4, abs=1e-9)
    assert horses[2].marketProbability is None
    active_total = sum(
        h.marketProbability or 0.0 for h in horses if not h.scratched
    )
    assert math.isclose(active_total, 1.0, abs_tol=1e-3)


def test_normalize_handles_field_with_none_values() -> None:
    horses = [_eq_horse(1, "Alpha"), _eq_horse(2, "Bravo")]
    horses[0].marketProbability = 0.5
    # horses[1] left at None — it should remain None, not be assigned
    normalize_probabilities(horses, field="marketProbability")
    assert horses[0].marketProbability == pytest.approx(1.0, abs=1e-9)
    assert horses[1].marketProbability is None


def test_normalize_no_op_when_total_zero() -> None:
    horses = [_eq_horse(1, "Alpha"), _eq_horse(2, "Bravo")]
    normalize_probabilities(horses, field="marketProbability")
    assert all(h.marketProbability is None for h in horses)


def test_normalize_works_for_morning_line_field() -> None:
    horses = [_eq_horse(1, "Alpha"), _eq_horse(2, "Bravo")]
    horses[0].morningLineProbability = 0.4
    horses[1].morningLineProbability = 0.7  # sum 1.1
    normalize_probabilities(horses, field="morningLineProbability")
    total = sum(h.morningLineProbability or 0.0 for h in horses)
    assert math.isclose(total, 1.0, abs_tol=1e-3)


# ---------- normalize_horse_name ----------


def test_normalize_horse_name_collapses_country_suffix_and_punct() -> None:
    assert normalize_horse_name("HORSE NAME (IRE)") == "horsename"
    assert normalize_horse_name("Horse-Name") == "horsename"
    assert normalize_horse_name("Horse'sName") == "horsesname"


def test_normalize_horse_name_handles_none_and_empty() -> None:
    assert normalize_horse_name(None) == ""
    assert normalize_horse_name("") == ""


# ---------- merge_horses ----------


def test_merge_matches_by_post_number_when_unambiguous() -> None:
    eq = [_eq_horse(1, "Alpha", ml="5/2"), _eq_horse(2, "Bravo", ml="3-1")]
    ts = [
        _ts_horse(1, "Alpha", current="2/1"),
        _ts_horse(2, "Bravo", current="4/1"),
    ]
    merged = merge_horses(eq, ts)
    assert merged[0].marketProbability == pytest.approx(1 / 3, abs=1e-6)
    assert merged[0].morningLineProbability == pytest.approx(0.2857, abs=1e-4)
    assert merged[0].currentOdds == "2/1"
    assert merged[1].marketProbability == pytest.approx(0.2, abs=1e-6)
    assert MISSING_LIVE_ODDS_FLAG not in merged[0].flags
    assert MISSING_LIVE_ODDS_FLAG not in merged[1].flags


def test_merge_falls_back_to_name_when_post_missing() -> None:
    # TS only knows the horse by some post we can't predict; matched by name.
    eq = [_eq_horse(7, "BIG RED MACHINE", ml="5/1")]
    ts = [_ts_horse(99, "Big Red Machine", current="3/1")]
    merged = merge_horses(eq, ts)
    assert merged[0].marketProbability == pytest.approx(0.25, abs=1e-9)
    assert merged[0].currentOdds == "3/1"
    assert MISSING_LIVE_ODDS_FLAG not in merged[0].flags


def test_merge_strips_country_suffix_for_name_match() -> None:
    # AC: Equibase "HORSE NAME (IRE)" merges with TwinSpires "HORSE NAME".
    eq = [_eq_horse(7, "HORSE NAME (IRE)", ml="5/1")]
    ts = [_ts_horse(99, "HORSE NAME", current="3/1")]
    merged = merge_horses(eq, ts)
    assert merged[0].currentOdds == "3/1"
    assert merged[0].marketProbability == pytest.approx(0.25, abs=1e-9)


def test_merge_difflib_fuzzy_match_at_cutoff() -> None:
    # Names differ by one letter — well above the 0.85 cutoff.
    eq = [_eq_horse(5, "Thunderbolt", ml="2/1")]
    ts = [_ts_horse(5, "Thunderbol", current="5/2")]  # missing trailing t
    merged = merge_horses(eq, ts)
    assert merged[0].marketProbability == pytest.approx(0.2857, abs=1e-4)


def test_merge_no_match_flags_missing_live_odds_and_keeps_ml_prob() -> None:
    eq = [_eq_horse(1, "Lonely", ml="4/1")]
    ts = [_ts_horse(2, "Stranger", current="2/1")]
    merged = merge_horses(eq, ts)
    assert merged[0].marketProbability is None
    assert merged[0].morningLineProbability == pytest.approx(0.2, abs=1e-9)
    assert MISSING_LIVE_ODDS_FLAG in merged[0].flags


def test_merge_resolves_coupled_entry_via_name() -> None:
    # Both Equibase entries have post=1 (Equibase strips letters from PP).
    # TwinSpires distinguishes via programNumber 1 / 1A.
    eq = [
        _eq_horse(1, "Coupled Alpha", ml="5/2"),
        _eq_horse(1, "Coupled Beta", ml="6/1"),
    ]
    ts = [
        _ts_horse(1, "Coupled Alpha", pn="1", current="2/1"),
        _ts_horse(1, "Coupled Beta", pn="1A", current="8/1"),
    ]
    merged = merge_horses(eq, ts)
    assert merged[0].currentOdds == "2/1"
    assert merged[1].currentOdds == "8/1"


def test_merge_does_not_mutate_inputs() -> None:
    eq = [_eq_horse(1, "Alpha", ml="2/1")]
    ts = [_ts_horse(1, "Alpha", current="3/1")]
    merge_horses(eq, ts)
    assert eq[0].marketProbability is None
    assert eq[0].morningLineProbability is None
    assert eq[0].currentOdds is None
    assert eq[0].flags == []


def test_merge_each_ts_runner_used_at_most_once() -> None:
    # Two equibase horses, only one TS runner — only the first match wins.
    eq = [
        _eq_horse(1, "Alpha", ml="2/1"),
        _eq_horse(2, "Bravo", ml="3/1"),
    ]
    ts = [_ts_horse(1, "Alpha", current="5/2")]
    merged = merge_horses(eq, ts)
    assert merged[0].currentOdds == "5/2"
    assert merged[1].currentOdds is None
    assert MISSING_LIVE_ODDS_FLAG in merged[1].flags


def test_merge_skips_market_prob_when_match_has_no_current_odds() -> None:
    eq = [_eq_horse(1, "Alpha", ml="2/1")]
    ts = [_ts_horse(1, "Alpha", current=None)]
    merged = merge_horses(eq, ts)
    assert merged[0].marketProbability is None
    assert merged[0].morningLineProbability == pytest.approx(1 / 3, abs=1e-6)


def test_name_match_cutoff_constant_matches_research() -> None:
    assert NAME_MATCH_CUTOFF == 0.85


# ---------- assign_pick5_sequence_roles ----------


def _race(num: int) -> Race:
    return Race(
        id=f"CD-2026-05-02-R{num:02d}",
        day="saturday",
        raceNumber=num,
    )


def test_assign_sets_leg_1_through_leg_5_in_order() -> None:
    races = [_race(n) for n in range(1, 14)]
    assign_pick5_sequence_roles(races, [9, 10, 11, 12, 13])
    by_num = {r.raceNumber: r for r in races}
    assert by_num[9].sequenceRole == "pick5-leg-1"
    assert by_num[10].sequenceRole == "pick5-leg-2"
    assert by_num[11].sequenceRole == "pick5-leg-3"
    assert by_num[12].sequenceRole == "pick5-leg-4"
    assert by_num[13].sequenceRole == "pick5-leg-5"


def test_assign_leaves_non_pick5_races_untouched() -> None:
    races = [_race(n) for n in range(1, 14)]
    assign_pick5_sequence_roles(races, [9, 10, 11, 12, 13])
    for r in races:
        if r.raceNumber not in {9, 10, 11, 12, 13}:
            assert r.sequenceRole is None


def test_assign_supports_oaks_friday_sequence() -> None:
    races = [_race(n) for n in range(1, 13)]
    assign_pick5_sequence_roles(races, [8, 9, 10, 11, 12])
    by_num = {r.raceNumber: r for r in races}
    assert by_num[8].sequenceRole == "pick5-leg-1"
    assert by_num[12].sequenceRole == "pick5-leg-5"


def test_assign_rejects_wrong_leg_count() -> None:
    with pytest.raises(ValueError):
        assign_pick5_sequence_roles([_race(1)], [1, 2, 3, 4])


def test_pick5_leg_count_constant() -> None:
    assert PICK5_LEG_COUNT == 5
