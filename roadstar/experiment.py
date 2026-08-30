"""Run every policy over a seeded sweep of instances and report the results.

Deterministic by construction: the seeds are enumerated, not drawn, so two runs
of the same command produce byte-identical JSON.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass

from .econ import OPERATING_COST_USD_PER_KM
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
        "best_instance_rel_improvement_pct": round(max(rel) * 100, 3),
        "worst_instance_rel_improvement_pct": round(min(rel) * 100, 3),
        "n_wins": sum(1 for d in improvements if d > 0),
        "n_ties": sum(1 for d in improvements if d == 0),
        "n_losses": sum(1 for d in improvements if d < 0),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="RoadStar backhaul sweep (synthetic instances)")
    ap.add_argument("--trucks", type=int, default=40)
    ap.add_argument("--loads", type=int, default=50)
    ap.add_argument("--instances", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args(argv)

    seeds = list(range(args.seed0, args.seed0 + args.instances))
    res = run_sweep(args.trucks, args.loads, seeds)
    payload = {
        "data_provenance": "SYNTHETIC instances (roadstar.instance.make_instance) over "
        "real public corridor coordinates (roadstar.geo.CORRIDOR). No organiser "
        "portal data was used; see plan.md R-2.",
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
            "operating_cost_usd_per_km": OPERATING_COST_USD_PER_KM,
            "note": "stated modelling assumption; every profit figure scales with it",
        },
        "comparisons": [
            paired_comparison(res, "greedy_feasible", "optimal_assignment", "deadhead_km"),
            paired_comparison(res, "greedy_feasible", "profit_assignment", "deadhead_km"),
            paired_comparison(res, "greedy_feasible", "profit_assignment", "profit_usd"),
            paired_comparison(res, "optimal_assignment", "profit_assignment", "profit_usd"),
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
