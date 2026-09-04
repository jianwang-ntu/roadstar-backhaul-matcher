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
from roadstar.models import Assignment, Solution
from roadstar.policies import (
    POLICIES,
    greedy_feasible,
    greedy_profit_pairwise,
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


def _brute_force_max_cardinality(trucks, loads) -> int:
    """Largest number of loads any legal pairing can cover. Oracle, not solver."""
    best = 0
    for k in range(len(trucks), 0, -1):
        if k <= best:
            break
        for tsub in itertools.combinations(range(len(trucks)), k):
            for lperm in itertools.permutations(range(len(loads)), k):
                if all(is_feasible(trucks[i], loads[j]) for i, j in zip(tsub, lperm)):
                    best = max(best, k)
                    break
            if best == k:
                break
    return best


def test_optimal_assignment_matches_brute_force_on_small_instances():
    """Cardinality FIRST, then cost at that cardinality.

    Round-1 audit finding D5: the previous version enumerated only over
    combinations of size len(sol.assignments) -- the solver supplied the
    cardinality the oracle then checked against, so a mutant returning the
    single cheapest legal pair passed the whole suite while the sweep collapsed
    to mean_matched 1.0. The oracle now derives the cardinality itself.
    """
    for seed in range(700, 712):
        trucks, loads = make_instance(4, 4, seed=seed)
        sol = optimal_assignment(trucks, loads)
        got = sum(a.deadhead_km for a in sol.assignments)

        max_card = _brute_force_max_cardinality(trucks, loads)
        assert len(sol.assignments) == max_card, (
            f"seed {seed}: matched {len(sol.assignments)}, oracle says {max_card}"
        )

        best = None
        for tsub in itertools.combinations(range(len(trucks)), max_card):
            for lperm in itertools.permutations(range(len(loads)), max_card):
                if all(is_feasible(trucks[i], loads[j]) for i, j in zip(tsub, lperm)):
                    tot = sum(leg(trucks[i], loads[j]).deadhead_km for i, j in zip(tsub, lperm))
                    best = tot if best is None else min(best, tot)
        assert best is not None
        assert got == pytest.approx(best, rel=1e-9), seed


def test_profit_assignment_maximises_its_stated_objective_by_brute_force():
    """Round-1 audit finding D6: the range this test runs over has to be one
    where the rejected big-M formulation actually loses, or "the oracle catches
    it" is untested. That is a property of the FEASIBILITY RULE, not a constant:
    when round-2 finding DOMAIN-01 was fixed and C3 started charging the shipper
    wait, 4x4 over seeds 800-829 stopped discriminating -- big-M matched the
    shipped solver on all 30. Re-measured on the rule that now ships, 5x5 over
    the same seeds discriminates at seeds 825 and 827, so that is the
    configuration used here and in
    tests/test_policies.py::test_big_m_formulation_is_rejected_by_the_oracle,
    which executes the rejected formulation and asserts the oracle rejects it.
    """
    for seed in range(800, 830):
        trucks, loads = make_instance(5, 5, seed=seed)
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


def _profit_assignment_big_m(trucks, loads):
    """The formulation this project REJECTED, kept executable so the claim that
    the oracle catches it is a measured fact rather than a README assertion."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if not trucks or not loads:
        return Solution("profit_assignment_big_m", ())
    values = np.zeros((len(trucks), len(loads)), dtype=float)
    feas = np.zeros((len(trucks), len(loads)), dtype=bool)
    for i, t in enumerate(trucks):
        outside = deadhead_if_unmatched(t) * OPERATING_COST_USD_PER_KM
        for j, ld in enumerate(loads):
            if is_feasible(t, ld):
                feas[i, j] = True
                values[i, j] = match_value_usd(leg(t, ld).deadhead_km, ld, outside)
    keep = feas & (values > 0)
    cost = np.where(keep, -values, 1e9)  # <-- the defect
    rows, cols = linear_sum_assignment(cost)
    out = [
        Assignment(trucks[i].truck_id, loads[j].load_id,
                   leg(trucks[i], loads[j]).deadhead_km, leg(trucks[i], loads[j]).arrive_min)
        for i, j in zip(rows, cols) if keep[i, j]
    ]
    return Solution("profit_assignment_big_m", tuple(out))


def test_big_m_formulation_is_rejected_by_the_oracle():
    """The shipped formulation beats the rejected one on at least one seed in
    the range the oracle test now covers, and never loses to it.

    Same configuration as the brute-force oracle above, and for the same reason:
    at 4x4 under the corrected C3 the two formulations agree on every seed in
    this range, so 4x4 would make this assertion vacuous. Measured seeds where
    the shipped formulation is strictly better at 5x5: 825 and 827."""
    strictly_better_somewhere = []
    for seed in range(800, 830):
        trucks, loads = make_instance(5, 5, seed=seed)
        outside = {t.truck_id: deadhead_if_unmatched(t) * OPERATING_COST_USD_PER_KM
                   for t in trucks}
        by_t = {t.truck_id: i for i, t in enumerate(trucks)}
        by_l = {ld.load_id: j for j, ld in enumerate(loads)}

        def total(sol):
            return sum(
                match_value_usd(leg(trucks[by_t[a.truck_id]], loads[by_l[a.load_id]]).deadhead_km,
                                loads[by_l[a.load_id]], outside[a.truck_id])
                for a in sol.assignments
            )

        shipped = total(profit_assignment(trucks, loads))
        rejected = total(_profit_assignment_big_m(trucks, loads))
        assert shipped >= rejected - 1e-9, seed
        if shipped > rejected + 1e-9:
            strictly_better_somewhere.append(seed)
    assert strictly_better_somewhere == [825, 827], (
        "the discriminating seeds moved. The README states which seeds separate "
        f"the two formulations; measured now: {strictly_better_somewhere}"
    )


def test_greedy_profit_pairwise_never_beats_the_exact_solver_on_their_shared_objective():
    """D3's new baseline optimises the SAME objective, heuristically. If it ever
    beat the exact solver, the exact solver would not be exact."""
    for seed in range(760, 772):
        trucks, loads = make_instance(6, 6, seed=seed)
        outside = {t.truck_id: deadhead_if_unmatched(t) * OPERATING_COST_USD_PER_KM
                   for t in trucks}
        by_t = {t.truck_id: i for i, t in enumerate(trucks)}
        by_l = {ld.load_id: j for j, ld in enumerate(loads)}

        def total(sol):
            return sum(
                match_value_usd(leg(trucks[by_t[a.truck_id]], loads[by_l[a.load_id]]).deadhead_km,
                                loads[by_l[a.load_id]], outside[a.truck_id])
                for a in sol.assignments
            )

        assert total(greedy_profit_pairwise(trucks, loads)) <= total(profit_assignment(trucks, loads)) + 1e-9, seed


def test_both_contribution_scored_policies_can_decline_a_load():
    """Round-2 audit finding CLAIMS-03.

    The previous revision's README said `profit_assignment` was "the only policy
    here that can" decline a load worth less than the run home. It is not: the
    profit-greedy baseline applies the identical `v > 0` filter and declines
    MORE. Declining follows from the objective, not from the exact solve, and
    the claim went unasserted by any test, which is how it survived a revision.

    Counted the way the README states it: trucks a policy left unmatched while
    at least one legal, still-unused load was available to them.
    """
    from roadstar.instance import make_instance as mk

    declined = {name: 0 for name in POLICIES}
    n_trucks = 0
    for seed in range(1000, 1030):
        trucks, loads = mk(40, 50, seed=seed)
        n_trucks += len(trucks)
        for name, fn in POLICIES.items():
            sol = fn(trucks, loads)
            used_t = {a.truck_id for a in sol.assignments} | {a.truck_id for a in sol.infeasible}
            used_l = {a.load_id for a in sol.assignments} | {a.load_id for a in sol.infeasible}
            declined[name] += sum(
                1 for t in trucks if t.truck_id not in used_t
                and any(is_feasible(t, ld) for ld in loads if ld.load_id not in used_l)
            )

    assert n_trucks == 1200
    assert declined["greedy_profit_pairwise"] == 12
    assert declined["profit_assignment"] == 8
    assert declined["greedy_profit_pairwise"] > declined["profit_assignment"], (
        "the exclusivity claim CLAIMS-03 refuted would be back"
    )
    assert declined["greedy_feasible"] == 0 and declined["optimal_assignment"] == 0
