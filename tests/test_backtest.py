import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
from ebot.backtest import build_trade, run_events
from ebot.config import load_config
from ebot.types import Bar, Event
from tests.test_gate import with_event

ET = ZoneInfo("US/Eastern")
CFG = load_config(Path("config.example.yaml"))


def extend(bars, n, step=1.01):
    out, d, px = list(bars), bars[-1].date, bars[-1].close
    for _ in range(n):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        px *= step
        out.append(Bar(bars[-1].symbol, d, px, px, px, px, 1_000_000))
    return out


def bench_for(bars, flat=400.0):
    return [Bar("SPY", b.date, flat, flat, flat, flat, 1) for b in bars]


def ev(t0):
    return Event("X", "0000000001", "acc-1",
                 dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))


def test_entry_price_is_t1_close_not_open():
    bars, t0, t1 = with_event()
    bars = extend(bars, 4)
    tr = build_trade(ev(t0), bars, bench_for(bars), CFG)
    assert tr is not None
    t1_bar = next(b for b in bars if b.date == t1)
    assert tr.entry_px == t1_bar.close, "spec 6.1: entry is the T+1 CLOSE"
    assert tr.entry_px != t1_bar.open, "fixture must distinguish open from close"


def test_exit_is_third_session_after_t1():
    bars, t0, t1 = with_event()
    bars = extend(bars, 4)
    tr = build_trade(ev(t0), bars, bench_for(bars), CFG)
    after = sorted(b.date for b in bars if b.date > t1)
    assert tr.exit_date == after[CFG.hold_days - 1]


def test_return_is_close_to_close():
    bars, t0, t1 = with_event()
    bars = extend(bars, 4)
    tr = build_trade(ev(t0), bars, bench_for(bars), CFG)
    entry_c = next(b.close for b in bars if b.date == tr.entry_date)
    exit_c = next(b.close for b in bars if b.date == tr.exit_date)
    assert abs(tr.ret - (exit_c / entry_c - 1.0)) < 1e-12


def test_returns_none_when_gate_fails():
    bars, t0, _ = with_event(gap_pct=0.2)
    bars = extend(bars, 4)
    assert build_trade(ev(t0), bars, bench_for(bars), CFG) is None


def test_returns_none_when_exit_bar_missing():
    bars, t0, _ = with_event()
    assert build_trade(ev(t0), bars, bench_for(bars), CFG) is None


def test_excess_is_zero_when_stock_matches_benchmark():
    bars, t0, _ = with_event()
    bars = extend(bars, 4)
    bench = [Bar("SPY", b.date, b.open, b.high, b.low, b.close, 1) for b in bars]
    tr = build_trade(ev(t0), bars, bench, CFG)
    assert abs(tr.excess) < 1e-12


def test_excess_subtracts_benchmark():
    bars, t0, _ = with_event()
    bars = extend(bars, 4)
    tr = build_trade(ev(t0), bars, bench_for(bars), CFG)
    assert abs(tr.excess - (tr.ret - tr.spy_ret)) < 1e-12
    assert tr.spy_ret == 0.0


def test_run_events_skips_unknown_symbols():
    bars, t0, _ = with_event()
    bars = extend(bars, 4)
    other = Event("ZZZZ", "0", "acc-2", dt.datetime.combine(
        t0, dt.time(16, 30), tzinfo=ET))
    out = run_events([ev(t0), other], {"X": bars}, bench_for(bars), CFG)
    assert [t.ticker for t in out] == ["X"]


def test_run_events_sorted_by_entry_date():
    bars, t0, _ = with_event()
    bars = extend(bars, 4)
    out = run_events([ev(t0)], {"X": bars}, bench_for(bars), CFG)
    assert out == sorted(out, key=lambda t: t.entry_date)
