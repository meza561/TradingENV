"""Spec 16 hypothesis search.

Separate from backtest.py on purpose: the code that produced the committed
2026-09-22 results is not modified, so those results stay reproducible.
"""
import datetime as dt
from dataclasses import dataclass
from statistics import median

from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.config import Config
from ebot.types import Bar, Event, Trade

SEARCH_T = 2.576          # p<0.01 = 0.05/k, k=5 (spec 16.2)


@dataclass(frozen=True)
class Hypothesis:
    name: str
    hold_days: int
    direction: str                 # "up" | "down" | "pre"
    gap_min_pct: float
    pre_event_sessions: int = 0
    market_filter: bool = False


HYPOTHESES = [
    Hypothesis("H1", 21, "up", 2.0),
    Hypothesis("H2", 3, "down", 2.0),
    Hypothesis("H3", 10, "up", 5.0),
    Hypothesis("H4", 0, "pre", 0.0, pre_event_sessions=5),
    Hypothesis("H5", 21, "up", 2.0, market_filter=True),
]


def _sma(bars: list[Bar], n: int) -> float | None:
    return sum(b.close for b in bars[-n:]) / n if len(bars) >= n else None


def gate_h(bars: list[Bar], t0: dt.date, t1: dt.date, cfg: Config,
           h: Hypothesis, spy: list[Bar] | None = None) -> tuple[bool, dict]:
    """Gate inputs are knowable at entry. For post-event hypotheses only
    t1's OPEN is read; its high/low/close are the entry price side."""
    by_date = {b.date: b for b in bars}
    if t0 not in by_date or t1 not in by_date:
        return False, {}
    prior = [b for b in bars if b.date < t0]
    if len(prior) < max(cfg.lookback_sessions, cfg.sma_window):
        return False, {}

    t0_bar, t1_bar = by_date[t0], by_date[t1]
    window = prior[-cfg.lookback_sessions:]
    sma = _sma(prior, cfg.sma_window)
    gap = t1_bar.open / t0_bar.close - 1.0

    checks = {
        "G1": abs(gap) >= h.gap_min_pct / 100.0,
        "G2": (t1_bar.open > t0_bar.close) if h.direction == "up"
              else (t1_bar.open < t0_bar.close),
        "G3": t0_bar.volume >= cfg.volume_mult * median(b.volume for b in window),
        "G4": median(b.close * b.volume for b in window) >= cfg.min_dollar_volume,
        "G5": t0_bar.close <= cfg.extended_mult * sma,
    }
    if h.market_filter:
        spy_by = {b.date: b for b in (spy or [])}
        spy_prior = [b for b in (spy or []) if b.date <= t0]
        spy_sma = _sma(spy_prior, 200)
        checks["M"] = (t0 in spy_by and spy_sma is not None
                       and spy_by[t0].close > spy_sma)
    return all(checks.values()), checks


def gate_pre(bars: list[Bar], entry: dt.date, cfg: Config) -> tuple[bool, dict]:
    """H4: only liquidity and not-extended, evaluated at the entry bar."""
    by_date = {b.date: b for b in bars}
    if entry not in by_date:
        return False, {}
    prior = [b for b in bars if b.date < entry]
    if len(prior) < max(cfg.lookback_sessions, cfg.sma_window):
        return False, {}
    window = prior[-cfg.lookback_sessions:]
    sma = _sma(prior, cfg.sma_window)
    checks = {
        "G4": median(b.close * b.volume for b in window) >= cfg.min_dollar_volume,
        "G5": by_date[entry].close <= cfg.extended_mult * sma,
    }
    return all(checks.values()), checks


def build_trade_h(event: Event, bars: list[Bar], bench_bars: list[Bar],
                  cfg: Config, h: Hypothesis,
                  spy: list[Bar] | None = None) -> Trade | None:
    sessions = sessions_from_bars(bars)
    timing = resolve_timing(event.accepted_at, sessions)
    if timing is None:
        return None
    t0, t1 = timing
    by_date = {b.date: b for b in bars}
    bench_by = {b.date: b for b in bench_bars}

    if h.direction == "pre":
        idx = sessions.index(t0)
        if idx < h.pre_event_sessions:
            return None
        entry = sessions[idx - h.pre_event_sessions]
        exit_ = t0
        ok, _ = gate_pre(bars, entry, cfg)
    else:
        ok, _ = gate_h(bars, t0, t1, cfg, h, spy)
        entry = t1
        after = [d for d in sessions if d > t1]
        if len(after) < h.hold_days:
            return None
        exit_ = after[h.hold_days - 1]
    if not ok:
        return None
    if entry not in by_date or exit_ not in by_date:
        return None
    if entry not in bench_by or exit_ not in bench_by:
        return None

    r = by_date[exit_].close / by_date[entry].close - 1.0
    br = bench_by[exit_].close / bench_by[entry].close - 1.0
    return Trade(ticker=event.ticker, accepted_at=event.accepted_at, t0=t0,
                 entry_date=entry, exit_date=exit_,
                 entry_px=by_date[entry].close, exit_px=by_date[exit_].close,
                 ret=r, spy_ret=br, excess=r - br)


def run_hypothesis(events: list[Event], bars_by_symbol: dict[str, list[Bar]],
                   bench_bars: list[Bar], cfg: Config,
                   h: Hypothesis) -> list[Trade]:
    out = []
    for e in events:
        bars = bars_by_symbol.get(e.ticker)
        if not bars:
            continue
        tr = build_trade_h(e, bars, bench_bars, cfg, h, bench_bars)
        if tr:
            out.append(tr)
    return sorted(out, key=lambda t: t.entry_date)
