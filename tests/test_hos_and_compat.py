from __future__ import annotations

import pytest

from roadstar.hos import (
    MAX_DAILY_DRIVE_MIN,
    MAX_DAILY_ONDUTY_MIN,
    PICKUP_ONDUTY_MIN,
    drive_minutes,
    hos_ok,
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


def test_hos_daily_drive_ceiling_is_exact_at_the_boundary():
    assert hos_ok(MAX_DAILY_DRIVE_MIN - 60, 0, 60) is True
    assert hos_ok(MAX_DAILY_DRIVE_MIN - 60, 0, 61) is False


def test_hos_onduty_ceiling_accounts_for_pickup_overhead():
    room = MAX_DAILY_ONDUTY_MIN - PICKUP_ONDUTY_MIN
    assert hos_ok(0, room - 30, 30) is True
    assert hos_ok(0, room - 30, 31) is False


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
