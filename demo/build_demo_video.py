"""Build the RoadStar Hackathon demo video from REAL captured terminal sessions.

Every terminal segment in the finished video is a byte-for-byte replay of a
session recorded with util-linux `script(1)` against the shipped repository at
git 153deaf.  Nothing is re-typed, re-ordered or re-worded: the renderer reads
the capture logs in `caps/` and paints them.  The only invented pixels are the
title/summary cards, which carry no figure that is not also in README.md.

Playback is slowed relative to the recorded wall clock so the output can be
read; each segment states its own real runtime on screen, so the pacing is
never implied to be real time.

Usage:  python3 build_demo_video.py <caps_dir> <out.mp4>
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- appearance

W, H = 1280, 720
BG = (13, 17, 23)
PANEL = (22, 27, 34)
FG = (201, 209, 217)
DIM = (139, 148, 158)
ACCENT = (88, 166, 255)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)

ANSI_FG = {
    30: (72, 79, 88), 31: RED, 32: GREEN, 33: YELLOW, 34: ACCENT,
    35: (188, 140, 255), 36: (57, 197, 207), 37: FG, 39: FG,
    90: DIM, 91: RED, 92: GREEN, 93: YELLOW, 94: ACCENT,
    95: (188, 140, 255), 96: (57, 197, 207), 97: (255, 255, 255),
}

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
MONO = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono.ttf", 15)
MONO_B = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono-Bold.ttf", 15)
CARD_M = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono.ttf", 16)
CARD_MB = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono-Bold.ttf", 16)
SANS = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 20)
SANS_B = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 20)
TITLE_F = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 40)
SUB_F = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 24)
CARD_H = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 28)

ADV = MONO.getlength("M")            # monospace advance, px
MARGIN = 34
HEADER_H = 52
CAPTION_H = 92
TERM_TOP = HEADER_H + 16
TERM_BOT = H - CAPTION_H - 10
LINE_H = 19
ROWS = (TERM_BOT - TERM_TOP) // LINE_H
COLS = int((W - 2 * MARGIN) // ADV)

FPS = 30

# ------------------------------------------------------------------ ANSI/log

SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SCRIPT_LINE = re.compile(r"^Script (started|done) on ")


def parse_capture(path: str) -> list[list[tuple[str, tuple[int, int, int], bool]]]:
    """Read a `script -O` log into styled lines: [(text, colour, bold), ...]."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    raw = raw.replace("\r\n", "\n").replace("\r", "")
    out: list[list[tuple[str, tuple[int, int, int], bool]]] = []
    for physical in raw.split("\n"):
        if SCRIPT_LINE.match(physical):
            continue
        spans: list[tuple[str, tuple[int, int, int], bool]] = []
        colour, bold, pos = FG, False, 0
        for m in SGR.finditer(physical):
            chunk = physical[pos:m.start()]
            if chunk:
                spans.append((chunk, colour, bold))
            for code in (m.group(1) or "0").split(";"):
                n = int(code or 0)
                if n == 0:
                    colour, bold = FG, False
                elif n == 1:
                    bold = True
                elif n == 22:
                    bold = False
                elif n in ANSI_FG:
                    colour = ANSI_FG[n]
            pos = m.end()
        tail = physical[pos:]
        if tail:
            spans.append((tail, colour, bold))
        spans = [(OTHER_CSI.sub("", t), c, b) for t, c, b in spans]
        spans = [s for s in spans if s[0]]
        out.append(spans)
    while out and not out[-1]:
        out.pop()
    while out and not out[0]:
        out.pop(0)
    return [wrapped for line in out for wrapped in _wrap(line)]


def _wrap(spans):
    """Hard-wrap one styled line at COLS characters."""
    if sum(len(t) for t, _, _ in spans) <= COLS:
        return [spans]
    rows, cur, used = [], [], 0
    for text, colour, bold in spans:
        while text:
            room = COLS - used
            take, text = text[:room], text[room:]
            cur.append((take, colour, bold))
            used += len(take)
            if used >= COLS:
                rows.append(cur)
                cur, used = [], 0
    if cur:
        rows.append(cur)
    return rows


# ------------------------------------------------------------------ painting


def _chrome(title_right: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.line([0, HEADER_H, W, HEADER_H], fill=(48, 54, 61))
    d.text((MARGIN, 15), "RoadStar backhaul matcher", font=SANS_B, fill=FG)
    tw = SANS.getlength(title_right)
    d.text((W - MARGIN - tw, 17), title_right, font=SANS, fill=DIM)
    return img, d


def _caption(d: ImageDraw.ImageDraw, lines: list[str]) -> None:
    d.rectangle([0, H - CAPTION_H, W, H], fill=PANEL)
    d.line([0, H - CAPTION_H, W, H - CAPTION_H], fill=(48, 54, 61))
    d.rectangle([0, H - CAPTION_H, 5, H], fill=ACCENT)
    y = H - CAPTION_H + 13
    for i, line in enumerate(lines[:3]):
        d.text((MARGIN, y), line, font=SANS_B if i == 0 else SANS,
               fill=FG if i == 0 else DIM)
        y += 26


def term_frame(lines, caption, header, pin=0) -> Image.Image:
    """Paint a terminal view. The first `pin` rows stay put while the rest
    scroll, so a table's column headings do not leave the screen."""
    img, d = _chrome(header)
    if len(lines) <= ROWS:
        view, rule_at = lines, None
    else:
        head = lines[:pin]
        tail = lines[pin:][-(ROWS - pin - (1 if pin else 0)):]
        view = head + ([[]] if pin else []) + tail
        rule_at = pin if pin else None
    y = TERM_TOP
    for i, spans in enumerate(view):
        if i == rule_at:
            d.line([MARGIN, y + 9, W - MARGIN, y + 9], fill=(48, 54, 61))
        x = MARGIN
        for text, colour, bold in spans:
            d.text((x, y), text, font=MONO_B if bold else MONO, fill=colour)
            x += ADV * len(text)
        y += LINE_H
    _caption(d, caption)
    return img


def card_frame(title, body, footer=None, header="RoadStar Hackathon 2026",
               big=False) -> Image.Image:
    img, d = _chrome(header)
    if big:
        d.text((MARGIN, 210), title, font=TITLE_F, fill=FG)
        y = 285
        for line in body:
            d.text((MARGIN, y), line, font=SUB_F, fill=DIM)
            y += 36
    else:
        d.text((MARGIN, HEADER_H + 34), title, font=CARD_H, fill=ACCENT)
        y = HEADER_H + 92
        for line in body:
            font, fill = CARD_M, FG
            if line.startswith("**"):
                line, font, fill = line[2:], CARD_MB, (255, 255, 255)
            elif line.startswith("~~"):
                line, fill = line[2:], DIM
            d.text((MARGIN, y), line, font=font, fill=fill)
            y += 25
    if footer:
        d.rectangle([0, H - CAPTION_H, W, H], fill=PANEL)
        d.line([0, H - CAPTION_H, W, H - CAPTION_H], fill=(48, 54, 61))
        d.rectangle([0, H - CAPTION_H, 5, H], fill=YELLOW)
        y = H - CAPTION_H + 13
        for i, line in enumerate(footer[:3]):
            d.text((MARGIN, y), line, font=SANS_B if i == 0 else SANS,
                   fill=FG if i == 0 else DIM)
            y += 26
    return img


# ----------------------------------------------------------------- scene ops


def build(scenes, caps_dir, out_mp4):
    work = os.path.join(os.path.dirname(os.path.abspath(out_mp4)), "_frames")
    os.makedirs(work, exist_ok=True)
    for stale in os.listdir(work):
        os.remove(os.path.join(work, stale))

    states: list[tuple[Image.Image, float]] = []
    for sc in scenes:
        if sc["kind"] == "card":
            states.append((card_frame(sc["title"], sc["body"],
                                      sc.get("footer"),
                                      sc.get("header", "RoadStar Hackathon 2026"),
                                      sc.get("big", False)), sc["dur"]))
            continue

        lines = parse_capture(os.path.join(caps_dir, sc["log"]))
        n = len(lines)
        hold = sc.get("hold", 6.0)
        reveal = max(sc["dur"] - hold, 1.0)
        step = max(1, int(round(n / (reveal * 2.2))))  # <= ~2.2 states/second
        idx = 0
        steps = []
        while idx < n:
            idx = min(n, idx + step)
            steps.append(idx)
        per = reveal / len(steps)
        for k, upto in enumerate(steps):
            dur = per if k < len(steps) - 1 else per + hold
            states.append((term_frame(lines[:upto], sc["caption"],
                                      sc.get("header", "RoadStar Hackathon 2026"),
                                      sc.get("pin", 0)),
                           dur))

    listing = os.path.join(work, "concat.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        for i, (img, dur) in enumerate(states):
            png = os.path.join(work, f"f{i:05d}.png")
            img.save(png)
            fh.write(f"file '{png}'\nduration {dur:.4f}\n")
        fh.write(f"file '{png}'\n")

    total = sum(d for _, d in states)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", listing, "-vf", f"fps={FPS},format=yuv420p", "-vsync", "cfr",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-profile:v", "high", "-level", "4.0",
         "-movflags", "+faststart", out_mp4],
        check=True)
    return total, len(states)


# ----------------------------------------------------------------- storyboard

SCENES = [
    {"kind": "card", "big": True, "dur": 11.0,
     "title": "RoadStar backhaul matcher",
     "body": ["Deadhead reduction for freight backhaul.",
              "Which waiting load should each just-emptied truck take?"],
     "footer": [
         "Every figure in this video is computed on SYNTHETIC instances over real public corridor coordinates.",
         "No organiser portal data was read. The portal loader raises rather than falling back to synthetic data."]},

    {"kind": "card", "dur": 17.0, "title": "The problem",
     "body": [
         "A tractor that delivers a load and then drives empty to its next pickup",
         "is running DEADHEAD. Those kilometres earn nothing and still cost fuel,",
         "hours off a driver's legal day, and the load the truck could have taken",
         "instead. The decision that creates them is made per truck, in minutes.",
         "",
         "**The decision:  which waiting load does each just-emptied truck take?",
         "",
         "Three things make it hard, and all three are modelled here:",
         "   trailer compatibility     a reefer load needs a reefer",
         "   pickup time windows       arrive before the window shuts",
         "   hours of service          13 h driving / 14 h on-duty, per duty day",
         "",
         "**The objective is contribution per truck, not nearest-load distance."],
     "footer": ["Judging criterion 1 - Industry Impact & Relevance (25%)."]},

    {"kind": "term", "log": "dispatch.log", "dur": 56.0, "hold": 13.0, "pin": 3,
     "caption": [
         "make dispatch  -  the actual truck -> load assignment for one 40 x 50 instance.",
         "A real recorded run: the dispatch computes in under a second, so playback is slowed to be readable.",
         "Last two rows: T007 and T038 are offered no backhaul worth taking, and the solver declines."]},

    {"kind": "card", "dur": 18.0, "title": "How it decides",
     "body": [
         "**1.  Price every (truck, load) pair against the empty-run alternative",
         "        v = revenue - $1.10/km x (deadhead + loaded km) + $1.10/km x run home",
         "     i.e. what taking this load is worth compared with sending the truck",
         "     home empty - not what it grosses.",
         "",
         "**2.  Solve the assignment exactly",
         "        scipy.optimize.linear_sum_assignment over that matrix.",
         "     An illegal or unprofitable pair is scored at exactly 0, the same as",
         "     leaving the truck unmatched - NOT at a big-M penalty, which would",
         "     force every truck onto some load. Checked against brute force.",
         "",
         "**3.  Decline any pair worth less than the run home",
         "     An empty truck is allowed to stay empty. Two of the 40 trucks did.",
         "",
         "~~Baselines scored on the identical instances: naive_nearest, greedy_feasible,",
         "~~greedy_profit_pairwise, optimal_assignment (deadhead-minimising)."],
     "footer": ["Judging criterion 2 - Innovation & Creativity (20%)."]},

    {"kind": "term", "log": "hos.log", "dur": 30.0, "hold": 9.0,
     "caption": [
         "The hours-of-service rule is tested against the regulated numbers written out as literals,",
         "by an oracle that rebuilds the duty day from primitives without consulting the feasibility code.",
         "Real recorded run: 10 passed in 1.51 s."]},

    {"kind": "card", "dur": 23.0, "title": "This rule has been wrong twice. Both corrections are measured.",
     "body": [
         "  version of the duty-day rule            dispatches it cleared      worst",
         "                                          that are now illegal     duty day",
         "  ---------------------------------------------------------------------------",
         "  empty repositioning drive only          530 of 1145   46.29%      29.38 h",
         "  both drives, no wait at the shipper     379 of 1096   34.58%      21.88 h",
         "**  both drives + shipper wait + overhead   -                         14.00 h",
         "",
         "Waiting at the shipper for the window to open is on-duty not-driving under",
         "both SOR/2005-313 and FMCSA 395.2. The previous revision charged none of it.",
         "",
         "**Charging it made every headline number worse:",
         "**     empty fraction 24.46% -> 31.89%        mean profit $8,222 -> $6,172",
         "",
         "~~That is reported as the result. It is not compensated for anywhere else."],
     "footer": [
         "Found by an independent adversarial audit, not by us.",
         "Table regenerated by tests/test_hos_binds_the_whole_duty_day.py; the two headline moves are the",
         "committed sweeps at git 8f97bb1 and 153deaf, side by side."]},

    {"kind": "term", "log": "guard_green.log", "dur": 11.0, "hold": 7.0,
     "caption": [
         "Every number printed in the README is compared against the committed results JSON by the suite.",
         "17 passed - the shipped prose and the shipped data agree."]},

    {"kind": "term", "log": "fab.log", "dur": 34.0, "hold": 11.0, "pin": 4,
     "caption": [
         "The same guard, on a clean clone, after fabricating exactly one README figure.",
         "$6,172 -> $9,999 in one table cell is enough to turn the suite red.",
         "A claim in this entry cannot drift from the run that produced it without CI saying so."]},

    {"kind": "term", "log": "table.log", "dur": 30.0, "hold": 14.0,
     "caption": [
         "make demo  -  five policies, 30 seeded instances, identical instances for every policy.",
         "profit_assignment: 31.89% empty vs 42.15% for the distance baseline, $3,439 -> $6,172 mean profit.",
         "Read the last two columns too: they charge every truck its run home, and they reverse the ranking."]},

    {"kind": "card", "dur": 26.0, "title": "What this does not do",
     "body": [
         "**Not a road network.   Road km = geodesic x a flat 1.20 circuity factor.",
         "**Partial HOS.          Daily 13 h / 14 h only. No 70 h cycle, no sleeper-berth",
         "                      split, no US rules across the border. Nothing here",
         "                      asserts regulatory compliance.",
         "**Single period.        A matched truck is not charged its run home. Under the",
         "                      fully symmetric boundary every policy loses money and",
         "                      profit_assignment is NOT the best one - it is",
         "                      greedy_profit_pairwise. Both views are in the table.",
         "**Degenerate instances. 19 corridor nodes and a flat rate card make matching",
         "                      easier than a real book of business.",
         "**No provided data.     None of the event's Samsara / Truck Mate / Motive / DAT",
         "                      feeds are used - criterion 4 (15%) is unmet, and said so.",
         "",
         "~~Two adversarial audits returned 37.3/100 and 44.7/100. Five truth defects are closed and",
         "~~verified; the findings that remain open are listed by name in the shipped README."],
     "footer": [
         "An honest smaller entry beats an inflated one.",
         "Nothing in this video is claimed that the repository cannot reproduce."]},

    {"kind": "card", "big": True, "dur": 9.0,
     "title": "Reproduce every number here",
     "body": ["make test      75 tests, green from a clean clone",
              "make sweep     regenerates results/*.json byte-identically",
              "make dispatch  prints the assignment you saw above"],
     "footer": ["RoadStar Hackathon 2026  -  Waterloo, Ontario."]},
]


if __name__ == "__main__":
    caps = sys.argv[1]
    out = sys.argv[2]
    seconds, n_states = build(SCENES, caps, out)
    print(f"OK {out}  planned={seconds:.1f}s states={n_states} cols={COLS} rows={ROWS}")
