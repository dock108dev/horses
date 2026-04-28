"""Canonical Pydantic data models and probability layer for the backend.

The first half of this module (Pydantic ``Horse``/``Race``/``OddsSnapshot``)
mirrors the TypeScript types in ``web/lib/types.ts`` so payloads serialize
cleanly across the FastAPI ↔ Next.js boundary.

The second half implements the probability blending model:

1. :func:`load_priors` reads ``data/priors.json``.
2. :func:`compute_model_prior` / :func:`apply_model_priors_to_race` apply
   race-type multipliers to ``marketProbability`` and re-normalize.
3. :func:`blend_probabilities` combines current/morning-line/model into
   ``finalProbability`` using ``0.70/0.20/0.10`` (or the ``0.80/0.20``
   fallback when no model prior exists).
4. :func:`apply_flags` populates per-horse ``flags`` lists with
   overbet/value/single/chaos/drift signals per the BRAINDUMP.
5. :func:`apply_user_boost_fade` honors user ``boost``/``fade`` tags by
   scaling ``finalProbability`` and re-normalizing the race.

LOC note: ~559 LOC, over the 500-line guideline but under the
~probability-layer-at-400-LOC extraction trigger. The probability layer
operates directly on the Pydantic models defined here; a split into
``api/probability.py`` would force every probability import in the
codebase + tests to change for no behavioral win. See
``docs/audits/cleanup-report.md`` "Files still >500 LOC" for the
extraction plan if the file grows further. The SSOT pass
(``docs/audits/ssot-report.md``) added Pick 5 sequence constants, the
``select_pick5_legs`` helper, and ``FLAG_LIKELY_SEPARATOR`` here so they
have a single home.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field

Day = Literal["friday", "saturday"]
Track = Literal["Churchill Downs"]
SequenceRole = Literal[
    "pick5-leg-1",
    "pick5-leg-2",
    "pick5-leg-3",
    "pick5-leg-4",
    "pick5-leg-5",
]
UserTag = Literal["single", "A", "B", "C", "toss", "chaos", "boost", "fade"]

PICK5_LEG_ROLES: tuple[SequenceRole, ...] = get_args(SequenceRole)
PICK5_LEG_COUNT = len(PICK5_LEG_ROLES)


class Horse(BaseModel):
    """A single entry in a race."""

    model_config = ConfigDict(extra="forbid")

    id: str
    raceId: str
    post: int = Field(ge=1)
    name: str
    jockey: str | None = None
    trainer: str | None = None
    morningLineOdds: str | None = None
    currentOdds: str | None = None
    scratched: bool | None = None
    source: str | None = None
    marketProbability: float | None = Field(default=None, ge=0.0, le=1.0)
    morningLineProbability: float | None = Field(default=None, ge=0.0, le=1.0)
    modelProbability: float | None = Field(default=None, ge=0.0, le=1.0)
    finalProbability: float | None = Field(default=None, ge=0.0, le=1.0)
    userTag: UserTag | None = None
    flags: list[str] = Field(default_factory=list)


class Race(BaseModel):
    """A single race on the card."""

    model_config = ConfigDict(extra="forbid")

    id: str
    day: Day
    track: Track = "Churchill Downs"
    raceNumber: int = Field(ge=1)
    postTime: str | None = None
    name: str | None = None
    surface: str | None = None
    distance: str | None = None
    sequenceRole: SequenceRole | None = None
    horses: list[Horse] = Field(default_factory=list)


class OddsSnapshot(BaseModel):
    """A point-in-time odds reading for a single horse."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    day: Day
    raceNumber: int = Field(ge=1)
    horseId: str
    odds: str
    impliedProbability: float = Field(ge=0.0, le=1.0)
    source: str


def select_pick5_legs(races: list[Race]) -> list[Race]:
    """Return the Pick 5 races in :data:`PICK5_LEG_ROLES` order, if all present.

    Returns a list shorter than :data:`PICK5_LEG_COUNT` when one or more
    legs are missing. Duplicate ``sequenceRole`` assignments resolve to the
    first occurrence.
    """
    by_role: dict[str, Race] = {}
    for race in races:
        if race.sequenceRole in PICK5_LEG_ROLES:
            by_role.setdefault(cast(str, race.sequenceRole), race)
    return [by_role[role] for role in PICK5_LEG_ROLES if role in by_role]


# ---------------------------------------------------------------------------
# Probability layer: priors, blending, flags, boost/fade
# ---------------------------------------------------------------------------

DEFAULT_PRIORS_PATH = Path("data/priors.json")

# Blend weights — current/morning-line/model. Fallback drops the model term
# and rolls the 0.10 weight into current.
BLEND_WEIGHT_MARKET = 0.70
BLEND_WEIGHT_ML = 0.20
BLEND_WEIGHT_MODEL = 0.10
BLEND_WEIGHT_MARKET_FALLBACK = 0.80
BLEND_WEIGHT_ML_FALLBACK = 0.20

# Flag thresholds (BRAINDUMP "Flags" section).
OVERBET_FAVORITE_RATIO = 1.15
USEFUL_VALUE_RATIO = 0.85
PUBLIC_SINGLE_THRESHOLD = 0.40
GOOD_SINGLE_LOWER = 0.28
GOOD_SINGLE_UPPER = 0.40
BAD_SINGLE_THRESHOLD = 0.45
CHAOS_FIELD_MIN = 10
CHAOS_PROB_MAX = 0.20
SPREAD_TOP_N = 4
SPREAD_TOLERANCE = 0.05

USER_BOOST_MULTIPLIER = 1.15
USER_FADE_MULTIPLIER = 0.85

FLAG_OVERBET_FAVORITE = "overbet_favorite"
FLAG_USEFUL_VALUE = "useful_value"
FLAG_PUBLIC_SINGLE = "public_single"
FLAG_GOOD_SINGLE = "good_single"
FLAG_BAD_SINGLE = "bad_single"
FLAG_CHAOS_RACE = "chaos_race"
FLAG_SPREAD_RACE = "spread_race"
FLAG_TAKING_MONEY = "taking_money"
FLAG_COLD_ON_BOARD = "cold_on_board"
FLAG_SCRATCH = "scratch"
FLAG_MISSING_ODDS = "missing_odds"
# Spec-mandated flag (BRAINDUMP "Flags" — "Likely separator"). Consumed by
# the simulator's separator-coverage metric; populated by ISSUE-010 once the
# separator-detection rule is defined. Kept here so producers and consumers
# share a single string.
FLAG_LIKELY_SEPARATOR = "likely_separator"

RaceType = Literal["large_field_dirt_route", "small_field_chalk"]
FieldSizeBucket = Literal["6-7", "8-10", "11-14", "15+"]
RunnerClass = Literal["favorite", "mid_price", "longshot"]


# ---- priors loading -------------------------------------------------------


def load_priors(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Read ``data/priors.json`` and return ``{race_type_priors, field_size_priors}``.

    Missing top-level keys default to ``{}`` so downstream code can treat
    "no priors configured" the same as "this race type has no entry".
    """
    p = Path(path) if path is not None else DEFAULT_PRIORS_PATH
    with open(p) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"priors file must be a JSON object, got {type(data).__name__}")
    return {
        "race_type_priors": dict(data.get("race_type_priors") or {}),
        "field_size_priors": dict(data.get("field_size_priors") or {}),
    }


# ---- race-shape classification --------------------------------------------


def field_size_bucket(field_size: int) -> FieldSizeBucket:
    """Bucket a non-scratched field count into the priors keys."""
    if field_size <= 7:
        return "6-7"
    if field_size <= 10:
        return "8-10"
    if field_size <= 14:
        return "11-14"
    return "15+"


def _is_route(distance: str | None) -> bool:
    """A 'route' is a race ≥ 1 mile. We detect 'M'/'mile' tokens.

    Accepts forms like ``"1 1/4M"``, ``"1M"``, ``"1 mile"`` (route);
    ``"6f"``, ``"5 1/2 furlongs"`` are sprints.
    """
    if not distance:
        return False
    s = distance.lower()
    if "mile" in s:
        return True
    # Distinguish 'M' (mile) from 'f'/'furlong'. Treat trailing 'm' as mile.
    if "f" in s and "mile" not in s:
        return False
    return "m" in s


def determine_race_type(race: Race, field_size: int) -> RaceType | None:
    """Map a race + field size to a priors key, or ``None`` if neither fits.

    - ``large_field_dirt_route``: dirt surface, route distance, field ≥ 10
    - ``small_field_chalk``: field ≤ 7 (favorites historically dominate)
    """
    surface = (race.surface or "").lower()
    if "dirt" in surface and _is_route(race.distance) and field_size >= CHAOS_FIELD_MIN:
        return "large_field_dirt_route"
    if field_size <= 7:
        return "small_field_chalk"
    return None


def _classify_runner(
    market_prob: float, sorted_probs_desc: list[float]
) -> RunnerClass:
    """Top → favorite, bottom third → longshot, else mid-price.

    ``sorted_probs_desc`` is the non-scratched horses' market probabilities
    in descending order (favorite first). Ties at the top all read as
    favorite, which matches the "favorite_soften" intent.
    """
    if not sorted_probs_desc:
        return "mid_price"
    if market_prob >= sorted_probs_desc[0]:
        return "favorite"
    n = len(sorted_probs_desc)
    longshot_cutoff = sorted_probs_desc[min(n - 1, max(0, (2 * n) // 3))]
    if market_prob <= longshot_cutoff:
        return "longshot"
    return "mid_price"


# ---- model-prior computation ---------------------------------------------


def compute_model_prior(
    horse: Horse, race: Race, priors: dict[str, dict[str, Any]]
) -> float | None:
    """Return the (un-normalized) model prior probability for one horse.

    Multiplies ``horse.marketProbability`` by the race-type multiplier
    selected by the horse's runner class. Returns ``None`` for scratched
    horses or horses without a market probability. Returns the raw market
    probability when no race-type multiplier applies.

    Re-normalization across the race is handled by
    :func:`apply_model_priors_to_race`.
    """
    if horse.scratched or horse.marketProbability is None:
        return None

    non_scratched = [h for h in race.horses if not h.scratched]
    field_size = len(non_scratched)
    race_type = determine_race_type(race, field_size)
    if race_type is None:
        return horse.marketProbability

    rt_priors = priors.get("race_type_priors", {}).get(race_type) or {}
    if not rt_priors:
        return horse.marketProbability

    sorted_probs = sorted(
        (h.marketProbability for h in non_scratched if h.marketProbability is not None),
        reverse=True,
    )
    runner_class = _classify_runner(horse.marketProbability, sorted_probs)
    if runner_class == "favorite":
        mult = float(rt_priors.get("favorite_soften", 1.0))
    elif runner_class == "longshot":
        mult = float(rt_priors.get("longshot_boost", 1.0))
    else:
        mult = float(rt_priors.get("mid_price_boost", 1.0))
    return horse.marketProbability * mult


def apply_model_priors_to_race(
    race: Race, priors: dict[str, dict[str, Any]]
) -> None:
    """Set ``modelProbability`` on each horse and re-normalize across the race.

    Scratched horses end up with ``modelProbability=None``.
    """
    for h in race.horses:
        h.modelProbability = compute_model_prior(h, race, priors)
    _renormalize(race.horses, "modelProbability")


# ---- blending --------------------------------------------------------------


def blend_probabilities(horse: Horse, has_model_prior: bool) -> None:
    """Set ``horse.finalProbability`` from current/ML/(model).

    With a model prior: ``current*0.70 + ml*0.20 + model*0.10``.
    Without:           ``current*0.80 + ml*0.20``.
    Falls back to whichever single component exists if the others are
    missing; sets ``None`` if no probability source is available.
    """
    market = horse.marketProbability
    ml = horse.morningLineProbability
    model = horse.modelProbability

    if has_model_prior and market is not None and ml is not None and model is not None:
        horse.finalProbability = (
            market * BLEND_WEIGHT_MARKET
            + ml * BLEND_WEIGHT_ML
            + model * BLEND_WEIGHT_MODEL
        )
        return
    if market is not None and ml is not None:
        horse.finalProbability = (
            market * BLEND_WEIGHT_MARKET_FALLBACK
            + ml * BLEND_WEIGHT_ML_FALLBACK
        )
        return
    horse.finalProbability = market if market is not None else ml


def blend_race(race: Race, has_model_prior: bool) -> None:
    """Apply :func:`blend_probabilities` to every horse in ``race``."""
    for h in race.horses:
        blend_probabilities(h, has_model_prior)


# ---- flags ----------------------------------------------------------------


def _market_vs_ml_flags(horse: Horse) -> list[str]:
    market = horse.marketProbability
    ml = horse.morningLineProbability
    if market is None or ml is None or ml <= 0:
        return []
    ratio = market / ml
    if ratio > OVERBET_FAVORITE_RATIO:
        return [FLAG_OVERBET_FAVORITE]
    if ratio < USEFUL_VALUE_RATIO:
        return [FLAG_USEFUL_VALUE]
    return []


def _drift_flags(drift_series: list[tuple[int, str, float]] | None) -> list[str]:
    """``drift_series`` is ``[(captured_at_ms, odds, implied_prob), ...]`` ascending.

    Higher latest-implied means odds got shorter (more money on the horse)
    → ``taking_money``. Lower latest-implied means odds drifted out
    → ``cold_on_board``.
    """
    if not drift_series or len(drift_series) < 2:
        return []
    earliest_prob = drift_series[0][2]
    latest_prob = drift_series[-1][2]
    if latest_prob > earliest_prob:
        return [FLAG_TAKING_MONEY]
    if latest_prob < earliest_prob:
        return [FLAG_COLD_ON_BOARD]
    return []


def compute_horse_flags(
    horse: Horse,
    drift_series: list[tuple[int, str, float]] | None = None,
) -> list[str]:
    """Per-horse flags only — see :func:`compute_race_flags` for race-level."""
    if horse.scratched:
        return [FLAG_SCRATCH]

    flags: list[str] = []
    if horse.marketProbability is None:
        flags.append(FLAG_MISSING_ODDS)

    flags.extend(_market_vs_ml_flags(horse))

    market = horse.marketProbability
    if market is not None:
        if market > BAD_SINGLE_THRESHOLD:
            flags.append(FLAG_BAD_SINGLE)
        if market > PUBLIC_SINGLE_THRESHOLD:
            flags.append(FLAG_PUBLIC_SINGLE)
        if (
            GOOD_SINGLE_LOWER <= market <= GOOD_SINGLE_UPPER
            and FLAG_USEFUL_VALUE in flags
        ):
            flags.append(FLAG_GOOD_SINGLE)

    flags.extend(_drift_flags(drift_series))
    return flags


def compute_race_flags(race: Race) -> list[str]:
    """Race-level flags propagated to every non-scratched horse."""
    non_scratched = [h for h in race.horses if not h.scratched]
    market_probs = [
        h.marketProbability for h in non_scratched if h.marketProbability is not None
    ]
    flags: list[str] = []
    if (
        len(non_scratched) >= CHAOS_FIELD_MIN
        and market_probs
        and max(market_probs) <= CHAOS_PROB_MAX
    ):
        flags.append(FLAG_CHAOS_RACE)
    if len(market_probs) >= SPREAD_TOP_N:
        top = sorted(market_probs, reverse=True)[:SPREAD_TOP_N]
        if top[0] - top[-1] <= SPREAD_TOLERANCE:
            flags.append(FLAG_SPREAD_RACE)
    return flags


def apply_flags(
    race: Race,
    drift_by_horse_id: dict[str, list[tuple[int, str, float]]] | None = None,
) -> None:
    """Compute and assign ``flags`` on every horse in ``race`` in place.

    ``drift_by_horse_id`` maps ``horse.id`` → drift series from
    :meth:`api.cache.OddsCache.get_drift_series`. Race-level flags
    (``chaos_race``, ``spread_race``) are appended only to non-scratched
    horses; scratched horses get only ``[FLAG_SCRATCH]``.
    """
    drift_map = drift_by_horse_id or {}
    race_flags = compute_race_flags(race)
    for h in race.horses:
        flags = compute_horse_flags(h, drift_series=drift_map.get(h.id))
        if not h.scratched:
            flags.extend(race_flags)
        h.flags = flags


# ---- user boost / fade -----------------------------------------------------


def apply_user_boost_fade(race: Race) -> None:
    """Scale ``finalProbability`` by 1.15 (boost) / 0.85 (fade), then re-normalize.

    No-op for horses without a ``finalProbability`` or a relevant tag.
    Scratched horses are excluded from the normalization sum.
    """
    for h in race.horses:
        if h.finalProbability is None or h.scratched:
            continue
        if h.userTag == "boost":
            h.finalProbability *= USER_BOOST_MULTIPLIER
        elif h.userTag == "fade":
            h.finalProbability *= USER_FADE_MULTIPLIER
    _renormalize(race.horses, "finalProbability")


# ---- internal helpers ------------------------------------------------------


def _renormalize(horses: list[Horse], field: str) -> None:
    """Rescale ``field`` so non-scratched horses sum to 1.0; clear on scratched.

    Duplicates the small bit of logic from :func:`api.normalize.normalize_probabilities`
    locally to avoid the circular import (``api.normalize`` imports from this module).
    """
    total = 0.0
    for h in horses:
        if h.scratched:
            continue
        v = getattr(h, field)
        if v is not None:
            total += v
    if total <= 0:
        for h in horses:
            if h.scratched and getattr(h, field) is not None:
                setattr(h, field, None)
        return
    for h in horses:
        if h.scratched:
            setattr(h, field, None)
            continue
        v = getattr(h, field)
        if v is None:
            continue
        setattr(h, field, v / total)


__all__ = [
    "Day",
    "Track",
    "SequenceRole",
    "UserTag",
    "PICK5_LEG_ROLES",
    "PICK5_LEG_COUNT",
    "Horse",
    "Race",
    "OddsSnapshot",
    "select_pick5_legs",
    "RaceType",
    "FieldSizeBucket",
    "RunnerClass",
    "DEFAULT_PRIORS_PATH",
    "BLEND_WEIGHT_MARKET",
    "BLEND_WEIGHT_ML",
    "BLEND_WEIGHT_MODEL",
    "BLEND_WEIGHT_MARKET_FALLBACK",
    "BLEND_WEIGHT_ML_FALLBACK",
    "OVERBET_FAVORITE_RATIO",
    "USEFUL_VALUE_RATIO",
    "PUBLIC_SINGLE_THRESHOLD",
    "GOOD_SINGLE_LOWER",
    "GOOD_SINGLE_UPPER",
    "BAD_SINGLE_THRESHOLD",
    "CHAOS_FIELD_MIN",
    "CHAOS_PROB_MAX",
    "SPREAD_TOP_N",
    "SPREAD_TOLERANCE",
    "USER_BOOST_MULTIPLIER",
    "USER_FADE_MULTIPLIER",
    "FLAG_OVERBET_FAVORITE",
    "FLAG_USEFUL_VALUE",
    "FLAG_PUBLIC_SINGLE",
    "FLAG_GOOD_SINGLE",
    "FLAG_BAD_SINGLE",
    "FLAG_CHAOS_RACE",
    "FLAG_SPREAD_RACE",
    "FLAG_TAKING_MONEY",
    "FLAG_COLD_ON_BOARD",
    "FLAG_SCRATCH",
    "FLAG_MISSING_ODDS",
    "FLAG_LIKELY_SEPARATOR",
    "load_priors",
    "field_size_bucket",
    "determine_race_type",
    "compute_model_prior",
    "apply_model_priors_to_race",
    "blend_probabilities",
    "blend_race",
    "compute_horse_flags",
    "compute_race_flags",
    "apply_flags",
    "apply_user_boost_fade",
]
