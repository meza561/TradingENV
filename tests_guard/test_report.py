import datetime as dt
from pathlib import Path
from guard import ledger
from guard.optconfig import OptionConfig
from guard.report import digest

TODAY = dt.date(2026, 9, 23)


def cfg_for(tmp_path):
    return OptionConfig(account_number="1", ledger_dir=tmp_path)


def test_empty_ledger_says_so(tmp_path):
    assert "no activity" in digest(cfg_for(tmp_path), TODAY)


def test_shows_open_position_and_caps(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {
        "kind": "paper_open", "option_id": "a", "underlying": "TLT",
        "strike": 83.0, "option_type": "call", "expiration": "2026-10-30",
        "quantity": 1, "fill_price": 0.40, "cost_usd": 40.0})
    d = digest(c, TODAY)
    assert "open 1/2" in d and "$40.00 of $2,000" in d
    assert "TLT 83.0C" in d and "37 DTE" in d


def test_stays_compact_as_the_ledger_grows(tmp_path):
    """Token cost must not scale with history."""
    c = cfg_for(tmp_path)
    for i in range(500):
        ledger.append(c.ledger_path, {"kind": "skipped", "period": f"p{i}",
                                      "codes": ["G6"]})
    d = digest(c, TODAY)
    assert len(d.splitlines()) <= 20, d
    assert "skipped 500" in d


def test_closed_position_leaves_no_open_row(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "paper_open", "option_id": "a",
                                  "underlying": "TLT", "strike": 83.0,
                                  "expiration": "2026-10-30", "quantity": 1,
                                  "fill_price": 0.4, "cost_usd": 40.0})
    ledger.append(c.ledger_path, {"kind": "paper_close", "option_id": "a",
                                  "reason": "take profit +52.0%"})
    d = digest(c, TODAY)
    assert "open 0/2" in d
    assert "deployed $40.00" in d, "a close must not refund the lifetime cap"
    assert "take profit" in d


def test_skips_are_excluded_from_recent_but_still_counted(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "declined", "rationale": "wide"})
    for i in range(10):
        ledger.append(c.ledger_path, {"kind": "skipped", "codes": ["G6"]})
    d = digest(c, TODAY)
    assert "declined" in d.split("last")[1]
    assert "skipped 10" in d


def test_bad_expiration_does_not_crash(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "paper_open", "option_id": "a",
                                  "underlying": "TLT", "strike": 83.0,
                                  "expiration": "garbage", "quantity": 1,
                                  "fill_price": 0.4, "cost_usd": 40.0})
    assert "? DTE" in digest(c, TODAY)
