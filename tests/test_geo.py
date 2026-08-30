"""Distance tests. The oracle is an independent ellipsoidal solver, not a
hard-coded table, so these tests fail if haversine is wrong rather than if a
transcribed constant is wrong."""

from __future__ import annotations

import itertools
import math

import pytest

from roadstar.geo import CORRIDOR, haversine_km, km_to_miles, road_km, vincenty_inverse_km


def test_zero_distance_is_zero():
    for c in CORRIDOR.values():
        assert haversine_km(c, c) == pytest.approx(0.0, abs=1e-9)
        assert vincenty_inverse_km(c, c) == pytest.approx(0.0, abs=1e-9)


def test_symmetry():
    for a, b in itertools.combinations(CORRIDOR.values(), 2):
        assert haversine_km(a, b) == pytest.approx(haversine_km(b, a), rel=1e-12)


def test_haversine_matches_wgs84_ellipsoid_within_half_a_percent():
    """Sphere vs WGS-84 ellipsoid disagree by a bounded amount, not arbitrarily."""
    worst = 0.0
    for a, b in itertools.combinations(CORRIDOR.values(), 2):
        h, v = haversine_km(a, b), vincenty_inverse_km(a, b)
        assert v > 0
        worst = max(worst, abs(h - v) / v)
    assert worst < 0.005, f"haversine drifts {worst:.4%} from the ellipsoid"


def test_triangle_inequality_holds_across_the_corridor():
    pts = list(CORRIDOR.values())
    for a, b, c in itertools.islice(itertools.permutations(pts, 3), 400):
        assert haversine_km(a, c) <= haversine_km(a, b) + haversine_km(b, c) + 1e-9


def test_toronto_montreal_matches_the_published_great_circle_distance():
    """~505 km is the widely published great-circle figure for this pair."""
    d = haversine_km(CORRIDOR["Toronto, ON"], CORRIDOR["Montreal, QC"])
    assert 495.0 < d < 515.0


def test_road_km_is_a_uniform_multiple_of_the_geodesic():
    a, b = CORRIDOR["Toronto, ON"], CORRIDOR["London, ON"]
    assert road_km(a, b) == pytest.approx(haversine_km(a, b) * 1.20, rel=1e-12)


def test_km_to_miles_roundtrip():
    assert km_to_miles(1.609344) == pytest.approx(1.0, rel=1e-12)


def test_all_corridor_coordinates_are_plausible_north_american_points():
    for name, (lat, lon) in CORRIDOR.items():
        assert 41.0 < lat < 47.0, name
        assert -84.0 < lon < -73.0, name
        assert not math.isnan(lat) and not math.isnan(lon)
