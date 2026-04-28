"""Tests for the FastAPI app — envelope shape, CORS, refresh fallbacks.

LOC note: ~932 LOC, well over the 500-line guideline. Fixtures
(FakeEquibase, FakeTwinSpires, _client_with_overrides, _seed_cache) are
shared across every endpoint test; splitting would either duplicate
fixtures or invent a conftest layer that obscures what each test sets
up. See ``docs/audits/cleanup-report.md`` "Files still >500 LOC".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.cache import OddsCache
from api.main import (
    ALLOWED_CORS_ORIGINS,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_returns_status_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Day path-param validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/api/cards/monday",
        "/api/odds/tuesday",
    ],
)
def test_invalid_day_returns_422(client: TestClient, url: str) -> None:
    resp = client.get(url)
    assert resp.status_code == 422


def test_invalid_day_on_post_refresh_returns_422(client: TestClient) -> None:
    resp = client.post("/api/cards/sunday/refresh")
    assert resp.status_code == 422


def test_invalid_day_on_simulate_returns_422(client: TestClient) -> None:
    resp = client.post("/api/simulate/wednesday")
    assert resp.status_code == 422


def test_invalid_day_on_tickets_returns_422(client: TestClient) -> None:
    resp = client.post("/api/tickets/thursday/build")
    assert resp.status_code == 422


@pytest.mark.parametrize("day", ["friday", "saturday"])
def test_valid_days_accepted(client: TestClient, day: str) -> None:
    resp = client.get(f"/api/cards/{day}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ALLOWED_CORS_ORIGINS)
def test_cors_allows_configured_origins(
    client: TestClient, origin: str
) -> None:
    resp = client.options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_allows_localhost_3000(client: TestClient) -> None:
    resp = client.get(
        "/api/health", headers={"Origin": "http://localhost:3000"}
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allows_mac_mini(client: TestClient) -> None:
    resp = client.get(
        "/api/health", headers={"Origin": "http://mac-mini.local:3000"}
    )
    assert (
        resp.headers.get("access-control-allow-origin")
        == "http://mac-mini.local:3000"
    )


# ---------------------------------------------------------------------------
# GET /api/cards/{day}
# ---------------------------------------------------------------------------


def test_get_card_empty_when_no_cache(client: TestClient) -> None:
    resp = client.get("/api/cards/saturday")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["stale"] is False
    assert body["cached_at"] is None
    assert body["source"] == "cache"
    assert "no cached card" in body["errors"][0]


def test_get_card_returns_cached(
    tmp_data_dir: Path, client: TestClient
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    resp = client.get("/api/cards/saturday")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is False
    assert body["cached_at"] is not None
    assert len(body["data"]) == 5
    assert body["errors"] == []


# ---------------------------------------------------------------------------
# POST /api/cards/{day}/refresh
# ---------------------------------------------------------------------------


def test_refresh_card_happy_path(tmp_data_dir: Path) -> None:
    eq_races = _full_card("saturday")
    ts_races = _full_card("saturday")
    fake_eq = FakeEquibase(eq_races)
    fake_ts = FakeTwinSpires(ts_races)
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            resp = tc.post("/api/cards/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is False
            assert body["source"] == "equibase+twinspires"
            assert len(body["data"]) == 5
            assert body["cached_at"] is not None
            assert body["errors"] == []
        finally:
            app.dependency_overrides.clear()


def test_refresh_card_falls_back_to_stale_on_exception(
    tmp_data_dir: Path,
) -> None:
    seeded_ms = _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    fake_eq = FakeEquibase([], fail=True)
    fake_ts = FakeTwinSpires([])
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            resp = tc.post("/api/cards/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is True
            assert body["cached_at"] is not None
            assert body["source"] == "cache"
            assert any("equibase boom" in e for e in body["errors"])
            assert len(body["data"]) == 5
            assert seeded_ms > 0
        finally:
            app.dependency_overrides.clear()


def test_refresh_card_stale_when_validation_fails(
    tmp_data_dir: Path,
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    fake_eq = FakeEquibase([])  # empty → validate fails (no legs)
    fake_ts = FakeTwinSpires([])
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            resp = tc.post("/api/cards/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is True
            assert body["source"] == "cache"
            assert any("Pick 5 leg" in e for e in body["errors"])
        finally:
            app.dependency_overrides.clear()


def test_refresh_card_no_stale_fallback_returns_empty_envelope(
    tmp_data_dir: Path,
) -> None:
    fake_eq = FakeEquibase([], fail=True)
    fake_ts = FakeTwinSpires([])
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            resp = tc.post("/api/cards/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is True
            assert body["data"] == []
            assert body["cached_at"] is None
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/odds/{day}
# ---------------------------------------------------------------------------


def test_get_odds_empty_when_no_card(client: TestClient) -> None:
    resp = client.get("/api/odds/friday")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert "no cached card" in body["errors"][0]


def test_get_odds_returns_per_race_runners(
    tmp_data_dir: Path, client: TestClient
) -> None:
    races = _full_card("saturday")
    _seed_cache("saturday", races, data_dir=tmp_data_dir)
    iso = day_to_iso_date("saturday")
    # Inject one odds record so the GET has something to surface.
    from api.cache import OddsSnapshotRecord

    with OddsCache(iso, data_dir=tmp_data_dir) as cache:
        cache.store_odds_batch(
            [
                OddsSnapshotRecord(
                    race_id=races[0].id,
                    horse_id=races[0].horses[0].id,
                    horse_name=races[0].horses[0].name,
                    odds="5/2",
                    implied_probability=2.0 / 7.0,
                    source="twinspires",
                    captured_at_ms=1_700_000_000_000,
                )
            ]
        )
    resp = client.get("/api/odds/saturday")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is False
    assert len(body["data"]) == 5
    leg_one = body["data"][0]
    assert leg_one["raceNumber"] == SATURDAY_LEGS[0]
    assert leg_one["sequenceRole"] == "pick5-leg-1"
    assert len(leg_one["runners"]) == 1
    assert leg_one["runners"][0]["odds"] == "5/2"


# ---------------------------------------------------------------------------
# POST /api/odds/{day}/refresh
# ---------------------------------------------------------------------------


def test_refresh_odds_polls_twinspires_and_returns_data(
    tmp_data_dir: Path,
) -> None:
    races = _full_card("saturday")
    _seed_cache("saturday", races, data_dir=tmp_data_dir)
    odds_payload = {
        leg: [
            {"programNumber": str(post), "winOdds": "3/1"}
            for post in range(1, 5)
        ]
        for leg in SATURDAY_LEGS
    }
    fake_ts = FakeTwinSpires(odds_by_race=odds_payload)
    for tc in _client_with_overrides(tmp_data_dir, twinspires=fake_ts):
        try:
            resp = tc.post("/api/odds/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is False
            assert body["source"] == "twinspires"
            assert len(body["data"]) == 5
            assert body["cached_at"] is not None
            assert fake_ts.odds_calls  # at least one race was polled
            for race_payload in body["data"]:
                assert len(race_payload["runners"]) == 4
        finally:
            app.dependency_overrides.clear()


def test_refresh_odds_no_card_returns_no_cache_error(client: TestClient) -> None:
    resp = client.post("/api/odds/saturday/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert body["data"] == []
    assert any("no cached card" in e for e in body["errors"])


def test_refresh_odds_stale_on_exception(tmp_data_dir: Path) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    fake_ts = FakeTwinSpires(fail_odds=True)
    for tc in _client_with_overrides(tmp_data_dir, twinspires=fake_ts):
        try:
            resp = tc.post("/api/odds/saturday/refresh")
            assert resp.status_code == 200
            body = resp.json()
            assert body["stale"] is True
            assert body["source"] == "cache"
            assert any("twinspires odds boom" in e for e in body["errors"])
            # data is the per-race payload (possibly empty runners) — list of 5 legs
            assert len(body["data"]) == 5
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Simulate / tickets stubs
# ---------------------------------------------------------------------------


def test_simulate_without_card_returns_no_cache_error(client: TestClient) -> None:
    resp = client.post("/api/simulate/saturday", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert any("no cached card" in e for e in body["errors"])


def test_simulate_with_card_returns_envelope(
    tmp_data_dir: Path, client: TestClient
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    resp = client.post("/api/simulate/saturday", json={"n_iterations": 100})
    assert resp.status_code == 200
    body = resp.json()
    # Sim engine not yet present → expect the placeholder envelope shape.
    assert "errors" in body
    assert "source" in body
    assert "cached_at" in body
    assert body["cached_at"] is not None


def test_tickets_without_card_returns_no_cache_error(client: TestClient) -> None:
    resp = client.post("/api/tickets/saturday/build", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert any("no cached card" in e for e in body["errors"])


def test_tickets_with_card_returns_envelope(
    tmp_data_dir: Path, client: TestClient
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    resp = client.post(
        "/api/tickets/saturday/build",
        json={"budget_dollars": 96.0, "base_unit": 0.50},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "errors" in body
    assert "source" in body
    assert body["cached_at"] is not None


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


def test_envelope_keys_present_on_every_endpoint(
    tmp_data_dir: Path,
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    fake_eq = FakeEquibase(_full_card("saturday"))
    fake_ts = FakeTwinSpires(
        races=_full_card("saturday"),
        odds_by_race={
            leg: [
                {"programNumber": str(post), "winOdds": "3/1"}
                for post in range(1, 5)
            ]
            for leg in SATURDAY_LEGS
        },
    )
    expected_keys = {"data", "stale", "cached_at", "source", "errors"}
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            checks = [
                ("GET", "/api/cards/saturday", None),
                ("POST", "/api/cards/saturday/refresh", None),
                ("GET", "/api/odds/saturday", None),
                ("POST", "/api/odds/saturday/refresh", None),
                ("POST", "/api/simulate/saturday", {}),
                ("POST", "/api/tickets/saturday/build", {}),
            ]
            for method, url, json_body in checks:
                resp = tc.request(method, url, json=json_body)
                assert resp.status_code == 200, f"{method} {url}"
                body = resp.json()
                assert set(body.keys()) >= expected_keys, f"{method} {url}"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Event-loop responsiveness during long-running refresh
# ---------------------------------------------------------------------------


def test_health_responsive_during_card_refresh(tmp_data_dir: Path) -> None:
    """A blocking source must not freeze the event loop.

    Equibase's real adapter sleeps 3s between legs and TwinSpires can
    block 15s on each XHR. If the async refresh handler called those
    sync helpers directly, every concurrent request — including the
    health check — would wait for the full refresh to finish. The fix
    offloads the work to a worker thread so the loop stays free.
    """
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    class BlockingEquibase:
        def fetch_race(
            self, iso_date: str, race_number: int, *, day: str
        ) -> Race | None:
            fetch_started.set()
            release_fetch.wait(timeout=5)
            return None

    fake_eq = BlockingEquibase()
    fake_ts = FakeTwinSpires()
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            refresh_thread = threading.Thread(
                target=lambda: tc.post("/api/cards/saturday/refresh"),
                daemon=True,
            )
            refresh_thread.start()
            assert fetch_started.wait(timeout=2.0), (
                "refresh handler never reached the blocking source — "
                "asyncio.to_thread offload may be wired incorrectly"
            )
            start = time.monotonic()
            health = tc.get("/api/health")
            elapsed = time.monotonic() - start
            assert health.status_code == 200
            assert elapsed < 1.0, (
                f"/api/health blocked for {elapsed:.2f}s while card refresh "
                "was in flight — event loop is not freed by asyncio.to_thread"
            )
            release_fetch.set()
            refresh_thread.join(timeout=5.0)
            assert not refresh_thread.is_alive()
        finally:
            release_fetch.set()
            app.dependency_overrides.clear()


def test_day_to_iso_date_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DERBY_FRIDAY_DATE", "2027-04-30")
    assert day_to_iso_date("friday") == "2027-04-30"
    monkeypatch.delenv("DERBY_FRIDAY_DATE")
    assert day_to_iso_date("friday") == DEFAULT_DERBY_DATES["friday"]


def test_get_equibase_adapter_wires_disk_cache(tmp_data_dir: Path) -> None:
    """Default factory must enable the disk cache so same-day re-refreshes
    skip the 12-15 live Equibase fetches plus the 3s/req rate-limit floor."""
    import asyncio

    expected = tmp_data_dir / "equibase_html"

    async def drive() -> Path:
        gen = get_equibase_adapter()
        adapter = await gen.__anext__()
        try:
            assert expected.is_dir()
            return adapter.cache_dir
        finally:
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

    cache_dir = asyncio.run(drive())
    assert cache_dir == expected


# ---------------------------------------------------------------------------
# Fixture mode (?source=fixture / PICK5_DATA_MODE=fixture)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "day, expected_legs",
    [("friday", FRIDAY_LEGS), ("saturday", SATURDAY_LEGS)],
)
def test_refresh_card_fixture_mode_query_param(
    client: TestClient, day: str, expected_legs: list[int]
) -> None:
    """Fixture mode must serve a 5-leg card without invoking live adapters.

    Validation runs the same way as live, the snapshot is persisted to
    SQLite, and the envelope reports ``source: "fixture"`` so the
    operator (and frontend) can see where the data came from.
    """
    start = time.monotonic()
    resp = client.post(f"/api/cards/{day}/refresh?source=fixture")
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fixture"
    assert body["stale"] is False
    assert body["errors"] == []
    assert body["cached_at"] is not None
    assert len(body["data"]) == 5
    assert [r["raceNumber"] for r in body["data"]] == expected_legs
    for race in body["data"]:
        assert len(race["horses"]) > 0
    assert elapsed < 0.5, f"fixture refresh took {elapsed:.3f}s"


def test_refresh_card_fixture_mode_env_var(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PICK5_DATA_MODE", "fixture")
    resp = client.post("/api/cards/friday/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fixture"
    assert len(body["data"]) == 5


def test_get_card_after_fixture_refresh_returns_cached(
    client: TestClient,
) -> None:
    refresh = client.post("/api/cards/friday/refresh?source=fixture")
    assert refresh.status_code == 200
    follow_up = client.get("/api/cards/friday")
    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["stale"] is False
    assert len(body["data"]) == 5
    assert body["cached_at"] is not None
    assert body["errors"] == []


def test_refresh_odds_fixture_mode(client: TestClient) -> None:
    """Fixture odds load must populate live odds for every horse in the card."""
    card = client.post("/api/cards/friday/refresh?source=fixture")
    assert card.status_code == 200
    odds = client.post("/api/odds/friday/refresh?source=fixture")
    assert odds.status_code == 200
    body = odds.json()
    assert body["source"] == "fixture"
    assert body["stale"] is False
    assert body["errors"] == []
    assert len(body["data"]) == 5
    for race_payload in body["data"]:
        # Every fixture card horse has a matching odds record.
        expected = sum(
            1
            for r in card.json()["data"]
            if r["raceNumber"] == race_payload["raceNumber"]
            for h in r["horses"]
            if not h.get("scratched")
        )
        assert len(race_payload["runners"]) == expected


def test_simulate_after_fixture_refresh_returns_data(
    client: TestClient,
) -> None:
    client.post("/api/cards/friday/refresh?source=fixture")
    resp = client.post("/api/simulate/friday", json={"n_iterations": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is not None
    assert body["errors"] == []
    assert body["source"] == "sim"


def test_tickets_after_fixture_refresh_returns_variants(
    client: TestClient,
) -> None:
    client.post("/api/cards/friday/refresh?source=fixture")
    resp = client.post(
        "/api/tickets/friday/build",
        json={"budget_dollars": 96.0, "base_unit": 0.50},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is not None
    assert body["source"] == "tickets"
    assert len(body["data"]["variants"]) > 0


# ---------------------------------------------------------------------------
# /api/pick5/days + /api/pick5/{day}/debug
# ---------------------------------------------------------------------------


def test_pick5_days_returns_friday_and_saturday_config(
    client: TestClient,
) -> None:
    resp = client.get("/api/pick5/days")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"friday", "saturday"}

    friday = body["friday"]
    assert friday["label"] == "Friday"
    assert friday["productName"] == "Kentucky Oaks Pick 5"
    assert friday["date"] == FRIDAY_ISO
    assert friday["track"] == "Churchill Downs"
    assert friday["sequence"] == FRIDAY_LEGS

    saturday = body["saturday"]
    assert saturday["label"] == "Saturday"
    assert saturday["productName"] == "Kentucky Derby Pick 5"
    assert saturday["date"] == SATURDAY_ISO
    assert saturday["track"] == "Churchill Downs"
    assert saturday["sequence"] == SATURDAY_LEGS


def test_pick5_days_responds_quickly(client: TestClient) -> None:
    start = time.monotonic()
    resp = client.get("/api/pick5/days")
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert elapsed < 0.1, f"/api/pick5/days took {elapsed:.3f}s"


def test_pick5_days_appears_in_openapi(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/pick5/days" in paths
    assert "/api/pick5/{day}/debug" in paths


def test_pick5_debug_with_no_cache(client: TestClient) -> None:
    resp = client.get("/api/pick5/saturday/debug")
    assert resp.status_code == 200
    body = resp.json()
    assert body["day"] == "saturday"
    assert body["config"]["date"] == SATURDAY_ISO
    assert body["config"]["track"] == "Churchill Downs"
    assert body["config"]["sequence"] == SATURDAY_LEGS
    assert body["card"]["loaded"] is False
    assert body["card"]["raceCount"] == 0
    assert body["card"]["runnerCount"] == 0
    assert body["card"]["lastRefresh"] is None
    assert body["card"]["source"] is None
    assert body["odds"]["loaded"] is False
    assert body["odds"]["matchedRunnerCount"] == 0
    assert body["odds"]["lastRefresh"] is None
    assert body["sim"] == {"available": False}
    assert body["tickets"] == {"available": False}


def test_pick5_debug_after_fixture_refresh(client: TestClient) -> None:
    refresh = client.post("/api/cards/friday/refresh?source=fixture")
    assert refresh.status_code == 200

    resp = client.get("/api/pick5/friday/debug")
    assert resp.status_code == 200
    body = resp.json()
    assert body["day"] == "friday"
    assert body["config"]["sequence"] == FRIDAY_LEGS
    assert body["card"]["loaded"] is True
    assert body["card"]["raceCount"] == 5
    assert body["card"]["runnerCount"] > 0
    assert body["card"]["lastRefresh"] is not None
    assert body["odds"]["loaded"] is False
    assert body["odds"]["matchedRunnerCount"] == 0


def test_pick5_debug_friday_loaded_does_not_leak_into_saturday(
    client: TestClient,
) -> None:
    """Per-day SQLite files must keep state isolated across days."""
    refresh = client.post("/api/cards/friday/refresh?source=fixture")
    assert refresh.status_code == 200

    sat = client.get("/api/pick5/saturday/debug")
    assert sat.status_code == 200
    sat_body = sat.json()
    assert sat_body["card"]["loaded"] is False
    assert sat_body["card"]["raceCount"] == 0


def test_pick5_debug_reports_odds_after_fixture_odds_refresh(
    client: TestClient,
) -> None:
    card = client.post("/api/cards/friday/refresh?source=fixture")
    assert card.status_code == 200
    odds = client.post("/api/odds/friday/refresh?source=fixture")
    assert odds.status_code == 200

    resp = client.get("/api/pick5/friday/debug")
    assert resp.status_code == 200
    body = resp.json()
    assert body["odds"]["loaded"] is True
    assert body["odds"]["matchedRunnerCount"] > 0
    assert body["odds"]["lastRefresh"] is not None


def test_pick5_debug_invalid_day_returns_422(client: TestClient) -> None:
    resp = client.get("/api/pick5/sunday/debug")
    assert resp.status_code == 422


def test_pick5_debug_responds_quickly(
    tmp_data_dir: Path, client: TestClient
) -> None:
    _seed_cache("saturday", _full_card("saturday"), data_dir=tmp_data_dir)
    start = time.monotonic()
    resp = client.get("/api/pick5/saturday/debug")
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert elapsed < 0.1, f"/api/pick5/{{day}}/debug took {elapsed:.3f}s"


def test_fixture_mode_makes_no_network_calls(client: TestClient) -> None:
    """Equibase / TwinSpires are overridden with stubs that raise on use.

    If fixture mode incorrectly fell through to the live path, the stubs
    would fire — surfacing a stale envelope rather than the success
    envelope this test asserts.
    """

    class ExplodingEquibase:
        def fetch_race(self, *a: object, **kw: object) -> Race | None:
            raise AssertionError("fixture mode must not hit equibase")

    class ExplodingTwinSpires:
        def fetch_program(self, *a: object, **kw: object) -> Race | None:
            raise AssertionError("fixture mode must not hit twinspires program")

        def fetch_odds(self, *a: object, **kw: object) -> list[Any]:
            raise AssertionError("fixture mode must not hit twinspires odds")

    app.dependency_overrides[get_equibase_adapter] = lambda: ExplodingEquibase()
    app.dependency_overrides[get_twinspires_adapter] = (
        lambda: ExplodingTwinSpires()
    )
    try:
        resp = client.post("/api/cards/saturday/refresh?source=fixture")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "fixture"
        assert body["stale"] is False

        resp = client.post("/api/odds/saturday/refresh?source=fixture")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "fixture"
        assert body["stale"] is False
    finally:
        app.dependency_overrides.clear()
