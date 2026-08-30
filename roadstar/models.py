"""Typed domain model for backhaul matching.

Times are integer minutes from a fixed epoch (the instance's t=0). Integers
keep every comparison exact, so feasibility is never decided by a float
rounding artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from .geo import Coord


class Equipment(str, Enum):
    DRY_VAN = "dry_van"
    REEFER = "reefer"
    FLATBED = "flatbed"


#: Which trailer can legally/physically carry which freight requirement.
#: A reefer can run dry freight (it simply does not power the unit); a dry van
#: cannot carry temperature-controlled freight; flatbed is disjoint from both.
_COMPAT: Final[dict[Equipment, frozenset[Equipment]]] = {
    Equipment.DRY_VAN: frozenset({Equipment.DRY_VAN}),
    Equipment.REEFER: frozenset({Equipment.DRY_VAN, Equipment.REEFER}),
    Equipment.FLATBED: frozenset({Equipment.FLATBED}),
}


def can_haul(trailer: Equipment, freight_requires: Equipment) -> bool:
    return freight_requires in _COMPAT[trailer]


@dataclass(frozen=True, slots=True)
class Truck:
    """A tractor that has just delivered, and is now empty at `at`."""

    truck_id: str
    at: Coord
    at_name: str
    free_from_min: int
    trailer: Equipment
    #: Minutes of driving already used in the current duty day.
    drive_used_min: int
    #: Minutes of on-duty time already used in the current duty day.
    onduty_used_min: int
    #: Domicile, used only for reporting; not a constraint.
    domicile_name: str


@dataclass(frozen=True, slots=True)
class Load:
    """An outbound load waiting for a tractor."""

    load_id: str
    origin: Coord
    origin_name: str
    dest: Coord
    dest_name: str
    #: Pickup window, inclusive, in minutes from epoch.
    pickup_open_min: int
    pickup_close_min: int
    requires: Equipment
    revenue_usd: float
    loaded_km: float


@dataclass(frozen=True, slots=True)
class Assignment:
    truck_id: str
    load_id: str
    deadhead_km: float
    arrive_min: int


@dataclass(frozen=True, slots=True)
class Solution:
    """Result of one matching run.

    `infeasible` counts assignments a policy proposed that violate at least one
    hard constraint. A feasible policy reports 0; the naive baseline does not,
    and that number is reported rather than hidden.
    """

    name: str
    assignments: tuple[Assignment, ...]
    infeasible: tuple[Assignment, ...] = ()

    @property
    def n_matched(self) -> int:
        return len(self.assignments)
