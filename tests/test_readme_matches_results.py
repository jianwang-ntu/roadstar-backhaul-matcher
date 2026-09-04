"""Every number in README.md must equal what the code actually produced.

A README that drifts from its own artifacts is the defect class that has sunk
candidates in this pipeline before, and round-2 audit finding CLAIMS-04 found
that the previous version of this file left the drift possible where it mattered
most: it checked four of five policy rows, five of eight columns, none of the
symmetric-boundary figures and none of the 100x120 paragraph. The auditor
demonstrated it by fabricating a profit-baseline row, fabricating both
symmetric-boundary columns and fabricating the whole 100x120 paragraph -- all
three passed CI.

The rule this file now enforces: if a number appears in README.md, either it is
compared here against a committed artifact, or it is recomputed here from the
code. There is no third category.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "sweep_40x50.json"
RESULTS_BIG = ROOT / "results" / "sweep_100x120.json"
README = ROOT / "README.md"

POLICIES_IN_TABLE = [
    "naive_nearest",
    "greedy_feasible",
    "greedy_profit_pairwise",
    "optimal_assignment",
    "profit_assignment",
]


@pytest.fixture(scope="module")
def data():
    if not RESULTS.exists():
        pytest.skip("run `make sweep` first")
    return json.loads(RESULTS.read_text())


@pytest.fixture(scope="module")
def data_big():
    if not RESULTS_BIG.exists():
        pytest.skip("run `make sweep` first")
    return json.loads(RESULTS_BIG.read_text())


@pytest.fixture(scope="module")
def readme():
    return README.read_text()


def _num(cell: str) -> float:
    """One README table cell as a number. Handles the typographic minus, the
    thousands separator, the currency mark, the percent sign and bold markers."""
    c = (cell.strip().strip("*").replace("−", "-")
         .replace(",", "").replace("$", "").rstrip("%").strip())
    return float(c)


def _row(readme_text: str, policy: str) -> list[str]:
    """The results-table row for `policy`.

    Anchored on the eight-column shape, so a comparison-table line or a prose
    mention can never be mistaken for it -- and so DELETING the two
    symmetric-boundary columns fails here instead of silently reducing coverage,
    which is half of what CLAIMS-04 was about.
    """
    want = f"`{policy}`"
    for line in readme_text.splitlines():
        s = line.strip()
        if not s.startswith("|") or want not in s:
            continue
        cells = [c.strip().strip("*") for c in s.strip("|").split("|")]
        if len(cells) != 8:
            continue
        if not cells[0].startswith(want):
            continue
        return cells
    raise AssertionError(f"no eight-column README results row for {policy}")


@pytest.mark.parametrize("policy", POLICIES_IN_TABLE)
def test_policy_table_matches_results(data, readme, policy):
    """All five rows, all seven numeric columns -- including the two
    symmetric-boundary ones the previous version of this test never read."""
    cells = _row(readme, policy)
    p = data["per_policy"][policy]
    assert _num(cells[1]) == pytest.approx(p["mean_deadhead_km"], abs=0.1), "deadhead"
    assert _num(cells[2]) == pytest.approx(
        p["mean_empty_fraction"] * 100, abs=0.02), "empty fraction"
    assert _num(cells[3]) == pytest.approx(p["mean_profit_usd"], abs=1.0), "profit"
    assert _num(cells[4]) == pytest.approx(p["mean_matched"], abs=0.05), "matched"
    assert int(_num(cells[5])) == p["total_infeasible_proposed"], "illegal proposals"
    assert _num(cells[6]) == pytest.approx(
        p["mean_empty_fraction_incl_return_leg"] * 100, abs=0.02), "empty fraction incl return"
    assert _num(cells[7]) == pytest.approx(
        p["mean_profit_usd_incl_return_leg"], abs=1.0), "profit incl return"


def test_every_policy_in_the_results_json_has_a_row_in_the_readme(data, readme):
    """Coverage, asserted rather than assumed: a policy cannot be added to the
    sweep and left out of the table it would have made look worse."""
    assert set(data["per_policy"]) == set(POLICIES_IN_TABLE)
    for policy in data["per_policy"]:
        _row(readme, policy)


def test_paired_comparison_percentages_match_results(data, readme):
    by_pair = {(c["treatment"], c["baseline"], c["metric"]): c for c in data["comparisons"]}
    checked = set()
    for line in readme.splitlines():
        m = re.match(
            r"\|\s*`?(\w+)`?\s*vs\s*`?(\w+)`?\s*\|\s*(profit|deadhead)\s*\|\s*"
            r"\*{0,2}([+\-−][\d.]+)%\*{0,2}\s*\|"      # mean
            r"\s*\*{0,2}([+\-−][\d.]+)%\*{0,2}\s*\|"   # median
            r"[^|]*\|"                                       # sd
            r"\s*\*{0,2}([+\-−][\d.]+)%\*{0,2}\s*\|"   # ratio of means
            r"\s*(\d+)\s*/\s*\*{0,2}(\d+)\*{0,2}\s*/\s*\*{0,2}(\d+)\*{0,2}\s*\|"
            r"\s*\*{0,2}([+\-−][\d.]+)%\*{0,2}\s*\|",  # worst instance
            line.replace("`", "").strip(),
        )
        if not m:
            continue
        treat, base, metric, pct, med, rom, w, t, l, worst = m.groups()
        key = (treat, base, "profit_usd" if metric == "profit" else "deadhead_km")
        assert key in by_pair, key
        c = by_pair[key]
        f = lambda v: float(v.replace("−", "-"))
        assert f(pct) == pytest.approx(c["mean_rel_improvement_pct"], abs=0.02), key
        assert f(med) == pytest.approx(c["median_rel_improvement_pct"], abs=0.02), key
        assert f(rom) == pytest.approx(
            c["ratio_of_means_rel_improvement_pct"], abs=0.02), key
        assert f(worst) == pytest.approx(
            c["worst_instance_rel_improvement_pct"], abs=0.02), key
        assert (int(w), int(t), int(l)) == (c["n_wins"], c["n_ties"], c["n_losses"]), key
        checked.add(key)
    assert checked == set(by_pair), (
        f"comparison rows in the JSON but not checked in the README: "
        f"{set(by_pair) - checked}"
    )


def _flat(text: str) -> str:
    """Collapse the markdown's hard line wrapping and emphasis markers so prose
    assertions are about the sentence, not about where the paragraph happened to
    break or which words were bolded."""
    return re.sub(r"\s+", " ", text.replace("*", ""))


def test_the_100x120_paragraph_matches_its_own_results_file(data_big, readme):
    """CLAIMS-04: the auditor fabricated this entire paragraph and CI passed it.

    It is a second sweep with its own committed JSON and nothing was reading it.
    """
    flat = _flat(readme)
    m = re.search(
        r"profit_assignment` reaches ([\d.]+)% empty fraction and \$([\d,]+) mean "
        r"profit, \+([\d.]+)% over `greedy_profit_pairwise` \((\d+)/(\d+)/(\d+)\) and "
        r"\+([\d.]+)% over `greedy_feasible` \((\d+)/(\d+)/(\d+)\)",
        flat,
    )
    assert m, "the 100x120 paragraph is missing or has changed shape"
    ef, profit, vs_gpp, w1, t1, l1, vs_gf, w2, t2, l2 = m.groups()

    p = data_big["per_policy"]["profit_assignment"]
    assert float(ef) == pytest.approx(p["mean_empty_fraction"] * 100, abs=0.02)
    assert float(profit.replace(",", "")) == pytest.approx(p["mean_profit_usd"], abs=1.0)

    by_pair = {(c["treatment"], c["baseline"], c["metric"]): c
               for c in data_big["comparisons"]}
    for pct, wins, base in (
        (vs_gpp, (w1, t1, l1), "greedy_profit_pairwise"),
        (vs_gf, (w2, t2, l2), "greedy_feasible"),
    ):
        c = by_pair[("profit_assignment", base, "profit_usd")]
        assert float(pct) == pytest.approx(c["mean_rel_improvement_pct"], abs=0.02), base
        assert tuple(int(x) for x in wins) == (c["n_wins"], c["n_ties"], c["n_losses"]), base

    assert data_big["config"]["instances"] == 10
    assert (data_big["config"]["trucks"], data_big["config"]["loads"]) == (100, 120)


def test_the_denominator_decomposition_is_recomputed_not_asserted(readme):
    """Round-2 findings CLAIMS-05 and DOMAIN-05: the README used to attribute the
    empty-fraction improvement to matching more trucks. Most of it is longer
    loads. The claim is now a measurement, so it is measured here."""
    from roadstar.instance import make_instance
    from roadstar.metrics import score
    from roadstar.policies import POLICIES

    agg = {}
    for name in ("greedy_feasible", "profit_assignment"):
        ms, lengths = [], []
        for seed in range(1000, 1030):
            trucks, loads = make_instance(40, 50, seed=seed)
            by_l = {ld.load_id: ld for ld in loads}
            sol = POLICIES[name](trucks, loads)
            ms.append(score(trucks, loads, sol))
            lengths += [by_l[a.load_id].loaded_km for a in sol.assignments]
        agg[name] = dict(
            dh=statistics.fmean(m.deadhead_km_total for m in ms),
            loaded=statistics.fmean(m.loaded_km for m in ms),
            matched=statistics.fmean(m.n_matched for m in ms),
            ef=statistics.fmean(m.empty_fraction for m in ms),
            length=statistics.fmean(lengths),
        )
    g, p = agg["greedy_feasible"], agg["profit_assignment"]
    ef_if_denominator_frozen = p["dh"] / (p["dh"] + g["loaded"])
    total_pp = (g["ef"] - p["ef"]) * 100
    numerator_pp = (g["ef"] - ef_if_denominator_frozen) * 100
    denominator_pp = total_pp - numerator_pp

    flat = _flat(readme)
    assert f"empty fraction falls {total_pp:.2f} points" in flat
    assert f"{numerator_pp:.2f} points come from driving fewer empty kilometres" in flat
    assert f"{denominator_pp:.2f} points — {100 * denominator_pp / total_pp:.1f}%" in flat
    assert f"denominator grows {100 * (p['loaded'] / g['loaded'] - 1):.2f}%" in flat
    assert f"matched count grows only {100 * (p['matched'] / g['matched'] - 1):.2f}%" in flat
    assert f"from {g['length']:.1f} km to {p['length']:.1f} km" in flat
    assert f"from {g['dh']:.1f} to {p['dh']:.1f}" in flat


def test_readme_declares_the_data_as_synthetic(readme):
    flat = _flat(readme)
    assert "computed on synthetic instances" in flat
    assert "No portal data has been read" in flat
    assert "raises" in flat and "falling back to synthetic data" in flat


def test_readme_declares_unmet_criteria(readme):
    flat = _flat(readme)
    assert "it is unmet" in flat
    assert "No demo video or slide deck yet" in flat
    assert "criterion 4 (provided data and APIs, 15% of the score) is unmet" in flat


def test_readme_states_the_accounting_boundary_and_its_direction(readme):
    """D4: the primary figures are one side of a truncation. The README must say
    which side, and must not omit that the symmetric view reverses the ranking."""
    flat = _flat(readme)
    assert "lower bounds" in flat and "upper bounds" in flat
    assert "`profit_assignment` is not the best policy" in flat


def test_readme_does_not_lead_on_the_skewed_ratio(readme):
    """The three-figure profit percentages are means of per-instance ratios over
    a near-zero baseline. They are reported, and they are also disarmed."""
    flat = _flat(readme)
    assert "Do not quote the three-figure profit percentages" in flat
    assert "+1527%" in flat
    assert "$3,439 → $6,172 of mean profit per instance" in flat


def test_readme_separates_the_objective_change_from_the_exact_solve(readme):
    """D3: the headline against the distance baseline must not stand alone."""
    flat = _flat(readme)
    assert "+18.207%" in flat and "+109.046%" in flat and "+151.993%" in flat


def test_readme_carries_the_hos_correction_and_its_cost(readme):
    """DOMAIN-01/CLAIMS-02. The severity table is regenerated by
    tests/test_hos_binds_the_whole_duty_day.py; this asserts the README prints
    it, and that the withdrawn figure is described as withdrawn."""
    flat = _flat(readme)
    assert "46.29%" in flat and "29.38 h" in flat
    assert "34.58%" in flat and "21.88 h" in flat
    assert "14.00 h" in flat
    assert "184 of `profit_assignment`'s 1051 accepted dispatches (17.51%)" in flat
    assert 'reported the D1 severity as "14.0%"' in flat
    assert "does not reproduce under any aggregation and has been withdrawn" in flat


def test_readme_does_not_repeat_the_refuted_exclusivity_claim(readme):
    """CLAIMS-03. Both halves: the false sentence must be gone, and the measured
    replacement must be present.

    The phrase itself is still in the document -- quoted inside the sentence that
    withdraws it -- so asserting its absence would be a scan that the fix's own
    explanation defeats. What must be absent is the phrase used as an ASSERTION:
    the original sentence, standing on its own after the objective is described.
    """
    flat = _flat(readme)
    assert "home. It is the only policy here that can." not in flat, (
        "the refuted CLAIMS-03 sentence is being asserted again"
    )
    for m in re.finditer(r"the only policy here that can", flat):
        window = flat[max(0, m.start() - 200):m.end() + 200]
        assert "was false" in window or "previous revision claimed" in window, (
            "the phrase appears outside the sentence that withdraws it"
        )
    assert 'claimed this policy was "the only policy here that can", and that was false' in flat
    assert "declines more" in flat
    assert "against `profit_assignment`'s 8, over 1200 trucks" in flat


def test_readme_test_count_matches_the_suite(readme):
    """The README states a test count; keep it honest automatically.

    Counted by asking pytest to collect (not run) the suite, so parametrised
    cases are counted the way the reported figure counts them.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
        capture_output=True, text=True, cwd=ROOT,
    )
    m = re.search(r"(\d+) tests? collected", proc.stdout)
    assert m, proc.stdout[-500:]
    collected = int(m.group(1))

    # Two sites DECLARE the count: the `make test` block and the layout block.
    declared = {int(n) for n in re.findall(r"#\s*(\d+) tests\b", readme)}
    declared |= {int(n) for n in re.findall(r"tests/\s+(\d+) tests\b", readme)}
    assert declared, "the README no longer declares a test count"
    assert declared == {collected}, f"README declares {declared}, suite collects {collected}"

    # Every OTHER count in the document must be one the audit section is quoting
    # about an earlier revision -- otherwise a stale figure could sit in the prose
    # while the two declaration sites stayed correct.
    flat = _flat(readme)
    for m in re.finditer(r"(\d+) tests\b", flat):
        n = int(m.group(1))
        if n == collected:
            continue
        window = flat[max(0, m.start() - 160):m.end() + 160]
        assert "previous revision" in window or "Under the previous" in window, (
            f"README mentions '{n} tests' outside a statement about an earlier "
            f"revision; suite collects {collected}"
        )
