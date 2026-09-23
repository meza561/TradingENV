"""Deterministic intent. No signal, no forecast, no model."""
import datetime as dt
from dataclasses import dataclass, asdict

from guard.config import Config
from guard.guards import period_key


@dataclass(frozen=True)
class Intent:
    symbol: str
    amount_usd: float
    side: str
    order_type: str
    period: str

    def as_dict(self) -> dict:
        return asdict(self)


def plan_order(cfg: Config, now_et: dt.datetime) -> Intent:
    return Intent(symbol=cfg.symbol, amount_usd=cfg.amount_usd, side="buy",
                  order_type="market", period=period_key(now_et, cfg.schedule))
