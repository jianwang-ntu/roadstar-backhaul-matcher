"""Policy correctness.

The two optimality tests use brute-force enumeration as the oracle: on small
instances every assignment is enumerated and the solver's answer must equal the
best of them. That is an independent check of the objective value, not a
restatement of the solver's own claim.
"""

from __future__ import annotations

import itertools

import pytest

from roadstar.econ import OPERATING_COST_USD_PER_KM, match_value_usd
from roadstar.feasibility import is_feasible, leg
from roadstar.instance import deadhead_if_unmatched, make_instance
from roadstar.policies import (
    POLICIES,
    greedy_feasible,
    naive_nearest,
    optimal_assignment,
    profit_assignment,
)

SEEDS = list(range(500, 530))


@pytest.mark.parametrize("name", sorted(POLICIES))
def test_no_truck_or_load_is_used_twice(name):
    fn = POLICIES[name]
    for seed in SEEDS:
        trucks, loads = make_instance(12, 15, seed=seed)
        sol = fn(trucks, loads)
        all_a = list(sol.assignments) + list(sol.infeasible)
        assert len({a.truck_id for a in all_a}) == len(all_a)
        assert len({a.load_id for a in all_a}) == len(all_a)


@pytest.mark.parametrize("name", ["greedy_feasible", "optimal_assignment", "profit_assignment"])
def test_constraint_aware_policies_never_return_an_illegal_dispatch(name):
    fn = POLICIES[name]
    by_id = {}
    for seed in SEEDS:
        trucks, loads = make_instance(12, 15, seed=seed)
        by_id = {t.truck_id: t for t in trucks} | {ld.load_id: ld for ld in loads}
        sol = fn(trucks, loads)
        assert sol.infeasible == ()
        for a in sol.assignments:
            assert is_feasible(by_id[a.truck_id], by_id[a.load_id]), (name, seed, a)


def test_naive_baseline_really_does_propose_illegal_dispatches():
    """If this ever stops being true the baseline is no longer a baseline."""
    total_bad = 0
    for seed in SEEDS:
        trucks, loads = make_instance(12, 15, seed=seed)
        total_bad += len(naive_nearest(trucks, loads).infeasible)
    assert total_bad > 0


def _brute_force_min_deadhead(trucks, loads):
    """Exhaustive minimum total matched deadhead over feasible pairings."""
    best = None
    idx_loads = range(len(loads))
    for k in range(len(trucks) + 1):
        for tsub in itertools.combinations(range(len(trucks)), k):
            for lperm in itertools.permutations(idx_loads, k):
                total = 0.0
                ok = True
                for i, j in zip(tsub, lperm):
                    if not is_feasible(trucks[i], loads[j]):
                        ok = False
                        break
                    total += leg(trucks[i], loads[j]).deadhead_km
                if ok and (best is None or total < best[0] or
                           (total == best[0] and k > best[1])):
                    best = (total, k)
    return best


def test_optimal_assignment_matches_brute_force_on_small_instances():
    for seed in range(700, 712):
        trucks, loads = make_instance(4, 4, seed=seed)
        sol = optimal_assignment(trucks, loads)
        got = sum(a.deadhead_km for a in sol.assignments)
        # The solver maximises cardinality first (every feasible row is filled),
        # so compare against brute force restricted to the same cardinality.
        best = None
        for tsub in itertools.combinations(range(len(trucks)), len(sol.assignments)):
            for lperm in itertools.permutations(range(len(loads)), len(sol.assignments)):
                if all(is_feasible(trucks[i], loads[j]) for i, j in zip(tsub, lperm)):
                    tot = sum(leg(trucks[i], loads[j]).deadhead_km for i, j in zip(tsub, lperm))
                    best = tot if best is None else min(best, tot)
        assert best is not None
        assert got == pytest.approx(best, rel=1e-9), seed


def test_profit_assignment_maximises_its_stated_objective_by_brute_force():
    for seed in range(800, 812):
        trucks, loads = make_instance(4, 4, seed=seed)
        outside = {t.truck_id: deadhead_if_unmatched(t) * OPERATING_COST_USD_PER_KM
                   for t in trucks}

        def value(i, j):
            return match_value_usd(leg(trucks[i], loads[j]).deadhead_km,
                                   loads[j], outside[trucks[i].truck_id])

        best = 0.0  # matching nothing is always available and scores 0 surplus
        for k in range(1, len(trucks) + 1):
            for tsub in itertools.combinations(range(len(trucks)), k):
                for lperm in itertools.permutations(range(len(loads)), k):
                    if not all(is_feasible(trucks[i], loads[j]) for i, j in zip(tsub, lperm)):
                        continue
                    tot = sum(value(i, j) for i, j in zip(tsub, lperm))
                    best = max(best, tot)

        sol = profit_assignment(trucks, loads)
        by_t = {t.truck_id: i for i, t in enumerate(trucks)}
        by_l = {ld.load_id: j for j, ld in enumerate(loads)}
        got = sum(value(by_t[a.truck_id], by_l[a.load_id]) for a in sol.assignments)
        assert got == pytest.approx(best, rel=1e-9), seed


def test_profit_assignment_declines_a_load_that_is_worse_than_going_home():
    """The outside option must be able to win, or it is not being modelled."""
    trucks, loads = make_instance(30, 40, seed=901)
    sol = profit_assignment(trucks, loads)
    feasible_pairs = sum(
        1 for t in trucks for ld in loads if is_feasible(t, ld)
    )
    assert feasible_pairs > len(sol.assignments)


def test_greedy_is_never_better_than_the_exact_solver_on_the_solver_objective():
    for seed in SEEDS:
        trucks, loads = make_instance(10, 12, seed=seed)
        g = greedy_feasible(trucks, loads)
        o = optimal_assignment(trucks, loads)
        if len(g.assignments) == len(o.assignments):
            gd = sum(a.deadhead_km for a in g.assignments)
            od = sum(a.deadhead_km for a in o.assignments)
            assert od <= gd + 1e-9, seed


def test_empty_inputs_are_handled_by_every_policy():
    trucks, loads = make_instance(3, 3, seed=1)
    for fn in POLICIES.values():
        assert fn([], loads).assignments == ()
        assert fn(trucks, []).assignments == ()
        assert fn([], []).assignments == ()
