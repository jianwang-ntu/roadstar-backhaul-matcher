"""Empty-mile accounting.

The headline number this project reports is the empty-mile fraction

    deadhead_km / (deadhead_km + loaded_km)

computed over the whole fleet for one instance under one policy. Two accounting
decisions are made explicitly because they are the two places a comparison like
this is normally rigged:

1. A truck that is NOT matched still runs empty -- it repositions to its
   domicile. Its kilometres are charged to the policy. A policy that matches
   nothing therefore does not score a perfect zero deadhead; it scores the
   worst.
2. Loaded kilometres counted are only those of loads the policy actually moved,
   plus, for the unmatched trucks, nothing. Revenue moved is reported alongside
   so a policy cannot look good by declining work.
3. The empty fraction is a RATIO, so a policy can lower it by hauling more
   loaded kilometres rather than by running fewer empty ones. `profit_assignment`
   does exactly that. Absolute `deadhead_km_total`, `revenue_usd` and
   `profit_usd` are therefore all reported next to it, and the README's headline
   claim is stated on profit -- the objective that policy actually optimises --
   not on the ratio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .econ import OPERATING_COST_USD_PER_KM
from .instance import deadhead_if_unmatched
from .models import Load, Solution, Truck


@dataclass(frozen=True, slots=True)
class Metrics:
    policy: str
    n_trucks: int
    n_loads: int
    n_matched: int
    n_infeasible_proposed: int
    deadhead_km_matched: float
    deadhead_km_reposition: float
    deadhead_km_total: float
    loaded_km: float
    empty_fraction: float
    revenue_usd: float
    operating_cost_usd: float
    profit_usd: float

    def as_dict(self) -> dict:
        return asdict(self)


def score(trucks: list[Truck], loads: list[Load], sol: Solution) -> Metrics:
    by_load = {ld.load_id: ld for ld in loads}

    matched_dh = sum(a.deadhead_km for a in sol.assignments)
    matched_trucks = {a.truck_id for a in sol.assignments}
    reposition_dh = sum(
        deadhead_if_unmatched(t) for t in trucks if t.truck_id not in matched_trucks
    )
    loaded = sum(by_load[a.load_id].loaded_km for a in sol.assignments)
    revenue = sum(by_load[a.load_id].revenue_usd for a in sol.assignments)
    total_dh = matched_dh + reposition_dh
    denom = total_dh + loaded
    # Every kilometre the fleet turns is charged, empty or loaded.
    op_cost = OPERATING_COST_USD_PER_KM * (total_dh + loaded)

    return Metrics(
        policy=sol.name,
        n_trucks=len(trucks),
        n_loads=len(loads),
        n_matched=len(sol.assignments),
        n_infeasible_proposed=len(sol.infeasible),
        deadhead_km_matched=round(matched_dh, 3),
        deadhead_km_reposition=round(reposition_dh, 3),
        deadhead_km_total=round(total_dh, 3),
        loaded_km=round(loaded, 3),
        empty_fraction=round(total_dh / denom, 6) if denom > 0 else 0.0,
        revenue_usd=round(revenue, 2),
        operating_cost_usd=round(op_cost, 2),
        profit_usd=round(revenue - op_cost, 2),
    )
