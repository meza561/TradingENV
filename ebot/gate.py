import datetime as dt
from statistics import median

from ebot.config import Config
from ebot.types import Bar


def passes_gate(bars: list[Bar], t0: dt.date, t1: dt.date,
                cfg: Config) -> tuple[bool, dict[str, bool]]:
    """Spec 6.2 conditions G1-G5.

    Reads only t1's OPEN. t1's high/low/close/volume are off limits: the
    entry price is t1's close, so using it here would be circular.
    """
    by_date = {b.date: b for b in bars}
    if t0 not in by_date or t1 not in by_date:
        return False, {}
    prior = [b for b in bars if b.date < t0]
    if len(prior) < max(cfg.lookback_sessions, cfg.sma_window):
        return False, {}

    t0_bar, t1_bar = by_date[t0], by_date[t1]
    window = prior[-cfg.lookback_sessions:]
    sma = sum(b.close for b in prior[-cfg.sma_window:]) / cfg.sma_window
    gap = t1_bar.open / t0_bar.close - 1.0

    checks = {
        "G1": abs(gap) >= cfg.gap_min_pct / 100.0,
        "G2": t1_bar.open > t0_bar.close,
        "G3": t0_bar.volume >= cfg.volume_mult * median(b.volume for b in window),
        "G4": median(b.close * b.volume for b in window) >= cfg.min_dollar_volume,
        "G5": t0_bar.close <= cfg.extended_mult * sma,
    }
    return all(checks.values()), checks
