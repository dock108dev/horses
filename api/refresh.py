"""Refresh-cycle orchestration: card build + odds polling.

Splits the heavy lifting out of ``api/main.py`` so the FastAPI app stays
focused on HTTP wiring, response shaping, and the stale-cache fallback
contract. These helpers are pure functions over the source-adapter and
cache interfaces — easy to unit-test in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from api.cache import OddsCache, OddsSnapshotRecord
from api.model import PICK5_LEG_ROLES, Horse, Race
from api.normalize import (
    assign_pick5_sequence_roles,
    merge_horses,
    normalize_probabilities,
    odds_to_probability,
)
from api.sources.equibase import EquibaseAdapter
from api.sources.twinspires import (
    SOURCE_NAME as TWINSPIRES_SOURCE,
    TwinSpiresAdapter,
    post_from_program_number,
    to_fractional_odds,
)

_log = logging.getLogger(__name__)


def build_card(
    *,
    day: str,
    iso_date: str,
    legs: list[int],
    equibase: EquibaseAdapter,
    twinspires: TwinSpiresAdapter,
) -> list[Race]:
    """Fetch + merge + normalize one race per Pick 5 leg.

    Equibase is canonical for IDs / morning line / jockey / trainer.
    TwinSpires program JSON is best-effort live odds; a TwinSpires error
    on a single race is downgraded to a warning so the rest of the card
    still ingests. Equibase errors propagate so the caller can fall back
    to the SQLite cache.
    """
    races: list[Race] = []
    for race_number in legs:
        eq_race = equibase.fetch_race(iso_date, race_number, day=day)
        if eq_race is None:
            continue
        try:
            ts_race = twinspires.fetch_program(iso_date, race_number, day=day)
        except Exception as exc:
            # Per-leg downgrade — a single TwinSpires hiccup must not
            # blank out the rest of the card. validate_card downstream
            # will still flag missing odds. See finding F4.
            _log.warning(
                "TwinSpires program fetch failed for race %d: %s",
                race_number,
                exc,
            )
            ts_race = None
        ts_horses = ts_race.horses if ts_race is not None else []
        merged = _merge_and_score(eq_race.horses, ts_horses)
        normalize_probabilities(merged, field="marketProbability")
        normalize_probabilities(merged, field="morningLineProbability")
        races.append(eq_race.model_copy(update={"horses": merged}))
    assign_pick5_sequence_roles(races, legs)
    return races


def _merge_and_score(
    equibase_horses: list[Horse], twinspires_horses: list[Horse]
) -> list[Horse]:
    merged = merge_horses(equibase_horses, twinspires_horses)
    for h in merged:
        if h.morningLineProbability is None:
            ml = odds_to_probability(h.morningLineOdds)
            if ml is not None:
                h.morningLineProbability = ml
    return merged


def poll_pick5_odds(
    races: Iterable[Race],
    *,
    iso_date: str,
    twinspires: TwinSpiresAdapter,
    captured_at_ms: int,
) -> list[OddsSnapshotRecord]:
    """Poll TwinSpires odds for every Pick 5 leg, returning storable records."""
    records: list[OddsSnapshotRecord] = []
    for race in races:
        if race.sequenceRole not in PICK5_LEG_ROLES:
            continue
        horses_by_post = {h.post: h for h in race.horses if not h.scratched}
        rows = twinspires.fetch_odds(iso_date, race.raceNumber)
        for row in rows:
            pn = str(row.get("programNumber") or "")
            win = row.get("winOdds")
            if not pn or not win:
                continue
            post = post_from_program_number(pn)
            if post is None or post not in horses_by_post:
                continue
            horse = horses_by_post[post]
            fractional = to_fractional_odds(win) or win
            prob = odds_to_probability(fractional)
            if prob is None:
                continue
            records.append(
                OddsSnapshotRecord(
                    race_id=race.id,
                    horse_id=horse.id,
                    horse_name=horse.name,
                    odds=fractional,
                    implied_probability=prob,
                    source=TWINSPIRES_SOURCE,
                    captured_at_ms=captured_at_ms,
                )
            )
    return records


def races_with_latest_odds(
    races: list[Race], cache: OddsCache
) -> list[Race]:
    """Copy ``races`` with currentOdds + marketProbability filled from cache."""
    updated: list[Race] = []
    for race in races:
        latest = {r.horse_id: r for r in cache.get_latest_odds(race.id)}
        new_horses: list[Horse] = []
        for h in race.horses:
            rec = latest.get(h.id)
            if rec is None or h.scratched:
                new_horses.append(h.model_copy())
                continue
            new_horses.append(
                h.model_copy(
                    update={
                        "currentOdds": rec.odds,
                        "marketProbability": rec.implied_probability,
                    }
                )
            )
        normalize_probabilities(new_horses, field="marketProbability")
        updated.append(race.model_copy(update={"horses": new_horses}))
    return updated


__all__ = [
    "build_card",
    "poll_pick5_odds",
    "races_with_latest_odds",
]
