"""Shared test fixtures and helpers for the API test suite.

Pytest auto-discovers ``conftest.py`` and exposes its fixtures to every
test module in this directory. The factories (``_client_with_overrides``,
``_seed_cache``, ``_full_card``) and stub adapters (``FakeEquibase``,
``FakeTwinSpires``) are imported by name from individual test modules.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.cache import OddsCache
from api.main import (
    DEFAULT_DERBY_DATES,
    app,
    day_to_iso_date,
    get_equibase_adapter,
    get_twinspires_adapter,
)
from api.model import PICK5_LEG_ROLES, Horse, Race


SATURDAY_ISO = DEFAULT_DERBY_DATES["saturday"]
FRIDAY_ISO = DEFAULT_DERBY_DATES["friday"]
SATURDAY_LEGS = [9, 10, 11, 12, 13]
FRIDAY_LEGS = [8, 9, 10, 11, 12]


def _race_id(iso_date: str, num: int) -> str:
    return f"CD-{iso_date}-R{num:02d}"


def _make_horses(
    iso_date: str,
    race_num: int,
    *,
    n: int = 4,
    with_market: bool = False,
) -> list[Horse]:
    each = 1.0 / n if with_market else None
    return [
        Horse(
            id=f"{_race_id(iso_date, race_num)}-p{post:02d}",
            raceId=_race_id(iso_date, race_num),
            post=post,
            name=f"Horse {race_num}-{post}",
            morningLineOdds="3/1",
            currentOdds="5/2",
            morningLineProbability=each,
            marketProbability=each,
        )
        for post in range(1, n + 1)
    ]


def _make_race(
    iso_date: str,
    race_num: int,
    leg_index: int,
    day: str = "saturday",
    with_market: bool = True,
) -> Race:
    return Race(
        id=_race_id(iso_date, race_num),
        day=day,
        raceNumber=race_num,
        sequenceRole=PICK5_LEG_ROLES[leg_index],
        horses=_make_horses(iso_date, race_num, with_market=with_market),
    )


def _full_card(day: str = "saturday") -> list[Race]:
    if day == "saturday":
        iso, legs = SATURDAY_ISO, SATURDAY_LEGS
    else:
        iso, legs = FRIDAY_ISO, FRIDAY_LEGS
    return [_make_race(iso, num, i, day=day) for i, num in enumerate(legs)]


class FakeEquibase:
    """Stub adapter that serves a pre-built card by race number."""

    def __init__(self, races: list[Race], *, fail: bool = False) -> None:
        self._by_num = {r.raceNumber: r for r in races}
        self.fail = fail

    def fetch_race(self, iso_date: str, race_number: int, *, day: str) -> Race | None:
        if self.fail:
            raise RuntimeError("equibase boom")
        return self._by_num.get(race_number)


class FakeTwinSpires:
    """Stub adapter for program + odds JSON."""

    def __init__(
        self,
        races: list[Race] | None = None,
        odds_by_race: dict[int, list[dict[str, str | None]]] | None = None,
        *,
        fail_program: bool = False,
        fail_odds: bool = False,
    ) -> None:
        self._by_num = {r.raceNumber: r for r in (races or [])}
        self._odds = odds_by_race or {}
        self.fail_program = fail_program
        self.fail_odds = fail_odds
        self.odds_calls: list[tuple[str, int]] = []

    def fetch_program(self, iso_date: str, race_number: int, *, day: str) -> Race | None:
        if self.fail_program:
            raise RuntimeError("twinspires program boom")
        return self._by_num.get(race_number)

    def fetch_odds(
        self, iso_date: str, race_number: int
    ) -> list[dict[str, str | None]]:
        self.odds_calls.append((iso_date, race_number))
        if self.fail_odds:
            raise RuntimeError("twinspires odds boom")
        return self._odds.get(race_number, [])


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the API at an isolated SQLite directory for the test."""
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client(tmp_data_dir: Path) -> Iterator[TestClient]:
    yield from _client_with_overrides(tmp_data_dir)
    app.dependency_overrides.clear()


def _client_with_overrides(
    tmp_data_dir: Path,
    *,
    equibase: Any = None,
    twinspires: Any = None,
) -> Iterator[TestClient]:
    if equibase is not None:
        app.dependency_overrides[get_equibase_adapter] = lambda: equibase
    if twinspires is not None:
        app.dependency_overrides[get_twinspires_adapter] = lambda: twinspires
    with TestClient(app) as tc:
        yield tc


def _seed_cache(day: str, races: list[Race], *, data_dir: Path) -> int:
    iso = day_to_iso_date(day)
    with OddsCache(iso, data_dir=data_dir) as cache:
        return cache.store_card(iso, races, validated=True)
