"""Run every policy over a seeded sweep of instances and report the results.

Deterministic by construction: the seeds are enumerated, not drawn, so two runs
of the same command produce byte-identical JSON.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass

from . import econ
from .instance import make_instance
from .metrics import Metrics, score
from .policies import POLICIES


@dataclass(frozen=True, slots=True)
class SweepResult:
    n_instances: int
    n_trucks: int
    n_loads: int
    seeds: tuple[int, ...]
    per_policy: dict[str, dict]


def run_sweep(n_trucks: int, n_loads: int, seeds: list[int]) -> SweepResult:
    rows: dict[str, list[Metrics]] = {name: [] for name in POLICIES}
    for seed in seeds:
        trucks, loads = make_instance(n_trucks, n_loads, seed=seed)
        for name, fn in POLICIES.items():
            rows[name].append(score(trucks, loads, fn(trucks, loads)))

    per_policy: dict[str, dict] = {}
    for name, ms in rows.items():
        per_policy[name] = {
            "mean_empty_fraction": round(statistics.fmean(m.empty_fraction for m in ms), 6),
            "mean_deadhead_km": round(statistics.fmean(m.deadhead_km_total for m in ms), 3),
            "mean_matched": round(statistics.fmean(m.n_matched for m in ms), 3),
            "mean_revenue_usd": round(statistics.fmean(m.revenue_usd for m in ms), 2),
            "total_infeasible_proposed": sum(m.n_infeasible_proposed for m in ms),
            "mean_profit_usd": round(statistics.fmean(m.profit_usd for m in ms), 2),
            "mean_empty_fraction_incl_return_leg": round(
                statistics.fmean(m.empty_fraction_incl_return for m in ms), 6),
            "mean_profit_usd_incl_return_leg": round(
                statistics.fmean(m.profit_usd_incl_return for m in ms), 2),
            "per_instance_empty_fraction": [m.empty_fraction for m in ms],
            "per_instance_deadhead_km": [m.deadhead_km_total for m in ms],
            "per_instance_profit_usd": [m.profit_usd for m in ms],
        }

    return SweepResult(
        n_instances=len(seeds),
        n_trucks=n_trucks,
        n_loads=n_loads,
        seeds=tuple(seeds),
        per_policy=per_policy,
    )


def paired_comparison(
    res: SweepResult, baseline: str, treatment: str, metric: str = "deadhead_km"
) -> dict:
    """Per-instance paired comparison of treatment against baseline.

    Paired because both policies see the identical instance -- that is the only
    comparison this sweep licenses. `higher_is_better` flips the sign so
    "improvement" always means better, and losses are always reported: a
    treatment that wins on average while losing on some instances says so here
    rather than in a footnote.
    """
    higher_is_better = metric == "profit_usd"
    key = f"per_instance_{metric}"
    b = res.per_policy[baseline][key]
    t = res.per_policy[treatment][key]

    sign = 1.0 if higher_is_better else -1.0
    improvements = [sign * (ti - bi) for bi, ti in zip(b, t)]
    rel = [sign * (ti - bi) / abs(bi) for bi, ti in zip(b, t) if bi != 0]

    return {
        "metric": metric,
        "higher_is_better": higher_is_better,
        "baseline": baseline,
        "treatment": treatment,
        "n_instances": len(improvements),
        "mean_baseline": round(statistics.fmean(b), 3),
        "mean_treatment": round(statistics.fmean(t), 3),
        "mean_abs_improvement": round(statistics.fmean(improvements), 3),
        "mean_rel_improvement_pct": round(statistics.fmean(rel) * 100, 3),
        "mean_rel_improvement_pct_is": "mean of per-instance ratios, not a ratio of means",
        "median_rel_improvement_pct": round(statistics.median(rel) * 100, 3),
        "stdev_rel_improvement_pct": (
            round(statistics.stdev(rel) * 100, 3) if len(rel) > 1 else None),
        "stdev_abs_improvement": (
            round(statistics.stdev(improvements), 3) if len(improvements) > 1 else None),
        "ratio_of_means_rel_improvement_pct": (
            round(sign * (statistics.fmean(t) - statistics.fmean(b)) / abs(statistics.fmean(b)) * 100, 3)
            if statistics.fmean(b) != 0 else None),
        "best_instance_rel_improvement_pct": round(max(rel) * 100, 3),
        "worst_instance_rel_improvement_pct": round(min(rel) * 100, 3),
        "n_wins": sum(1 for d in improvements if d > 0),
        "n_ties": sum(1 for d in improvements if d == 0),
        "n_losses": sum(1 for d in improvements if d < 0),
    }


def _print_dispatch(n_trucks: int, n_loads: int, seed: int) -> int:
    """The product surface a dispatcher would actually read: who takes what."""
    from .feasibility import leg
    from .instance import deadhead_if_unmatched

    trucks, loads = make_instance(n_trucks, n_loads, seed=seed)
    by_load = {ld.load_id: ld for ld in loads}
    by_truck = {t.truck_id: t for t in trucks}
    sol = POLICIES["profit_assignment"](trucks, loads)
    print(f"# profit_assignment dispatch, synthetic instance seed={seed} "
          f"({n_trucks} trucks x {n_loads} loads)")
    print(f"{'truck':>6} {'at':<14} {'load':>5} {'origin':<14} {'dest':<14} "
          f"{'deadhead_km':>11} {'arrive_min':>10} {'contribution_usd':>16}")
    matched = set()
    for a in sorted(sol.assignments, key=lambda x: x.truck_id):
        t, ld = by_truck[a.truck_id], by_load[a.load_id]
        outside = deadhead_if_unmatched(t) * econ.OPERATING_COST_USD_PER_KM
        v = ld.revenue_usd - econ.OPERATING_COST_USD_PER_KM * (a.deadhead_km + ld.loaded_km) + outside
        matched.add(a.truck_id)
        print(f"{a.truck_id:>6} {t.at_name:<14} {a.load_id:>5} {ld.origin_name:<14} "
              f"{ld.dest_name:<14} {a.deadhead_km:>11.1f} {a.arrive_min:>10d} {v:>16.2f}")
    for t in trucks:
        if t.truck_id not in matched:
            print(f"{t.truck_id:>6} {t.at_name:<14} {'--':>5} {'(no backhaul worth taking)':<29} "
                  f"{deadhead_if_unmatched(t):>11.1f} {'':>10} {'':>16}")
    print(f"# matched {len(matched)} of {len(trucks)} trucks")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="RoadStar backhaul sweep (synthetic instances)")
    ap.add_argument("--trucks", type=int, default=40)
    ap.add_argument("--loads", type=int, default=50)
    ap.add_argument("--instances", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--out", type=str, default="")
    ap.add_argument("--cost-per-km", type=float, default=econ.OPERATING_COST_USD_PER_KM,
                    help="override the stated operating-cost assumption (sensitivity)")
    ap.add_argument("--dispatch", action="store_true",
                    help="print the actual truck->load dispatch list for seed0")
    args = ap.parse_args(argv)

    econ.OPERATING_COST_USD_PER_KM = args.cost_per_km

    if args.dispatch:
        return _print_dispatch(args.trucks, args.loads, args.seed0)

    seeds = list(range(args.seed0, args.seed0 + args.instances))
    res = run_sweep(args.trucks, args.loads, seeds)
    payload = {
        "data_provenance": "SYNTHETIC instances (roadstar.instance.make_instance) over "
        "real public corridor coordinates (roadstar.geo.CORRIDOR). No organiser "
        "portal data was used; the portal loader raises rather than falling back "
        "(see README, 'Read this before any number below').",
        "accounting_boundary": "Primary figures charge the empty repositioning leg TO "
        "the pickup, plus the run home of every UNMATCHED truck. The post-delivery "
        "run home of a MATCHED truck lies outside the single-period boundary, so the "
        "primary empty fractions are LOWER BOUNDS and the primary profits UPPER "
        "BOUNDS. The fully symmetric figures are reported alongside as "
        "*_incl_return_leg and they reverse the headline; see README.",
        "config": {
            "trucks": args.trucks,
            "loads": args.loads,
            "instances": args.instances,
            "seeds": [seeds[0], seeds[-1]],
        },
        "per_policy": {
            k: {kk: vv for kk, vv in v.items() if not kk.startswith("per_instance")}
            for k, v in res.per_policy.items()
        },
        "cost_model": {
            "operating_cost_usd_per_km": econ.OPERATING_COST_USD_PER_KM,
            "note": "stated modelling assumption. Profit is revenue MINUS cost*km, so "
                    "it does not merely scale with this constant -- the constant moves "
                    "profit and the relative comparisons non-proportionally. Re-run with "
                    "--cost-per-km to measure that; D7.",
        },
        "comparisons": [
            paired_comparison(res, "greedy_feasible", "optimal_assignment", "deadhead_km"),
            paired_comparison(res, "greedy_feasible", "profit_assignment", "deadhead_km"),
            paired_comparison(res, "greedy_feasible", "profit_assignment", "profit_usd"),
            paired_comparison(res, "optimal_assignment", "profit_assignment", "profit_usd"),
            # D3: the objective change and the exact solve, separated.
            paired_comparison(res, "greedy_feasible", "greedy_profit_pairwise", "profit_usd"),
            paired_comparison(res, "greedy_profit_pairwise", "profit_assignment", "profit_usd"),
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
