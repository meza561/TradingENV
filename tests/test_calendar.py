import datetime as dt
import pytest
from zoneinfo import ZoneInfo
from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.types import Bar

ET = ZoneInfo("US/Eastern")
# Mon 2024-05-06 .. Fri 2024-05-10, then Mon 2024-05-13
SESSIONS = [dt.date(2024, 5, 6), dt.date(2024, 5, 7), dt.date(2024, 5, 8),
            dt.date(2024, 5, 9), dt.date(2024, 5, 10), dt.date(2024, 5, 13)]


def at(y, m, d, h, mi):
    return dt.datetime(y, m, d, h, mi, tzinfo=ET)


def test_post_close_filing_observes_next_session():
    assert resolve_timing(at(2024, 5, 8, 16, 5), SESSIONS) == (
        dt.date(2024, 5, 8), dt.date(2024, 5, 9))


def test_intraday_filing_forgoes_same_day():
    assert resolve_timing(at(2024, 5, 8, 11, 0), SESSIONS) == (
        dt.date(2024, 5, 8), dt.date(2024, 5, 9))


def test_pre_open_filing_observes_same_day():
    assert resolve_timing(at(2024, 5, 8, 7, 30), SESSIONS) == (
        dt.date(2024, 5, 7), dt.date(2024, 5, 8))


def test_exactly_0930_counts_as_intraday():
    assert resolve_timing(at(2024, 5, 8, 9, 30), SESSIONS) == (
        dt.date(2024, 5, 8), dt.date(2024, 5, 9))


def test_exactly_1600_counts_as_post_close():
    assert resolve_timing(at(2024, 5, 8, 16, 0), SESSIONS) == (
        dt.date(2024, 5, 8), dt.date(2024, 5, 9))


def test_friday_post_close_skips_weekend():
    assert resolve_timing(at(2024, 5, 10, 17, 0), SESSIONS) == (
        dt.date(2024, 5, 10), dt.date(2024, 5, 13))


def test_filing_on_non_session_day_rolls_forward():
    assert resolve_timing(at(2024, 5, 11, 10, 0), SESSIONS) == (
        dt.date(2024, 5, 10), dt.date(2024, 5, 13))


def test_returns_none_when_no_following_session():
    assert resolve_timing(at(2024, 5, 13, 17, 0), SESSIONS) is None


def test_returns_none_when_no_prior_session():
    assert resolve_timing(at(2024, 5, 6, 7, 0), SESSIONS) is None


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        resolve_timing(dt.datetime(2024, 5, 8, 11, 0), SESSIONS)


def test_utc_input_converted_before_session_logic():
    """22:00 UTC on 5/8 is 18:00 EDT -- post-close, not pre-open."""
    utc = dt.datetime(2024, 5, 8, 22, 0, tzinfo=dt.timezone.utc)
    assert resolve_timing(utc, SESSIONS) == (dt.date(2024, 5, 8), dt.date(2024, 5, 9))


def test_t1_is_always_after_t0():
    for h in (7, 9, 11, 16, 20):
        r = resolve_timing(at(2024, 5, 8, h, 0), SESSIONS)
        if r:
            assert r[1] > r[0], f"t1 must follow t0 (hour {h})"


def test_sessions_from_bars_sorted_unique():
    bars = [Bar("AAPL", dt.date(2024, 5, 8), 1, 1, 1, 1, 1),
            Bar("AAPL", dt.date(2024, 5, 6), 1, 1, 1, 1, 1),
            Bar("AAPL", dt.date(2024, 5, 6), 1, 1, 1, 1, 1)]
    assert sessions_from_bars(bars) == [dt.date(2024, 5, 6), dt.date(2024, 5, 8)]
