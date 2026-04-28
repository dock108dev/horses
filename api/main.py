"""FastAPI application for the Derby Pick 5 backend.

All non-health endpoints return a single envelope: ``{data, stale,
cached_at, source, errors}``. ``stale=True`` means the response came
from the SQLite cache because the live source either failed validation
(``errors`` populated by ``validate_card``) or raised (``errors=[str(exc)]``).
Per the "Cache Strategy" section of ``BRAINDUMP.md``, the API never
returns a blank payload during race day if a prior validated snapshot
exists.

LOC note: ~816 LOC, over the 500-line guideline. Every section here is
FastAPI route wiring on the single app instance; an early ``routers/``
split would fragment the request/response contract for no behavioral
win. See ``docs/audits/cleanup-report.md`` "Files still >500 LOC".
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from api.cache import OddsCache
from api.model import PICK5_LEG_ROLES, Race, blend_race
from api.refresh import build_card, poll_pick5_odds, races_with_latest_odds
from api.sources.equibase import SOURCE_NAME as EQUIBASE_SOURCE, EquibaseAdapter
from api.sources.fixture import (
    SOURCE_NAME as FIXTURE_SOURCE,
    fixture_mode_enabled,
    load_card as load_fixture_card,
    load_odds_records as load_fixture_odds,
)
from api.sources.pick5 import get_pick5_legs
from api.sources.twinspires import (
    SOURCE_NAME as TWINSPIRES_SOURCE,
    TwinSpiresAdapter,
)
from api.validate import validate_card

DayParam = Literal["friday", "saturday"]

DEFAULT_DERBY_DATES: dict[str, str] = {
    "friday": "2026-05-01",
    "saturday": "2026-05-02",
}

PICK5_DAY_LABELS: dict[str, str] = {
    "friday": "Friday",
    "saturday": "Saturday",
}

PICK5_PRODUCT_NAMES: dict[str, str] = {
    "friday": "Kentucky Oaks Pick 5",
    "saturday": "Kentucky Derby Pick 5",
}

PICK5_TRACK = "Churchill Downs"

ALLOWED_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://mac-mini.local:3000",
    "http://localhost:8000",
]

CACHE_SOURCE = "cache"
COMBINED_SOURCE = f"{EQUIBASE_SOURCE}+{TWINSPIRES_SOURCE}"
SIM_SOURCE = "sim"
TICKETS_SOURCE = "tickets"
NO_CARD_ERROR = "no cached card; call POST /api/cards/{day}/refresh first"
LIVE_SOURCE_ERROR = "live source unavailable; serving cached snapshot"
SIM_INTERNAL_ERROR = "simulation failed; check server logs"
TICKETS_INTERNAL_ERROR = "ticket build failed; check server logs"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# URL fragments and absolute filesystem paths in the message bodies of
# upstream exceptions can leak source endpoints / internal layout to the
# browser. Strip both before placing the redacted string in an Envelope.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_FS_PATH_RE = re.compile(r"(?:/[^\s'\"]+){2,}")

_log = logging.getLogger(__name__)


def _redact_exc(exc: BaseException) -> str:
    """Return an exception summary safe to surface in an HTTP response.

    Keeps the exception class name (useful for the iPad UI to distinguish
    an HTTP 5xx from a parse failure) but strips any absolute URLs and
    filesystem paths from the message — those can leak the upstream
    scraper endpoints and the on-disk cache layout. Full traceback is
    still logged via ``_log.exception`` at the call site.
    """
    raw = str(exc) or exc.__class__.__name__
    cleaned = _URL_RE.sub("<url>", raw)
    cleaned = _FS_PATH_RE.sub("<path>", cleaned)
    return f"{exc.__class__.__name__}: {cleaned}"


# ---------------------------------------------------------------------------
# Response envelope + helpers
# ---------------------------------------------------------------------------


class Envelope(BaseModel):
    """Standard response shape for every non-health endpoint."""

    data: Any
    stale: bool
    cached_at: str | None
    source: str
    errors: list[str]


def day_to_iso_date(day: str) -> str:
    """Map ``"friday"`` / ``"saturday"`` to an ISO date.

    Override per-day with ``DERBY_FRIDAY_DATE`` / ``DERBY_SATURDAY_DATE``
    env vars (deploy-time configuration for the next year's Derby). The
    env value must match ``YYYY-MM-DD`` exactly — without that the value
    flows into both the on-disk SQLite filename (``odds_{iso_date}.db``)
    and the upstream-scraper URL builders, where ``../`` segments would
    enable a path-traversal write or an oddly-shaped outbound request.
    """
    env_value = os.getenv(f"DERBY_{day.upper()}_DATE")
    if env_value:
        if not _ISO_DATE_RE.match(env_value):
            raise ValueError(
                f"DERBY_{day.upper()}_DATE must be YYYY-MM-DD, got "
                f"{env_value!r}"
            )
        return env_value
    return DEFAULT_DERBY_DATES[day]


def _data_dir() -> Path:
    return Path(os.getenv("API_DATA_DIR", "data"))


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _races_to_data(races: list[Race]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in races]


# ---------------------------------------------------------------------------
# FastAPI dependencies (overridable in tests)
# ---------------------------------------------------------------------------


async def get_cache(day: DayParam) -> AsyncIterator[OddsCache]:
    """Yield a per-request SQLite cache opened on the event-loop thread.

    Async so the connection lives on the same thread as the async
    endpoint that consumes it — sqlite3 connections are not safe to share
    across threads, and FastAPI runs sync dependencies in a worker pool.
    """
    iso_date = day_to_iso_date(day)
    cache = OddsCache(iso_date, data_dir=_data_dir())
    try:
        yield cache
    finally:
        cache.close()


async def get_equibase_adapter() -> AsyncIterator[EquibaseAdapter]:
    # Persist Equibase HTML to disk so a same-day re-refresh skips the 12-15
    # live HTTP fetches plus the 3s/req rate-limit floor. Cache keys are URL
    # paths (date- and race-scoped by construction), so no TTL is needed —
    # a stale page only resurfaces if we re-run on the same calendar date,
    # which is exactly when re-fetching would be wasteful.
    cache_dir = _data_dir() / "equibase_html"
    with EquibaseAdapter(cache_dir=cache_dir) as adapter:
        yield adapter


async def get_twinspires_adapter() -> AsyncIterator[TwinSpiresAdapter]:
    with TwinSpiresAdapter() as adapter:
        yield adapter


# ---------------------------------------------------------------------------
# App + CORS + middleware
# ---------------------------------------------------------------------------


app = FastAPI(
    title="Derby Pick 5 API",
    version="0.1.0",
    description=(
        "Backend for Derby weekend Pick 5 race-card ingestion, "
        "simulation, and ticket building."
    ),
)

_env_origins = os.getenv("API_CORS_ORIGINS", "").strip()
if _env_origins:
    _origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
else:
    _origins = ALLOWED_CORS_ORIGINS

# Reject the wildcard explicitly. Starlette's CORSMiddleware reflects the
# request Origin back when allow_origins=["*"] AND allow_credentials=True,
# which effectively allows any third-party site to read this API in the
# user's browser. There is no auth on this app — there is also no CORS
# need for *.
if "*" in _origins:
    raise RuntimeError(
        "API_CORS_ORIGINS=* is not permitted; list explicit origins."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # No cookies / Authorization headers are sent by the SPA, so there is
    # no reason to opt into credentialed CORS — and disabling it removes
    # the wildcard-with-credentials reflection vector entirely.
    allow_credentials=False,
    # Narrow to the verbs and headers the SPA actually uses. allow_headers
    # is a preflight allow-list, not a request filter, but tightening it
    # blocks third-party tools from probing exotic header behavior.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
    max_age=600,
)


# Security headers — defense-in-depth for the iPad browser surface. We do
# not ship cookies or third-party assets; CSP is therefore strict by
# default.
@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Response:
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "interest-cohort=(), geolocation=(), camera=()"
    )
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    return response


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _stale_card_envelope(
    cache: OddsCache, iso_date: str, *, errors: list[str]
) -> Envelope:
    cached = cache.get_last_good_card(iso_date)
    if cached is None:
        return Envelope(
            data=[],
            stale=True,
            cached_at=None,
            source=CACHE_SOURCE,
            errors=errors or ["no cached card available"],
        )
    return Envelope(
        data=_races_to_data(cached.races),
        stale=True,
        cached_at=_iso_from_ms(cached.captured_at_ms),
        source=CACHE_SOURCE,
        errors=errors,
    )


@app.get("/api/cards/{day}", response_model=Envelope)
async def get_card(
    day: DayParam,
    cache: OddsCache = Depends(get_cache),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    cached = cache.get_last_good_card(iso_date)
    if cached is None:
        return Envelope(
            data=[],
            stale=False,
            cached_at=None,
            source=CACHE_SOURCE,
            errors=["no cached card; call POST /api/cards/{day}/refresh"],
        )
    return Envelope(
        data=_races_to_data(cached.races),
        stale=False,
        cached_at=_iso_from_ms(cached.captured_at_ms),
        source=CACHE_SOURCE,
        errors=[],
    )


@app.post("/api/cards/{day}/refresh", response_model=Envelope)
async def refresh_card(
    day: DayParam,
    source: str | None = None,
    cache: OddsCache = Depends(get_cache),
    equibase: EquibaseAdapter = Depends(get_equibase_adapter),
    twinspires: TwinSpiresAdapter = Depends(get_twinspires_adapter),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    if fixture_mode_enabled(source_query=source):
        try:
            races = load_fixture_card(day)
            result = validate_card(races, day)
            if not result.valid:
                return _stale_card_envelope(
                    cache, iso_date, errors=result.errors
                )
            captured_at_ms = cache.store_card(iso_date, races, validated=True)
            return Envelope(
                data=_races_to_data(races),
                stale=False,
                cached_at=_iso_from_ms(captured_at_ms),
                source=FIXTURE_SOURCE,
                errors=[],
            )
        except Exception as exc:
            _log.exception("Fixture card refresh failed for day=%s", day)
            return _stale_card_envelope(
                cache, iso_date, errors=[LIVE_SOURCE_ERROR, _redact_exc(exc)]
            )
    year = int(iso_date.split("-", 1)[0])
    try:
        legs = get_pick5_legs(year=year, day=day)
        # build_card is sync and performs blocking I/O (httpx GETs, rate-limit
        # sleeps). Run it in a worker thread so the event-loop thread stays
        # free for /api/health, /docs, and other concurrent requests during
        # the 60-240s refresh window.
        races = await asyncio.to_thread(
            functools.partial(
                build_card,
                day=day,
                iso_date=iso_date,
                legs=legs,
                equibase=equibase,
                twinspires=twinspires,
            )
        )
        result = validate_card(races, day)
        if not result.valid:
            return _stale_card_envelope(cache, iso_date, errors=result.errors)
        captured_at_ms = cache.store_card(iso_date, races, validated=True)
        return Envelope(
            data=_races_to_data(races),
            stale=False,
            cached_at=_iso_from_ms(captured_at_ms),
            source=COMBINED_SOURCE,
            errors=[],
        )
    except Exception as exc:
        # Broad catch is the BRAINDUMP cache-fallback contract: any live
        # ingestion failure must surface as stale data, never a 500.
        # Logged via _log.exception so the original traceback is captured.
        # See error-handling-report finding F3. Surface a redacted message
        # only — raw str(exc) leaks scraper URLs (security-report S3).
        _log.exception("Card refresh failed for day=%s", day)
        return _stale_card_envelope(
            cache, iso_date, errors=[LIVE_SOURCE_ERROR, _redact_exc(exc)]
        )


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------


def _odds_payload(
    races: list[Race], cache: OddsCache
) -> list[dict[str, Any]]:
    """Build the per-race latest-odds list for GET / POST odds endpoints."""
    out: list[dict[str, Any]] = []
    for race in races:
        if race.sequenceRole not in PICK5_LEG_ROLES:
            continue
        rows = cache.get_latest_odds(race.id)
        out.append(
            {
                "raceId": race.id,
                "raceNumber": race.raceNumber,
                "sequenceRole": race.sequenceRole,
                "runners": [
                    {
                        "horseId": r.horse_id,
                        "horseName": r.horse_name,
                        "odds": r.odds,
                        "impliedProbability": r.implied_probability,
                        "source": r.source,
                        "capturedAt": _iso_from_ms(r.captured_at_ms),
                    }
                    for r in rows
                ],
            }
        )
    return out


def _stale_odds_envelope(
    cache: OddsCache, races: list[Race], *, errors: list[str]
) -> Envelope:
    payload = _odds_payload(races, cache)
    latest = max(
        (
            run["capturedAt"]
            for race in payload
            for run in race["runners"]
        ),
        default=None,
    )
    return Envelope(
        data=payload,
        stale=True,
        cached_at=latest,
        source=CACHE_SOURCE,
        errors=errors,
    )


@app.get("/api/odds/{day}", response_model=Envelope)
async def get_odds(
    day: DayParam,
    cache: OddsCache = Depends(get_cache),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    cached_card = cache.get_last_good_card(iso_date)
    if cached_card is None:
        return Envelope(
            data=[],
            stale=False,
            cached_at=None,
            source=CACHE_SOURCE,
            errors=["no cached card; call POST /api/cards/{day}/refresh"],
        )
    return Envelope(
        data=_odds_payload(cached_card.races, cache),
        stale=False,
        cached_at=_iso_from_ms(cached_card.captured_at_ms),
        source=CACHE_SOURCE,
        errors=[],
    )


@app.post("/api/odds/{day}/refresh", response_model=Envelope)
async def refresh_odds(
    day: DayParam,
    source: str | None = None,
    cache: OddsCache = Depends(get_cache),
    twinspires: TwinSpiresAdapter = Depends(get_twinspires_adapter),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    cached_card = cache.get_last_good_card(iso_date)
    if cached_card is None:
        return Envelope(
            data=[],
            stale=True,
            cached_at=None,
            source=CACHE_SOURCE,
            errors=[NO_CARD_ERROR],
        )
    if fixture_mode_enabled(source_query=source):
        try:
            captured_at_ms = int(time.time() * 1000)
            records = load_fixture_odds(
                day, cached_card.races, captured_at_ms=captured_at_ms
            )
            cache.store_odds_batch(records)
            updated = races_with_latest_odds(cached_card.races, cache)
            result = validate_card(updated, day)
            if not result.valid:
                return _stale_odds_envelope(
                    cache, cached_card.races, errors=result.errors
                )
            return Envelope(
                data=_odds_payload(updated, cache),
                stale=False,
                cached_at=_iso_from_ms(captured_at_ms),
                source=FIXTURE_SOURCE,
                errors=[],
            )
        except Exception as exc:
            _log.exception("Fixture odds refresh failed for day=%s", day)
            return _stale_odds_envelope(
                cache,
                cached_card.races,
                errors=[LIVE_SOURCE_ERROR, _redact_exc(exc)],
            )
    try:
        captured_at_ms = int(time.time() * 1000)
        # poll_pick5_odds blocks on TwinSpires HTTP calls plus the per-race
        # 30s odds-poll floor; offload to a worker thread so concurrent
        # requests are not stalled. See refresh_card for the same pattern.
        records = await asyncio.to_thread(
            functools.partial(
                poll_pick5_odds,
                cached_card.races,
                iso_date=iso_date,
                twinspires=twinspires,
                captured_at_ms=captured_at_ms,
            )
        )
        cache.store_odds_batch(records)
        updated = races_with_latest_odds(cached_card.races, cache)
        result = validate_card(updated, day)
        if not result.valid:
            return _stale_odds_envelope(
                cache, cached_card.races, errors=result.errors
            )
        return Envelope(
            data=_odds_payload(updated, cache),
            stale=False,
            cached_at=_iso_from_ms(captured_at_ms),
            source=TWINSPIRES_SOURCE,
            errors=[],
        )
    except Exception as exc:
        # Same cache-fallback contract as refresh_card; finding F3. Same
        # redaction as refresh_card to avoid leaking the TwinSpires odds
        # endpoint URL (security-report S3).
        _log.exception("Odds refresh failed for day=%s", day)
        return _stale_odds_envelope(
            cache,
            cached_card.races,
            errors=[LIVE_SOURCE_ERROR, _redact_exc(exc)],
        )


# ---------------------------------------------------------------------------
# Simulation + tickets (delegated; placeholders until those modules land)
# ---------------------------------------------------------------------------


class SimulateRequest(BaseModel):
    # Forbid extras so the UI cannot quietly post fields the backend does
    # not consume (e.g. `tags`, `oddsOverrides`). Pydantic's default of
    # silent acceptance hid a real ack-and-drop hazard — see
    # error-handling-report finding F17 / Escalation E1.
    model_config = ConfigDict(extra="forbid")

    # Upper bound mirrors ``api.sim.MAX_ITERATIONS`` so the request is
    # rejected with a 422 at the boundary instead of being silently clamped
    # inside the engine. ``ge=1`` rejects 0 / negative / overflowed inputs
    # before any work runs. See security-report S4.
    n_iterations: int | None = Field(default=None, ge=1, le=100_000)


class TicketsRequest(BaseModel):
    # See SimulateRequest — same extra-forbid contract for the same
    # silent-drop reason. F17.
    model_config = ConfigDict(extra="forbid")

    # ``budget_dollars`` ge=0 matches ``BudgetVariant.budget_dollars``
    # already at the response boundary; lifting it to the request boundary
    # converts a noisy internal ValidationError into a clean 422 and keeps
    # negative budgets out of ``build_tickets_for_budgets``. ``base_unit``
    # is strictly positive: zero would make every ticket cost $0 (driving
    # ``_fit_to_budget`` add-loop until every horse is selected) and a
    # negative value would invert the cost ordering. ``le`` caps cap the
    # values so a fat-fingered keypad input or a hostile payload cannot
    # produce huge numeric strings in the response. See security-report S4.
    budget_dollars: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    base_unit: float | None = Field(default=None, gt=0.0, le=1_000_000.0)


def _no_card_envelope(source: str) -> Envelope:
    return Envelope(
        data=None,
        stale=True,
        cached_at=None,
        source=source,
        errors=[NO_CARD_ERROR],
    )


@app.post("/api/simulate/{day}", response_model=Envelope)
async def simulate(
    day: DayParam,
    request: SimulateRequest | None = None,
    cache: OddsCache = Depends(get_cache),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    cached_card = cache.get_last_good_card(iso_date)
    if cached_card is None:
        return _no_card_envelope(CACHE_SOURCE)
    cached_at = _iso_from_ms(cached_card.captured_at_ms)
    from api import sim

    n_iterations = (request.n_iterations if request else None) or sim.DEFAULT_ITERATIONS
    races = cached_card.races
    for race in races:
        if any(h.finalProbability is None for h in race.horses if not h.scratched):
            blend_race(race, has_model_prior=False)
    tickets = sim.default_tickets_from_tags(races)
    if not tickets:
        return Envelope(
            data=None,
            stale=False,
            cached_at=cached_at,
            source=SIM_SOURCE,
            errors=["no eligible Pick 5 selections; tag horses or refresh card"],
        )
    try:
        result = sim.simulate(races, tickets, n_iterations=n_iterations)
    except Exception as exc:
        # Same envelope contract as the cache fallbacks; finding F8.
        # Redacted message only — raw str(exc) leaks paths under stack
        # traces from numpy / pydantic (security-report S3).
        _log.exception("Simulation failed for day=%s", day)
        return Envelope(
            data=None,
            stale=False,
            cached_at=cached_at,
            source=SIM_SOURCE,
            errors=[SIM_INTERNAL_ERROR, _redact_exc(exc)],
        )
    return Envelope(
        data=result.model_dump(mode="json"),
        stale=False,
        cached_at=cached_at,
        source=SIM_SOURCE,
        errors=[],
    )


@app.post("/api/tickets/{day}/build", response_model=Envelope)
async def build_tickets(
    day: DayParam,
    request: TicketsRequest | None = None,
    cache: OddsCache = Depends(get_cache),
) -> Envelope:
    iso_date = day_to_iso_date(day)
    cached_card = cache.get_last_good_card(iso_date)
    if cached_card is None:
        return _no_card_envelope(CACHE_SOURCE)
    cached_at = _iso_from_ms(cached_card.captured_at_ms)
    from api import tickets

    base_unit = (request.base_unit if request else None) or 0.50
    custom_budget = request.budget_dollars if request else None
    budgets: list[float] = list(tickets.STANDARD_BUDGETS)
    if custom_budget is not None and float(custom_budget) not in budgets:
        budgets.append(float(custom_budget))

    races = cached_card.races
    for race in races:
        if any(h.finalProbability is None for h in race.horses if not h.scratched):
            blend_race(race, has_model_prior=False)

    try:
        variants = tickets.build_tickets_for_budgets(
            races, budgets=budgets, base_unit=base_unit
        )
    except Exception as exc:
        # Same envelope contract as the cache fallbacks; finding F8.
        # Redacted message only (security-report S3).
        _log.exception("Ticket build failed for day=%s", day)
        return Envelope(
            data=None,
            stale=False,
            cached_at=cached_at,
            source=TICKETS_SOURCE,
            errors=[TICKETS_INTERNAL_ERROR, _redact_exc(exc)],
        )
    return Envelope(
        data={"variants": [v.model_dump(mode="json") for v in variants]},
        stale=False,
        cached_at=cached_at,
        source=TICKETS_SOURCE,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Self-describe + debug
# ---------------------------------------------------------------------------


def _day_config(day: str) -> dict[str, Any]:
    iso_date = day_to_iso_date(day)
    year = int(iso_date.split("-", 1)[0])
    sequence = get_pick5_legs(year=year, day=day)
    return {
        "label": PICK5_DAY_LABELS[day],
        "productName": PICK5_PRODUCT_NAMES[day],
        "date": iso_date,
        "track": PICK5_TRACK,
        "sequence": sequence,
    }


def _card_source_label(races: list[Race]) -> str | None:
    sources = {
        h.source for r in races for h in r.horses if h.source
    }
    if not sources:
        return None
    return "+".join(sorted(sources))


@app.get("/api/pick5/days")
async def get_pick5_days() -> dict[str, dict[str, Any]]:
    """Return the authoritative day/date/track/sequence config.

    No external calls — reads ``PICK5_SEQUENCES`` plus the configured ISO
    dates so the frontend (and anyone hitting Swagger) has a single source
    of truth for which races make up each Pick 5.
    """
    return {day: _day_config(day) for day in ("friday", "saturday")}


@app.get("/api/pick5/{day}/debug")
async def get_pick5_debug(
    day: DayParam,
    cache: OddsCache = Depends(get_cache),
) -> dict[str, Any]:
    """Return current workflow state for ``day`` from the SQLite cache.

    No external calls — useful for diagnosing what state the system is
    in without opening browser devtools. ``card.source`` is derived from
    the cached horses' ``source`` fields (e.g. ``"fixture"`` or
    ``"equibase+twinspires"``); ``None`` when no source attribution
    survived round-tripping through the cache.
    """
    iso_date = day_to_iso_date(day)
    cached = cache.get_last_good_card(iso_date)

    if cached is None:
        card_info: dict[str, Any] = {
            "loaded": False,
            "raceCount": 0,
            "runnerCount": 0,
            "lastRefresh": None,
            "source": None,
        }
        odds_info: dict[str, Any] = {
            "loaded": False,
            "matchedRunnerCount": 0,
            "lastRefresh": None,
        }
    else:
        card_info = {
            "loaded": True,
            "raceCount": len(cached.races),
            "runnerCount": sum(len(r.horses) for r in cached.races),
            "lastRefresh": _iso_from_ms(cached.captured_at_ms),
            "source": _card_source_label(cached.races),
        }
        matched = 0
        latest_ms = 0
        for race in cached.races:
            rows = cache.get_latest_odds(race.id)
            matched += len(rows)
            for row in rows:
                if row.captured_at_ms > latest_ms:
                    latest_ms = row.captured_at_ms
        odds_info = {
            "loaded": matched > 0,
            "matchedRunnerCount": matched,
            "lastRefresh": _iso_from_ms(latest_ms) if latest_ms > 0 else None,
        }

    return {
        "day": day,
        "config": {
            "date": iso_date,
            "track": PICK5_TRACK,
            "sequence": _day_config(day)["sequence"],
        },
        "card": card_info,
        "odds": odds_info,
        # Sim and ticket results are computed on demand, not cached, so
        # there is nothing to surface here beyond "the route exists".
        "sim": {"available": False},
        "tickets": {"available": False},
    }


__all__ = [
    "ALLOWED_CORS_ORIGINS",
    "DEFAULT_DERBY_DATES",
    "Envelope",
    "PICK5_DAY_LABELS",
    "PICK5_PRODUCT_NAMES",
    "PICK5_TRACK",
    "app",
    "day_to_iso_date",
    "get_cache",
    "get_equibase_adapter",
    "get_twinspires_adapter",
]
