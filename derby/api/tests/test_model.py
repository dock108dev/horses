"""Tests for the canonical data models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from api.model import Horse, OddsSnapshot, Race


def _full_horse() -> Horse:
    return Horse(
        id="h-1",
        raceId="r-1",
        post=4,
        name="Mage",
        jockey="J. Castellano",
        trainer="G. Sano",
        morningLineOdds="15-1",
        currentOdds="8-1",
        scratched=False,
        source="twinspires",
        marketProbability=0.111,
        morningLineProbability=0.0625,
        modelProbability=0.09,
        finalProbability=0.1,
        userTag="A",
        flags=["taking money"],
    )


def _full_race() -> Race:
    return Race(
        id="2026-05-02-r12",
        day="saturday",
        track="Churchill Downs",
        raceNumber=12,
        postTime="2026-05-02T22:57:00Z",
        name="Kentucky Derby",
        surface="dirt",
        distance="1 1/4M",
        sequenceRole="pick5-leg-5",
        horses=[_full_horse()],
    )


def _full_snapshot() -> OddsSnapshot:
    return OddsSnapshot(
        timestamp="2026-05-02T20:15:00Z",
        day="saturday",
        raceNumber=12,
        horseId="h-1",
        odds="8-1",
        impliedProbability=0.111,
        source="twinspires",
    )


def test_race_round_trips_through_json() -> None:
    race = _full_race()
    payload = race.model_dump_json()
    rebuilt = Race.model_validate_json(payload)
    assert rebuilt == race
    assert json.loads(payload)["horses"][0]["userTag"] == "A"


def test_horse_round_trips_through_dict() -> None:
    horse = _full_horse()
    rebuilt = Horse.model_validate(horse.model_dump())
    assert rebuilt == horse


def test_odds_snapshot_round_trips_through_json() -> None:
    snap = _full_snapshot()
    rebuilt = OddsSnapshot.model_validate_json(snap.model_dump_json())
    assert rebuilt == snap


def test_race_track_defaults_to_churchill_downs() -> None:
    race = Race(id="r", day="friday", raceNumber=1)
    assert race.track == "Churchill Downs"
    assert race.horses == []


def test_horse_flags_defaults_to_empty_list() -> None:
    horse = Horse(id="h", raceId="r", post=1, name="N")
    assert horse.flags == []


def test_invalid_user_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        Horse(id="h", raceId="r", post=1, name="N", userTag="bogus")  # type: ignore[arg-type]


def test_invalid_sequence_role_rejected() -> None:
    with pytest.raises(ValidationError):
        Race(id="r", day="friday", raceNumber=1, sequenceRole="pick5-leg-9")  # type: ignore[arg-type]


def test_implied_probability_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        OddsSnapshot(
            timestamp="t",
            day="friday",
            raceNumber=1,
            horseId="h",
            odds="1-1",
            impliedProbability=1.5,
            source="x",
        )


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Horse.model_validate(
            {"id": "h", "raceId": "r", "post": 1, "name": "N", "unknown": True}
        )
