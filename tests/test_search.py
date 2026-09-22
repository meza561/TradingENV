import datetime as dt
from pathlib import Path
import pytest
from ebot.config import load_config
from ebot.search import (Hypothesis, HYPOTHESES, gate_h, gate_pre,
                         build_trade_h, SEARCH_T)
from ebot.types import Bar, Event
from zoneinfo import ZoneInfo
from tests.test_gate import with_event, series

ET = ZoneInfo("US/Eastern")
CFG = load_config(Path("config.example.yaml"))
UP = Hypothesis("t", 3, "up", 2.0)
DOWN = Hypothesis("t", 3, "down", 2.0)


def extend(bars, n):
    out, d, px = list(bars), bars[-1].date, bars[-1].close
    for _ in range(n):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        px *= 1.01
        out.append(Bar(bars[-1].symbol, d, px, px, px, px, 1_000_000))
    return out


def ev(t0):
    return Event("X", "0", "a1", dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))


def test_frozen_list_is_exactly_five():
    assert len(HYPOTHESES) == 5
    assert [h.name for h in HYPOTHESES] == ["H1", "H2", "H3", "H4", "H5"]


def test_bonferroni_bar_matches_spec():
    assert SEARCH_T == 2.576


def test_up_direction_rejects_gap_down():
    bars, t0, t1 = with_event(gap_pct=-3.0)
    ok, d = gate_h(bars, t0, t1, CFG, UP)
    assert ok is False and d["G2"] is False


def test_down_direction_accepts_gap_down():
    bars, t0, t1 = with_event(gap_pct=-3.0)
    ok, d = gate_h(bars, t0, t1, CFG, DOWN)
    assert ok is True and d["G2"] is True


def test_down_direction_rejects_gap_up():
    bars, t0, t1 = with_event(gap_pct=3.0)
    ok, d = gate_h(bars, t0, t1, CFG, DOWN)
    assert d["G2"] is False


def test_higher_gap_threshold_filters():
    bars, t0, t1 = with_event(gap_pct=3.0)
    assert gate_h(bars, t0, t1, CFG, Hypothesis("t", 3, "up", 5.0))[1]["G1"] is False
    assert gate_h(bars, t0, t1, CFG, UP)[1]["G1"] is True


MKT = Hypothesis("t", 3, "up", 2.0, market_filter=True)


def long_spy(t0, close_at_t0, n=260):
    """SPY series of n sessions ENDING at t0 -- SMA200 needs 200 of them."""
    days, d = [], t0
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    out = [Bar("SPY", x, 100.0, 100.0, 100.0, 100.0, 1) for x in days[:-1]]
    c = close_at_t0
    out.append(Bar("SPY", t0, c, c, c, c, 1))
    return out


def test_market_filter_blocks_when_spy_below_sma():
    bars, t0, t1 = with_event(gap_pct=3.0)
    assert gate_h(bars, t0, t1, CFG, MKT, long_spy(t0, 10.0))[1]["M"] is False


def test_market_filter_passes_when_spy_above_sma():
    bars, t0, t1 = with_event(gap_pct=3.0)
    assert gate_h(bars, t0, t1, CFG, MKT, long_spy(t0, 999.0))[1]["M"] is True


def test_market_filter_fails_closed_without_200_sessions():
    """H5 drops events lacking 200 days of SPY history. Fail closed, never crash."""
    bars, t0, t1 = with_event(gap_pct=3.0)
    short = long_spy(t0, 999.0, n=50)
    assert gate_h(bars, t0, t1, CFG, MKT, short)[1]["M"] is False
    assert gate_h(bars, t0, t1, CFG, MKT, [])[1]["M"] is False


def test_pre_event_gate_uses_only_liquidity_and_extension():
    bars, t0, t1 = with_event(gap_pct=3.0)
    ok, d = gate_pre(bars, bars[-10].date, CFG)
    assert set(d) == {"G4", "G5"}


def test_pre_event_trade_exits_at_t0_close():
    bars, t0, t1 = with_event(gap_pct=3.0)
    bars = extend(bars, 4)
    h = Hypothesis("H4", 0, "pre", 0.0, pre_event_sessions=5)
    spy = [Bar("SPY", b.date, 400.0, 400.0, 400.0, 400.0, 1) for b in bars]
    tr = build_trade_h(ev(t0), bars, spy, CFG, h)
    assert tr is not None
    assert tr.exit_date == t0, "H4 must exit at the T0 close"
    assert tr.entry_date < t0


def test_hold_days_respected():
    bars, t0, t1 = with_event(gap_pct=3.0)
    bars = extend(bars, 12)
    spy = [Bar("SPY", b.date, 400.0, 400.0, 400.0, 400.0, 1) for b in bars]
    sess = sorted(b.date for b in bars if b.date > t1)
    for n in (3, 10):
        tr = build_trade_h(ev(t0), bars, spy, CFG, Hypothesis("t", n, "up", 2.0))
        assert tr.exit_date == sess[n - 1]


def test_returns_none_when_not_enough_sessions_after_entry():
    bars, t0, t1 = with_event(gap_pct=3.0)
    spy = [Bar("SPY", b.date, 400.0, 400.0, 400.0, 400.0, 1) for b in bars]
    assert build_trade_h(ev(t0), bars, spy, CFG, Hypothesis("t", 21, "up", 2.0)) is None


def test_entry_price_is_a_close_not_an_open():
    bars, t0, t1 = with_event(gap_pct=3.0)
    bars = extend(bars, 4)
    spy = [Bar("SPY", b.date, 400.0, 400.0, 400.0, 400.0, 1) for b in bars]
    tr = build_trade_h(ev(t0), bars, spy, CFG, UP)
    t1_bar = next(b for b in bars if b.date == t1)
    assert tr.entry_px == t1_bar.close and tr.entry_px != t1_bar.open
