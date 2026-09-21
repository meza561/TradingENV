import datetime as dt
from pathlib import Path
from ebot.config import load_config
from ebot.types import Bar
from ebot.validate_bars import validate_bars, FATAL_KINDS

CFG = load_config(Path("config.example.yaml"))


def good_year(year=2020, n=252, px=100.0):
    out, d = [], dt.date(year, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(Bar("X", d, px, px * 1.01, px * 0.99, px, 1_000_000))
        d += dt.timedelta(days=1)
    return out


def kinds(issues):
    return {i.kind for i in issues}


def test_clean_data_has_no_issues():
    assert validate_bars(good_year(), CFG) == []


def test_high_below_low_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 90.0, 110.0, 100, 1_000_000)
    assert "ohlc" in kinds(validate_bars(bars, CFG))
    assert "ohlc" in FATAL_KINDS


def test_close_outside_high_low_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 101.0, 99.0, 500.0, 1_000_000)
    assert "ohlc" in kinds(validate_bars(bars, CFG))


def test_zero_price_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 0.0, 0.0, 0.0, 0.0, 1_000_000)
    assert "ohlc" in kinds(validate_bars(bars, CFG))


def test_negative_volume_is_fatal():
    bars = good_year()
    b = bars[10]
    bars[10] = Bar("X", b.date, b.open, b.high, b.low, b.close, -5)
    assert "ohlc" in kinds(validate_bars(bars, CFG))


def test_duplicate_date_is_fatal():
    bars = good_year()
    bars.append(bars[10])
    assert "duplicate" in kinds(validate_bars(bars, CFG))
    assert "duplicate" in FATAL_KINDS


def test_short_year_flagged_as_count_not_fatal():
    issues = validate_bars(good_year(n=150), CFG)
    assert "count" in kinds(issues)
    assert "count" not in FATAL_KINDS


def test_long_gap_flagged():
    bars = good_year()
    del bars[100:115]
    assert "gap" in kinds(validate_bars(bars, CFG))


def test_extreme_move_flagged_not_fatal():
    bars = good_year()
    b = bars[50]
    bars[50] = Bar("X", b.date, 100, 200.0, 99.0, 180.0, 1_000_000)
    assert "extreme" in kinds(validate_bars(bars, CFG))
    assert "extreme" not in FATAL_KINDS


def test_issue_carries_symbol_and_date():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 90.0, 110.0, 100, 1_000_000)
    i = next(i for i in validate_bars(bars, CFG) if i.kind == "ohlc")
    assert i.symbol == "X" and i.date == bars[10].date and i.detail


def test_empty_input_is_not_an_error():
    assert validate_bars([], CFG) == []
