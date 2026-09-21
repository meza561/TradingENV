import datetime as dt
from pathlib import Path
from ebot.gate import passes_gate
from ebot.config import load_config
from ebot.types import Bar

CFG = load_config(Path("config.example.yaml"))


def series(n=60, px=100.0, vol=1_000_000):
    out, d = [], dt.date(2024, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(Bar("X", d, px, px * 1.001, px * 0.999, px, vol))
        d += dt.timedelta(days=1)
    return out


def with_event(gap_pct=3.0, t0_vol_mult=2.0, px=100.0, t0_close=None):
    """Returns (bars, t0, t1). The t1 bar's high/low/close deliberately
    differ from its open so look-ahead tests are meaningful."""
    bars = series(px=px)
    t0d = bars[-1].date
    c = px if t0_close is None else t0_close
    bars[-1] = Bar("X", t0d, c, c, c, c, int(1_000_000 * t0_vol_mult))
    t1d = t0d + dt.timedelta(days=1)
    while t1d.weekday() >= 5:
        t1d += dt.timedelta(days=1)
    o = c * (1 + gap_pct / 100.0)
    bars.append(Bar("X", t1d, o, o * 1.02, o * 0.98, o * 1.01, 1_500_000))
    return bars, t0d, t1d


def kinds(detail):
    return {k for k, v in detail.items() if not v}


def test_passes_when_all_conditions_met():
    bars, t0, t1 = with_event()
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is True and all(detail.values())


def test_g1_fails_on_small_gap():
    bars, t0, t1 = with_event(gap_pct=0.5)
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is False and detail["G1"] is False


def test_g2_fails_on_negative_gap():
    bars, t0, t1 = with_event(gap_pct=-3.0)
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is False and detail["G2"] is False


def test_g3_fails_on_normal_volume():
    bars, t0, t1 = with_event(t0_vol_mult=1.0)
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is False and detail["G3"] is False


def test_g4_fails_on_thin_liquidity():
    bars, t0, t1 = with_event(px=1.0)
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is False and detail["G4"] is False


def test_g5_fails_when_extended_above_sma():
    bars, t0, t1 = with_event(t0_close=150.0)
    ok, detail = passes_gate(bars, t0, t1, CFG)
    assert ok is False and detail["G5"] is False


def test_insufficient_history_returns_false_not_partial():
    bars, t0, t1 = with_event()
    ok, detail = passes_gate(bars[-5:], t0, t1, CFG)
    assert ok is False and detail == {}


def test_missing_t0_or_t1_returns_false():
    bars, t0, t1 = with_event()
    assert passes_gate([b for b in bars if b.date != t1], t0, t1, CFG) == (False, {})


def test_gate_ignores_bars_after_t1():
    bars, t0, t1 = with_event()
    base, _ = passes_gate(bars, t0, t1, CFG)
    poisoned = bars + [Bar("X", t1 + dt.timedelta(days=i), 1e9, 1e9, 1e9, 1e9, 1)
                       for i in range(1, 6)]
    assert passes_gate(poisoned, t0, t1, CFG)[0] == base


def test_gate_reads_only_t1_open_not_its_hlcv():
    """Spec 6.1: gate inputs are frozen at the T+1 open. The entry price IS
    t1's close, so admitting it as a gate input would be circular."""
    bars, t0, t1 = with_event()
    before = passes_gate(bars, t0, t1, CFG)
    mutated = [Bar(b.symbol, b.date, b.open, 1e9, 0.0, 1e9, 10 ** 12)
               if b.date == t1 else b for b in bars]
    assert passes_gate(mutated, t0, t1, CFG) == before, \
        "gate read t1 high/low/close/volume -- look-ahead"
