"""Deterministic SYNTHETIC instance generator.

Every instance produced here is synthetic and is labelled synthetic in every
artifact that reports a number derived from it. The geography is real (public
city coordinates, roadstar.geo.CORRIDOR); the trucks, loads, time windows and
revenues are generated. No claim in this project asserts that these instances
reproduce any real carrier's book of business.

Why synthetic: the event's own freight/order/trip/truck-spec tables sit behind
the organiser's participant portal, which requires creating an account. See
plan.md R-1/R-2. When that access lands, `load_portal_instance` is the seam to
implement -- nothing else in the codebase needs to change.
"""

from __future__ import annotations

import random
from typing import Final

from .geo import CORRIDOR, road_km
from .hos import drive_minutes
from .models import Equipment, Load, Truck

#: Weight of each trailer type in a generated fleet. Roughly reflects the
#: dry-van-dominant mix of southern-Ontario general freight; a modelling
#: assumption, not a measurement.
_TRAILER_MIX: Final[list[tuple[Equipment, float]]] = [
    (Equipment.DRY_VAN, 0.60),
    (Equipment.REEFER, 0.25),
    (Equipment.FLATBED, 0.15),
]


def _pick_trailer(rng: random.Random) -> Equipment:
    r = rng.random()
    acc = 0.0
    for eq, w in _TRAILER_MIX:
        acc += w
        if r < acc:
            return eq
    return _TRAILER_MIX[-1][0]


def make_instance(
    n_trucks: int,
    n_loads: int,
    seed: int,
    *,
    horizon_min: int = 12 * 60,
) -> tuple[list[Truck], list[Load]]:
    """Build one synthetic instance. Identical seed => identical instance."""
    if n_trucks < 0 or n_loads < 0:
        raise ValueError("counts must be non-negative")
    rng = random.Random(seed)
    names = sorted(CORRIDOR)

    trucks: list[Truck] = []
    for i in range(n_trucks):
        at_name = rng.choice(names)
        home = rng.choice(names)
        trucks.append(
            Truck(
                truck_id=f"T{i:03d}",
                at=CORRIDOR[at_name],
                at_name=at_name,
                free_from_min=rng.randrange(0, horizon_min // 2, 15),
                trailer=_pick_trailer(rng),
                drive_used_min=rng.randrange(0, 9 * 60, 30),
                onduty_used_min=rng.randrange(0, 10 * 60, 30),
                domicile_name=home,
            )
        )
        # Keep the duty-day state internally consistent: on-duty time always
        # includes driving time.
        t = trucks[-1]
        if t.onduty_used_min < t.drive_used_min:
            trucks[-1] = Truck(
                t.truck_id, t.at, t.at_name, t.free_from_min, t.trailer,
                t.drive_used_min, t.drive_used_min, t.domicile_name,
            )

    loads: list[Load] = []
    for j in range(n_loads):
        o_name = rng.choice(names)
        d_name = rng.choice([n for n in names if n != o_name])
        origin, dest = CORRIDOR[o_name], CORRIDOR[d_name]
        open_min = rng.randrange(0, horizon_min, 15)
        close_min = open_min + rng.choice([120, 180, 240, 360, 480])
        loaded = road_km(origin, dest)
        loads.append(
            Load(
                load_id=f"L{j:03d}",
                origin=origin,
                origin_name=o_name,
                dest=dest,
                dest_name=d_name,
                pickup_open_min=open_min,
                pickup_close_min=close_min,
                requires=_pick_trailer(rng),
                # A linehaul rate card of the shape $/km + fixed; synthetic.
                revenue_usd=round(1.85 * loaded + 120.0, 2),
                loaded_km=loaded,
            )
        )

    return trucks, loads


def load_portal_instance(path: str) -> tuple[list[Truck], list[Load]]:
    """Seam for the organiser's provided freight tables (plan.md R-2).

    Deliberately unimplemented. It raises rather than silently falling back to
    synthetic data, so no run can ever report portal-sourced numbers it did not
    have.
    """
    raise NotImplementedError(
        "Portal data is behind the participant-account wall (plan.md R-1). "
        "No portal dataset has been read; this project reports synthetic "
        "results only."
    )


def total_loaded_km(loads: list[Load]) -> float:
    return sum(ld.loaded_km for ld in loads)


def deadhead_if_unmatched(truck: Truck, home: str = "") -> float:
    """Deadhead a truck incurs when it gets no backhaul: it runs home empty."""
    target = home or truck.domicile_name
    return road_km(truck.at, CORRIDOR[target])


__all__ = [
    "make_instance",
    "load_portal_instance",
    "total_loaded_km",
    "deadhead_if_unmatched",
    "drive_minutes",
]
