"""Deterministic exit rules. The analyst has no say here.

For a LONG option, closing is always available and holding an unevaluable
position risks expiring worthless -- so uncertainty resolves to HALT (stop and
let a human look), never to silent holding.
"""
import datetime as dt
import math
from dataclasses import dataclass

from guard.optconfig import OptionConfig

HOLD, CLOSE, HALT = "hold", "close", "halt"


@dataclass(frozen=True)
class OptionPosition:
    option_id: str
    underlying: str
    strike: float
    expiration: dt.date
    quantity: int
    average_price: float          # premium per share, e.g. 0.77


def days_to_expiry(pos: OptionPosition, today: dt.date) -> int:
    return (pos.expiration - today).days


def pnl_pct(pos: OptionPosition, mark: float) -> float:
    return (mark / pos.average_price - 1.0) * 100.0


def exit_decision(pos: OptionPosition, mark: float, today: dt.date,
                  cfg: OptionConfig) -> tuple[str, str]:
    """Returns (HOLD|CLOSE|HALT, reason)."""
    for name, v in (("average_price", pos.average_price), ("mark", mark)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(v) or v <= 0:
            return HALT, f"unevaluable {name}: {v!r}"
    if pos.quantity <= 0:
        return HALT, f"non-positive quantity: {pos.quantity}"

    dte = days_to_expiry(pos, today)
    if dte < 0:
        return HALT, f"expiration {pos.expiration} already passed"

    pnl = pnl_pct(pos, mark)
    # Profit target first: a position can hit +50% on its last eligible day,
    # and taking the gain beats closing on the calendar.
    if pnl >= cfg.take_profit_pct:
        return CLOSE, f"take profit {pnl:+.1f}% >= {cfg.take_profit_pct}%"
    if pnl <= -cfg.stop_loss_pct:
        return CLOSE, f"stop loss {pnl:+.1f}% <= -{cfg.stop_loss_pct}%"
    if dte <= cfg.close_at_dte:
        return CLOSE, f"{dte} DTE <= {cfg.close_at_dte}"
    return HOLD, f"{pnl:+.1f}%, {dte} DTE"
