"""The real safety layer. Assumes the plan may be wrong or hostile:
every value is re-derived from config and the ledger, never trusted.
"""
import datetime as dt
import math
from pathlib import Path

from guard import ledger
from guard.config import Config
from guard.guards import market_window_ok, period_key
from guard.plan import Intent


def validate(intent: Intent, cfg: Config, now_et: dt.datetime) -> tuple[bool, list[str]]:
    bad: list[str] = []
    path = cfg.ledger_path

    if intent.side != "buy":
        bad.append(f"G2 buy-only: side={intent.side!r}")
    if intent.symbol not in cfg.whitelist:
        bad.append(f"G3 symbol {intent.symbol!r} not whitelisted")
    if intent.order_type == "market":
        if intent.symbol not in cfg.whitelist:
            bad.append("G4 market order only allowed for whitelisted ETFs")
    elif intent.order_type != "limit":
        bad.append(f"G4 order_type {intent.order_type!r} not allowed")

    amt = intent.amount_usd
    if not isinstance(amt, (int, float)) or isinstance(amt, bool) \
            or not math.isfinite(amt) or amt <= 0:
        bad.append(f"G5 amount_usd not a positive finite number: {amt!r}")
        return False, bad                      # every cap below needs a number
    if amt > cfg.max_order_usd:
        bad.append(f"G5 amount {amt} over per-order cap {cfg.max_order_usd}")
    if amt != cfg.amount_usd:
        bad.append(f"G5 amount {amt} does not match configured {cfg.amount_usd}")

    expected = period_key(now_et, cfg.schedule)
    if intent.period != expected:
        bad.append(f"G8 period {intent.period!r} != expected {expected!r}")

    if ledger.spent_in_period(path, expected) + amt > cfg.max_spend_per_period_usd:
        bad.append("G5 per-period spend cap would be exceeded")
    if ledger.spent_lifetime(path) + amt > cfg.max_lifetime_spend_usd:
        bad.append("G5 lifetime spend cap would be exceeded")
    if expected in ledger.periods_bought(path):
        bad.append(f"G8 already bought in period {expected}")

    ok, why = market_window_ok(now_et, cfg)
    if not ok:
        bad.append(f"G6 market window: {why}")
    return (not bad), bad
