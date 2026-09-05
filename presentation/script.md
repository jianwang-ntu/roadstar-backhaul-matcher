# Speaker script — RoadStar Hackathon 2026

Timings are per slide and are the authority for the deck's total length.
`verify_presentation.py` sums them and checks each block's word count against a
100–165 words-per-minute band, so a slide cannot be given thirty seconds and
four hundred words of script.

Delivery notes: no number in this script is spoken that is not on the slide and
checked. Where a figure is unflattering it is spoken, not skipped.

<!-- script: 1 -->
Good afternoon. I'm a solo entrant, presenting from Singapore.

The question this project answers is the one a dispatcher asks a few hundred
times a day: a tractor has just delivered and gone empty — which of the waiting
loads should it take?

Two things before any number. Everything I show runs on synthetic instances over
real corridor geography. And I did not use the provided RoadStar data — I'll
come back to that, because it costs me a criterion and I want to say so early
rather than have you find it.

<!-- script: 2 -->
When a truck delivers and then drives empty to its next pickup, that empty leg
is deadhead. It's paid for in fuel, in driver hours and in equipment
utilisation, and it earns nothing at all.

What makes the decision hard is that three constraints bite at once.

Trailer compatibility: a reefer load does not go on a dry van. Binary, and
everybody models it.

The pickup window: the truck has to physically reach the shipper inside it, so
the constraint depends on where the truck is right now.

And hours of service: a daily driving ceiling and a daily on-duty ceiling — and
the time the truck spends waiting at the shipper for the window to open is on
duty. That third one is where the difficulty lives, and I'll spend a whole slide
on it, because I got it wrong twice.

Any one of the three can make an otherwise attractive load illegal.

<!-- script: 3 -->
The common shortcut is: send each empty truck to its nearest compatible load.

That optimises distance. The carrier is paid on contribution. Those two come
apart in two ways that matter.

First, a closer load can simply be worth less than a further one.

Second — and this is the one nearest-load dispatch cannot express at all —
sometimes the right answer is to take nothing. If a load earns less than what
the empty run home would have cost you anyway, you should decline it and send
the truck home.

A policy that has no price for the empty run home has no way of saying that.

<!-- script: 4 -->
Five dispatch policies, all scored by one shared definition of a legal dispatch.

Naive nearest is the shortcut I just described. It ignores the pickup window and
hours of service. I keep it as a control.

Greedy feasible is that idea done legally — the nearest load that passes all
three constraints. My distance baseline.

Greedy profit pairwise moves to the right objective: contribution, with the
outside option priced. My profit baseline, and a strong one.

Optimal assignment solves the matching exactly, but on deadhead.

Profit assignment is the entry: the exact assignment maximising contribution net
of the outside option.

The important line is the last one. Feasibility dot py is the only place a
dispatch is judged, and the naive control goes through that same function.
That's why its illegal proposals show up as a number instead of being silently
counted as matches. A comparison where the baseline is allowed to cheat is not a
comparison, and I wanted mine to be able to fail.

<!-- script: 5 -->
Here is the objective. For truck i and load j: the revenue of the load, minus
the cost per kilometre times the sum of the deadhead to the pickup and the
loaded kilometres, plus the cost per kilometre times the truck's repositioning
distance.

That last term is the whole idea. It's the outside option — what this truck
costs the carrier anyway if it takes nothing and runs home empty. Once it's
inside the objective, a load that's worth less than the run home scores
negative, and the assignment declines it. Declining becomes an outcome the
optimiser can choose rather than a special case bolted on afterwards.

The assignment itself is solved exactly, Jonker–Volgenant, through SciPy's
linear sum assignment.

And because a solver that quietly drops a row would look like a better answer,
it's checked against brute-force enumeration on small instances by an oracle
that derives the matching cardinality itself instead of accepting whatever the
solver returned.

<!-- script: 6 -->
Forty trucks, fifty loads, thirty seeded instances. Paired: every policy sees
the identical instances under identical feasibility rules.

Read the last column first. The naive control proposes seven hundred and
ninety-five illegal dispatches across the sweep. That's not a footnote about the
control — it's the reason the control exists. Every other policy proposes zero.

Down the profit column: the distance baseline earns three thousand four hundred
and thirty-nine dollars a scenario. The profit baseline earns five thousand
three hundred and twenty-one. The entry earns six thousand one hundred and
seventy-two.

Against the distance baseline that's a median per-instance improvement of
sixty-two point four nine per cent, a ratio of means of seventy-nine point four
six, and it wins thirty instances out of thirty. Deadhead falls eighteen per
cent.

But the comparison I'd actually defend is the one against the profit baseline,
because that baseline already optimises the right thing. There the improvement
is eighteen point two one per cent on the mean, fourteen point nine on the
median, and thirty wins, no draws, no losses.

<!-- script: 7 -->
Three things about those numbers you should be told rather than left to find.

First: do not quote the biggest percentage. Against the distance baseline, the
mean of the per-instance ratios is a hundred and fifty-two per cent — with a
standard deviation of two hundred and ninety points. The baseline earns
near-zero profit on a few instances and those ratios dominate. The defensible
statements are the median, the ratio of means, and the absolute dollars. Both
are printed side by side in the repository, deliberately.

Second: most of the empty-fraction improvement is denominator growth, not
emptier trucks. The empty fraction falls ten point two six points. Four and a
half come from driving fewer empty kilometres. Five point seven — fifty-five per
cent of the gain — come from hauling more loaded ones, because the policy picks
longer loads. Mean matched length goes from two hundred and eight kilometres to
two hundred and forty-two.

Third: the exact solve is the smaller half of the gap. Changing the objective
gets most of it. Solving it exactly adds the eighteen per cent. Reporting only
the total would credit my solver with a gain that mostly comes from scoring the
right thing.

<!-- script: 8 -->
This is where I got it wrong twice, both times in the flattering direction.

My first hours-of-service rule charged only the empty repositioning drive. Under
the rule that ships, five hundred and thirty of the eleven hundred and forty-five
dispatches it cleared are illegal — forty-six per cent — and its worst modelled
duty day was twenty-nine point four hours. There is no twenty-nine hour duty day.

The second version charged both drives but not the wait at the shipper. Still
three hundred and seventy-nine illegal, thirty-four per cent, worst day
twenty-one point nine hours.

The rule that ships charges both drives, the wait, and pickup overhead. Worst
modelled duty day: fourteen hours.

Waiting at the shipper is on-duty-not-driving under both the Canadian and the US
regulations, and the version that charged none of it had a mean wait of a hundred
and ninety minutes on its accepted dispatches.

One charity remains, and I count it: a wait of eight hours or more is treated as
the off-duty period that resets the shift, unverified. A hundred and eighty-four
of one thousand and fifty-one accepted dispatches — seventeen and a half per
cent — depend on that reading.

That table is regenerated by a test, so it fails the build rather than ageing
quietly.

<!-- script: 9 -->
And here is the boundary that reverses my headline.

A truck that takes no backhaul is charged its empty run to domicile. A truck
that takes one is not charged the empty run home from wherever it drops. That's
a single-period boundary, and it is not symmetric.

Which means my primary empty fractions are lower bounds and my primary profits
are upper bounds.

The fully symmetric figures are in the same results file. Under that boundary,
every policy is loss-making, and my entry is not the best one — the greedy
profit baseline is, at minus four thousand one hundred and eighty-nine dollars
against my minus four thousand three hundred and ninety.

I'm telling you that from the stage because it's what the runs did. If the
single-period boundary is the wrong one for your operation, my headline is the
wrong number for your operation.

<!-- script: 10 -->
This repository was audited adversarially twice, by independent reviewers holding
only the code and your published rules — not my plan, not my build notes.

Round one: major revision required, thirty-seven out of a hundred, fifteen defects.

Round two: not fit to submit, a mean of forty-four point seven, thirty-four
findings. A lower score after a revision, and the reason is worth saying — round
one had closed defects one at a time while leaving their classes open.

The second revision closed the five findings that made the repository state
things that were not true. The findings that remain open are listed in the README
and in the write-up. They are not closed quietly.

Note the direction of the correction: the fixed model is less flattering than the
broken one in every column. Empty fraction moved from twenty-four per cent to
thirty-two, and mean profit fell from eight thousand two hundred to six thousand
two hundred.

<!-- script: 11 -->
Criterion four. Use of provided data and APIs, fifteen per cent of your rubric.
It is unmet, and I'm claiming it as unmet.

The Samsara, Truck Mate, Motive, DAT and Loadlink resources, and the CSV, JSON
and SQL drops, are distributed through the participant portal. I don't hold a
participant account, so I read none of them. Not a partial integration, not a
sample — none.

The loader for that data exists in the code. It raises rather than falling back
to synthetic data, specifically so that no run of mine can report portal-derived
numbers it never had.

I would rather be marked at one on this criterion than describe a synthetic run
as if it came from your tables.

<!-- script: 12 -->
The demo video is four minutes twenty-five, inside your three-to-five minute
band. It's recorded terminal sessions, not slides of terminal sessions.

The segment I'd point you at is the one where the README-versus-results guard
goes red on a clean clone, because I fabricated a single figure to see whether
the guard would catch it.

Reproducing this is four commands. Clone, install, make test — seventy-six tests
— and make sweep, which regenerates both results files byte-identically.

And the check that matters most to me: deleting the loaded leg from the
hours-of-service rule, deleting the shipper wait, or raising either ceiling all
turn the suite red.

<!-- script: 13 -->
To close, plainly.

What I am claiming: a dispatch objective that prices the outside option, solved
exactly, beats a strong profit-greedy baseline by eighteen per cent on thirty
paired synthetic instances, under a duty-day model that charges the shipper wait.

What I am not claiming: this is not a measurement of any real carrier's fleet.
No routed distances — geodesic times a fixed circuity factor of one point two.
Hours of service is partial, and nothing here asserts regulatory compliance.
Single period. And the instances come from nineteen corridor nodes, which makes
them easier than a real book of business.

The honest next step is your freight tables. Same objective, same feasibility
function, your data instead of mine.

Thank you — I'm happy to take questions.
