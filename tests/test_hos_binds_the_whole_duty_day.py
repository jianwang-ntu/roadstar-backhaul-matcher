"""C3 must bind on the WHOLE duty day, and this suite must be able to tell.

Round-2 audit, domain lens, three findings that are really one:

  DOMAIN-01  the hours-of-service check charged no time for waiting at the
             shipper, so 42.79% of the dispatches the previous revision called
             legal blew the 14 h on-duty ceiling once the wait was charged, and
             the worst modelled duty day was 24.45 h.
  DOMAIN-02  deleting the loaded leg from the feasibility check -- reverting the
             fix the previous README led with -- passed all 52 tests and
             regenerated the flattering pre-fix headline to the cent.
  DOMAIN-03  the two hours-of-service tests recomputed their boundary from the
             constant under test, so both ceilings could be set to 30 h and the
             suite stayed green.

A constraint whose removal does not turn the suite red is not tested, whatever
the pass count says. So the oracle below does not call `hos_ok` or `violations`.
It reconstructs the duty day from primitives -- the truck's opening clock, the
two drives, the shipper wait, the pickup overhead -- and compares it against the
regulated ceilings written out as LITERALS. Any of the three defects above makes
it fail:

  drop the loaded leg   -> accepted dispatches exceed the recomputed ceiling
  drop the shipper wait -> accepted dispatches exceed the recomputed ceiling
  raise the ceilings    -> the literals here do not move, so the same happens
"""

from __future__ import annotations

import pytest

from roadstar.feasibility import is_feasible, leg, loaded_drive_minutes, violations
from roadstar.geo import CORRIDOR, road_km
from roadstar.hos import drive_minutes, hos_ok
from roadstar.instance import make_instance
from roadstar.models import Equipment, Load, Truck
from roadstar.policies import POLICIES

# SOR/2005-313 south-of-60 day limits, and this project's stated pickup
# overhead, written out rather than imported. See DOMAIN-03.
CEILING_DRIVE_MIN = 780
CEILING_ONDUTY_MIN = 840
PICKUP_OVERHEAD_MIN = 45
RESET_OFF_DUTY_MIN = 480

CONSTRAINT_AWARE = ["greedy_feasible", "optimal_assignment",
                    "greedy_profit_pairwise", "profit_assignment"]

#: The headline sweep configuration. The numbers this file asserts are the
#: numbers README.md prints, so a model change fails here before it can reach a
#: judge.
SWEEP = dict(n_trucks=40, n_loads=50, seeds=range(1000, 1030))


def _duty_day(truck: Truck, load: Load) -> tuple[int, int, int]:
    """(driving minutes, on-duty minutes, shipper wait) for one dispatch.

    Rebuilt from the primitive quantities. Deliberately does not consult
    `hos_ok`, `violations` or `Leg.wait_min`, so it stays a real oracle when
    those are the thing that is broken.
    """
    deadhead_min = drive_minutes(road_km(truck.at, load.origin))
    arrive = truck.free_from_min + deadhead_min
    wait = max(0, load.pickup_open_min - arrive)
    charged_wait = 0 if wait >= RESET_OFF_DUTY_MIN else wait
    loaded_min = drive_minutes(load.loaded_km)
    driving = truck.drive_used_min + deadhead_min + loaded_min
    onduty = (truck.onduty_used_min + deadhead_min + loaded_min
              + PICKUP_OVERHEAD_MIN + charged_wait)
    return driving, onduty, wait


@pytest.mark.parametrize("name", CONSTRAINT_AWARE)
def test_no_accepted_dispatch_exceeds_the_duty_day(name):
    """The headline sweep, every policy, every accepted dispatch."""
    worst_drive = worst_onduty = 0
    checked = 0
    for seed in SWEEP["seeds"]:
        trucks, loads = make_instance(SWEEP["n_trucks"], SWEEP["n_loads"], seed=seed)
        by_t = {t.truck_id: t for t in trucks}
        by_l = {ld.load_id: ld for ld in loads}
        for a in POLICIES[name](trucks, loads).assignments:
            driving, onduty, _ = _duty_day(by_t[a.truck_id], by_l[a.load_id])
            assert driving <= CEILING_DRIVE_MIN, (name, seed, a.truck_id, driving)
            assert onduty <= CEILING_ONDUTY_MIN, (name, seed, a.truck_id, onduty)
            worst_drive = max(worst_drive, driving)
            worst_onduty = max(worst_onduty, onduty)
            checked += 1
    assert checked > 900, f"{name}: only {checked} dispatches checked"
    # A ceiling nobody ever reaches is not evidence that the ceiling binds.
    assert worst_onduty > CEILING_ONDUTY_MIN - 60, worst_onduty


def _accepted_under(rule, policy="profit_assignment"):
    """Run `policy` with `rule` standing in for the feasibility definition and
    return its dispatches. Used to measure what the two PREVIOUS versions of C3
    were letting through, judged by the one that ships now."""
    import roadstar.feasibility as F
    import roadstar.policies as P

    saved_v, saved_f, saved_pf = F.violations, F.is_feasible, P.is_feasible
    F.violations = rule
    F.is_feasible = P.is_feasible = lambda t, l: not rule(t, l)
    try:
        out = []
        for seed in SWEEP["seeds"]:
            trucks, loads = make_instance(SWEEP["n_trucks"], SWEEP["n_loads"], seed=seed)
            by_t = {t.truck_id: t for t in trucks}
            by_l = {ld.load_id: ld for ld in loads}
            out += [(by_t[a.truck_id], by_l[a.load_id])
                    for a in P.POLICIES[policy](trucks, loads).assignments]
        return out
    finally:
        F.violations, F.is_feasible, P.is_feasible = saved_v, saved_f, saved_pf


def _rule_pre_d1(truck: Truck, load: Load) -> tuple[str, ...]:
    """C3 as it stood before round-1 finding D1: the empty leg only."""
    from roadstar.models import can_haul
    bad = []
    if not can_haul(truck.trailer, load.requires):
        bad.append("C1_trailer")
    deadhead_min = drive_minutes(road_km(truck.at, load.origin))
    if truck.free_from_min + deadhead_min > load.pickup_close_min:
        bad.append("C2_window")
    if (truck.drive_used_min + deadhead_min > CEILING_DRIVE_MIN
            or truck.onduty_used_min + deadhead_min + PICKUP_OVERHEAD_MIN > CEILING_ONDUTY_MIN):
        bad.append("C3_hos")
    return tuple(bad)


def _rule_no_wait(truck: Truck, load: Load) -> tuple[str, ...]:
    """C3 as round 2 audited it: both drives, but the shipper wait unpriced."""
    from roadstar.models import can_haul
    bad = []
    if not can_haul(truck.trailer, load.requires):
        bad.append("C1_trailer")
    deadhead_min = drive_minutes(road_km(truck.at, load.origin))
    if truck.free_from_min + deadhead_min > load.pickup_close_min:
        bad.append("C2_window")
    added = deadhead_min + drive_minutes(load.loaded_km)
    if (truck.drive_used_min + added > CEILING_DRIVE_MIN
            or truck.onduty_used_min + added + PICKUP_OVERHEAD_MIN > CEILING_ONDUTY_MIN):
        bad.append("C3_hos")
    return tuple(bad)


def test_the_two_earlier_hos_rules_are_measurably_illegal_under_this_one():
    """The severity figures README.md quotes for D1 and DOMAIN-01, regenerated.

    Both are stated as a share of the winning policy's OWN accepted dispatches
    under the rule being retired, judged by the rule that ships. If either
    number in the README drifts from what the code does, this fails.
    """
    for rule, label, n_expect, bad_expect, pct_expect, worst_h in (
        (_rule_pre_d1, "pre-D1 (empty leg only)", 1145, 530, 46.29, 29.38),
        (_rule_no_wait, "round-2 audited (wait unpriced)", 1096, 379, 34.58, 21.88),
    ):
        pairs = _accepted_under(rule)
        illegal = [1 for t, l in pairs if violations(t, l)]
        worst = max(_duty_day(t, l)[1] for t, l in pairs)
        assert len(pairs) == n_expect, (label, len(pairs))
        assert len(illegal) == bad_expect, (label, len(illegal))
        assert round(100 * len(illegal) / len(pairs), 2) == pct_expect, label
        assert round(worst / 60, 2) == worst_h, (label, worst / 60)


def test_the_shipped_rule_reaches_the_ceiling_and_never_passes_it():
    """Worst modelled duty day under the rule that ships: exactly 14.00 h."""
    worst = 0
    for seed in SWEEP["seeds"]:
        trucks, loads = make_instance(SWEEP["n_trucks"], SWEEP["n_loads"], seed=seed)
        by_t = {t.truck_id: t for t in trucks}
        by_l = {ld.load_id: ld for ld in loads}
        for a in POLICIES["profit_assignment"](trucks, loads).assignments:
            worst = max(worst, _duty_day(by_t[a.truck_id], by_l[a.load_id])[1])
    assert worst == CEILING_ONDUTY_MIN, worst


def test_how_many_accepted_dispatches_lean_on_the_eight_hour_reset():
    """The model's one charity, counted rather than mentioned.

    A wait of 8 h or more is treated as the qualifying off-duty period that ends
    a shift, without checking that the driver took it off duty. This is the
    number README.md prints for how much of the result depends on that reading.
    """
    total = leaning = 0
    for seed in SWEEP["seeds"]:
        trucks, loads = make_instance(SWEEP["n_trucks"], SWEEP["n_loads"], seed=seed)
        by_t = {t.truck_id: t for t in trucks}
        by_l = {ld.load_id: ld for ld in loads}
        for a in POLICIES["profit_assignment"](trucks, loads).assignments:
            total += 1
            if _duty_day(by_t[a.truck_id], by_l[a.load_id])[2] >= RESET_OFF_DUTY_MIN:
                leaning += 1
    assert (total, leaning) == (1051, 184), (total, leaning)
    assert round(100 * leaning / total, 2) == 17.51


def _pair(*, at, origin, dest, drive_used, onduty_used, free_from, pickup_open,
          pickup_close=10_000) -> tuple[Truck, Load]:
    o, d = CORRIDOR[origin], CORRIDOR[dest]
    truck = Truck(truck_id="T", at=CORRIDOR[at], at_name=at, free_from_min=free_from,
                  trailer=Equipment.DRY_VAN, drive_used_min=drive_used,
                  onduty_used_min=onduty_used, domicile_name=at)
    load = Load(load_id="L", origin=o, origin_name=origin, dest=d, dest_name=dest,
                pickup_open_min=pickup_open, pickup_close_min=pickup_close,
                requires=Equipment.DRY_VAN, revenue_usd=10_000.0, loaded_km=road_km(o, d))
    return truck, load


def test_a_dispatch_whose_LOADED_leg_breaks_the_ceiling_is_refused():
    """DOMAIN-02, at the unit level: the empty leg alone fits, the loaded leg
    does not, and the dispatch must be refused. Deleting `loaded_drive_minutes`
    from feasibility.violations turns this red."""
    truck, load = _pair(at="Toronto, ON", origin="Toronto, ON", dest="Montreal, QC",
                        drive_used=700, onduty_used=700, free_from=0, pickup_open=0)
    assert leg(truck, load).drive_min == 0, "the empty leg must be the trivial one"
    assert loaded_drive_minutes(load) > 80, "the loaded leg must be the binding one"
    assert hos_ok(700, 700, 0, wait_min=0) is True, "control: without it, legal"
    assert "C3_hos" in violations(truck, load)
    assert not is_feasible(truck, load)


def test_a_dispatch_whose_SHIPPER_WAIT_breaks_the_ceiling_is_refused():
    """DOMAIN-01, at the unit level: both drives fit, the wait does not.
    Dropping `wait_min` from the hos_ok call turns this red."""
    truck, load = _pair(at="Toronto, ON", origin="Toronto, ON", dest="Hamilton, ON",
                        drive_used=0, onduty_used=600, free_from=0, pickup_open=200)
    lg = leg(truck, load)
    assert lg.drive_min == 0 and lg.wait_min == 200
    loaded = loaded_drive_minutes(load)
    assert 600 + loaded + PICKUP_OVERHEAD_MIN <= CEILING_ONDUTY_MIN, "control: fits without the wait"
    assert 600 + loaded + PICKUP_OVERHEAD_MIN + 200 > CEILING_ONDUTY_MIN, "and not with it"
    assert "C3_hos" in violations(truck, load)
    assert not is_feasible(truck, load)


def test_the_eight_hour_reset_is_the_only_wait_that_is_forgiven():
    """The same pair, once with a wait one minute short of the reset and once at
    it. Removing the carve-out, or widening it, moves exactly one of these."""
    short = _pair(at="Toronto, ON", origin="Toronto, ON", dest="Hamilton, ON",
                  drive_used=0, onduty_used=600, free_from=0, pickup_open=479)
    long_ = _pair(at="Toronto, ON", origin="Toronto, ON", dest="Hamilton, ON",
                  drive_used=0, onduty_used=600, free_from=0, pickup_open=480)
    assert leg(*short).wait_min == 479 and leg(*long_).wait_min == 480
    assert not is_feasible(*short)
    assert is_feasible(*long_)
