"""Tests for the per-day SQLite odds-snapshot cache."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from api.cache import CachedCard, OddsCache, OddsSnapshotRecord
from api.model import Horse, Race


DAY = "2026-05-02"
RACE_ID = "CD-2026-05-02-R09"


def _record(
    horse_id: str,
    horse_name: str,
    odds: str,
    prob: float,
    captured_at_ms: int,
    *,
    race_id: str = RACE_ID,
    source: str = "twinspires",
) -> OddsSnapshotRecord:
    return OddsSnapshotRecord(
        race_id=race_id,
        horse_id=horse_id,
        horse_name=horse_name,
        odds=odds,
        implied_probability=prob,
        source=source,
        captured_at_ms=captured_at_ms,
    )


def _race(num: int, *, with_horse: bool = True) -> Race:
    horses: list[Horse] = []
    if with_horse:
        horses.append(
            Horse(
                id=f"CD-2026-05-02-R{num:02d}-p01",
                raceId=f"CD-2026-05-02-R{num:02d}",
                post=1,
                name="Alpha",
                morningLineOdds="5/2",
                source="equibase",
            )
        )
    return Race(
        id=f"CD-2026-05-02-R{num:02d}",
        day="saturday",
        raceNumber=num,
        horses=horses,
    )


def test_db_file_created_on_first_write(tmp_path: Path) -> None:
    cache = OddsCache(DAY, data_dir=tmp_path)
    try:
        cache.store_odds_batch([_record("h1", "Alpha", "5/2", 0.2857, 1)])
    finally:
        cache.close()
    assert (tmp_path / f"odds_{DAY}.db").exists()


def test_data_survives_process_restart(tmp_path: Path) -> None:
    cache = OddsCache(DAY, data_dir=tmp_path)
    cache.store_odds_batch(
        [
            _record("h1", "Alpha", "5/2", 0.2857, 1_000),
            _record("h2", "Bravo", "3/1", 0.25, 1_000),
            _record("h1", "Alpha", "2/1", 0.3333, 2_000),
        ]
    )
    cache.close()

    # Simulate a fresh process: brand new OddsCache instance, same file.
    reopened = OddsCache(DAY, data_dir=tmp_path)
    try:
        latest = {r.horse_id: r for r in reopened.get_latest_odds(RACE_ID)}
    finally:
        reopened.close()

    assert latest["h1"].odds == "2/1"
    assert latest["h1"].implied_probability == pytest.approx(0.3333, abs=1e-4)
    assert latest["h1"].captured_at_ms == 2_000
    assert latest["h2"].odds == "3/1"
    assert latest["h2"].captured_at_ms == 1_000


def test_get_latest_odds_picks_max_captured_at_per_horse(tmp_path: Path) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_odds_batch(
            [
                _record("h1", "Alpha", "5/2", 0.2857, 100),
                _record("h1", "Alpha", "3/1", 0.25, 200),
                _record("h1", "Alpha", "7/2", 0.2222, 150),
                _record("h2", "Bravo", "4/1", 0.20, 50),
            ]
        )
        latest = sorted(
            cache.get_latest_odds(RACE_ID),
            key=lambda r: r.horse_id,
        )

    assert len(latest) == 2
    assert latest[0].horse_id == "h1"
    assert latest[0].captured_at_ms == 200
    assert latest[0].odds == "3/1"
    assert latest[1].horse_id == "h2"
    assert latest[1].captured_at_ms == 50


def test_get_latest_odds_filters_by_race_id(tmp_path: Path) -> None:
    other_race = "CD-2026-05-02-R10"
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_odds_batch(
            [
                _record("h1", "Alpha", "2/1", 0.333, 1, race_id=RACE_ID),
                _record("h1", "Alpha", "9/1", 0.10, 5, race_id=other_race),
            ]
        )
        latest = cache.get_latest_odds(RACE_ID)

    assert len(latest) == 1
    assert latest[0].odds == "2/1"


def test_get_drift_series_is_chronological(tmp_path: Path) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        # Insert out of order to prove ORDER BY is doing the work.
        cache.store_odds_batch(
            [
                _record("h1", "Alpha", "5/2", 0.2857, 300),
                _record("h1", "Alpha", "3/1", 0.25, 100),
                _record("h1", "Alpha", "7/2", 0.2222, 200),
                _record("h2", "Bravo", "10/1", 0.0909, 150),  # different horse
            ]
        )
        series = cache.get_drift_series(RACE_ID, "h1")

    assert [point[0] for point in series] == [100, 200, 300]
    assert [point[1] for point in series] == ["3/1", "7/2", "5/2"]
    # implied probabilities preserved
    assert series[0][2] == pytest.approx(0.25, abs=1e-9)


def test_get_drift_series_empty_when_nothing_stored(tmp_path: Path) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        assert cache.get_drift_series(RACE_ID, "missing") == []


def test_50_horse_batch_insert_under_100ms(tmp_path: Path) -> None:
    snaps = [
        _record(f"h{i}", f"Horse {i}", "5/2", 0.2857, 1_000 + i)
        for i in range(50)
    ]
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        start = time.perf_counter()
        cache.store_odds_batch(snaps)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert len(cache.get_latest_odds(RACE_ID)) == 50

    assert elapsed_ms < 100.0, f"batch insert took {elapsed_ms:.1f} ms"


def test_store_odds_batch_no_op_for_empty_iterable(tmp_path: Path) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_odds_batch([])
        assert cache.get_latest_odds(RACE_ID) == []


def test_store_card_then_get_last_good_card(tmp_path: Path) -> None:
    races = [_race(9), _race(10)]
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        ts = cache.store_card(DAY, races, validated=True, captured_at_ms=12345)
        cached = cache.get_last_good_card(DAY)

    assert ts == 12345
    assert cached is not None
    assert cached.captured_at_ms == 12345
    assert [r.id for r in cached.races] == [r.id for r in races]
    assert cached.races[0].horses[0].name == "Alpha"


def test_get_last_good_card_returns_none_when_no_validated_card(
    tmp_path: Path,
) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        # Empty DB.
        assert cache.get_last_good_card(DAY) is None
        # Unvalidated stores must not satisfy the lookup either.
        cache.store_card(DAY, [_race(9)], validated=False, captured_at_ms=1)
        assert cache.get_last_good_card(DAY) is None


def test_get_last_good_card_returns_most_recent_validated(tmp_path: Path) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_card(DAY, [_race(9)], validated=True, captured_at_ms=100)
        cache.store_card(DAY, [_race(10)], validated=True, captured_at_ms=300)
        cache.store_card(DAY, [_race(11)], validated=True, captured_at_ms=200)
        cached = cache.get_last_good_card(DAY)

    assert cached is not None
    assert cached.captured_at_ms == 300
    assert cached.races[0].raceNumber == 10


def test_get_last_good_card_skips_unvalidated_even_when_more_recent(
    tmp_path: Path,
) -> None:
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_card(DAY, [_race(9)], validated=True, captured_at_ms=100)
        cache.store_card(DAY, [_race(10)], validated=False, captured_at_ms=999)
        cached = cache.get_last_good_card(DAY)

    assert cached is not None
    assert cached.captured_at_ms == 100
    assert cached.races[0].raceNumber == 9


def test_get_last_good_card_filters_by_day(tmp_path: Path) -> None:
    other_day = "2026-05-01"
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_card(other_day, [_race(9)], validated=True, captured_at_ms=1)
        assert cache.get_last_good_card(DAY) is None
        assert cache.get_last_good_card(other_day) is not None


def test_card_round_trips_through_json_blob(tmp_path: Path) -> None:
    """Race objects are reconstructed identically from the stored JSON."""
    races = [_race(9), _race(10, with_horse=False)]
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_card(DAY, races, validated=True, captured_at_ms=1)
        cached = cache.get_last_good_card(DAY)

    assert cached is not None
    assert cached.races == races


def test_wal_journal_mode_active(tmp_path: Path) -> None:
    cache = OddsCache(DAY, data_dir=tmp_path)
    try:
        mode = cache._conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        cache.close()
    assert str(mode).lower() == "wal"


def test_returns_cached_card_dataclass(tmp_path: Path) -> None:
    """Sanity-check the return type so downstream callers can pattern match."""
    with OddsCache(DAY, data_dir=tmp_path) as cache:
        cache.store_card(DAY, [_race(9)], validated=True, captured_at_ms=42)
        cached = cache.get_last_good_card(DAY)
    assert isinstance(cached, CachedCard)
