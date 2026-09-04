from __future__ import annotations

import pytest

from roadstar.hos import (
    MAX_DAILY_DRIVE_MIN,
    MAX_DAILY_ONDUTY_MIN,
    MIN_RESET_OFF_DUTY_MIN,
    PICKUP_ONDUTY_MIN,
    drive_minutes,
    hos_ok,
    onduty_wait_min,
)
from roadstar.models import Equipment, can_haul


def test_drive_minutes_rounds_up_never_down():
    """Rounding up can only make a dispatch look less feasible."""
    assert drive_minutes(85.0) == 60
    assert drive_minutes(85.0 / 60) == 1
    assert drive_minutes(85.0 / 60 * 1.01) == 2
    assert drive_minutes(0.0) == 0


def test_drive_minutes_rejects_negative_distance():
    with pytest.raises(ValueError):
        drive_minutes(-1.0)


def test_drive_minutes_is_monotone():
    prev = -1
    for km in range(0, 2000, 7):
        cur = drive_minutes(float(km))
        assert cur >= prev
        prev = cur


def test_the_ceilings_are_the_regulated_numbers_not_whatever_is_in_the_module():
    """Round-2 audit finding DOMAIN-03: the boundary tests below used to derive
    their boundary from the very constant under test, so both ceilings could be
    set to 30 h and all 52 tests still passed while the headline empty fraction
    moved. The literals here are the SOR/2005-313 south-of-60 day limits, and
    they are written out so a change to the constants is a failing test."""
    assert MAX_DAILY_DRIVE_MIN == 780, "13 h driving"
    assert MAX_DAILY_ONDUTY_MIN == 840, "14 h on-duty"
    assert MIN_RESET_OFF_DUTY_MIN == 480, "8 consecutive hours ends a shift"


def test_hos_daily_drive_ceiling_is_exact_at_the_boundary():
    """Pinned to 780 minutes, not to MAX_DAILY_DRIVE_MIN. See DOMAIN-03."""
    assert hos_ok(780 - 60, 0, 60, wait_min=0) is True
    assert hos_ok(780 - 60, 0, 61, wait_min=0) is False


def test_hos_onduty_ceiling_accounts_for_pickup_overhead():
    """Pinned to 840 minutes and to the 45-minute overhead. See DOMAIN-03."""
    room = 840 - 45
    assert hos_ok(0, room - 30, 30, wait_min=0) is True
    assert hos_ok(0, room - 30, 31, wait_min=0) is False


def test_hos_charges_the_shipper_wait_against_the_onduty_ceiling():
    """Round-2 audit finding DOMAIN-01. Waiting to be loaded is on-duty
    not-driving (SOR/2005-313; FMCSA 395.2). A dispatch that fits without the
    wait and not with it must be rejected, or the ceiling binds on only part of
    the duty day."""
    room = 840 - 45
    assert hos_ok(0, room - 120, 30, wait_min=0) is True
    assert hos_ok(0, room - 120, 30, wait_min=90) is True
    assert hos_ok(0, room - 120, 30, wait_min=91) is False


def test_hos_will_not_silently_accept_a_caller_that_forgets_the_wait():
    """The DOMAIN-01 defect was a caller that never passed the wait. `wait_min`
    is keyword-only and undefaulted so that caller cannot exist silently."""
    with pytest.raises(TypeError):
        hos_ok(0, 0, 60)  # type: ignore[call-arg]


def test_a_wait_long_enough_to_end_the_shift_is_not_charged():
    """The one charity in the model, made explicit and bounded: a wait of at
    least 8 h is treated as the qualifying off-duty period that ends a shift.
    One minute short of it is charged in full."""
    assert onduty_wait_min(479) == 479
    assert onduty_wait_min(480) == 0
    assert onduty_wait_min(1000) == 0
    room = 840 - 45
    assert hos_ok(0, room - 120, 30, wait_min=479) is False
    assert hos_ok(0, room - 120, 30, wait_min=480) is True


def test_onduty_wait_rejects_a_negative_wait():
    with pytest.raises(ValueError):
        onduty_wait_min(-1)


def test_reefer_may_haul_dry_freight_but_not_the_reverse():
    assert can_haul(Equipment.REEFER, Equipment.DRY_VAN) is True
    assert can_haul(Equipment.DRY_VAN, Equipment.REEFER) is False


def test_flatbed_is_disjoint_from_the_enclosed_trailers():
    for other in (Equipment.DRY_VAN, Equipment.REEFER):
        assert can_haul(Equipment.FLATBED, other) is False
        assert can_haul(other, Equipment.FLATBED) is False


def test_every_trailer_can_haul_its_own_type():
    for eq in Equipment:
        assert can_haul(eq, eq) is True
