"""Accounting honesty and reproducibility.

These are the tests that stop the headline number from being gameable.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from roadstar.experiment import paired_comparison, run_sweep
from roadstar.instance import load_portal_instance, make_instance
from roadstar.metrics import score
from roadstar.models import Solution
from roadstar.policies import POLICIES, greedy_feasible


def test_matching_nothing_scores_worst_not_best():
    """A policy that declines all work must not win the empty-mile metric."""
    trucks, loads = make_instance(20, 25, seed=42)
    do_nothing = score(trucks, loads, Solution("do_nothing", ()))
    working = score(trucks, loads, greedy_feasible(trucks, loads))
    assert do_nothing.empty_fraction == 1.0
    assert do_nothing.empty_fraction > working.empty_fraction
    assert do_nothing.profit_usd < working.profit_usd


def test_unmatched_trucks_are_charged_repositioning_kilometres():
    trucks, loads = make_instance(15, 3, seed=11)
    m = score(trucks, loads, greedy_feasible(trucks, loads))
    assert m.n_matched < len(trucks)
    assert m.deadhead_km_reposition > 0
    assert m.deadhead_km_total == pytest.approx(
        m.deadhead_km_matched + m.deadhead_km_reposition, rel=1e-9
    )


def test_profit_equals_revenue_minus_costed_kilometres():
    from roadstar.econ import OPERATING_COST_USD_PER_KM

    trucks, loads = make_instance(20, 25, seed=7)
    for fn in POLICIES.values():
        m = score(trucks, loads, fn(trucks, loads))
        expect = m.revenue_usd - OPERATING_COST_USD_PER_KM * (m.deadhead_km_total + m.loaded_km)
        assert m.profit_usd == pytest.approx(expect, abs=0.02)


def test_empty_fraction_is_bounded():
    trucks, loads = make_instance(20, 25, seed=3)
    for fn in POLICIES.values():
        m = score(trucks, loads, fn(trucks, loads))
        assert 0.0 <= m.empty_fraction <= 1.0


def test_same_seed_gives_an_identical_instance():
    a = make_instance(25, 30, seed=99)
    b = make_instance(25, 30, seed=99)
    assert a == b


def test_different_seeds_give_different_instances():
    assert make_instance(25, 30, seed=1) != make_instance(25, 30, seed=2)


def test_sweep_is_reproducible():
    a = run_sweep(15, 20, list(range(300, 306)))
    b = run_sweep(15, 20, list(range(300, 306)))
    assert a.per_policy == b.per_policy


def test_cli_is_byte_identical_across_runs():
    cmd = [sys.executable, "-m", "roadstar.experiment",
           "--trucks", "10", "--loads", "12", "--instances", "4"]
    one = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    two = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    assert one == two
    json.loads(one)


def test_paired_comparison_reports_losses_rather_than_hiding_them():
    res = run_sweep(40, 50, list(range(1000, 1030)))
    cmp_dh = paired_comparison(res, "greedy_feasible", "optimal_assignment", "deadhead_km")
    assert cmp_dh["n_wins"] + cmp_dh["n_ties"] + cmp_dh["n_losses"] == cmp_dh["n_instances"]
    # This specific comparison is known to lose on some instances; if that ever
    # becomes zero the claim in README.md must be restated.
    assert cmp_dh["n_losses"] > 0


def test_portal_loader_refuses_to_invent_data():
    """It must raise, not silently fall back to synthetic data."""
    with pytest.raises(NotImplementedError, match="account wall"):
        load_portal_instance("anything.csv")
