"""Normalization layer for the Derby Pick 5 backend.

Four primitives the rest of the backend can compose:

1. :func:`odds_to_probability` — parse fractional ('5/2'), integer-to-1
   ('4-1'), decimal ('4.80'), and 'EVS' odds strings into implied
   probabilities using ``prob = 1 / (decimal_equivalent + 1)``.
2. :func:`normalize_probabilities` — pari-mutuel overround removal.
   Divide each non-scratched horse's probability by the sum so they
   total exactly 1.0; clear the field for scratched horses.
3. :func:`merge_horses` — combine the Equibase entry list (canonical
   for IDs / morning line) with the TwinSpires runner list (live odds).
   Match by post number first, then a normalized-name fallback with
   ``difflib.get_close_matches(cutoff=0.85)``.
4. :func:`assign_pick5_sequence_roles` — tag the five legs of the Pick 5
   sequence on the supplied :class:`Race` objects.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, cast

from api.model import PICK5_LEG_COUNT, Horse, Race, SequenceRole

MISSING_LIVE_ODDS_FLAG = "missing-live-odds"
NAME_MATCH_CUTOFF = 0.85

_COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,4})\)\s*$")
_NAME_PUNCT_RE = re.compile(r"[^a-z0-9]")
_FRACTIONAL_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)$")
_EVENS_TOKENS = frozenset({"evs", "even", "evens", "ev", "even money"})


# ---------------------------------------------------------------------------
# Odds parsing
# ---------------------------------------------------------------------------


def odds_to_probability(odds: Any) -> float | None:
    """Parse an odds string into an implied win probability in ``[0, 1]``.

    Accepts fractional (``"5/2"``), integer-to-1 (``"4-1"``), decimal
    (``"4.80"``), and the literal ``"EVS"``/``"EVEN"`` token. Returns
    ``None`` for missing, blank, or unparseable inputs (so callers can
    distinguish "no quote" from "0% probability").
    """
    if odds is None:
        return None
    raw = str(odds).strip()
    if not raw:
        return None

    if raw.lower() in _EVENS_TOKENS:
        return 0.5

    decimal: float | None = _parse_odds_to_decimal(raw)
    if decimal is None or decimal < 0:
        return None
    return 1.0 / (decimal + 1.0)


def _parse_odds_to_decimal(raw: str) -> float | None:
    """Return the win-payout ratio as a decimal, or ``None`` if unparseable.

    ``"5/2"`` and ``"5-2"`` both produce ``2.5``; ``"4.80"`` produces
    ``4.80``; ``"3"`` produces ``3.0``.
    """
    s = raw.replace(" ", "")
    match = _FRACTIONAL_RE.match(s)
    if match:
        try:
            num = float(match.group(1))
            den = float(match.group(2))
        except ValueError:
            # Unparseable token — caller distinguishes None ("no quote")
            # from 0.0 ("zero probability"). See finding F11.
            return None
        if den == 0:
            return None
        return num / den
    try:
        return float(s)
    except ValueError:
        # Same None-as-sentinel contract as above. F11.
        return None


# ---------------------------------------------------------------------------
# Per-race probability normalization
# ---------------------------------------------------------------------------


def normalize_probabilities(
    horses: list[Horse],
    *,
    field: str = "marketProbability",
) -> None:
    """In-place: rescale ``field`` so non-scratched horses sum to 1.0.

    Removes pari-mutuel overround. Scratched horses are excluded from the
    denominator and have ``field`` cleared to ``None``. Horses missing a
    value are left at ``None`` (they don't contribute to the sum and
    don't get a value assigned). A no-op when nothing has a probability.
    """
    total = 0.0
    for h in horses:
        if h.scratched:
            continue
        value = getattr(h, field)
        if value is not None:
            total += value
    if total <= 0:
        for h in horses:
            if h.scratched and getattr(h, field) is not None:
                setattr(h, field, None)
        return
    for h in horses:
        if h.scratched:
            setattr(h, field, None)
            continue
        value = getattr(h, field)
        if value is None:
            continue
        setattr(h, field, value / total)


# ---------------------------------------------------------------------------
# Source merging (Equibase + TwinSpires)
# ---------------------------------------------------------------------------


def normalize_horse_name(name: str | None) -> str:
    """Lowercase, drop country suffix and punctuation for fuzzy comparison.

    ``"HORSE NAME (IRE)"`` and ``"Horse-Name"`` both collapse to
    ``"horsename"``. Returns ``""`` for ``None`` / empty input.
    """
    if not name:
        return ""
    base = _COUNTRY_SUFFIX_RE.sub("", name).lower()
    return _NAME_PUNCT_RE.sub("", base)


def merge_horses(
    equibase_horses: list[Horse],
    twinspires_horses: list[Horse],
) -> list[Horse]:
    """Return Equibase-canonical horses enriched with TwinSpires live odds.

    Match strategy per Equibase entry:

    1. If exactly one TwinSpires horse shares the post number → match.
    2. If multiple TwinSpires horses share the post (coupled entries)
       → name-based match within the group.
    3. Otherwise → name-based match across all unmatched TwinSpires
       horses, exact normalized name first, then
       ``difflib.get_close_matches(cutoff=0.85)``.

    Each returned :class:`Horse` carries:

    - ``morningLineProbability`` parsed from Equibase ``morningLineOdds``
    - ``marketProbability``       parsed from the matched TwinSpires
                                   ``currentOdds`` (``None`` if no match)
    - ``currentOdds``             from the matched TwinSpires horse
    - ``flags`` appended with :data:`MISSING_LIVE_ODDS_FLAG` when no
      live-odds match was found.

    The input lists are not mutated; a new ``list[Horse]`` is returned.
    """
    by_post: dict[int, list[Horse]] = {}
    for ts in twinspires_horses:
        by_post.setdefault(ts.post, []).append(ts)

    used_ts_ids: set[str] = set()
    merged: list[Horse] = []

    for eq in equibase_horses:
        candidates = [
            h for h in by_post.get(eq.post, []) if h.id not in used_ts_ids
        ]
        match: Horse | None = None
        if len(candidates) == 1:
            match = candidates[0]
        elif len(candidates) > 1:
            match = _match_by_name(eq, candidates)
        if match is None:
            unused = [h for h in twinspires_horses if h.id not in used_ts_ids]
            match = _match_by_name(eq, unused)

        if match is not None:
            used_ts_ids.add(match.id)

        ml_prob = odds_to_probability(eq.morningLineOdds)
        market_prob: float | None = None
        current_odds: str | None = eq.currentOdds
        flags = list(eq.flags)

        if match is not None:
            if match.currentOdds:
                current_odds = match.currentOdds
                market_prob = odds_to_probability(match.currentOdds)
        else:
            if MISSING_LIVE_ODDS_FLAG not in flags:
                flags.append(MISSING_LIVE_ODDS_FLAG)

        merged.append(
            eq.model_copy(
                update={
                    "morningLineProbability": ml_prob,
                    "marketProbability": market_prob,
                    "currentOdds": current_odds,
                    "flags": flags,
                }
            )
        )

    return merged


def _match_by_name(eq_horse: Horse, candidates: list[Horse]) -> Horse | None:
    target = normalize_horse_name(eq_horse.name)
    if not target or not candidates:
        return None
    by_norm: dict[str, Horse] = {}
    for c in candidates:
        key = normalize_horse_name(c.name)
        if key and key not in by_norm:
            by_norm[key] = c
    if not by_norm:
        return None
    if target in by_norm:
        return by_norm[target]
    matches = difflib.get_close_matches(
        target, list(by_norm.keys()), n=1, cutoff=NAME_MATCH_CUTOFF
    )
    if matches:
        return by_norm[matches[0]]
    return None


# ---------------------------------------------------------------------------
# Pick 5 sequenceRole assignment
# ---------------------------------------------------------------------------


def assign_pick5_sequence_roles(races: list[Race], legs: list[int]) -> None:
    """In-place: tag the five Pick 5 legs as ``"pick5-leg-1"``..``"pick5-leg-5"``.

    ``legs`` is the list returned by ``api.sources.pick5.get_pick5_legs`` —
    five race numbers in leg order. Races whose ``raceNumber`` is not in
    ``legs`` are left untouched (their existing ``sequenceRole`` is
    preserved).
    """
    if len(legs) != PICK5_LEG_COUNT:
        raise ValueError(
            f"legs must have {PICK5_LEG_COUNT} entries, got {len(legs)}"
        )
    role_by_race: dict[int, SequenceRole] = {
        race_number: cast(SequenceRole, f"pick5-leg-{i + 1}")
        for i, race_number in enumerate(legs)
    }
    for race in races:
        role = role_by_race.get(race.raceNumber)
        if role is not None:
            race.sequenceRole = role


__all__ = [
    "MISSING_LIVE_ODDS_FLAG",
    "NAME_MATCH_CUTOFF",
    "assign_pick5_sequence_roles",
    "merge_horses",
    "normalize_horse_name",
    "normalize_probabilities",
    "odds_to_probability",
]
