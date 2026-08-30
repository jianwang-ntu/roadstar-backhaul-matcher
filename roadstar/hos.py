"""Hours-of-service feasibility.

Models the daily limits of the Canadian federal HOS rule (SOR/2005-313,
south-of-60 day limits): at most 13 h driving and at most 14 h on-duty between
mandatory off-duty periods.

This is a SIMPLIFICATION and is described as one everywhere it is reported. It
covers the daily driving and on-duty ceilings only. It does NOT model the 70 h /
7 day cycle, the 24 h reset, sleeper-berth splitting, deferral, or the US
rules that apply once a truck crosses at Windsor or Buffalo. No claim in this
project asserts regulatory compliance; the constraint exists so the matcher
cannot propose a dispatch a compliant driver could not legally run.
"""

from __future__ import annotations

from typing import Final

MAX_DAILY_DRIVE_MIN: Final[int] = 13 * 60
MAX_DAILY_ONDUTY_MIN: Final[int] = 14 * 60

#: Fixed non-driving on-duty overhead charged at pickup (hook, inspection,
#: paperwork). A modelling constant, not a regulation.
PICKUP_ONDUTY_MIN: Final[int] = 45


def drive_minutes(distance_km: float, avg_speed_kph: float = 85.0) -> int:
    """Whole minutes to cover `distance_km`, rounded up.

    Rounding up is the conservative direction: it can only make a dispatch look
    less feasible, never more.
    """
    if distance_km < 0:
        raise ValueError("distance_km must be non-negative")
    return -(-int(round(distance_km * 60.0 / avg_speed_kph * 1000)) // 1000)


def hos_ok(drive_used_min: int, onduty_used_min: int, added_drive_min: int) -> bool:
    """True if adding `added_drive_min` of driving plus pickup overhead is legal."""
    if drive_used_min + added_drive_min > MAX_DAILY_DRIVE_MIN:
        return False
    if onduty_used_min + added_drive_min + PICKUP_ONDUTY_MIN > MAX_DAILY_ONDUTY_MIN:
        return False
    return True
