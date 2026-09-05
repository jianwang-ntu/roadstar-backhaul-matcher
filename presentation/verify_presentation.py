#!/usr/bin/env python3
"""Adversarial verifier for the RoadStar live-presentation deck.

House rule for this workspace: an artifact is not READY because it exists, it is
READY because a check that can go red says it is right. This file is that check
for submission/presentation/.

What it enforces
----------------
A. STRUCTURE   every slide declares its seconds and its criteria; every slide
               has exactly one script block and vice versa.
B. TIMING      the seconds sum into the organiser's 10-15 minute band, and each
               block's word count implies a speaking rate inside 100-165 wpm.
               A slide cannot be given 30 s and 400 words.
C. FIGURES     every figure the deck states is recomputed or re-read from a
               primary artifact -- results JSON, the HOS test, the audit files,
               the demo artifact record, git, the rubric, the running suite --
               and must match to the digit.
D. UNSOURCED   the two-sided half of C. Every claimed literal is deleted from
               the deck text, and any number-shaped token that SURVIVES must be
               on an allow-list that states why. A presence check that can only
               ever pass is not a check; this is the half that can fail on a
               figure nobody remembered to claim.
E. DISCLOSE    the statements this entry must not drop -- synthetic data, C4
               unmet, the boundary that reverses the headline, the open audit
               findings, the skew warning -- are present.
F. FORBID      the claims this entry must never make -- a hosted video, portal
               data, regulatory compliance, the skewed headline percentage,
               an attendance promise -- are absent.
G. RUBRIC      the criteria tags cover C1..C5 and the weights quoted in the deck
               match demo/judging_rubric.json.
H. RENDERED    slides.html is the CURRENT slides.md rendered -- it records the
               source digest and this refuses a stale one. A rendered deck that
               has drifted from the checked source is worse than none, because
               it is the copy that would actually be shown.

Then it runs its own negative controls: eleven mutations of the deck, each of
which must turn a NAMED check red, plus a pristine control that must stay green.
A verifier that has never been observed to fail is a decoration.

Usage
    python3 verify_presentation.py                 # verify + negative controls
    python3 verify_presentation.py --no-controls   # verify only (used BY the controls)
    python3 verify_presentation.py --dir D --project P
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- fatal helper

FAILURES: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    if not ok:
        FAILURES.append((name, detail))
    return ok


# ------------------------------------------------------------------ normalise

def flat(text: str) -> str:
    """Typographic characters folded to ASCII so a claim cannot pass or fail on
    an en-dash. Whitespace collapsed so a line wrap cannot hide a literal."""
    for a, b in (
        ("−", "-"), ("–", "-"), ("—", "-"), ("‘", "'"),
        ("’", "'"), ("“", '"'), ("”", '"'), ("→", "->"),
        ("×", "x"), (" ", " "),
    ):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text)


# ------------------------------------------------------------------- resolvers

class Sources:
    """Every number in the deck resolves through one of these. Nothing resolves
    through another prose document -- writeup.md and README.md are downstream of
    the same artifacts and would only launder an error."""

    def __init__(self, project: pathlib.Path, workspace: pathlib.Path,
                 deck_dir: pathlib.Path):
        self.project = project
        self.workspace = workspace
        self.deck_dir = deck_dir
        self._cache: dict = {}

    def _j(self, rel: str):
        if rel not in self._cache:
            self._cache[rel] = json.loads((self.project / rel).read_text())
        return self._cache[rel]

    def sweep40(self):
        return self._j("results/sweep_40x50.json")

    def sweep100(self):
        return self._j("results/sweep_100x120.json")

    def cmp40(self, treatment: str, baseline: str, metric: str) -> dict:
        for c in self.sweep40()["comparisons"]:
            if (c["treatment"], c["baseline"], c["metric"]) == (treatment, baseline, metric):
                return c
        raise KeyError((treatment, baseline, metric))

    def audit(self, n: int) -> dict:
        """Four audit figures, with a deliberate two-source arrangement.

        The audit reports are not shipped in the repository -- shipping them
        would contaminate any future blind round. audit_scores_pinned.json
        carries the four numbers so a judge can check the deck from a clean
        clone. When the real reports ARE present (the entry workspace) they are
        read and the pin is checked against them, so the pin cannot silently
        become the only source of truth. Disagreement is a failure, not a
        preference."""
        key = f"audit{n}"
        if key in self._cache:
            return self._cache[key]
        pin = json.loads((self.deck_dir / "audit_scores_pinned.json").read_text())[f"round{n}"]
        real = self.workspace / "audit" / f"audit_round{n}.json"
        if real.exists():
            d = json.loads(real.read_text())
            digest = hashlib.sha256(real.read_bytes()).hexdigest()
            got = ({"overall": d["scores"]["overall"], "defects": len(d["defects"])}
                   if n == 1 else
                   {"mean_of_completed_lenses": d["scores"]["mean_of_completed_lenses"],
                    "findings_total": d["findings_total"]})
            check(f"C.audit_pin_agrees[round{n}]",
                  all(pin[k] == v for k, v in got.items()) and pin["sha256"] == digest,
                  f"audit_scores_pinned.json says {({k: pin[k] for k in got})} "
                  f"sha {pin['sha256'][:16]}..., the report says {got} sha {digest[:16]}...")
        else:
            check(f"C.audit_pin_agrees[round{n}]", True,
                  "clean clone: the report is absent, only the pin was read")
        self._cache[key] = pin
        return pin

    def hos_row(self, idx: int) -> tuple:
        """The two superseded HOS rules, read from the parametrisation of the
        test that regenerates them -- not from README prose."""
        src = (self.project / "tests" / "test_hos_binds_the_whole_duty_day.py").read_text()
        rows = re.findall(
            r"\(_rule_\w+,\s*\"[^\"]*\",\s*(\d+),\s*(\d+),\s*([\d.]+),\s*([\d.]+)\)", src)
        if len(rows) < 2:
            raise AssertionError("HOS parametrisation not found in the test file")
        return rows[idx]

    def hos_literal(self, pattern: str) -> str:
        src = (self.project / "tests" / "test_hos_binds_the_whole_duty_day.py").read_text()
        m = re.search(pattern, src)
        if not m:
            raise AssertionError(f"HOS literal not found: {pattern}")
        return m.group(1)

    def demo_duration_s(self) -> float:
        txt = (self.workspace / "demo" / "ARTIFACT.txt").read_text()
        m = re.search(r"duration\s+([\d.]+)\s*s", txt)
        assert m, "no duration in demo/ARTIFACT.txt"
        return float(m.group(1))

    def rubric(self):
        return json.loads((self.workspace / "demo" / "judging_rubric.json").read_text())

    def weight(self, cid: str) -> int:
        for c in self.rubric()["criteria"]:
            if c["id"] == cid:
                return c["weight_pct"]
        raise KeyError(cid)

    def geo_circuity(self) -> str:
        src = (self.project / "roadstar" / "geo.py").read_text()
        m = re.search(r"def road_km\([^)]*circuity: float = ([\d.]+)", src, re.S)
        assert m, "circuity default not found in roadstar/geo.py"
        return m.group(1)

    def corridor_nodes(self) -> int:
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys;sys.path.insert(0,'.');from roadstar.geo import CORRIDOR;print(len(CORRIDOR))"],
            cwd=self.project, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-400:]
        return int(out.stdout.strip())

    def suite_size(self) -> int:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
            cwd=self.project, capture_output=True, text=True, timeout=300)
        m = re.search(r"(\d+) tests? collected", out.stdout)
        assert m, out.stdout[-600:]
        return int(m.group(1))

    def prerevision(self, policy: str, field: str) -> float:
        """The pre-revision figures, taken from the commit itself. The claim
        'the correction made us look worse' is only worth making if the
        before-number comes from the before-commit."""
        out = subprocess.run(
            ["git", "show", "8f97bb1:results/sweep_40x50.json"],
            cwd=self.project, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr[-400:]
        return json.loads(out.stdout)["per_policy"][policy][field]

    def declines(self) -> dict:
        """The decline branch, measured rather than described.

        Round-2 audit finding RUBRIC-02 (BLOCKER) said the demo never exercises
        it: on seed 1000 the model then matched 40 of 40. The revision that
        charged the shipper wait changed that, and this recomputes it rather
        than trusting the finding or its rebuttal."""
        code = r'''
import json, sys
sys.path.insert(0, ".")
from roadstar.instance import make_instance
from roadstar.policies import POLICIES
demo_t, demo_m = None, None
seeds_with_a_decline = 0
for seed in range(1000, 1030):
    trucks, loads = make_instance(40, 50, seed=seed)
    sol = POLICIES["profit_assignment"](trucks, loads)
    if seed == 1000:
        demo_t, demo_m = len(trucks), len(sol.assignments)
    if len(sol.assignments) < len(trucks):
        seeds_with_a_decline += 1
print(json.dumps({"demo_trucks": demo_t, "demo_matched": demo_m,
                  "seeds_with_a_decline": seeds_with_a_decline, "seeds": 30}))
'''
        out = subprocess.run([sys.executable, "-c", code], cwd=self.project,
                             capture_output=True, text=True, timeout=600)
        assert out.returncode == 0, out.stderr[-600:]
        return json.loads(out.stdout)

    def decomposition(self) -> dict:
        """Recomputed here, from the policies, exactly as
        tests/test_readme_matches_results.py recomputes it. Reading these five
        numbers out of README.md would make this verifier a transcription
        check of a transcription."""
        code = r'''
import json, statistics, sys
sys.path.insert(0, ".")
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
        length=statistics.fmean(lengths))
g, p = agg["greedy_feasible"], agg["profit_assignment"]
frozen = p["dh"] / (p["dh"] + g["loaded"])
total = (g["ef"] - p["ef"]) * 100
num = (g["ef"] - frozen) * 100
print(json.dumps({"total_pp": total, "numerator_pp": num,
                  "denominator_pp": total - num,
                  "denominator_share": 100 * (total - num) / total,
                  "len_base": g["length"], "len_entry": p["length"]}))
'''
        out = subprocess.run([sys.executable, "-c", code], cwd=self.project,
                             capture_output=True, text=True, timeout=600)
        assert out.returncode == 0, out.stderr[-600:]
        return json.loads(out.stdout)


# --------------------------------------------------------------------- figures

def build_figures(S: Sources) -> list[tuple[str, str, str]]:
    """(literal as it must appear in the deck, resolved value, source)."""
    p40 = S.sweep40()["per_policy"]
    cfg = S.sweep40()["config"]
    p100 = S.sweep100()["per_policy"]
    cfg100 = S.sweep100()["config"]
    d = S.decomposition()
    F: list[tuple[str, str, str]] = []

    def add(lit, val, src):
        F.append((lit, str(val), src))

    # -- the results table, all five rows -------------------------------------
    for pol, dh, ef, pr in (
        ("naive_nearest", "7718.6", "75.03%", "-$4,949"),
        ("greedy_feasible", "4872.5", "42.15%", "$3,439"),
        ("greedy_profit_pairwise", "4157.9", "34.21%", "$5,321"),
        ("optimal_assignment", "4391.4", "35.64%", "$5,379"),
        ("profit_assignment", "3996.1", "31.89%", "$6,172"),
    ):
        r = p40[pol]
        add(dh, f"{r['mean_deadhead_km']:.1f}", f"sweep_40x50.per_policy.{pol}.mean_deadhead_km")
        add(ef, f"{100 * r['mean_empty_fraction']:.2f}%",
            f"sweep_40x50.per_policy.{pol}.mean_empty_fraction")
        money = f"${abs(r['mean_profit_usd']):,.0f}"
        add(pr, ("-" + money) if r["mean_profit_usd"] < 0 else money,
            f"sweep_40x50.per_policy.{pol}.mean_profit_usd")
    add("795", p40["naive_nearest"]["total_infeasible_proposed"],
        "sweep_40x50.per_policy.naive_nearest.total_infeasible_proposed")
    # The four zeros in the illegal-proposed column are a claim too. They cannot
    # be matched as a unique string, so they are checked structurally here and
    # the bare token "0" is allow-listed in (D) pointing back at this check.
    for pol in ("greedy_feasible", "greedy_profit_pairwise",
                "optimal_assignment", "profit_assignment"):
        check(f"C.zero_illegal[{pol}]", p40[pol]["total_infeasible_proposed"] == 0,
              f"{pol} proposed {p40[pol]['total_infeasible_proposed']} illegal dispatches, "
              f"but the deck's table prints 0")

    # -- sweep configuration ---------------------------------------------------
    add("40 trucks", f"{cfg['trucks']} trucks", "sweep_40x50.config.trucks")
    add("50 loads", f"{cfg['loads']} loads", "sweep_40x50.config.loads")
    add("30 seeded instances", f"{cfg['instances']} seeded instances",
        "sweep_40x50.config.instances")
    add("30 paired synthetic instances", f"{cfg['instances']} paired synthetic instances",
        "sweep_40x50.config.instances")

    # -- headline comparisons --------------------------------------------------
    c_dist = S.cmp40("profit_assignment", "greedy_feasible", "profit_usd")
    add("+62.485%", f"+{c_dist['median_rel_improvement_pct']:.3f}%",
        "comparison(profit_assignment vs greedy_feasible, profit).median")
    add("+79.460%", f"+{c_dist['ratio_of_means_rel_improvement_pct']:.3f}%",
        "comparison(...).ratio_of_means")
    add("30 of 30", f"{c_dist['n_wins']} of {c_dist['n_instances']}",
        "comparison(...).n_wins / n_instances")
    add("+151.993%", f"+{c_dist['mean_rel_improvement_pct']:.3f}%",
        "comparison(...).mean_rel_improvement_pct -- quoted ONLY as the one not to use")
    add("290.436", f"{c_dist['stdev_rel_improvement_pct']:.3f}",
        "comparison(...).stdev_rel_improvement_pct")

    c_dh = S.cmp40("profit_assignment", "greedy_feasible", "deadhead_km")
    add("-18.0%", f"-{c_dh['ratio_of_means_rel_improvement_pct']:.1f}%",
        "comparison(profit_assignment vs greedy_feasible, deadhead).ratio_of_means")

    c_prof = S.cmp40("profit_assignment", "greedy_profit_pairwise", "profit_usd")
    add("+18.207%", f"+{c_prof['mean_rel_improvement_pct']:.3f}%",
        "comparison(profit_assignment vs greedy_profit_pairwise, profit).mean")
    add("+14.886%", f"+{c_prof['median_rel_improvement_pct']:.3f}%", "comparison(...).median")
    add("30/0/0", f"{c_prof['n_wins']}/{c_prof['n_ties']}/{c_prof['n_losses']}",
        "comparison(...).n_wins/n_ties/n_losses")

    # -- denominator decomposition, recomputed --------------------------------
    add("10.26", f"{d['total_pp']:.2f}", "recomputed empty-fraction gap, points")
    add("4.55", f"{d['numerator_pp']:.2f}", "recomputed, from fewer empty km")
    add("5.71", f"{d['denominator_pp']:.2f}", "recomputed, from more loaded km")
    add("55.6%", f"{d['denominator_share']:.1f}%", "recomputed denominator share")
    add("208.2", f"{d['len_base']:.1f}", "recomputed mean matched load length, baseline")
    add("242.2", f"{d['len_entry']:.1f}", "recomputed mean matched load length, entry")

    # -- the decline branch, measured on the demo instance and the sweep -------
    dec = S.declines()
    add("38 of 40", f"{dec['demo_matched']} of {dec['demo_trucks']}",
        "live run of profit_assignment on the demo seed 1000")
    add("29 of 30", f"{dec['seeds_with_a_decline']} of {dec['seeds']}",
        "live run: seeds leaving at least one truck deliberately unmatched")

    # -- hours of service ------------------------------------------------------
    tot0, ill0, pct0, worst0 = S.hos_row(0)
    tot1, ill1, pct1, worst1 = S.hos_row(1)
    add("530 of 1145", f"{ill0} of {tot0}", "test_hos_binds_the_whole_duty_day parametrisation")
    add("46.29%", f"{pct0}%", "same")
    add("29.38 h", f"{worst0} h", "same")
    add("379 of 1096", f"{ill1} of {tot1}", "same")
    add("34.58%", f"{pct1}%", "same")
    add("21.88 h", f"{worst1} h", "same")
    add("14.00 h", S.hos_literal(r"duty day under the rule that ships: exactly ([\d.]+) h") + " h",
        "test docstring for the shipped rule")
    add("184 of 1051",
        (lambda t, l: f"{l} of {t}")(*re.search(
            r"\(total, leaning\) == \((\d+), (\d+)\)",
            (S.project / "tests" / "test_hos_binds_the_whole_duty_day.py").read_text()).groups()),
        "test assertion (total, leaning)")
    add("17.51%", S.hos_literal(r"leaning / total, 2\) == ([\d.]+)") + "%", "test assertion")
    add("190", "190", "README-declared mean wait, minutes -- see ALLOWED note")

    # -- symmetric boundary ----------------------------------------------------
    add("-$4,189", f"-${abs(p40['greedy_profit_pairwise']['mean_profit_usd_incl_return_leg']):,.0f}",
        "sweep_40x50.per_policy.greedy_profit_pairwise.mean_profit_usd_incl_return_leg")
    add("-$4,390", f"-${abs(p40['profit_assignment']['mean_profit_usd_incl_return_leg']):,.0f}",
        "sweep_40x50.per_policy.profit_assignment.mean_profit_usd_incl_return_leg")

    # -- audit history ---------------------------------------------------------
    a1, a2 = S.audit(1), S.audit(2)
    add("37.28", f"{a1['overall']:.2f}", "audit round 1 overall (pin, cross-checked)")
    add("15", str(a1["defects"]), "audit round 1 defect count")
    add("44.67", f"{a2['mean_of_completed_lenses']:.2f}",
        "audit round 2 mean of completed lenses")
    add("34", str(a2["findings_total"]), "audit round 2 findings_total")
    add("24.46%", f"{100 * S.prerevision('profit_assignment', 'mean_empty_fraction'):.2f}%",
        "git 8f97bb1 results, pre-revision empty fraction")
    add("$8,222", f"${S.prerevision('profit_assignment', 'mean_profit_usd'):,.0f}",
        "git 8f97bb1 results, pre-revision mean profit")

    # -- demo, suite, rubric, model constants ---------------------------------
    dur = S.demo_duration_s()
    add("4 min 25 s", f"{int(dur // 60)} min {int(dur % 60)} s", "demo/ARTIFACT.txt duration")
    add("76 tests", f"{S.suite_size()} tests", "pytest --collect-only on the project suite")
    add("15% of this rubric", f"{S.weight('C4')}% of this rubric", "judging_rubric.json C4.weight_pct")
    add("1.20", S.geo_circuity(), "roadstar/geo.py road_km circuity default")
    add("19", str(S.corridor_nodes()), "len(roadstar.geo.CORRIDOR)")

    # 100x120 config is quoted nowhere in the deck; assert that stays true in D.
    assert cfg100["instances"] == 10
    return F


# ---------------------------------------------------- allow-list for check (D)

ALLOWED = {
    "2026": "the event year, in the deck title",
    "2005-313": "SOR/2005-313, a Canadian regulation number, not a measurement",
    "395.2": "FMCSA 395.2, a US regulation number, not a measurement",
    "3-5": "the organiser's own video length band, quoted from the rules",
    "10-15": "the organiser's own presentation length band, quoted from the rules",
    "8": "the model's own stated reset threshold in hours, a rule not a result",
    "1": "structural: the 'script(1)' man-page section and the numbered caveats",
    "2": "structural: numbered caveat",
    "3": "structural: numbered caveat",
    "4": "structural: 'Criterion 4', named from the rubric",
    "5": "structural: 'five policies' written as a numeral in 'C1..C5'",
    "100": "the '/ 100' denominator of the audit scores, stated with them",
    "0": "the illegal-proposed column's four zeros -- checked structurally by "
         "C.zero_illegal[...] rather than by string match",
}

TOKEN = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?\s*%?")

# checks (E) and (F): the sentences this entry must and must not carry.
# (name, pattern the SLIDES must carry, pattern the SCRIPT must carry).
# Checked per document, not over the concatenation. A judge reads the slides; the
# room hears the script. A disclosure deleted from one and surviving in the other
# is a real defect, and searching the concatenation would hide exactly that --
# which is how the first draft of these controls passed against a deck whose
# honesty slide had been removed.
MUST_SAY = [
    ("synthetic",
     r"synthetic instances over real corridor geography",
     r"synthetic instances over real corridor geography"),
    ("no portal data",
     r"No RoadStar portal data was read",
     r"did not use the provided RoadStar data"),
    ("c4 unmet",
     r"UNMET, and I am claiming it as unmet",
     r"[Ii]t is unmet, and I'm claiming it as unmet"),
    ("boundary reverses",
     r"`profit_assignment` is not the best one",
     r"my entry is not the best one"),
    ("lower/upper bounds",
     r"lower bounds.{0,90}upper bounds",
     r"lower bounds.{0,90}upper bounds"),
    ("skew warning",
     r"Do not quote the biggest percentage",
     r"do not quote the biggest percentage"),
    ("open findings",
     r"remain open are listed",
     r"remain open are listed"),
    ("no compliance",
     r"nothing here asserts regulatory compliance",
     r"nothing here asserts regulatory compliance"),
    ("baseline scored equally",
     r"is the \*\*only\*\* place a dispatch is judged",
     r"is the only place a dispatch is judged"),
]

MUST_NOT_SAY = [
    ("video is hosted", r"YouTube|Vimeo|hosted at|streaming"),
    ("used portal data", r"using the provided (data|tables)|integrated the portal"),
    ("attendance promise", r"I will be (there|present)|see you in Waterloo|I am attending"),
    ("compliance claim", r"is compliant with|regulatory compliance is|meets FMCSA"),
    ("production claim", r"in production|deployed to|live customers"),
    ("won/placed", r"we won|prize-winning|award-winning"),
    ("headline uses skewed mean",
     r"improves (profit )?by \+?151|a 151% improvement|151\.993% improvement"),
]


# ------------------------------------------------------------------ the checks

def parse_slides(text: str) -> list[dict]:
    out = []
    for m in re.finditer(
            r"<!--\s*slide:\s*(\d+)\s*\|\s*seconds:\s*(\d+)\s*\|\s*criteria:\s*([^>]*?)-->",
            text):
        out.append({"n": int(m.group(1)), "seconds": int(m.group(2)),
                    "criteria": m.group(3).split(), "start": m.end()})
    for i, s in enumerate(out):
        s["body"] = text[s["start"]: out[i + 1]["start"] if i + 1 < len(out) else len(text)]
    return out


def parse_script(text: str) -> dict[int, str]:
    blocks, marks = {}, list(re.finditer(r"<!--\s*script:\s*(\d+)\s*-->", text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        blocks[int(m.group(1))] = text[m.end(): end]
    return blocks


def verify(d: pathlib.Path, project: pathlib.Path, workspace: pathlib.Path,
           verbose: bool = True) -> bool:
    FAILURES.clear()
    slides_raw = (d / "slides.md").read_text()
    script_raw = (d / "script.md").read_text()
    S = Sources(project, workspace, d)

    slides = parse_slides(slides_raw)
    script = parse_script(script_raw)

    # ---- A structure
    check("A.slides_present", len(slides) >= 10, f"{len(slides)} slides")
    check("A.numbering", [s["n"] for s in slides] == list(range(1, len(slides) + 1)),
          str([s["n"] for s in slides]))
    check("A.script_pairs", set(script) == {s["n"] for s in slides},
          f"slides {sorted(s['n'] for s in slides)} vs script {sorted(script)}")

    # ---- B timing
    total = sum(s["seconds"] for s in slides)
    check("B.total_in_band", 600 <= total <= 900, f"{total} s = {total // 60}m{total % 60:02d}s")
    for s in slides:
        words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", script.get(s["n"], "")))
        wpm = 60.0 * words / s["seconds"]
        check(f"B.rate.slide{s['n']}", 100.0 <= wpm <= 165.0,
              f"{words} words in {s['seconds']} s = {wpm:.0f} wpm")

    # ---- C figures
    figures = build_figures(S)
    fslides = flat(slides_raw)
    for lit, resolved, src in figures:
        check(f"C.matches[{lit}]", flat(lit) == flat(resolved),
              f"deck says {lit!r}, {src} resolves to {resolved!r}")
        check(f"C.present[{lit}]", flat(lit) in fslides, f"not on any slide; source {src}")

    # ---- D nothing unsourced
    # The slide directives are structural markup, not spoken content; their
    # seconds and slide numbers are checked by (A) and (B) instead.
    stripped = re.sub(r"<!--.*?-->", " @ ", fslides)
    for lit, _, _ in sorted(figures, key=lambda f: -len(f[0])):
        stripped = stripped.replace(flat(lit), " @ ")
    for cid in ("C1", "C2", "C3", "C4", "C5"):
        stripped = stripped.replace(cid, " @ ")
    stripped = re.sub(r"sweep_\d+x\d+|40x50|100x120|\bgeo\.py\b|\bv_ij\b|\bC\d\b", " @ ", stripped)
    # Regulation citations are identifiers, not measurements. Stripped by exact
    # literal so nothing else can hide behind the exemption.
    for citation in ("SOR/2005-313", "FMCSA 395.2"):
        stripped = stripped.replace(citation, " @ ")
    # The organiser's own published bands, quoted verbatim from the rules. They
    # are requirements this deck must satisfy, not results it is reporting; (B)
    # is what checks we actually sit inside the presentation one.
    for band in ("3-5 minute", "10-15 minute"):
        stripped = stripped.replace(band, " @ ")
    leftovers = []
    for m in TOKEN.finditer(stripped):
        tok = m.group(0).strip()
        if tok.rstrip("%").rstrip() in ALLOWED or tok in ALLOWED:
            continue
        ctx = stripped[max(0, m.start() - 45): m.end() + 45]
        leftovers.append(f"{tok!r} in ...{ctx}...")
    check("D.no_unsourced_number", not leftovers,
          " || ".join(leftovers[:6]) + (f" (+{len(leftovers) - 6} more)" if len(leftovers) > 6 else ""))

    # ---- E / F disclosures and prohibitions
    fscript = flat(script_raw)
    for name, pat_s, pat_k in MUST_SAY:
        check(f"E.says[{name}@slides]", re.search(pat_s, fslides) is not None, pat_s)
        check(f"E.says[{name}@script]", re.search(pat_k, fscript) is not None, pat_k)
    both = fslides + " ~ " + fscript
    for name, pat in MUST_NOT_SAY:
        m = re.search(pat, both)
        check(f"F.silent[{name}]", m is None, f"matched {m.group(0)!r}" if m else "")

    # ---- H the rendered deck is not stale
    hpath = d / "slides.html"
    if check("H.rendered_exists", hpath.exists(), "run build_presentation.py"):
        htxt = hpath.read_text()
        want = hashlib.sha256(slides_raw.encode()).hexdigest()
        check("H.rendered_current", f"slides.md sha256: {want}" in htxt,
              "slides.html records a different source digest -- rebuild it")
        check("H.self_contained",
              not re.search(r'(?:src|href)\s*=\s*["\']https?://', htxt),
              "the rendered deck pulls a remote resource; it has to open offline")
        for lit, _, _ in figures:
            check(f"H.carries[{lit}]", flat(lit) in flat(htxt),
                  "figure is on slides.md but did not survive rendering")

    # ---- G rubric coverage
    tagged = {c for s in slides for c in s["criteria"] if c != "-"}
    check("G.covers_all_criteria", tagged == {"C1", "C2", "C3", "C4", "C5"}, str(sorted(tagged)))
    check("G.weights_sum", sum(c["weight_pct"] for c in S.rubric()["criteria"])
          == S.rubric()["weights_sum_pct"], "rubric file self-inconsistent")

    if verbose:
        run = len(FAILURES) + sum(1 for _ in ())  # counted below instead
        print(f"slides={len(slides)}  total={total} s ({total // 60}m{total % 60:02d}s)  "
              f"figures={len(figures)}")
        if FAILURES:
            print(f"\nRED  {len(FAILURES)} failing check(s):")
            for n, det in FAILURES:
                print(f"  - {n}: {det}")
        else:
            print("GREEN  every check passed")
    return not FAILURES


# -------------------------------------------------------------- neg. controls

# Each row: (name, file, anchor, replacement, the check that MUST go red).
# Naming the expected check matters. A mutation that turns the suite red for
# some unrelated reason has not shown that the check we care about works -- and
# two of these rows were written wrong the first time and caught exactly that
# way: they went red under C.present while claiming to exercise C.matches.
MUTATIONS = [
    # -- deck contradicts the artifact ---------------------------------------
    # Anchored on a figure that appears exactly ONCE in the deck. The first
    # version of this row moved "$6,172" on the results slide and the deck still
    # passed C.present, because slide 10 quotes the same figure again -- so the
    # control was reporting the strength of a check it was not reaching.
    ("figure changed by one digit", "slides.md", "**3996.1**", "**3996.2**", "C.present"),
    ("audit score flattered", "slides.md", "**37.28** / 100", "**77.28** / 100", "C.present"),
    ("unsourced number introduced", "slides.md",
     "winning **30 of 30**.", "winning **30 of 30**, roughly 4.2x.", "D.no_unsourced"),
    ("audit pin drifts from the report", "audit_scores_pinned.json",
     '"overall": 37.28', '"overall": 67.28', "C.audit_pin_agrees[round1]"),
    ("decline rate overstated", "slides.md", "**29 of 30**", "**30 of 30**", "C.present"),
    # -- honesty deleted from the slides -------------------------------------
    ("the reversal deleted", "slides.md",
     "**`profit_assignment` is not the best one**", "**`profit_assignment` wins here too**",
     "E.says[boundary reverses@slides]"),
    ("C4 quietly upgraded", "slides.md",
     "UNMET, and I am claiming\nit as unmet", "PARTIAL, using the provided data",
     "E.says[c4 unmet@slides]"),
    ("skew warning dropped", "slides.md",
     "**1. Do not quote the biggest percentage.**", "**1. A note on ratios.**",
     "E.says[skew warning@slides]"),
    ("synthetic disclosure removed", "slides.md",
     "**synthetic instances over real corridor geography**", "**real corridor operations**",
     "E.says[synthetic@slides]"),
    ("open findings hushed", "slides.md",
     "**The findings that remain open are listed in the\nREADME and in the write-up, not closed quietly.**",
     "**Everything found has been addressed.**", "E.says[open findings@slides]"),
    # -- honesty deleted from the SPOKEN script only, slides untouched --------
    ("script drops the skew warning", "script.md",
     "First: do not quote the biggest percentage.", "First: the headline ratio.",
     "E.says[skew warning@script]"),
    ("script drops the reversal", "script.md",
     "and my entry is not the best one", "and my entry still wins",
     "E.says[boundary reverses@script]"),
    # -- claims this entry must never make ------------------------------------
    ("video claimed as hosted", "slides.md",
     "is built\nfrom `script(1)` recordings", "is on YouTube and built from `script(1)` recordings",
     "F.silent[video is hosted]"),
    ("compliance asserted", "slides.md",
     "**nothing here asserts regulatory compliance**", "the model meets FMCSA rules",
     "F.silent[compliance claim]"),
    # -- the rendered deck drifts from the checked source ---------------------
    ("slides.md edited without rebuilding", "slides.md",
     "Any one of the three can make an otherwise attractive load illegal.",
     "Any one of the three can make a load illegal.", "H.rendered_current"),
    # -- structure and timing --------------------------------------------------
    ("deck overruns the band", "slides.md", "seconds: 75", "seconds: 375", "B.total_in_band"),
    ("slide starved of script", "script.md",
     "<!-- script: 3 -->", "<!-- script: 3 -->\nSKIP.\n<!-- script: 99 -->", "A.script_pairs"),
]

# The controls above all mutate the DECK. They cannot show that the figures are
# read from the artifacts rather than from constants in this file -- for that the
# ARTIFACT has to move while the deck stays still. This one does that, and it is
# the control that would catch build_figures() being quietly turned into a table
# of literals.
ARTIFACT_MUTATIONS = [
    ("results JSON moved under a still deck", "results/sweep_40x50.json",
     lambda d: d["per_policy"]["profit_assignment"].__setitem__("mean_profit_usd", 9999.0),
     "C.matches"),
]


def run_controls(d: pathlib.Path, project: pathlib.Path, workspace: pathlib.Path) -> bool:
    ok = True
    for name, fname, old, new, expect in [("PRISTINE (must stay green)", None, None, None, None)] + MUTATIONS:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="pres_ctl_"))
        try:
            stage = tmp / "presentation"          # fresh dir; never copy INTO an existing one
            shutil.copytree(d, stage)
            if fname is not None:
                p = stage / fname
                txt = p.read_text()
                if old not in txt:
                    print(f"  CONTROL BROKEN  {name}: anchor {old!r} not in {fname}")
                    ok = False
                    continue
                p.write_text(txt.replace(old, new, 1))
            out = subprocess.run(
                [sys.executable, str(stage / "verify_presentation.py"), "--no-controls",
                 "--dir", str(stage), "--project", str(project), "--workspace", str(workspace)],
                capture_output=True, text=True, timeout=900)
            red = out.returncode != 0
            if fname is None:
                good = not red
                detail = "" if good else out.stdout[-500:]
            else:
                good = red and any(
                    line.strip().startswith("- " + expect) for line in out.stdout.splitlines())
                detail = "" if good else f"expected a failing check named {expect}*; got rc={out.returncode}"
            print(f"  [{'ok ' if good else 'BAD'}] {name}")
            if detail:
                print(f"        {detail}")
            ok &= good
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- artifact-side controls: move the source, hold the deck still --------
    for name, rel, mutate, expect in ARTIFACT_MUTATIONS:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="pres_art_"))
        try:
            proj = tmp / "project"
            shutil.copytree(project, proj,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            target = proj / rel
            data = json.loads(target.read_text())
            mutate(data)
            target.write_text(json.dumps(data, indent=1, ensure_ascii=False))
            out = subprocess.run(
                [sys.executable, str(d / "verify_presentation.py"), "--no-controls",
                 "--dir", str(d), "--project", str(proj), "--workspace", str(workspace)],
                capture_output=True, text=True, timeout=900)
            good = out.returncode != 0 and any(
                line.strip().startswith("- " + expect) for line in out.stdout.splitlines())
            print(f"  [{'ok ' if good else 'BAD'}] {name}")
            if not good:
                print(f"        expected a failing check named {expect}*; "
                      f"got rc={out.returncode}\n        {out.stdout[-400:]}")
            ok &= good
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(here))
    ap.add_argument("--project", default=str(here.parent.parent / "project"))
    ap.add_argument("--workspace", default=str(here.parent.parent))
    ap.add_argument("--no-controls", action="store_true")
    a = ap.parse_args()
    d = pathlib.Path(a.dir).resolve()
    project = pathlib.Path(a.project).resolve()
    workspace = pathlib.Path(a.workspace).resolve()

    green = verify(d, project, workspace)
    if a.no_controls:
        return 0 if green else 1

    print("\nnegative controls -- each mutation must turn a NAMED check red:")
    controls_ok = run_controls(d, project, workspace)
    print()
    if green and controls_ok:
        print("VERDICT: GREEN -- deck verified, and the verifier is demonstrably able to fail.")
        return 0
    print(f"VERDICT: RED -- deck_green={green} controls_ok={controls_ok}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
