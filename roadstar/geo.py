"""Geodesic distance and the fixed corridor geography.

Two independent distance implementations live here on purpose. `haversine_km`
is the one the matcher uses; `vincenty_inverse_km` is a WGS-84 ellipsoidal
solver used only by the test suite as an independent oracle. Agreement between
a sphere and an ellipsoid is bounded at roughly 0.5%, so the differential test
asserts that bound rather than exact equality.

City coordinates are the public decimal-degree centroids of the freight
corridor this build targets (Ontario/Quebec + the Michigan/New York border
crossings). They are real; the loads placed on them are synthetic and are
labelled as such everywhere they surface.
"""

from __future__ import annotations

import math
from typing import Final

EARTH_RADIUS_KM: Final[float] = 6371.0088  # IUGG mean radius
KM_PER_MILE: Final[float] = 1.609344

# WGS-84
_WGS84_A: Final[float] = 6378137.0
_WGS84_F: Final[float] = 1 / 298.257223563
_WGS84_B: Final[float] = _WGS84_A * (1 - _WGS84_F)

Coord = tuple[float, float]

#: Real decimal-degree coordinates. Source: public city centroids, rounded to
#: 4 dp (~11 m), which is far below any resolution this model needs.
CORRIDOR: Final[dict[str, Coord]] = {
    "Toronto, ON": (43.6532, -79.3832),
    "Mississauga, ON": (43.5890, -79.6441),
    "Brampton, ON": (43.7315, -79.7624),
    "Waterloo, ON": (43.4643, -80.5204),
    "Kitchener, ON": (43.4516, -80.4925),
    "Cambridge, ON": (43.3616, -80.3144),
    "Guelph, ON": (43.5448, -80.2482),
    "Hamilton, ON": (43.2557, -79.8711),
    "London, ON": (42.9849, -81.2453),
    "Windsor, ON": (42.3149, -83.0364),
    "Sarnia, ON": (42.9745, -82.4066),
    "Woodstock, ON": (43.1306, -80.7467),
    "Barrie, ON": (44.3894, -79.6903),
    "Oshawa, ON": (43.8971, -78.8658),
    "Kingston, ON": (44.2312, -76.4860),
    "Ottawa, ON": (45.4215, -75.6972),
    "Montreal, QC": (45.5019, -73.5674),
    "Detroit, MI": (42.3314, -83.0458),
    "Buffalo, NY": (42.8864, -78.8784),
}


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance on a sphere of radius EARTH_RADIUS_KM."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def vincenty_inverse_km(a: Coord, b: Coord, *, max_iter: int = 200, tol: float = 1e-12) -> float:
    """Vincenty inverse solution on the WGS-84 ellipsoid. Test oracle only.

    Raises ValueError if the iteration does not converge (near-antipodal
    points), which never occurs inside this corridor.
    """
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    if abs(lat1 - lat2) < 1e-15 and abs(lon1 - lon2) < 1e-15:
        return 0.0

    L = lon2 - lon1
    U1 = math.atan((1 - _WGS84_F) * math.tan(lat1))
    U2 = math.atan((1 - _WGS84_F) * math.tan(lat2))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lam = L
    for _ in range(max_iter):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt(
            (cosU2 * sin_lam) ** 2 + (cosU1 * sinU2 - sinU1 * cosU2 * cos_lam) ** 2
        )
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha**2
        cos2sigma_m = 0.0 if cos_sq_alpha == 0 else cos_sigma - 2 * sinU1 * sinU2 / cos_sq_alpha
        C = _WGS84_F / 16 * cos_sq_alpha * (4 + _WGS84_F * (4 - 3 * cos_sq_alpha))
        lam_prev = lam
        lam = L + (1 - C) * _WGS84_F * sin_alpha * (
            sigma + C * sin_sigma * (cos2sigma_m + C * cos_sigma * (-1 + 2 * cos2sigma_m**2))
        )
        if abs(lam - lam_prev) < tol:
            break
    else:
        raise ValueError("Vincenty did not converge")

    u_sq = cos_sq_alpha * (_WGS84_A**2 - _WGS84_B**2) / _WGS84_B**2
    A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    d_sigma = (
        B
        * sin_sigma
        * (
            cos2sigma_m
            + B
            / 4
            * (
                cos_sigma * (-1 + 2 * cos2sigma_m**2)
                - B / 6 * cos2sigma_m * (-3 + 4 * sin_sigma**2) * (-3 + 4 * cos2sigma_m**2)
            )
        )
    )
    return _WGS84_B * A * (sigma - d_sigma) / 1000.0


def road_km(a: Coord, b: Coord, *, circuity: float = 1.20) -> float:
    """Road distance estimated from the geodesic by a fixed circuity factor.

    NOT a routed distance. 1.20 is a stated modelling assumption applied
    uniformly to every leg, so it cancels out of every ratio this project
    reports (empty-mile fraction, percentage reduction) and shifts only the
    absolute kilometre totals. See README 'What this does not do'.
    """
    return haversine_km(a, b) * circuity


def km_to_miles(km: float) -> float:
    return km / KM_PER_MILE
