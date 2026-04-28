"""Post-refresh validation for the Pick 5 race card.

After each ingestion cycle the API runs :func:`validate_card` against
the merged, normalized races. If the card fails validation, the API
caller falls back to ``OddsCache.get_last_good_card`` and returns the
cached card with ``stale=True`` plus the surfaced error list — see the
"Scraper Validation" / "Cache Strategy" sections of ``BRAINDUMP.md``.

The check enforces, per the BRAINDUMP contract:

1. all five Pick 5 legs are present (by ``sequenceRole``)
2. every horse in every Pick 5 leg has a non-empty name (the Pydantic
   ``Horse`` model already enforces ``post >= 1``)
3. each non-scratched horse has at least one parseable odds value
   (morning line OR current)
4. no duplicate ``(raceId, post)`` entries
5. scratched horses are flagged, not silently removed (they remain in
   ``horses`` with ``scratched=True`` and are excluded from odds /
   probability checks rather than dropped)
6. per-race normalized probabilities sum to ``1.0 ± 0.01`` across the
   non-scratched horses
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.model import PICK5_LEG_ROLES, Race
from api.normalize import odds_to_probability

PROBABILITY_TOLERANCE = 0.01
PROBABILITY_FIELDS: tuple[str, ...] = (
    "marketProbability",
    "morningLineProbability",
)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a single :func:`validate_card` pass.

    ``errors`` is empty iff ``valid`` is True. Each entry is one
    human-readable string suitable for surfacing directly in the API
    response payload.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_card(races: list[Race], day: str) -> ValidationResult:
    """Run the post-refresh checks against ``races`` for ``day``.

    The API caller treats ``valid=False`` as the trigger to fall back
    to the SQLite cache: serve ``OddsCache.get_last_good_card`` with
    ``stale=True`` and attach this object's ``errors`` list to the
    response so the UI can show why the live data was rejected.
    """
    errors: list[str] = []

    day_races = [r for r in races if r.day == day]

    pick5_by_role: dict[str, Race] = {}
    for race in day_races:
        role = race.sequenceRole
        if role in PICK5_LEG_ROLES:
            # First occurrence wins; duplicate-role assignment is a
            # caller bug we don't try to repair here.
            pick5_by_role.setdefault(role, race)

    for i, role in enumerate(PICK5_LEG_ROLES, start=1):
        if role not in pick5_by_role:
            errors.append(f"Pick 5 leg {i} not found in card")

    for role in PICK5_LEG_ROLES:
        race = pick5_by_role.get(role)
        if race is None:
            continue
        errors.extend(_validate_race(race))

    return ValidationResult(valid=not errors, errors=errors)


def _validate_race(race: Race) -> list[str]:
    """Return the list of error strings for a single Pick 5 race."""
    label = f"Race {race.raceNumber}"
    horses = race.horses
    errors: list[str] = []

    post_counts: dict[int, int] = {}
    for h in horses:
        post_counts[h.post] = post_counts.get(h.post, 0) + 1
    for post in sorted(p for p, n in post_counts.items() if n > 1):
        errors.append(f"{label} has duplicate horses at post {post}")

    missing_name = sum(1 for h in horses if not h.name.strip())
    if missing_name > 0:
        noun = "horse" if missing_name == 1 else "horses"
        errors.append(f"{label} missing name for {missing_name} {noun}")

    missing_odds = 0
    for h in horses:
        if h.scratched:
            continue
        if (
            odds_to_probability(h.morningLineOdds) is None
            and odds_to_probability(h.currentOdds) is None
            and h.morningLineProbability is None
            and h.marketProbability is None
        ):
            missing_odds += 1
    if missing_odds > 0:
        noun = "horse" if missing_odds == 1 else "horses"
        errors.append(f"{label} missing odds for {missing_odds} {noun}")

    for prob_field in PROBABILITY_FIELDS:
        values = [
            getattr(h, prob_field)
            for h in horses
            if not h.scratched and getattr(h, prob_field) is not None
        ]
        if not values:
            continue
        total = sum(values)
        if abs(total - 1.0) > PROBABILITY_TOLERANCE:
            errors.append(
                f"{label} {prob_field} sum {total:.3f} outside "
                f"1.0 ± {PROBABILITY_TOLERANCE}"
            )

    return errors


__all__ = [
    "PROBABILITY_FIELDS",
    "PROBABILITY_TOLERANCE",
    "ValidationResult",
    "validate_card",
]
