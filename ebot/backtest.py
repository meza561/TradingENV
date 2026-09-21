import datetime as dt

from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.config import Config
from ebot.gate import passes_gate
from ebot.types import Bar, Event, Trade


def _ret(bars: dict[dt.date, Bar], entry: dt.date, exit_: dt.date) -> float | None:
    """Close-to-close. Spec 6.1: entry is the T+1 CLOSE, not the open."""
    if entry not in bars or exit_ not in bars:
        return None
    return bars[exit_].close / bars[entry].close - 1.0


def build_trade(event: Event, bars: list[Bar], bench_bars: list[Bar],
                cfg: Config) -> Trade | None:
    sessions = sessions_from_bars(bars)
    timing = resolve_timing(event.accepted_at, sessions)
    if timing is None:
        return None
    t0, t1 = timing
    ok, _ = passes_gate(bars, t0, t1, cfg)
    if not ok:
        return None
    after = [d for d in sessions if d > t1]
    if len(after) < cfg.hold_days:
        return None
    exit_ = after[cfg.hold_days - 1]

    by_date = {b.date: b for b in bars}
    bench_by_date = {b.date: b for b in bench_bars}
    r = _ret(by_date, t1, exit_)
    br = _ret(bench_by_date, t1, exit_)
    if r is None or br is None:
        return None
    return Trade(ticker=event.ticker, accepted_at=event.accepted_at, t0=t0,
                 entry_date=t1, exit_date=exit_,
                 entry_px=by_date[t1].close, exit_px=by_date[exit_].close,
                 ret=r, spy_ret=br, excess=r - br)


def run_events(events: list[Event], bars_by_symbol: dict[str, list[Bar]],
               bench_bars: list[Bar], cfg: Config) -> list[Trade]:
    out = []
    for e in events:
        bars = bars_by_symbol.get(e.ticker)
        if not bars:
            continue
        tr = build_trade(e, bars, bench_bars, cfg)
        if tr:
            out.append(tr)
    return sorted(out, key=lambda t: t.entry_date)
