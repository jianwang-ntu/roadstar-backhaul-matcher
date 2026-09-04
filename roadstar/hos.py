"""Hours-of-service feasibility.

Models the daily limits of the Canadian federal HOS rule (SOR/2005-313,
south-of-60 day limits): at most 13 h driving and at most 14 h on-duty between
mandatory off-duty periods.

What counts as on-duty here
---------------------------
On-duty is not the same thing as driving. A dispatch charges, against the 14 h
ceiling: the empty repositioning drive, the time the truck spends waiting at the
shipper for the pickup window to open, a fixed hook/inspection/paperwork
overhead, and the loaded drive. Time spent waiting to be loaded is on-duty
not-driving under both SOR/2005-313 and FMCSA 395.2, and round-2 audit finding
DOMAIN-01 measured what leaving it out cost: 42.79% of the dispatches the
previous revision called legal exceeded the 14 h ceiling once the wait was
charged, and the worst modelled duty day was 24.45 h -- longer than the 23.8 h
defect the previous revision's README led with as the thing it had fixed. A
ceiling that binds on part of the duty day is not a ceiling.

This is still a SIMPLIFICATION and is described as one everywhere it is
reported. It covers the daily driving and on-duty ceilings only. It does NOT
model the 70 h / 7 day cycle, sleeper-berth splitting, deferral, or the US rules
that apply once a truck crosses at Windsor or Buffalo. No claim in this project
asserts regulatory compliance; the constraint exists so the matcher cannot
propose a dispatch a compliant driver could not legally run.

Two modelling choices are recorded here rather than left implicit, because both
are places where a different reading would change the numbers:

1. A wait of at least `MIN_RESET_OFF_DUTY_MIN` is treated as a qualifying
   off-duty period that ends the shift, so it is not charged. The model does not
   verify that the driver actually took it off duty -- this is the charitable
   reading, it is stated, and the README quantifies how many accepted dispatches
   depend on it.
2. The 16 h elapsed-shift window of SOR/2005-313 is not implemented as a
   separate check because under this accounting it can never bind: every minute
   the elapsed window would count is already charged against the strictly lower
   14 h on-duty ceiling, and a wait long enough to reset one resets the other.
   Prior on-duty time is NOT forgiven by that reset, which is the conservative
   direction -- it can only make a dispatch look less feasible.
"""

from __future__ import annotations

from typing import Final

MAX_DAILY_DRIVE_MIN: Final[int] = 13 * 60
MAX_DAILY_ONDUTY_MIN: Final[int] = 14 * 60

#: Fixed non-driving on-duty overhead charged at pickup (hook, inspection,
#: paperwork). A modelling constant, not a regulation.
PICKUP_ONDUTY_MIN: Final[int] = 45

#: Consecutive off-duty minutes that end a shift under SOR/2005-313. A wait at
#: least this long is not charged as on-duty time. See choice (1) above.
MIN_RESET_OFF_DUTY_MIN: Final[int] = 8 * 60


def drive_minutes(distance_km: float, avg_speed_kph: float = 85.0) -> int:
    """Whole minutes to cover `distance_km`, rounded up.

    Rounding up is the conservative direction: it can only make a dispatch look
    less feasible, never more.
    """
    if distance_km < 0:
        raise ValueError("distance_km must be non-negative")
    return -(-int(round(distance_km * 60.0 / avg_speed_kph * 1000)) // 1000)


def onduty_wait_min(wait_min: int) -> int:
    """The part of a shipper wait that is charged as on-duty time.

    Zero if the wait is long enough to be the qualifying off-duty period that
    ends a shift; the whole wait otherwise.
    """
    if wait_min < 0:
        raise ValueError("wait_min must be non-negative")
    return 0 if wait_min >= MIN_RESET_OFF_DUTY_MIN else wait_min


def hos_ok(
    drive_used_min: int,
    onduty_used_min: int,
    added_drive_min: int,
    *,
    wait_min: int,
) -> bool:
    """True if the whole dispatch fits inside the duty day.

    `wait_min` is keyword-only and has no default ON PURPOSE. The defect this
    function was carrying (DOMAIN-01) was a caller that simply did not pass the
    shipper wait; a default of 0 would have let that caller keep compiling and
    keep understating the duty day. A caller that forgets it now raises
    TypeError instead of silently clearing an illegal dispatch.
    """
    if drive_used_min + added_drive_min > MAX_DAILY_DRIVE_MIN:
        return False
    onduty = (
        onduty_used_min
        + added_drive_min
        + PICKUP_ONDUTY_MIN
        + onduty_wait_min(wait_min)
    )
    if onduty > MAX_DAILY_ONDUTY_MIN:
        return False
    return True
