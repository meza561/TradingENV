"""Independent re-check of a proposed option purchase.

Re-derives every value from the config, the candidate's own numbers and the
account state. It does not trust the selector that produced the candidate or
the analyst that chose it.
"""
import datetime as dt
import math

from guard.guards import market_window_ok
from guard.optconfig import OptionConfig
from guard.selector import Candidate, spread_pct_of_mid
from guard.sizing import affordable


def validate_open(cand: Candidate, cfg: OptionConfig, *, account_value: float,
                  buying_power: float, spent: float, n_open: int,
                  now_et: dt.datetime) -> tuple[bool, list[str]]:
    bad: list[str] = []
    today = now_et.date()

    if cand.underlying not in cfg.underlyings:
        bad.append(f"V1 underlying {cand.underlying!r} not whitelisted")
    if cand.option_type not in {"call", "put"}:
        bad.append(f"V2 option_type {cand.option_type!r} not long-only call/put")

    dte = (cand.expiration - today).days
    if not (cfg.min_dte <= dte <= cfg.max_dte):
        bad.append(f"V3 {dte} DTE outside {cfg.min_dte}-{cfg.max_dte}")

    if not isinstance(cand.delta, (int, float)) or not math.isfinite(cand.delta):
        bad.append(f"V4 unevaluable delta {cand.delta!r}")
    elif abs(abs(cand.delta) - cfg.target_delta) > cfg.delta_tolerance + 1e-9:
        bad.append(f"V4 delta {cand.delta:.3f} outside band")

    sp = spread_pct_of_mid(cand.bid, cand.ask)
    if sp > cfg.max_spread_pct_of_mid:
        shown = "unevaluable" if math.isinf(sp) else f"{sp:.1f}%"
        bad.append(f"V5 spread {shown} > {cfg.max_spread_pct_of_mid}%")

    if cand.open_interest < cfg.min_open_interest:
        bad.append(f"V6 open interest {cand.open_interest} < {cfg.min_open_interest}")

    if n_open >= cfg.max_open_positions:
        bad.append(f"V7 {n_open} open >= max {cfg.max_open_positions}")

    amount, why = affordable(account_value, spent, buying_power, cfg)
    if amount <= 0:
        bad.append(f"V8 {why}")
    else:
        cost = cand.ask * 100.0
        if cost > amount + 1e-9:
            bad.append(f"V8 cost ${cost:.2f} > deployable ${amount:.2f}")
        if abs(cost - cand.cost_usd) > 0.01:
            bad.append(f"V8 cost_usd {cand.cost_usd} disagrees with ask x 100 "
                       f"({cost:.2f})")

    ok, whyw = market_window_ok(now_et, cfg)
    if not ok:
        bad.append(f"V9 market window: {whyw}")
    return (not bad), bad
