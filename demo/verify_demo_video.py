"""Runtime evidence that roadstar_demo.mp4 is a fit submission artifact.

The demo video is the one requirement row this entry can move without the
participant portal, and a video is the easiest artifact in a hackathon to
inflate: nobody re-derives a number that flashed past on a slide.  So every
figure the video puts on screen is re-derived here from something on disk --
the committed sweeps, the previous commit's sweeps, the source constants, the
`script(1)` capture logs -- and the check fails if the storyboard and the
artifact disagree.

Three classes of check:

  CONTAINER   the file is a playable h264/yuv420p video whose duration is
              inside the organiser's stated 3-5 minute band, and every frame
              decodes.
  PROVENANCE  every terminal segment is one of the capture logs, each log is
              pinned by sha256, and each log really is the output of the
              command the video says produced it.
  CLAIMS      every numeric string the cards assert is recomputed from an
              artifact and compared.

Run:  python3 verify_demo_video.py [video.mp4]
Exit 0 = every check passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# This directory lives in two places on purpose: beside the repository checkout
# in the entry workspace, and inside the published repository so a judge can
# reach the video and re-run this file. Resolve the project root for both rather
# than hard-coding one, because a __file__-relative path that is right in only
# one layout fails silently in the other.
_PARENT = os.path.dirname(HERE)
PROJECT = (_PARENT if os.path.isdir(os.path.join(_PARENT, "roadstar"))
           else os.path.join(_PARENT, "project"))
CAPS = os.path.join(HERE, "caps")

sys.path.insert(0, HERE)
import build_demo_video as story  # noqa: E402  (the storyboard under test)

MIN_S, MAX_S = 180.0, 300.0      # organiser's rule: "video submission (3-5 min)"

# sha256 of each capture, pinned when the video was cut. A capture that is
# re-recorded without re-cutting the video is a silent divergence between the
# pixels a judge sees and the bytes this file checks.
PINNED = {
    "dispatch.log":    "19db47356e41561d3ecd0076c173eb1f5b0a5181dabb6858a88337f3fef31500",
    "hos.log":         "a2bbd79cf7e51ebf0e08f7cfc82a083e2be04f5c2df878cd9f2adf9ed856c97a",
    "guard_green.log": "f6844a5e417597b4369eaf6f4b7e8a56f587ff736f03472f7b4c9e21e401b138",
    "fab.log":         "688f8675b8fb5867b055efe19882d6cfd727f570c15a3665be7f72590e02fbd0",
    "table.log":       "79b8393ba6389547bd664674b947c798bff5f09a4a36a16d7ce73328e2519746",
}

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label + (f" -- {detail}" if detail else ""))


def sh(*cmd: str, cwd: str | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


def cap(name: str) -> str:
    with open(os.path.join(CAPS, name), encoding="utf-8", errors="replace") as fh:
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", fh.read())


def card_text() -> str:
    """Every word the storyboard paints that is not a capture replay."""
    parts = []
    for sc in story.SCENES:
        parts.append(sc.get("title", ""))
        parts.extend(sc.get("body", []))
        parts.extend(sc.get("footer", []) or [])
        parts.extend(sc.get("caption", []) or [])
    return " ".join(parts).replace("**", "").replace("~~", "")


def main(video: str) -> int:
    print(f"VERIFY {video}")
    text = card_text()

    # ---------------------------------------------------------- CONTAINER
    print("\nCONTAINER")
    probe = sh("ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", video)
    meta = json.loads(probe) if probe.strip() else {}
    streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    check("one video stream", len(streams) == 1)
    if streams:
        s = streams[0]
        check("h264 / yuv420p", s.get("codec_name") == "h264"
              and s.get("pix_fmt") == "yuv420p",
              f"{s.get('codec_name')}/{s.get('pix_fmt')}")
        check("1280x720", (s.get("width"), s.get("height")) == (1280, 720),
              f"{s.get('width')}x{s.get('height')}")
    dur = float(meta.get("format", {}).get("duration", 0.0))
    check(f"duration inside the rules' 3-5 min band", MIN_S <= dur <= MAX_S,
          f"{dur:.1f}s = {int(dur // 60)}m{int(dur % 60):02d}s")
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-f", "null", "-"],
                            capture_output=True, text=True)
    check("every frame decodes without error",
          decode.returncode == 0 and not decode.stderr.strip(),
          decode.stderr.strip()[:120] or "clean")
    check("no audio track is claimed anywhere in the storyboard",
          "narration" not in text.lower() and "voice" not in text.lower())

    # --------------------------------------------------------- PROVENANCE
    print("\nPROVENANCE")
    used = [sc["log"] for sc in story.SCENES if sc["kind"] == "term"]
    check("every terminal segment is a capture log on disk",
          all(os.path.exists(os.path.join(CAPS, n)) for n in used),
          ", ".join(used))
    for name in used:
        digest = hashlib.sha256(
            open(os.path.join(CAPS, name), "rb").read()).hexdigest()
        check(f"{name} matches its pinned sha256",
              digest == PINNED.get(name), digest[:16])
    # the capture logs must be what they are said to be
    # ARTIFACT.txt is the provenance record that ships to a judge. Its pins were
    # a written record only: nothing compared them to the files, so an edit here
    # would have left a shipped document quietly asserting a digest that no
    # longer existed. Every pin it carries is now checked against the bytes.
    _art = open(os.path.join(HERE, "ARTIFACT.txt")).read()
    for _name in ("build_demo_video.py", "verify_demo_video.py",
                  "judging_rubric.json"):
        _m = re.search(re.escape(_name) + r"\s+([0-9a-f]{64})", _art)
        _actual = hashlib.sha256(
            open(os.path.join(HERE, _name), "rb").read()).hexdigest()
        check(f"ARTIFACT.txt's pin for {_name} matches the file",
              _m is not None and _m.group(1) == _actual,
              (_m.group(1)[:12] if _m else "NO PIN") + f" vs {_actual[:12]}")

    check("dispatch.log is the output of `make dispatch`",
          "--dispatch" in cap("dispatch.log")
          and "# matched 38 of 40 trucks" in cap("dispatch.log"))
    check("hos.log is the duty-day suite",
          "test_hos_binds_the_whole_duty_day.py" in cap("hos.log")
          and "10 passed" in cap("hos.log"))
    check("guard_green.log is the README-vs-results guard, green",
          "17 passed" in cap("guard_green.log"))
    check("fab.log is that same guard turning red on one fabricated cell",
          "fabricate ONE number" in cap("fab.log")
          and "1 failed, 16 passed" in cap("fab.log")
          and "9999.0 == 6172.08" in cap("fab.log"))
    check("table.log is a live 30-instance sweep, not a stored file",
          "roadstar.experiment" in cap("table.log")
          and "--instances 30" in cap("table.log"))

    # -------------------------------------------------------------- CLAIMS
    print("\nCLAIMS  (each recomputed from an artifact, then compared)")
    results = json.load(open(os.path.join(PROJECT, "results", "sweep_40x50.json")))
    per = results["per_policy"]
    pa, gf, gpp = per["profit_assignment"], per["greedy_feasible"], per["greedy_profit_pairwise"]

    check('"31.89% empty" == profit_assignment mean_empty_fraction',
          f"{pa['mean_empty_fraction'] * 100:.2f}%" in text,
          f"{pa['mean_empty_fraction'] * 100:.2f}%")
    check('"42.15%" == greedy_feasible mean_empty_fraction',
          f"{gf['mean_empty_fraction'] * 100:.2f}%" in text,
          f"{gf['mean_empty_fraction'] * 100:.2f}%")
    check('"$3,439 -> $6,172" == the two mean profits',
          f"${gf['mean_profit_usd']:,.0f}" in text and f"${pa['mean_profit_usd']:,.0f}" in text,
          f"${gf['mean_profit_usd']:,.0f} -> ${pa['mean_profit_usd']:,.0f}")

    prev = json.loads(sh("git", "show", "8f97bb1:results/sweep_40x50.json", cwd=PROJECT))
    ppa = prev["per_policy"]["profit_assignment"]
    check('"24.46% -> 31.89%" is the pre/post-revision empty fraction',
          f"{ppa['mean_empty_fraction'] * 100:.2f}% -> {pa['mean_empty_fraction'] * 100:.2f}%" in text,
          f"git 8f97bb1 {ppa['mean_empty_fraction'] * 100:.2f}% -> HEAD {pa['mean_empty_fraction'] * 100:.2f}%")
    check('"$8,222 -> $6,172" is the pre/post-revision mean profit',
          f"${ppa['mean_profit_usd']:,.0f} -> ${pa['mean_profit_usd']:,.0f}" in text,
          f"${ppa['mean_profit_usd']:,.0f} -> ${pa['mean_profit_usd']:,.0f}")
    check("the revision it narrates made the headline WORSE, as the video says",
          pa["mean_profit_usd"] < ppa["mean_profit_usd"]
          and pa["mean_empty_fraction"] > ppa["mean_empty_fraction"]
          and "worse" in text.lower())
    check("greedy_profit_pairwise really is best under the symmetric boundary",
          max(v["mean_profit_usd_incl_return_leg"] for v in per.values())
          == gpp["mean_profit_usd_incl_return_leg"]
          and "greedy_profit_pairwise" in text)
    check("every policy really does lose money under the symmetric boundary",
          all(v["mean_profit_usd_incl_return_leg"] < 0 for v in per.values()))

    # read the constant the code actually uses, not a regex over its source --
    # `OPERATING_COST_USD_PER_KM: Final[float] = 1.10` defeats the obvious one.
    sys.path.insert(0, PROJECT)
    from roadstar import econ as econ_mod  # noqa: E402
    check('"$1.10/km" == roadstar.econ.OPERATING_COST_USD_PER_KM',
          abs(econ_mod.OPERATING_COST_USD_PER_KM - 1.10) < 1e-9 and "$1.10/km" in text,
          f"{econ_mod.OPERATING_COST_USD_PER_KM}")

    hos = open(os.path.join(PROJECT, "roadstar", "hos.py")).read()
    hours = set(re.findall(r"\b(1[0-9])\s*\*\s*60|\b(1[0-9])\.0?\s*h", hos))
    check('"13 h / 14 h" ceilings appear in roadstar/hos.py',
          "13" in hos and "14" in hos and "13 h" in text and "14 h" in text,
          f"literals seen: {sorted({a or b for a, b in hours})}")

    disp = cap("dispatch.log")
    n_declined = len(re.findall(r"no backhaul worth taking", disp))
    check('"Two of the 40 trucks did" == declines in the recorded dispatch',
          n_declined == 2 and "matched 38 of 40" in disp and "Two of the 40 trucks" in text,
          f"{n_declined} declined, 38 of 40 matched")
    check("the two declining trucks are named correctly in the caption",
          all(t in disp and t in text for t in ("T007", "T038")))

    readme = open(os.path.join(PROJECT, "README.md")).read()
    for figure in ("530 of 1145", "46.29%", "29.38 h",
                   "379 of 1096", "34.58%", "21.88 h", "14.00 h",
                   "37.3/100", "44.7/100", "1.20 circuity"):
        key = figure.replace(" circuity", "")
        check(f'"{figure}" is carried by the shipped README',
              key in readme.replace("**", "") and key in text.replace(" circuity", ""))

    check('"10 passed in 1.51 s" matches hos.log',
          "10 passed in 1.51s" in cap("hos.log") and "10 passed in 1.51 s" in text)
    check('"17 passed" matches guard_green.log',
          "17 passed" in cap("guard_green.log") and "17 passed" in text)

    # ---- two-sided: no figure may appear on a card unless it is derivable ----
    #
    # Every check above is a PRESENCE check: it proves the right number is on
    # screen somewhere. A mutation campaign showed that is not enough --
    # rewriting the results caption from "31.89% empty" to "35.00% empty" left
    # all of them green, because 31.89% still appeared on another card. So the
    # rule is the one the repo's own README guard uses: if a figure appears, it
    # is compared against a committed artifact or recomputed from one. There is
    # no third category.
    FIGURE = re.compile(
        r"\$[\d,]+(?:\.\d+)?"
        r"|\d+(?:\.\d+)?%"
        r"|\d+(?:\.\d+)?\s*h\b"
        r"|\d+\s+of\s+\d+"
        r"|\d+(?:\.\d+)?/100"
        r"|\d+\s+passed\b"
        r"|\d+(?:\.\d+)?\s*s\b"
        r"|\d+\s*x\s*\d+"
        r"|\d+\s+tests?\b")

    def figures(blob: str) -> set[str]:
        return {re.sub(r"\s+", "", f).lower() for f in FIGURE.findall(blob)}

    allowed = set()
    allowed |= figures(readme)                       # itself CI-checked vs results

    # The video is a RECORDING of the repository as it stood when it was cut,
    # and it says so on screen. Figures that were true at that commit and have
    # since moved -- the suite size is the obvious one, it grows -- must be
    # sourced against that commit, not against HEAD. Sourcing them against HEAD
    # only ever worked while the two happened to agree, and the alternative
    # would be re-cutting a verified video every time a test is added.
    cut = re.search(r"project git HEAD\s+([0-9a-f]{40})", open(
        os.path.join(HERE, "ARTIFACT.txt")).read())
    check("ARTIFACT.txt pins the commit the video was cut against",
          cut is not None, cut.group(1)[:12] if cut else "MISSING")
    if cut is None:
        raise SystemExit("FATAL: ARTIFACT.txt no longer pins the commit the "
                         "video was cut against, so the figures on its cards "
                         "have no source. Refusing to report a pass.")
    cut_sha = cut.group(1)
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", cut_sha, "HEAD"],
        cwd=PROJECT, capture_output=True).returncode == 0
    check("the cut commit is an ancestor of HEAD, not an unrelated tree",
          is_ancestor, cut_sha[:12])
    cut_readme = sh("git", "show", f"{cut_sha}:README.md", cwd=PROJECT)
    check("the cut commit's README is readable from this checkout",
          len(cut_readme) > 1000, f"{len(cut_readme)} bytes")
    allowed |= figures(cut_readme)                   # CI-checked at that commit

    for name in used:
        allowed |= figures(cap(name))                # the recorded runs
    for name, p in per.items():                      # committed sweep, HEAD
        allowed |= {f"{p['mean_empty_fraction'] * 100:.2f}%",
                    f"{p['mean_empty_fraction_incl_return_leg'] * 100:.2f}%",
                    f"${p['mean_profit_usd']:,.0f}",
                    f"${abs(p['mean_profit_usd_incl_return_leg']):,.0f}"}
    for name, p in prev["per_policy"].items():       # committed sweep, 8f97bb1
        allowed |= {f"{p['mean_empty_fraction'] * 100:.2f}%",
                    f"${p['mean_profit_usd']:,.0f}"}
    # The judging weights the cards put on screen come from the organiser's
    # rubric. It is shipped beside this file so the check still has a source in
    # a clean clone, where the entry workspace's manifest.json does not exist --
    # a check that cannot run is a check that cannot fail. When the manifest IS
    # present, both are read and disagreement is a failure, so shipping a copy
    # does not create a second version of the truth.
    rubric = json.load(open(os.path.join(HERE, "judging_rubric.json")))
    weights = [c["weight_pct"] for c in rubric["criteria"]]
    ws_manifest = os.path.join(os.path.dirname(PROJECT), "manifest.json")
    if os.path.exists(ws_manifest):
        mw = [c["weight_pct"]
              for c in json.load(open(ws_manifest))["judging"]["criteria"]]
        check("shipped rubric agrees with the entry manifest's weights",
              mw == weights, f"manifest {mw} vs shipped {weights}")
    else:
        check("shipped rubric is the weight source (no entry manifest here)",
              len(weights) == 5, f"clean-clone layout, weights {weights}")
    check("shipped rubric reproduces the organiser's own arithmetic",
          sum(weights) == rubric["weights_sum_pct"] == 95,
          f"sum {sum(weights)} -- the page publishes 95, not 100")
    allowed |= {f"{w}%" for w in weights}
    allowed = {a.lower() for a in allowed}

    unsourced = sorted(f for f in figures(text) if f not in allowed)
    check("every figure on every card is derivable from an artifact",
          not unsourced, f"unsourced: {unsourced}" if unsourced else
          f"{len(figures(text))} figures, all sourced")

    check("scipy.optimize.linear_sum_assignment is what actually solves it",
          "from scipy.optimize import linear_sum_assignment"
          in open(os.path.join(PROJECT, "roadstar", "policies.py")).read()
          and "scipy.optimize.linear_sum_assignment" in text)

    # the dispatch caption's speed claim, re-measured rather than remembered
    t0 = __import__("time").time()
    subprocess.run([sys.executable, "-m", "roadstar.experiment", "--trucks", "40",
                    "--loads", "50", "--dispatch"], cwd=PROJECT,
                   capture_output=True, text=True)
    elapsed = __import__("time").time() - t0
    check('"computes in under a second" re-measured now',
          elapsed < 1.0 and "under a second" in text, f"{elapsed:.2f}s")

    # nothing may be claimed that the entry does not have
    print("\nNON-CLAIMS  (the video must not assert what does not exist)")
    lower = text.lower()
    for forbidden in ("deployed", "in production", "customers", "pilot with",
                      "real fleet", "live api"):
        check(f'does not claim "{forbidden}"', forbidden not in lower)
    # "portal data" is allowed only inside the sentence that denies using it --
    # a bare substring ban fires on the disclosure itself.
    check('"portal data" appears only in the denial, never as a use claim',
          lower.count("portal data") == lower.count("no organiser portal data was read"),
          f'{lower.count("portal data")} mention(s)')
    check("states the data is synthetic", "synthetic" in lower)
    check("states criterion 4 is unmet", "criterion 4" in lower and "unmet" in lower)
    check("states no organiser portal data was read",
          "no organiser portal data was read" in lower)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else os.path.join(HERE, "roadstar_demo.mp4")))
