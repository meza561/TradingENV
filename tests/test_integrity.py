"""Look-ahead controls. If these fail, every other number is meaningless."""
import datetime as dt
import random
from pathlib import Path
from zoneinfo import ZoneInfo

from ebot.backtest import run_events
from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.config import load_config
from ebot.gate import passes_gate
from ebot.stats import evaluate
from ebot.types import Bar, Event

ET = ZoneInfo("US/Eastern")
CFG = load_config(Path("config.example.yaml"))


def random_walk(symbol, n=3000, seed=7, overnight=0.015, intraday=0.012):
    """Random walk WITH overnight gaps.

    An earlier version set open(t) = close(t-1), making the gap identically
    zero so G1 could never fire and the control silently passed on an empty
    trade set. Real prices gap overnight; the fixture must too.
    """
    rnd = random.Random(seed)
    out, d, close = [], dt.date(2018, 1, 2), 100.0
    while len(out) < n:
        if d.weekday() < 5:
            o = close * (1 + rnd.gauss(0, overnight))
            close = o * (1 + rnd.gauss(0, intraday))
            hi, lo = max(o, close) * 1.005, min(o, close) * 0.995
            out.append(Bar(symbol, d, o, hi, lo, close,
                           rnd.randint(5_000_000, 40_000_000)))
        d += dt.timedelta(days=1)
    return out


def _control_t(seed):
    """Random events on a random walk. Truth is: no edge exists."""
    bars = random_walk("X", seed=seed)
    raw = random_walk("SPY", seed=seed + 1000)
    bench = [Bar("SPY", s.date, b.open, b.high, b.low, b.close, b.volume)
             for s, b in zip(bars, raw)]
    rnd = random.Random(seed * 31 + 7)
    dates = sorted({b.date for b in bars})[60:-10]
    # Sample WITHOUT replacement: duplicate events would be identical trades,
    # inflating n with zero new information and biasing |t| upward.
    picked = rnd.sample(dates, len(dates))
    events = [Event("X", "0000000001", f"acc-{i}",
                    dt.datetime.combine(d, dt.time(16, 30), tzinfo=ET))
              for i, d in enumerate(picked)]
    trades = run_events(events, {"X": bars}, bench, CFG)
    return evaluate([t.excess for t in trades])


def test_control_actually_produces_trades():
    r = _control_t(1)
    assert r["n"] >= 20, f"fixture too tight, only {r['n']} trades survived gating"


def test_shuffled_labels_produce_no_edge():
    """A random walk has no edge by construction. If the pipeline finds one,
    it is leaking future information. Run across seeds so a single unlucky
    draw cannot fail the build (nor hide a real leak)."""
    ts = [_control_t(s)["t_stat"] for s in (1, 2, 3, 4, 5)]
    breaches = [t for t in ts if abs(t) >= 2.0]
    assert len(breaches) <= 1, (
        f"LOOK-AHEAD BUG: {len(breaches)}/5 seeds show |t|>=2. t-stats={ts}")


def test_gate_inputs_never_include_t1_close():
    """Only t1's OPEN is knowable at decision time."""
    bars = random_walk("X")
    sessions = sessions_from_bars(bars)
    t0, t1 = resolve_timing(
        dt.datetime.combine(sessions[200], dt.time(16, 30), tzinfo=ET), sessions)
    before = passes_gate(bars, t0, t1, CFG)
    mutated = [Bar(b.symbol, b.date, b.open, 1e9, 0.0, 1e9, 10 ** 12)
               if b.date == t1 else b for b in bars]
    assert passes_gate(mutated, t0, t1, CFG) == before


def test_future_bars_cannot_change_any_trade():
    """Appending future data must not alter trades already resolvable."""
    bars = random_walk("X", n=400)
    bench = [Bar("SPY", b.date, b.open, b.high, b.low, b.close, b.volume)
             for b in bars]
    dates = sorted({b.date for b in bars})
    events = [Event("X", "0", f"a{i}",
                    dt.datetime.combine(d, dt.time(16, 30), tzinfo=ET))
              for i, d in enumerate(dates[60:300])]
    base = run_events(events, {"X": bars}, bench, CFG)
    assert base, "fixture produced no trades; the check below would be vacuous"

    extra = random_walk("X", n=500)[400:]
    grown = bars + extra
    gbench = [Bar("SPY", b.date, b.open, b.high, b.low, b.close, b.volume)
              for b in grown]
    after = run_events(events, {"X": grown}, gbench, CFG)

    by_acc = {t.accepted_at: t for t in after}
    for t in base:
        assert by_acc[t.accepted_at] == t, "future data changed a settled trade"
