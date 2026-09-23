"""Position sizing. Fixed-fractional between a floor and a ceiling."""
import math

from guard.optconfig import OptionConfig


def size_position(account_value: float, cfg: OptionConfig) -> float:
    """Dollars to deploy on one position, or 0.0 when the account is too
    small to buy a sane contract.

    Below the floor there is nothing worth buying: the cheapest reasonable
    contracts observed were ~$36, and going lower forces far-OTM lottery
    tickets. So an account that cannot fund the floor does not trade at all
    rather than trading badly.
    """
    if not isinstance(account_value, (int, float)) or isinstance(account_value, bool) \
            or not math.isfinite(account_value) or account_value <= 0:
        return 0.0
    target = account_value * cfg.position_fraction
    if target < cfg.min_position_usd:
        # Can the account still afford the floor outright?
        return cfg.min_position_usd if account_value >= cfg.min_position_usd else 0.0
    return min(target, cfg.max_position_usd)


def remaining_lifetime(spent: float, cfg: OptionConfig) -> float:
    return max(0.0, cfg.max_lifetime_usd - spent)


def affordable(account_value: float, spent: float, buying_power: float,
               cfg: OptionConfig) -> tuple[float, str]:
    """Final deployable amount after every cap. Returns (amount, reason)."""
    size = size_position(account_value, cfg)
    if size <= 0:
        return 0.0, f"account value {account_value} below the {cfg.min_position_usd} floor"
    left = remaining_lifetime(spent, cfg)
    if left <= 0:
        return 0.0, (f"lifetime cap reached: {spent} of {cfg.max_lifetime_usd} "
                     f"deployed -- a human must raise it to continue")
    if left < size:
        size = left
    if size < cfg.min_position_usd:
        return 0.0, f"remaining headroom {left} below the {cfg.min_position_usd} floor"
    if buying_power < size:
        return 0.0, f"buying power {buying_power} below position size {size}"
    return round(size, 2), ""
