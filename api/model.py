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
4. :func:`apply_historical_priors` adjusts ``finalProbability`` via a
   four-step pipeline — per-rank odds multiplier, field-size compression,
   race-type chaos flatten, and re-normalize.
5. :func:`apply_flags` populates per-horse ``flags`` lists with
   overbet/value/single/chaos/drift signals per the BRAINDUMP.
6. :func:`apply_movement_adjustment` applies an odds-velocity nudge
   computed from cached drift series, sets the ``steam_horse`` boolean,
   and re-normalizes the race.
7. :func:`classify_race` writes the four-way race classification
   (``KEY``/``TIGHT``/``MID``/``CHAOS``), Shannon entropy, chaos level,
   and strategy label onto the ``Race`` from the adjusted probabilities.
8. :func:`apply_edge_model` writes the per-horse edge layer
   (``ownership_proxy``, ``true_prob``, ``edge_score``, ``confidence_score``,
   ``computedBucket``) plus the ``trap_favorite``/``separator_candidate``/
   ``value_horse``/``cold_horse`` booleans. Reads ``finalProbability`` and
   ``flags`` after the prior steps; reads ``classification`` from
   :func:`classify_race`; reads drift series for the velocity component.

LOC note: ~1374 LOC, well over the 500-line guideline. The probability
layer operates directly on the Pydantic models defined here; a split
into ``api/probability.py`` would force every probability import in the
codebase + tests to change for no behavioral win. See
``docs/audits/cleanup-report.md`` "Files still >500 LOC" for the
extraction plan if the file grows further. The SSOT pass
(``docs/audits/ssot-report.md``) added Pick 5 sequence constants, the
``select_pick5_legs`` helper, and ``FLAG_LIKELY_SEPARATOR`` here so they
have a single home.
"""

from __future__ import annotations

import json
import math
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
UserTag = Literal["single", "A", "B", "C", "toss", "chaos"]
ComputedBucket = Literal["CORE", "VALUE", "CHAOS", "TRAP", "DEAD"]
RaceClassification = Literal["KEY", "TIGHT", "MID", "CHAOS"]
ChaosLevel = Literal["LOW", "MODERATE", "HIGH", "EXTREME"]
StrategyLabel = Literal["SINGLE", "2-DEEP", "MID", "CHAOS SPREAD", "MAX CHAOS"]

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
    # Pass 2 score fields — populated by the edge-model layer once it lands.
    # Default ``None`` keeps Pass 1 endpoints serializing valid payloads.
    # Bounds match the producer in ``apply_edge_model``: ``ownership_proxy``
    # comes from ``OWNERSHIP_PROXY_BY_RANK`` (max 0.65) and the tail value
    # 0.03; ``confidence_score`` is ``raw * stability`` where both factors
    # are in [0, 1]. Constraining at construction documents the contract
    # and rejects malformed cached / replayed payloads at the boundary.
    true_prob: float | None = Field(default=None, ge=0.0, le=1.0)
    ownership_proxy: float | None = Field(default=None, ge=0.0, le=1.0)
    edge_score: float | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    computedBucket: ComputedBucket | None = None
    userTag: UserTag | None = None
    flags: list[str] = Field(default_factory=list)
    # Pass 2 boolean flag fields — set by the edge model. Default ``False``
    # so the frontend can read them without a None-check.
    steam_horse: bool = False
    separator_candidate: bool = False
    trap_favorite: bool = False
    value_horse: bool = False
    cold_horse: bool = False


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
    # Pass 2 race-shape outputs — populated by the classification layer.
    classification: RaceClassification | None = None
    strategy: str | None = None
    entropy: float | None = Field(default=None, ge=0.0)
    chaos_level: ChaosLevel | None = None


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
# Probability layer: priors, blending, flags
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

# Race classification thresholds (KEY/TIGHT/MID/CHAOS) — applied to
# adjusted ``finalProbability`` after the historical-priors and movement
# steps have run.
KEY_TOP_PROB_MIN = 0.42
KEY_GAP_MIN = 0.15
TIGHT_TOP2_MIN = 0.55
TIGHT_TOP_PROB_MIN = 0.32
TIGHT_SECOND_PROB_MIN = 0.20
MID_TOP3_MIN = 0.62
MID_ENTROPY_MAX = 2.8

# Chaos-level thresholds. Independent ``factor`` (priors-driven) and
# ``ratio`` (entropy-driven) ladders; the resulting level is the higher
# of the two (LOW < MODERATE < HIGH < EXTREME).
CHAOS_LEVEL_FACTOR_LOW = 1.05
CHAOS_LEVEL_FACTOR_MODERATE = 1.15
CHAOS_LEVEL_FACTOR_HIGH = 1.25
CHAOS_LEVEL_RATIO_LOW = 0.60
CHAOS_LEVEL_RATIO_MODERATE = 0.72
CHAOS_LEVEL_RATIO_HIGH = 0.84

# Hard-override threshold: a race whose chaos_factor reaches this value
# (Derby-grade) is forced to ``MAX CHAOS`` regardless of classification.
MAX_CHAOS_FACTOR_OVERRIDE = 1.35

STRATEGY_LABEL_SINGLE: StrategyLabel = "SINGLE"
STRATEGY_LABEL_TWO_DEEP: StrategyLabel = "2-DEEP"
STRATEGY_LABEL_MID: StrategyLabel = "MID"
STRATEGY_LABEL_CHAOS_SPREAD: StrategyLabel = "CHAOS SPREAD"
STRATEGY_LABEL_MAX_CHAOS: StrategyLabel = "MAX CHAOS"

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
# the simulator's separator-coverage metric. Producer not yet wired —
# kept here so producers and consumers share a single string.
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
        "odds_rank": dict(data.get("odds_rank") or {}),
        "race_type": dict(data.get("race_type") or {}),
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


# ---- historical-priors adjustment -----------------------------------------

# Field-size compression activates for fields this large or larger; below
# this threshold, only the per-rank multiplier and chaos flatten run.
FIELD_SIZE_COMPRESSION_MIN = 14

ChaosRaceType = Literal["derby", "maiden", "turf_sprint", "default"]


def _classify_chaos_race_type(race: Race) -> ChaosRaceType:
    """Pick the ``race_type`` (chaos) priors key for a race.

    Priority: ``derby`` (highest-stakes, flattest) > ``maiden`` (debut
    runners, more variance) > ``turf_sprint`` (short turf races skew
    chaotic) > ``default``.
    """
    name = (race.name or "").lower()
    if "derby" in name:
        return "derby"
    if "maiden" in name:
        return "maiden"
    surface = (race.surface or "").lower()
    if "turf" in surface and not _is_route(race.distance):
        return "turf_sprint"
    return "default"


def _odds_rank_multiplier(rank: int, table: dict[str, Any]) -> float:
    """Look up the multiplier for a 1-indexed ``rank`` in the ``odds_rank`` table.

    The table uses sparse keys (``"1"``, ``"2"``, ``"3"``, ``"4-6"``,
    ``"7+"``) — anything not matching falls through to ``1.0``.

    The narrow ``except ValueError`` blocks below skip malformed range keys
    in priors.json (e.g. ``"x+"`` or ``"a-b"``). Falling through to the
    default 1.0 multiplier is a safe no-op; priors.json is committed config
    and a malformed key would only result from a bad edit. See
    docs/audits/error-handling-report.md F22.
    """
    if rank <= 0:
        return 1.0
    direct = table.get(str(rank))
    if direct is not None:
        return float(direct)
    for key, value in table.items():
        if key.endswith("+"):
            try:
                lo = int(key[:-1])
            except ValueError:
                continue
            if rank >= lo:
                return float(value)
        elif "-" in key:
            lo_s, _, hi_s = key.partition("-")
            try:
                lo = int(lo_s)
                hi = int(hi_s)
            except ValueError:
                continue
            if lo <= rank <= hi:
                return float(value)
    return 1.0


def apply_historical_priors(
    race: Race, priors: dict[str, dict[str, Any]]
) -> None:
    """Adjust ``finalProbability`` via the four-step historical-priors pipeline.

    Operates in place after :func:`blend_race` has set ``finalProbability``:

    1. Per-horse ``odds_rank`` multiplier — favorites are softened, mid-tier
       (ranks 4–6) is boosted, very-long-shot (rank 7+) is depressed.
    2. Field-size compression for fields ≥ :data:`FIELD_SIZE_COMPRESSION_MIN`:
       cap the favorite at the historical favorite-win-rate anchor. The
       slack redistributes to mid-tier/longshots through re-normalization.
    3. Race-type chaos flattening: blend each probability toward uniform by
       ``chaos_factor - 1`` (Derby/maiden/turf-sprint flatten more).
    4. Re-normalize so non-scratched horses sum to 1.0.

    No-op for horses without a ``finalProbability`` or for races with no
    eligible runners.
    """
    eligible = [
        h for h in race.horses
        if not h.scratched and h.finalProbability is not None
    ]
    if not eligible:
        _renormalize(race.horses, "finalProbability")
        return

    # Step 1 — per-rank multiplier.
    odds_rank_table = priors.get("odds_rank") or {}
    if odds_rank_table:
        ranked = sorted(
            eligible, key=lambda h: h.finalProbability or 0.0, reverse=True
        )
        for rank, horse in enumerate(ranked, start=1):
            mult = _odds_rank_multiplier(rank, odds_rank_table)
            if horse.finalProbability is not None:
                horse.finalProbability *= mult

    # Step 2 — field-size compression: cap the favorite at the anchor.
    field_size = len([h for h in race.horses if not h.scratched])
    if field_size >= FIELD_SIZE_COMPRESSION_MIN:
        bucket = field_size_bucket(field_size)
        bucket_priors = (priors.get("field_size_priors") or {}).get(bucket) or {}
        anchor_raw = bucket_priors.get("favoriteWinRate")
        if anchor_raw is not None:
            anchor = float(anchor_raw)
            favorite = max(
                eligible, key=lambda h: h.finalProbability or 0.0
            )
            if (
                favorite.finalProbability is not None
                and favorite.finalProbability > anchor
            ):
                favorite.finalProbability = anchor

    # Step 3 — race-type chaos flatten toward uniform.
    race_type_table = priors.get("race_type") or {}
    rtype = _classify_chaos_race_type(race)
    rtype_entry = race_type_table.get(rtype) or race_type_table.get("default") or {}
    chaos_factor = float(rtype_entry.get("chaos", 1.0)) if isinstance(
        rtype_entry, dict
    ) else 1.0
    if chaos_factor > 1.0 and eligible:
        n = len(eligible)
        uniform = 1.0 / n
        blend = chaos_factor - 1.0
        if blend > 1.0:
            blend = 1.0
        for horse in eligible:
            if horse.finalProbability is not None:
                horse.finalProbability = (
                    (1.0 - blend) * horse.finalProbability + blend * uniform
                )

    # Step 4 — restore sum-to-one across non-scratched horses.
    _renormalize(race.horses, "finalProbability")


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


# ---- movement-adjustment engine -------------------------------------------

# Conceptual reference window for normalizing the velocity rate. A rate
# computed over a shorter span is projected to the equivalent change you
# would see over a full T-120→current window so calibration constants
# (clamp, noise floor, weights) stay comparable regardless of how much
# history is available.
MOVEMENT_REFERENCE_WINDOW_MS = 7_200_000  # 120 minutes

VELOCITY_CLAMP = 0.15
VELOCITY_NOISE_FLOOR = 0.02
ADJUSTMENT_MAX = 0.08
ADJUSTMENT_MIN = -0.05
MAX_SINGLE_HORSE_PROB = 0.85

MOVEMENT_WEIGHT_MID_TIER_SHORTEN = 0.40
MOVEMENT_WEIGHT_FAVORITE_SHORTEN = 0.15
MOVEMENT_WEIGHT_LONGSHOT_SHORTEN = 0.25
MOVEMENT_WEIGHT_DRIFT = 0.20
MOVEMENT_WEIGHT_FLAT_DEFAULT = 0.35
LONGSHOT_VELOCITY_DAMPENER = 0.70

# Tier thresholds expressed in fractional odds (5/1 → 5.0). A horse with
# fractional odds < FAVORITE_CEILING is a favorite, in the inclusive range
# [FAVORITE_CEILING, LONGSHOT_FLOOR] is mid-tier, above is longshot.
TIER_FAVORITE_CEILING_ODDS = 5.0
TIER_LONGSHOT_FLOOR_ODDS = 12.0


def _compute_velocity(
    drift_series: list[tuple[int, str, float]] | None,
) -> float:
    """Return the implied-probability change rate, clamped to ±VELOCITY_CLAMP.

    Uses the widest available window — earliest snapshot vs latest — and
    normalizes to a canonical 120-min reference span so the rate is
    directly comparable to the calibration constants regardless of how
    much history was captured. Returns 0 for empty/single-row series and
    when the timestamp delta is non-positive.
    """
    if not drift_series or len(drift_series) < 2:
        return 0.0
    earliest_ts, _, earliest_p = drift_series[0]
    latest_ts, _, latest_p = drift_series[-1]
    # Reject non-finite probabilities at the boundary — drift tuples come
    # straight from cache rows and are not Pydantic-validated. Letting NaN
    # propagate would silently flow into ``finalProbability`` and JSON-
    # serialize as the non-standard ``NaN`` literal, breaking strict
    # parsers. See docs/audits/error-handling-report.md F23.
    if not (math.isfinite(earliest_p) and math.isfinite(latest_p)):
        return 0.0
    delta_t_ms = latest_ts - earliest_ts
    if delta_t_ms <= 0:
        return 0.0
    rate = (latest_p - earliest_p) / delta_t_ms
    velocity = rate * MOVEMENT_REFERENCE_WINDOW_MS
    if not math.isfinite(velocity):
        return 0.0
    if velocity > VELOCITY_CLAMP:
        return VELOCITY_CLAMP
    if velocity < -VELOCITY_CLAMP:
        return -VELOCITY_CLAMP
    return velocity


def _fractional_odds_from_prob(market_prob: float | None) -> float | None:
    """Convert an implied probability to fractional odds (5/1 → 5.0)."""
    if market_prob is None or market_prob <= 0.0 or market_prob >= 1.0:
        return None
    return (1.0 / market_prob) - 1.0


def _is_mid_tier(market_prob: float | None) -> bool:
    """True when the horse's market odds put it in the 5-1 to 12-1 band."""
    fractional = _fractional_odds_from_prob(market_prob)
    if fractional is None:
        return False
    return TIER_FAVORITE_CEILING_ODDS <= fractional <= TIER_LONGSHOT_FLOOR_ODDS


def _movement_weight(market_prob: float | None, velocity: float) -> float:
    """Pick the per-horse movement weight from velocity sign and tier."""
    if velocity < 0:
        return MOVEMENT_WEIGHT_DRIFT
    fractional = _fractional_odds_from_prob(market_prob)
    if fractional is None:
        return MOVEMENT_WEIGHT_FLAT_DEFAULT
    if fractional < TIER_FAVORITE_CEILING_ODDS:
        return MOVEMENT_WEIGHT_FAVORITE_SHORTEN
    if fractional <= TIER_LONGSHOT_FLOOR_ODDS:
        return MOVEMENT_WEIGHT_MID_TIER_SHORTEN
    return MOVEMENT_WEIGHT_LONGSHOT_SHORTEN * LONGSHOT_VELOCITY_DAMPENER


def apply_movement_adjustment(
    race: Race,
    drift_by_horse_id: dict[str, list[tuple[int, str, float]]] | None = None,
) -> None:
    """Apply odds-velocity nudges to ``finalProbability`` and set ``steam_horse``.

    Pipeline slot is between :func:`apply_flags` and
    :func:`classify_race`. Per-horse:

    1. Compute velocity from the drift series (earliest→latest snapshot,
       normalized to a 120-min reference window, clamped to ±0.15).
    2. Skip horses whose ``|velocity|`` is below the noise floor (0.02).
    3. Look up the movement weight by tier (favorite/mid/longshot) and
       direction (shortening/drifting); cap the resulting adjustment to
       ``[-0.05, +0.08]``.
    4. Add the adjustment to ``finalProbability``, clamped at zero.
    5. Re-normalize across non-scratched horses.
    6. If any single horse exceeds :data:`MAX_SINGLE_HORSE_PROB`, cap and
       re-normalize once more.

    Sets ``horse.steam_horse = True`` for mid-tier horses (5-1 to 12-1
    fractional odds) with shortening velocity at or above the noise
    floor.
    """
    drift_map = drift_by_horse_id or {}
    for h in race.horses:
        if h.scratched or h.finalProbability is None:
            continue
        velocity = _compute_velocity(drift_map.get(h.id))
        if velocity >= VELOCITY_NOISE_FLOOR and _is_mid_tier(h.marketProbability):
            h.steam_horse = True
        if abs(velocity) < VELOCITY_NOISE_FLOOR:
            continue
        weight = _movement_weight(h.marketProbability, velocity)
        adjustment = velocity * weight
        if adjustment > ADJUSTMENT_MAX:
            adjustment = ADJUSTMENT_MAX
        elif adjustment < ADJUSTMENT_MIN:
            adjustment = ADJUSTMENT_MIN
        new_prob = h.finalProbability + adjustment
        h.finalProbability = max(0.0, new_prob)

    _renormalize(race.horses, "finalProbability")

    # Per-horse 0.85 ceiling guard. After renormalization, at most one
    # horse can exceed 0.85 (the rest must sum to ≤ 0.15). Cap that horse
    # and rescale the remaining horses to fill the leftover mass — a
    # plain renormalize would just push the capped horse back over the
    # ceiling.
    over: list[Horse] = []
    under: list[Horse] = []
    for h in race.horses:
        if h.scratched or h.finalProbability is None:
            continue
        if h.finalProbability > MAX_SINGLE_HORSE_PROB:
            over.append(h)
        else:
            under.append(h)
    if over:
        for h in over:
            h.finalProbability = MAX_SINGLE_HORSE_PROB
        capped_total = MAX_SINGLE_HORSE_PROB * len(over)
        remaining = max(0.0, 1.0 - capped_total)
        under_total = sum(
            h.finalProbability for h in under if h.finalProbability is not None
        )
        if under_total > 0 and remaining > 0:
            scale = remaining / under_total
            for h in under:
                if h.finalProbability is not None:
                    h.finalProbability *= scale


# ---- race classification (KEY/TIGHT/MID/CHAOS + strategy label) ----------

# Lookup classification × chaos_level → strategy label. The override at
# chaos_factor ≥ MAX_CHAOS_FACTOR_OVERRIDE short-circuits this table.
_STRATEGY_TABLE: dict[tuple[RaceClassification, ChaosLevel], StrategyLabel] = {
    ("KEY", "LOW"): STRATEGY_LABEL_SINGLE,
    ("KEY", "MODERATE"): STRATEGY_LABEL_SINGLE,
    ("KEY", "HIGH"): STRATEGY_LABEL_TWO_DEEP,
    ("KEY", "EXTREME"): STRATEGY_LABEL_TWO_DEEP,
    ("TIGHT", "LOW"): STRATEGY_LABEL_TWO_DEEP,
    ("TIGHT", "MODERATE"): STRATEGY_LABEL_TWO_DEEP,
    ("TIGHT", "HIGH"): STRATEGY_LABEL_MID,
    ("TIGHT", "EXTREME"): STRATEGY_LABEL_CHAOS_SPREAD,
    ("MID", "LOW"): STRATEGY_LABEL_MID,
    ("MID", "MODERATE"): STRATEGY_LABEL_MID,
    ("MID", "HIGH"): STRATEGY_LABEL_CHAOS_SPREAD,
    ("MID", "EXTREME"): STRATEGY_LABEL_MAX_CHAOS,
    ("CHAOS", "LOW"): STRATEGY_LABEL_CHAOS_SPREAD,
    ("CHAOS", "MODERATE"): STRATEGY_LABEL_CHAOS_SPREAD,
    ("CHAOS", "HIGH"): STRATEGY_LABEL_MAX_CHAOS,
    ("CHAOS", "EXTREME"): STRATEGY_LABEL_MAX_CHAOS,
}

_LEVEL_ORDER: dict[ChaosLevel, int] = {
    "LOW": 0,
    "MODERATE": 1,
    "HIGH": 2,
    "EXTREME": 3,
}


def _shannon_entropy(probs: list[float]) -> float:
    """Return ``-Σ p·log2(p)`` over the strictly-positive entries."""
    total = 0.0
    for p in probs:
        if p > 0:
            total -= p * math.log2(p)
    return total


def _classify_from_probs(
    probs_desc: list[float], entropy: float
) -> RaceClassification:
    """Apply the four-way decision tree to a sorted-desc probability list."""
    top = probs_desc[0] if probs_desc else 0.0
    second = probs_desc[1] if len(probs_desc) > 1 else 0.0
    third = probs_desc[2] if len(probs_desc) > 2 else 0.0
    if top >= KEY_TOP_PROB_MIN and (top - second) >= KEY_GAP_MIN:
        return "KEY"
    if (top + second) >= TIGHT_TOP2_MIN or (
        top >= TIGHT_TOP_PROB_MIN and second >= TIGHT_SECOND_PROB_MIN
    ):
        return "TIGHT"
    if (top + second + third) >= MID_TOP3_MIN and entropy <= MID_ENTROPY_MAX:
        return "MID"
    return "CHAOS"


def _level_from_factor(chaos_factor: float) -> ChaosLevel:
    if chaos_factor <= CHAOS_LEVEL_FACTOR_LOW:
        return "LOW"
    if chaos_factor <= CHAOS_LEVEL_FACTOR_MODERATE:
        return "MODERATE"
    if chaos_factor <= CHAOS_LEVEL_FACTOR_HIGH:
        return "HIGH"
    return "EXTREME"


def _level_from_ratio(entropy_ratio: float) -> ChaosLevel:
    if entropy_ratio <= CHAOS_LEVEL_RATIO_LOW:
        return "LOW"
    if entropy_ratio <= CHAOS_LEVEL_RATIO_MODERATE:
        return "MODERATE"
    if entropy_ratio <= CHAOS_LEVEL_RATIO_HIGH:
        return "HIGH"
    return "EXTREME"


def _compute_chaos_level(
    chaos_factor: float, entropy: float, field_size: int
) -> ChaosLevel:
    """Take the higher of the factor-derived and ratio-derived levels."""
    factor_level = _level_from_factor(chaos_factor)
    if field_size > 1:
        max_entropy = math.log2(field_size)
        ratio = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        ratio = 0.0
    ratio_level = _level_from_ratio(ratio)
    if _LEVEL_ORDER[factor_level] >= _LEVEL_ORDER[ratio_level]:
        return factor_level
    return ratio_level


def _race_chaos_factor(
    race: Race, priors: dict[str, dict[str, Any]]
) -> float:
    """Resolve the priors-driven chaos factor for ``race`` (default 1.0)."""
    rtype = _classify_chaos_race_type(race)
    table = priors.get("race_type") or {}
    entry = table.get(rtype) or table.get("default") or {}
    if isinstance(entry, dict):
        return float(entry.get("chaos", 1.0))
    return 1.0


def classify_race(
    race: Race, priors: dict[str, dict[str, Any]]
) -> None:
    """Populate ``classification``, ``entropy``, ``chaos_level``, ``strategy``.

    Reads ``finalProbability`` on non-scratched horses (must be set first
    by ``blend_race`` and ``apply_historical_priors``). Sets all four race
    fields to ``None`` when no eligible runner has a positive probability.

    Strategy resolution: ``classification × chaos_level`` lookup, with a
    hard override that returns ``MAX CHAOS`` whenever the priors-derived
    chaos factor is at or above :data:`MAX_CHAOS_FACTOR_OVERRIDE` (Derby).
    """
    probs = sorted(
        (
            h.finalProbability
            for h in race.horses
            if (
                not h.scratched
                and h.finalProbability is not None
                and h.finalProbability > 0
            )
        ),
        reverse=True,
    )
    if not probs:
        race.classification = None
        race.entropy = None
        race.chaos_level = None
        race.strategy = None
        return

    entropy = _shannon_entropy(probs)
    classification = _classify_from_probs(probs, entropy)
    chaos_factor = _race_chaos_factor(race, priors)
    chaos_level = _compute_chaos_level(chaos_factor, entropy, len(probs))
    if chaos_factor >= MAX_CHAOS_FACTOR_OVERRIDE:
        strategy: StrategyLabel = STRATEGY_LABEL_MAX_CHAOS
    else:
        strategy = _STRATEGY_TABLE[(classification, chaos_level)]

    race.classification = classification
    race.entropy = entropy
    race.chaos_level = chaos_level
    race.strategy = strategy


# ---- edge model (ownership, edge, confidence, bucket, flags) -------------

# Ownership proxy table — keyed by 1-indexed odds rank; rank 13+ falls
# through to OWNERSHIP_PROXY_TAIL.
OWNERSHIP_PROXY_BY_RANK: dict[int, float] = {
    1: 0.65,
    2: 0.50,
    3: 0.38,
    4: 0.25,
    5: 0.19,
    6: 0.13,
    7: 0.09,
    8: 0.07,
    9: 0.06,
    10: 0.05,
    11: 0.04,
    12: 0.04,
}
OWNERSHIP_PROXY_TAIL = 0.03

# Linear mapping from ownership_proxy → ownership_discount additive term.
OWNERSHIP_NEUTRAL = 0.20
OWNERSHIP_SCALE = 0.18

# Linear mapping from race chaos_factor → per-horse chaos_bonus (rank ≥ 2).
CHAOS_BONUS_SCALE = 0.15

# Confidence score components.
PROB_STRONG_THRESHOLD = 0.40
MAX_VELOCITY = 0.10
CONFIDENCE_WEIGHT_PROB = 0.60
CONFIDENCE_WEIGHT_MOVEMENT = 0.40
RACE_STABILITY_MODIFIER: dict[RaceClassification, float] = {
    "KEY": 0.90,
    "TIGHT": 0.75,
    "MID": 0.60,
    "CHAOS": 0.40,
}
RACE_STABILITY_DEFAULT = 0.60  # used when classification is unset

# Edge-derived flag thresholds.
VALUE_HORSE_EDGE_MIN = 0.03
SEPARATOR_EDGE_MIN = 0.05
SEPARATOR_OWNERSHIP_MAX = 0.13
COLD_HORSE_VELOCITY_MAX = -0.02

# Bucket thresholds.
CORE_PROB_MIN = 0.30
DEAD_EDGE_MAX = -0.05
CHAOS_EDGE_MIN = -0.02


def _ownership_proxy_for_rank(rank: int) -> float:
    """Look up the ownership proxy for a 1-indexed odds rank."""
    return OWNERSHIP_PROXY_BY_RANK.get(rank, OWNERSHIP_PROXY_TAIL)


def _movement_signal_from_velocity(velocity: float, rank: int | None) -> float:
    """Map a velocity to the [0, 1] confidence-component signal.

    Applies :data:`LONGSHOT_VELOCITY_DAMPENER` to the velocity for rank ≥ 7
    so longshot steam can never fully saturate the confidence movement
    component. Flat odds (velocity = 0) return 0.5 (neutral).
    """
    if rank is not None and rank >= 7:
        velocity = velocity * LONGSHOT_VELOCITY_DAMPENER
    norm = velocity / MAX_VELOCITY
    if norm > 1.0:
        norm = 1.0
    elif norm < -1.0:
        norm = -1.0
    return (norm + 1.0) / 2.0


def _compute_bucket(
    horse: Horse, edge_score: float | None, race_chaos_flag: bool
) -> ComputedBucket:
    """Apply the priority-ordered bucket rules from the issue spec."""
    if horse.scratched:
        return "DEAD"
    if (
        FLAG_BAD_SINGLE in horse.flags
        and edge_score is not None
        and edge_score < DEAD_EDGE_MAX
    ):
        return "DEAD"
    if horse.trap_favorite:
        return "TRAP"
    fp = horse.finalProbability
    if (
        fp is not None
        and fp >= CORE_PROB_MIN
        and edge_score is not None
        and edge_score >= 0.0
    ):
        return "CORE"
    if (
        edge_score is not None
        and edge_score >= CHAOS_EDGE_MIN
        and (horse.steam_horse or race_chaos_flag)
    ):
        return "CHAOS"
    return "VALUE"


def apply_edge_model(
    race: Race,
    priors: dict[str, dict[str, Any]],
    drift_by_horse_id: dict[str, list[tuple[int, str, float]]] | None = None,
) -> None:
    """Populate the per-horse edge fields on ``race``.

    Pipeline slot: after :func:`apply_movement_adjustment`,
    :func:`classify_race`, and :func:`apply_flags` — those steps must have
    run first because this one
    reads ``finalProbability`` (final), ``flags`` (for ``bad_single``/
    ``chaos_race``), ``steam_horse`` (set by movement), and
    ``classification`` (for the confidence stability modifier).

    Per non-scratched horse, sets ``ownership_proxy`` (by odds rank),
    ``true_prob`` (= ``finalProbability``), ``edge_score`` (true_prob
    minus market plus ownership discount plus chaos bonus),
    ``confidence_score`` (weighted prob/movement signal × race stability),
    the four edge flags (``trap_favorite``, ``separator_candidate``,
    ``value_horse``, ``cold_horse``), and ``computedBucket``.

    Scratched horses receive ``None`` for the numeric fields, ``False``
    for the booleans, and ``"DEAD"`` for ``computedBucket``.

    ``drift_by_horse_id`` is the same drift map passed to
    :func:`apply_movement_adjustment`. When omitted, velocity is treated
    as zero (neutral movement signal, no ``cold_horse`` flag).
    """
    drift_map = drift_by_horse_id or {}
    chaos_factor = _race_chaos_factor(race, priors)

    # Odds rank by descending marketProbability among non-scratched horses
    # that have a market price. Horses without market data get no rank.
    eligible = [
        h for h in race.horses
        if not h.scratched and h.marketProbability is not None
    ]
    ranked = sorted(
        eligible, key=lambda h: h.marketProbability or 0.0, reverse=True
    )
    rank_by_id: dict[str, int] = {h.id: i + 1 for i, h in enumerate(ranked)}

    race_has_chaos_flag = any(
        FLAG_CHAOS_RACE in h.flags for h in race.horses if not h.scratched
    )
    classification = race.classification
    stability = (
        RACE_STABILITY_MODIFIER[classification]
        if classification is not None
        else RACE_STABILITY_DEFAULT
    )

    for h in race.horses:
        if h.scratched:
            h.ownership_proxy = None
            h.true_prob = None
            h.edge_score = None
            h.confidence_score = None
            h.trap_favorite = False
            h.separator_candidate = False
            h.value_horse = False
            h.cold_horse = False
            h.computedBucket = "DEAD"
            continue

        rank = rank_by_id.get(h.id)
        h.ownership_proxy = (
            _ownership_proxy_for_rank(rank) if rank is not None else None
        )

        h.true_prob = h.finalProbability

        if h.finalProbability is not None and h.marketProbability is not None:
            edge = h.finalProbability - h.marketProbability
            owner = h.ownership_proxy if h.ownership_proxy is not None else 0.0
            ownership_discount = -(owner - OWNERSHIP_NEUTRAL) * OWNERSHIP_SCALE
            chaos_bonus = (
                (chaos_factor - 1.0) * CHAOS_BONUS_SCALE
                if rank is not None and rank > 1 and chaos_factor > 1.0
                else 0.0
            )
            h.edge_score = edge + ownership_discount + chaos_bonus
        else:
            h.edge_score = None

        velocity = _compute_velocity(drift_map.get(h.id))

        h.trap_favorite = (
            rank == 1 and h.edge_score is not None and h.edge_score < 0.0
        )
        h.separator_candidate = (
            h.edge_score is not None
            and h.edge_score >= SEPARATOR_EDGE_MIN
            and h.ownership_proxy is not None
            and h.ownership_proxy <= SEPARATOR_OWNERSHIP_MAX
        )
        h.value_horse = (
            h.edge_score is not None and h.edge_score >= VALUE_HORSE_EDGE_MIN
        )
        h.cold_horse = (
            velocity < COLD_HORSE_VELOCITY_MAX
            and h.edge_score is not None
            and h.edge_score < 0.0
        )

        if h.finalProbability is not None:
            prob_strength = h.finalProbability / PROB_STRONG_THRESHOLD
            if prob_strength > 1.0:
                prob_strength = 1.0
            elif prob_strength < 0.0:
                prob_strength = 0.0
            movement_signal = _movement_signal_from_velocity(velocity, rank)
            raw = (
                CONFIDENCE_WEIGHT_PROB * prob_strength
                + CONFIDENCE_WEIGHT_MOVEMENT * movement_signal
            )
            h.confidence_score = raw * stability
        else:
            h.confidence_score = None

        h.computedBucket = _compute_bucket(h, h.edge_score, race_has_chaos_flag)


# ---- internal helpers ------------------------------------------------------


def _renormalize(horses: list[Horse], field: str) -> None:
    """Rescale ``field`` so non-scratched horses sum to 1.0; clear on scratched.

    Duplicates the small bit of logic from :func:`api.normalize.normalize_probabilities`
    locally to avoid the circular import (``api.normalize`` imports from this module).

    Non-finite contributions (NaN/inf) are dropped from the sum and replaced
    with ``None`` on the horse — defense-in-depth against priors-driven
    multipliers that could otherwise poison the whole race. Pydantic's
    JSON encoder defaults to ``inf_nan_mode='null'`` which would null these
    out at the wire, but downstream pipeline steps (sim, classification,
    edge model) read the in-memory values before serialization.
    """
    total = 0.0
    for h in horses:
        if h.scratched:
            continue
        v = getattr(h, field)
        if v is None or not math.isfinite(v):
            continue
        total += v
    if total <= 0 or not math.isfinite(total):
        for h in horses:
            if h.scratched and getattr(h, field) is not None:
                setattr(h, field, None)
            elif not h.scratched:
                v = getattr(h, field)
                if v is not None and not math.isfinite(v):
                    setattr(h, field, None)
        return
    for h in horses:
        if h.scratched:
            setattr(h, field, None)
            continue
        v = getattr(h, field)
        if v is None:
            continue
        if not math.isfinite(v):
            setattr(h, field, None)
            continue
        setattr(h, field, v / total)


__all__ = [
    "Day",
    "Track",
    "SequenceRole",
    "UserTag",
    "ComputedBucket",
    "RaceClassification",
    "ChaosLevel",
    "StrategyLabel",
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
    "FIELD_SIZE_COMPRESSION_MIN",
    "ChaosRaceType",
    "load_priors",
    "field_size_bucket",
    "determine_race_type",
    "compute_model_prior",
    "apply_model_priors_to_race",
    "blend_probabilities",
    "blend_race",
    "apply_historical_priors",
    "compute_horse_flags",
    "compute_race_flags",
    "apply_flags",
    "apply_movement_adjustment",
    "classify_race",
    "KEY_TOP_PROB_MIN",
    "KEY_GAP_MIN",
    "TIGHT_TOP2_MIN",
    "TIGHT_TOP_PROB_MIN",
    "TIGHT_SECOND_PROB_MIN",
    "MID_TOP3_MIN",
    "MID_ENTROPY_MAX",
    "CHAOS_LEVEL_FACTOR_LOW",
    "CHAOS_LEVEL_FACTOR_MODERATE",
    "CHAOS_LEVEL_FACTOR_HIGH",
    "CHAOS_LEVEL_RATIO_LOW",
    "CHAOS_LEVEL_RATIO_MODERATE",
    "CHAOS_LEVEL_RATIO_HIGH",
    "MAX_CHAOS_FACTOR_OVERRIDE",
    "STRATEGY_LABEL_SINGLE",
    "STRATEGY_LABEL_TWO_DEEP",
    "STRATEGY_LABEL_MID",
    "STRATEGY_LABEL_CHAOS_SPREAD",
    "STRATEGY_LABEL_MAX_CHAOS",
    "MOVEMENT_REFERENCE_WINDOW_MS",
    "VELOCITY_CLAMP",
    "VELOCITY_NOISE_FLOOR",
    "ADJUSTMENT_MAX",
    "ADJUSTMENT_MIN",
    "MAX_SINGLE_HORSE_PROB",
    "MOVEMENT_WEIGHT_MID_TIER_SHORTEN",
    "MOVEMENT_WEIGHT_FAVORITE_SHORTEN",
    "MOVEMENT_WEIGHT_LONGSHOT_SHORTEN",
    "MOVEMENT_WEIGHT_DRIFT",
    "MOVEMENT_WEIGHT_FLAT_DEFAULT",
    "LONGSHOT_VELOCITY_DAMPENER",
    "TIER_FAVORITE_CEILING_ODDS",
    "TIER_LONGSHOT_FLOOR_ODDS",
    "OWNERSHIP_PROXY_BY_RANK",
    "OWNERSHIP_PROXY_TAIL",
    "OWNERSHIP_NEUTRAL",
    "OWNERSHIP_SCALE",
    "CHAOS_BONUS_SCALE",
    "PROB_STRONG_THRESHOLD",
    "MAX_VELOCITY",
    "CONFIDENCE_WEIGHT_PROB",
    "CONFIDENCE_WEIGHT_MOVEMENT",
    "RACE_STABILITY_MODIFIER",
    "RACE_STABILITY_DEFAULT",
    "VALUE_HORSE_EDGE_MIN",
    "SEPARATOR_EDGE_MIN",
    "SEPARATOR_OWNERSHIP_MAX",
    "COLD_HORSE_VELOCITY_MAX",
    "CORE_PROB_MIN",
    "DEAD_EDGE_MAX",
    "CHAOS_EDGE_MIN",
    "apply_edge_model",
]
