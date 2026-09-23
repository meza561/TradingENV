import datetime as dt
import pytest
from pathlib import Path
from zoneinfo import ZoneInfo
from guard import ledger
from guard.config import Config
from guard.guards import (halted, is_live, market_window_ok, period_key,
                          already_bought)

ET = ZoneInfo("US/Eastern")


def cfg(**kw):
    d = dict(account_number="1", symbol="VTI", amount_usd=25.0)
    d.update(kw)
    return Config(**d)


def at(y, m, d, h, mi):
    return dt.datetime(y, m, d, h, mi, tzinfo=ET)


def test_halt_file_detected(tmp_path):
    assert halted(tmp_path)[0] is False
    (tmp_path / "HALT").touch()
    ok, why = halted(tmp_path)
    assert ok is True and "HALT" in why


def test_live_requires_both_keys(tmp_path):
    assert is_live(cfg(mode="live"), tmp_path) is False   # no file
    (tmp_path / "LIVE_ENABLED").touch()
    assert is_live(cfg(mode="live"), tmp_path) is True
    assert is_live(cfg(mode="paper"), tmp_path) is False  # file but paper


def test_window_rejects_weekend():
    assert market_window_ok(at(2026, 9, 26, 12, 0), cfg())[0] is False


def test_window_rejects_first_15_minutes():
    assert market_window_ok(at(2026, 9, 25, 9, 40), cfg())[0] is False
    assert market_window_ok(at(2026, 9, 25, 9, 46), cfg())[0] is True


def test_window_rejects_last_10_minutes():
    assert market_window_ok(at(2026, 9, 25, 15, 55), cfg())[0] is False
    assert market_window_ok(at(2026, 9, 25, 15, 49), cfg())[0] is True


def test_window_rejects_overnight():
    assert market_window_ok(at(2026, 9, 25, 3, 0), cfg())[0] is False
    assert market_window_ok(at(2026, 9, 25, 20, 0), cfg())[0] is False


def test_window_requires_tzaware():
    with pytest.raises(ValueError):
        market_window_ok(dt.datetime(2026, 9, 25, 12, 0), cfg())


def test_utc_input_converted_before_window_check():
    """17:00 UTC is 13:00 ET - inside the window, not outside."""
    utc = dt.datetime(2026, 9, 25, 17, 0, tzinfo=dt.timezone.utc)
    assert market_window_ok(utc, cfg())[0] is True


def test_period_key_weekly_and_monthly():
    d = at(2026, 9, 25, 12, 0)
    assert period_key(d, "weekly").startswith("2026-W")
    assert period_key(d, "monthly") == "2026-09"


def test_period_key_stable_within_a_week():
    a = period_key(at(2026, 9, 21, 12, 0), "weekly")
    b = period_key(at(2026, 9, 25, 12, 0), "weekly")
    assert a == b


def test_already_bought(tmp_path):
    p = tmp_path / "l.jsonl"
    assert already_bought(p, "2026-W39") is False
    ledger.append(p, {"kind": "paper", "amount_usd": 25.0, "period": "2026-W39"})
    assert already_bought(p, "2026-W39") is True
    assert already_bought(p, "2026-W40") is False
