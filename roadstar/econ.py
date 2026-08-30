"""Cost model.

One stated constant, applied uniformly. It is a modelling assumption, not a
measurement of any carrier's cost base, and it is reported as such wherever a
dollar figure derived from it appears.
"""

from __future__ import annotations

from typing import Final

from .models import Load

#: All-in operating cost per kilometre (fuel, driver, maintenance, tractor).
#: A stated assumption. Every profit number in this project scales with it, so
#: it is surfaced in the results payload rather than buried.
OPERATING_COST_USD_PER_KM: Final[float] = 1.10


def match_value_usd(deadhead_km: float, load: Load, outside_option_usd: float) -> float:
    """Contribution of running `load` versus the truck's empty alternative."""
    running = OPERATING_COST_USD_PER_KM * (deadhead_km + load.loaded_km)
    return load.revenue_usd - running + outside_option_usd


def profit_usd(deadhead_km: float, loaded_km: float, revenue_usd: float) -> float:
    return revenue_usd - OPERATING_COST_USD_PER_KM * (deadhead_km + loaded_km)
