# RoadStar Hackathon 2026 — live presentation deck

Source of the rubric this deck answers: `demo/judging_rubric.json`, pinned from
https://roadstarhackathon.com/judging.

Every figure on these slides is checked against a primary artifact by
`verify_presentation.py`. Nothing here is a round number chosen for a slide.

<!-- slide: 1 | seconds: 40 | criteria: - -->
## Backhaul matching under hours of service

**Which waiting load should this just-emptied tractor take?**

Solo entrant · Singapore · RoadStar Hackathon 2026

- Code: `github.com/jianwang-ntu/roadstar-backhaul-matcher`
- Demo: `demo/roadstar_demo.mp4` in that same repository
- Everything below runs on **synthetic instances over real corridor geography**.
  No RoadStar portal data was read.

---

<!-- slide: 2 | seconds: 60 | criteria: C1 -->
## The decision, and what it costs to get wrong

A tractor delivers, goes empty, and drives to its next pickup. That empty leg is
**deadhead**: paid for in fuel, driver hours and equipment, and it earns nothing.

The dispatcher's decision is made under three hard constraints *at once*:

| | constraint | why it bites |
|---|---|---|
| **C1** | trailer compatibility | a reefer load does not go on a dry van |
| **C2** | pickup window | the truck has to physically reach the shipper inside it |
| **C3** | hours of service | daily driving **and** on-duty ceilings — and *waiting at the shipper is on duty* |

Any one of the three can make an otherwise attractive load illegal.

---

<!-- slide: 3 | seconds: 45 | criteria: C1 C2 -->
## "Send it to the nearest load" optimises the wrong quantity

Nearest-load dispatch minimises **distance**. The carrier is paid on
**contribution**.

Those come apart in two ways that matter:

- a closer load can be worth less than a further one, and
- **sometimes the right answer is to take nothing** — send the truck home rather
  than haul a load that earns less than the empty run home costs.

A policy with no price for the empty run home cannot express the second answer.

---

<!-- slide: 4 | seconds: 70 | criteria: C2 C3 -->
## What was built

Five dispatch policies, scored by **one** shared definition of a legal dispatch.

| policy | what it does |
|---|---|
| `naive_nearest` | nearest compatible load, ignores C2 and C3 — the shortcut, kept as a control |
| `greedy_feasible` | nearest **legal** load — the distance baseline |
| `greedy_profit_pairwise` | greedy on contribution, outside option priced — the profit baseline |
| `optimal_assignment` | exact assignment minimising matched deadhead |
| **`profit_assignment`** | **the entry** — exact assignment maximising contribution net of the outside option |

`roadstar/feasibility.py` is the **only** place a dispatch is judged. The naive
control is scored by that same function, which is why its illegal proposals
appear as a number instead of being quietly counted as matches.

A comparison in which the baseline is allowed to cheat is not a comparison.

---

<!-- slide: 5 | seconds: 80 | criteria: C2 -->
## The objective, and the outside option

For truck *i* and load *j*:

```
v_ij  =  revenue_j  −  cost_per_km × (deadhead_ij + loaded_km_j)
                    +  cost_per_km × reposition_i
```

That last term is the **outside option**: what the truck costs the carrier
anyway if it takes nothing. Pricing it inside the objective is what lets the
dispatcher correctly **decline**.

Solved exactly — Jonker–Volgenant, via `scipy.optimize.linear_sum_assignment` —
and checked against brute-force enumeration on small instances by an oracle that
derives the matching **cardinality** itself rather than accepting the solver's.

**And it declines.** On the demo instance `make dispatch` matches **38 of 40**
trucks and prints the other two as *no backhaul worth taking*; across the sweep
the policy leaves at least one truck deliberately unmatched on **29 of 30**
instances.

---

<!-- slide: 6 | seconds: 75 | criteria: C1 C3 -->
## Results

40 trucks × 50 loads, 30 seeded instances, **paired** — every policy sees the
identical instances under the identical feasibility rules.

| policy | mean deadhead km | empty fraction | mean profit | illegal proposed |
|---|---:|---:|---:|---:|
| `naive_nearest` | 7718.6 | 75.03% | -$4,949 | **795** |
| `greedy_feasible` (distance baseline) | 4872.5 | 42.15% | $3,439 | 0 |
| `greedy_profit_pairwise` (profit baseline) | 4157.9 | 34.21% | $5,321 | 0 |
| `optimal_assignment` | 4391.4 | 35.64% | $5,379 | 0 |
| **`profit_assignment`** | **3996.1** | **31.89%** | **$6,172** | 0 |

Against the **distance** baseline: median per-instance profit improvement
**+62.485%**, ratio of means **+79.460%**, winning **30 of 30**.
Deadhead falls **-18.0%**.

Against the **profit** baseline — the harder comparison, because it already
optimises the right objective — **+18.207%** mean, **+14.886%** median, 30/0/0.

---

<!-- slide: 7 | seconds: 75 | criteria: C1 C3 -->
## Three things about those numbers you should be told, not left to find

**1. Do not quote the biggest percentage.** Against the distance baseline the
*mean of per-instance ratios* is **+151.993%** with a standard deviation of
**290.436** points, because the baseline earns near-zero profit on some
instances and dominates the ratio. The defensible statements are the median,
the ratio of means, and the absolute dollars. Both statistics are printed side
by side in the repository for exactly this reason.

**2. Most of the empty-fraction gain is denominator growth.** The empty fraction
falls **10.26** points, of which **4.55** points come from driving fewer empty
kilometres and **5.71** points — **55.6%** — from hauling more loaded ones: the
policy selects *longer* loads, mean matched length **208.2** km → **242.2** km.

**3. The exact solve is the smaller half of the gap.** Changing the objective
gets most of it; solving it exactly adds **+18.207%**. Reporting only the total
would credit the solver with a gain that mostly comes from scoring the right thing.

---

<!-- slide: 8 | seconds: 85 | criteria: C3 -->
## Hours of service charges the whole duty day

This was wrong twice, both times in the flattering direction. Both corrections
are **measured**, and the table is regenerated by a test, so it fails CI rather
than ageing quietly.

| version of the C3 rule | dispatches it cleared that the current rule calls illegal | worst duty day |
|---|---:|---:|
| empty repositioning drive only | **530 of 1145 — 46.29%** | 29.38 h |
| both drives, no shipper wait | **379 of 1096 — 34.58%** | 21.88 h |
| **shipped: both drives + shipper wait + pickup overhead** | — | **14.00 h** |

Waiting at the shipper for the window to open is on-duty-not-driving under both
SOR/2005-313 and FMCSA 395.2. The revision that charged none of it had a mean
wait of **190** minutes on its accepted dispatches — a ceiling that binds on
part of the duty day is not a ceiling.

**One charity in the model, counted.** A wait of 8 h or more is treated as the
qualifying off-duty period that ends a shift, unverified. **184 of 1051**
accepted dispatches — **17.51%** — depend on that reading.

---

<!-- slide: 9 | seconds: 60 | criteria: C3 -->
## The accounting boundary — and it reverses the headline

A truck that takes **no** backhaul is charged its empty run to domicile. A truck
that **takes** one is not charged the empty run home from where it drops.

So the primary empty fractions are **lower bounds** and the primary profits are
**upper bounds**.

The fully symmetric figures are printed in the same table. Under that boundary:

- every policy is **loss-making**, and
- **`profit_assignment` is not the best one** — `greedy_profit_pairwise` is,
  at **-$4,189** against **-$4,390**.

That is on the slide because it is what the runs did.

---

<!-- slide: 10 | seconds: 60 | criteria: C3 -->
## How this was reviewed, and what is still open

Audited adversarially **twice**, by independent reviewers holding only the code
and the published rules — not the plan, not the build notes.

- Round 1: `MAJOR_REVISION_REQUIRED` at **37.28** / 100 over **15** defects.
- Round 2: `NOT_FIT_TO_SUBMIT` at a mean of **44.67** / 100 over **34** findings
  — a *lower* score, because round 1's revision had closed defects one at a time
  while leaving their classes open.

The second revision closed the five findings that made the repository state
things that were not true. **The findings that remain open are listed in the
README and in the write-up, not closed quietly.**

The corrected model is **less flattering** than the defective one in every
column: empty fraction moved 24.46% → 31.89%, mean profit $8,222 → $6,172.

---

<!-- slide: 11 | seconds: 50 | criteria: C4 -->
## Criterion 4: I did not use the provided data

**Use of Provided Data & APIs — 15% of this rubric — is UNMET, and I am claiming
it as unmet.**

The Samsara / Truck Mate / Motive / DAT / Loadlink resources and the CSV, JSON
and SQL drops are distributed through the RoadStar participant portal. I do not
hold a participant account, so I read none of them.

`roadstar/instance.py::load_portal_instance` is the seam where that data
attaches. It **raises** rather than falling back to synthetic data, so no run
can report portal-derived numbers it did not have.

I would rather be marked at 1 on this criterion than describe a synthetic run as
if it came from your tables.

---

<!-- slide: 12 | seconds: 45 | criteria: C5 -->
## Demo, and reproducing this

The demo video is **4 min 25 s** — inside the 3–5 minute band — and is built
from `script(1)` recordings of real terminal sessions, not from slides of them.
One segment shows the README-vs-results guard turned **red** on a clean clone by
fabricating a single figure.

```
git clone https://github.com/jianwang-ntu/roadstar-backhaul-matcher
pip install -r requirements.txt
make test      # 76 tests
make sweep     # regenerates results/*.json byte-identically
make dispatch  # prints the actual truck -> load dispatch
```

Deleting the loaded leg from the HOS rule, deleting the shipper wait, or raising
either ceiling all turn the suite **red**.

---

<!-- slide: 13 | seconds: 55 | criteria: C1 C2 C3 C4 C5 -->
## What I am claiming, and what I am not

**Claiming.** A dispatch objective that prices the outside option, solved
exactly, beats a strong profit-greedy baseline by **+18.207%** on 30 paired
synthetic instances under a duty-day model that charges the shipper wait.

**Not claiming.** Not a measurement of any real carrier's fleet. No routed
distances — geodesic × a fixed **1.20** circuity factor. Partial hours of
service; **nothing here asserts regulatory compliance**. Single period, one
round of matching. The instances are drawn from **19** corridor nodes and are
easier than a real book of business.

**The honest next step** is the portal freight tables — the same objective, the
same feasibility function, on your data instead of mine.
