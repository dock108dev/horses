"""Fixture-mode source: load static JSON instead of hitting Equibase / TwinSpires.

Activated by ``?source=fixture`` on the ``/refresh`` endpoints or by the
``PICK5_DATA_MODE=fixture`` env var. Reads card + odds JSON from
``fixtures/pick5/{day}-{card,odds}.json`` (override the directory with
``PICK5_FIXTURES_DIR``). Lets the operator exercise the full Pick 5
workflow before the live sources are publishing entries / odds — see
``BRAINDUMP.md`` "Cache Strategy" for the live-source timing window.

The loader runs the same odds → ``morningLineProbability`` parse +
per-race ``normalize_probabilities`` step that ``api.refresh.build_card``
applies to live data, so the fixture path is byte-compatible with the
downstream blend / sim / ticket layers.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from api.cache import OddsSnapshotRecord
from api.model import Horse, Race
from api.normalize import normalize_probabilities, odds_to_probability

SOURCE_NAME = "fixture"
DEFAULT_FIXTURES_DIR = Path("fixtures/pick5")
ENV_DATA_MODE = "PICK5_DATA_MODE"
ENV_FIXTURES_DIR = "PICK5_FIXTURES_DIR"


def fixtures_dir() -> Path:
    """Return the directory holding the ``{day}-card.json`` / ``{day}-odds.json`` files."""
    override = os.getenv(ENV_FIXTURES_DIR, "").strip()
    if override:
        return Path(override)
    return DEFAULT_FIXTURES_DIR


def fixture_mode_enabled(*, source_query: str | None = None) -> bool:
    """Decide whether the request should be served from fixtures.

    Truthy when either the ``?source=fixture`` query param is supplied or
    ``PICK5_DATA_MODE=fixture`` is set in the process environment.
    """
    if source_query is not None and source_query.strip().lower() == SOURCE_NAME:
        return True
    return os.getenv(ENV_DATA_MODE, "").strip().lower() == SOURCE_NAME


def load_card(day: str) -> list[Race]:
    """Read ``{day}-card.json`` and return the parsed, normalized races.

    Mirrors :func:`api.refresh.build_card`: parses ``morningLineOdds``
    into ``morningLineProbability`` for each non-scratched horse and
    re-normalizes per race so the post-refresh validate check passes.
    """
    path = fixtures_dir() / f"{day}-card.json"
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(
            f"fixture card file {path} must be a JSON array, got "
            f"{type(raw).__name__}"
        )
    races = [Race.model_validate(r) for r in raw]
    for race in races:
        for h in race.horses:
            if h.scratched:
                continue
            if h.morningLineProbability is None:
                ml = odds_to_probability(h.morningLineOdds)
                if ml is not None:
                    h.morningLineProbability = ml
        normalize_probabilities(race.horses, field="morningLineProbability")
    return races


def load_odds_records(
    day: str,
    races: list[Race],
    *,
    captured_at_ms: int | None = None,
) -> list[OddsSnapshotRecord]:
    """Read ``{day}-odds.json`` and resolve it against the supplied card.

    Each fixture entry is ``{"raceId", "post", "odds"}``. Records whose
    ``(raceId, post)`` does not match a non-scratched horse in ``races``
    are skipped — keeps a fixture odds file usable across small card
    edits without needing to be regenerated.
    """
    path = fixtures_dir() / f"{day}-odds.json"
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(
            f"fixture odds file {path} must be a JSON array, got "
            f"{type(raw).__name__}"
        )

    horses_by_key: dict[tuple[str, int], Horse] = {}
    for race in races:
        for h in race.horses:
            if h.scratched:
                continue
            horses_by_key[(race.id, h.post)] = h

    captured = (
        captured_at_ms if captured_at_ms is not None else int(time.time() * 1000)
    )
    records: list[OddsSnapshotRecord] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        race_id = str(entry.get("raceId") or "").strip()
        post = entry.get("post")
        odds_raw = entry.get("odds")
        if not race_id or not isinstance(post, int) or odds_raw is None:
            continue
        odds = str(odds_raw).strip()
        if not odds:
            continue
        horse = horses_by_key.get((race_id, post))
        if horse is None:
            continue
        prob = odds_to_probability(odds)
        if prob is None:
            continue
        records.append(
            OddsSnapshotRecord(
                race_id=race_id,
                horse_id=horse.id,
                horse_name=horse.name,
                odds=odds,
                implied_probability=prob,
                source=SOURCE_NAME,
                captured_at_ms=captured,
            )
        )
    return records


__all__ = [
    "DEFAULT_FIXTURES_DIR",
    "ENV_DATA_MODE",
    "ENV_FIXTURES_DIR",
    "SOURCE_NAME",
    "fixture_mode_enabled",
    "fixtures_dir",
    "load_card",
    "load_odds_records",
]
