"""The five dispatch policies compared in this project.

All five are handed the identical instance and scored by the identical
feasibility rules (roadstar.feasibility). The differences between them are the
whole experiment:

  naive_nearest        distance only. Ignores C1/C2/C3, so it proposes
                       dispatches a real fleet would have to reject. Its
                       infeasible count is reported, never suppressed.
  greedy_feasible      the DISTANCE baseline: nearest load among those that
                       are actually legal. This is what a dispatcher with a load
                       board does.
  greedy_profit_pairwise
                       the PROFIT baseline: sort every legal pair by the same
                       contribution the exact solver optimises and take them
                       greedily. Added after round-1 audit finding D3, which
                       showed that comparing an exact profit solver only against
                       a distance-greedy dispatcher credits the solver with the
                       gain from changing the objective. This baseline isolates
                       that: greedy_feasible -> greedy_profit_pairwise is the
                       objective change, greedy_profit_pairwise ->
                       profit_assignment is what solving it exactly is worth.
  optimal_assignment   global minimum-deadhead assignment over the feasible
                       pairs only, solved exactly.
  profit_assignment    the same exact solver against the objective the operator
                       actually has. A truck that takes no backhaul still runs
                       empty to its domicile, so the value of a match is scored
                       against that outside option and against the load's
                       revenue -- not against zero, which is what lets it
                       decline a load worth less than sending the truck home.

Declining is a property of the OBJECTIVE, not of the exact solve. Round-2 audit
finding CLAIMS-03: the previous revision claimed profit_assignment was "the only
policy here that can" decline, and greedy_profit_pairwise refutes it in this same
file -- it applies the identical `v > 0` filter and, on the headline sweep,
declines more often (12 trucks left unmatched beside a legal unused load, against
profit_assignment's 8, over 1200 trucks). Asserted in
tests/test_policies.py::test_both_contribution_scored_policies_can_decline_a_load.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import econ
from .econ import match_value_usd
from .feasibility import is_feasible, leg
from .instance import deadhead_if_unmatched
from .models import Assignment, Load, Solution, Truck


def _assign(truck: Truck, load: Load) -> Assignment:
    lg = leg(truck, load)
    return Assignment(truck.truck_id, load.load_id, lg.deadhead_km, lg.arrive_min)


def naive_nearest(trucks: list[Truck], loads: list[Load]) -> Solution:
    """Nearest available load by distance, constraints ignored."""
    taken: set[str] = set()
    ok: list[Assignment] = []
    bad: list[Assignment] = []
    for truck in trucks:  # instance order is seeded and therefore deterministic
        pool = [ld for ld in loads if ld.load_id not in taken]
        if not pool:
            break
        best = min(pool, key=lambda ld: (leg(truck, ld).deadhead_km, ld.load_id))
        taken.add(best.load_id)
        (ok if is_feasible(truck, best) else bad).append(_assign(truck, best))
    return Solution("naive_nearest", tuple(ok), tuple(bad))


def greedy_feasible(trucks: list[Truck], loads: list[Load]) -> Solution:
    """Nearest *legal* load, taken truck by truck."""
    taken: set[str] = set()
    ok: list[Assignment] = []
    for truck in trucks:
        pool = [ld for ld in loads if ld.load_id not in taken and is_feasible(truck, ld)]
        if not pool:
            continue
        best = min(pool, key=lambda ld: (leg(truck, ld).deadhead_km, ld.load_id))
        taken.add(best.load_id)
        ok.append(_assign(truck, best))
    return Solution("greedy_feasible", tuple(ok))


#: Cost placed on an infeasible pair. Chosen so that any assignment containing
#: one is strictly worse than every assignment that avoids it; verified by
#: test_policies.py::test_forbidden_pair_never_selected_when_avoidable.
_FORBIDDEN = 1e9


def optimal_assignment(trucks: list[Truck], loads: list[Load]) -> Solution:
    """Exact minimum total deadhead over feasible pairs (Jonker-Volgenant).

    Infeasible pairs get a prohibitive cost rather than being deleted, which
    keeps the matrix rectangular and the solver total. Any pair the solver is
    forced onto is then dropped, so the returned solution contains only legal
    dispatches -- it matches fewer loads rather than proposing an illegal one.
    """
    if not trucks or not loads:
        return Solution("optimal_assignment", ())

    cost = np.full((len(trucks), len(loads)), _FORBIDDEN, dtype=float)
    for i, truck in enumerate(trucks):
        for j, load in enumerate(loads):
            if is_feasible(truck, load):
                cost[i, j] = leg(truck, load).deadhead_km

    rows, cols = linear_sum_assignment(cost)
    out = [
        _assign(trucks[i], loads[j])
        for i, j in zip(rows, cols)
        if cost[i, j] < _FORBIDDEN
    ]
    return Solution("optimal_assignment", tuple(out))


POLICIES = {
    "naive_nearest": naive_nearest,
    "greedy_feasible": greedy_feasible,
    "optimal_assignment": optimal_assignment,
}


def profit_assignment(trucks: list[Truck], loads: list[Load]) -> Solution:
    """Exact maximum-contribution assignment against the empty-run alternative.

    Fixes a real defect in `optimal_assignment`, which minimises the deadhead of
    the matches it makes while the fleet's actual bill also contains the empty
    repositioning of every truck it leaves unmatched. Minimising the first does
    not minimise the second, and on a 30-instance sweep `optimal_assignment`
    came out worse than plain greedy on 2 instances for exactly that reason.

    Here the value of pairing truck i with load j is measured against what that
    truck would otherwise do -- run empty to its domicile:

        v_ij = revenue_j - cost_per_km * (deadhead_ij + loaded_km_j)
                         + cost_per_km * reposition_i

    Pairs with v_ij <= 0 are dropped after the solve: taking that load is worth
    less than sending the truck home, so the model declines it. `greedy_profit_
    pairwise` applies the same filter to the same objective and declines too --
    round-2 audit finding CLAIMS-03 refuted the previous claim that this was the
    only policy that could. What is exclusive to the two contribution-scored
    policies is that they can legitimately match FEWER loads than a
    distance-scored one, which is why revenue and profit are both reported for
    every policy rather than matched count alone.
    """
    if not trucks or not loads:
        return Solution("profit_assignment", ())

    values = np.zeros((len(trucks), len(loads)), dtype=float)
    feasible = np.zeros((len(trucks), len(loads)), dtype=bool)
    for i, truck in enumerate(trucks):
        outside = deadhead_if_unmatched(truck) * econ.OPERATING_COST_USD_PER_KM
        for j, load in enumerate(loads):
            if is_feasible(truck, load):
                feasible[i, j] = True
                values[i, j] = match_value_usd(leg(truck, load).deadhead_km, load, outside)

    # An unprofitable or illegal pair costs exactly 0 -- the same as leaving the
    # truck unmatched -- rather than a large penalty. That matters: a big-M
    # penalty still forces the solver to fill every row of the permutation, and
    # forcing a truck that ought to go home onto some load displaces a second
    # truck from its best load. Scoring the non-options at 0 lets the solver
    # leave rows genuinely empty, which makes this an exact max-weight matching
    # with weights max(v_ij, 0). Verified against brute force in
    # tests/test_policies.py::test_profit_assignment_maximises_its_stated_objective_by_brute_force,
    # which fails on the big-M formulation.
    keep = feasible & (values > 0)
    cost = np.where(keep, -values, 0.0)

    rows, cols = linear_sum_assignment(cost)
    out = [_assign(trucks[i], loads[j]) for i, j in zip(rows, cols) if keep[i, j]]
    return Solution("profit_assignment", tuple(out))


def greedy_profit_pairwise(trucks: list[Truck], loads: list[Load]) -> Solution:
    """The profit-greedy baseline: best remaining legal pair, taken repeatedly.

    Scored on exactly the objective `profit_assignment` optimises, so the two
    differ only in HOW the objective is solved -- greedily here, exactly there.
    Round-1 audit finding D3: without this row, the exact solver's headline is
    the sum of two effects (a better objective and an exact solve) reported as
    one, and the first is available from fifteen lines of code.
    """
    if not trucks or not loads:
        return Solution("greedy_profit_pairwise", ())

    pairs: list[tuple[float, str, str, int, float]] = []
    for truck in trucks:
        outside = deadhead_if_unmatched(truck) * econ.OPERATING_COST_USD_PER_KM
        for load in loads:
            if not is_feasible(truck, load):
                continue
            lg = leg(truck, load)
            v = match_value_usd(lg.deadhead_km, load, outside)
            if v > 0:
                pairs.append((v, truck.truck_id, load.load_id, lg.arrive_min, lg.deadhead_km))

    # Deterministic: value descending, then ids ascending to break every tie.
    pairs.sort(key=lambda r: (-r[0], r[1], r[2]))
    used_t: set[str] = set()
    used_l: set[str] = set()
    out: list[Assignment] = []
    for _v, tid, lid, arrive, dh in pairs:
        if tid in used_t or lid in used_l:
            continue
        used_t.add(tid)
        used_l.add(lid)
        out.append(Assignment(tid, lid, dh, arrive))
    out.sort(key=lambda a: a.truck_id)
    return Solution("greedy_profit_pairwise", tuple(out))


POLICIES["greedy_profit_pairwise"] = greedy_profit_pairwise


POLICIES["profit_assignment"] = profit_assignment
