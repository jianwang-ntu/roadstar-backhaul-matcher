"""The single definition of a legal truck->load dispatch.

Every policy in this project is scored against this one function, so a
"constraint-aware" policy and the naive baseline cannot be judged by different
rules. Three hard constraints:

  C1 trailer compatibility        (models.can_haul)
  C2 pickup time window           truck must arrive by pickup_close_min
  C3 hours of service             deadhead drive + pickup overhead must fit
"""

from __future__ import annotations

from dataclasses import dataclass

from .geo import road_km
from .hos import drive_minutes, hos_ok
from .models import Load, Truck, can_haul


@dataclass(frozen=True, slots=True)
class Leg:
    deadhead_km: float
    drive_min: int
    arrive_min: int


def leg(truck: Truck, load: Load) -> Leg:
    """The empty repositioning leg from where the truck sits to the pickup."""
    km = road_km(truck.at, load.origin)
    dm = drive_minutes(km)
    return Leg(deadhead_km=km, drive_min=dm, arrive_min=truck.free_from_min + dm)


def violations(truck: Truck, load: Load) -> tuple[str, ...]:
    """Every hard constraint this pairing breaks. Empty tuple == feasible."""
    bad: list[str] = []
    if not can_haul(truck.trailer, load.requires):
        bad.append("C1_trailer")
    lg = leg(truck, load)
    if lg.arrive_min > load.pickup_close_min:
        bad.append("C2_window")
    if not hos_ok(truck.drive_used_min, truck.onduty_used_min, lg.drive_min):
        bad.append("C3_hos")
    return tuple(bad)


def is_feasible(truck: Truck, load: Load) -> bool:
    return not violations(truck, load)
