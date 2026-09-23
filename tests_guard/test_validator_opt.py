import datetime as dt
import pytest
from zoneinfo import ZoneInfo
from guard.optconfig import OptionConfig
from guard.selector import Candidate
from guard.validator_opt import validate_open

ET = ZoneInfo("US/Eastern")
NOW = dt.datetime(2026, 9, 25, 12, 0, tzinfo=ET)          # Friday midday
EXP = dt.date(2026, 10, 30)                               # 35 DTE
CFG = OptionConfig(account_number="1")


def cand(**kw):
    d = dict(option_id="o1", underlying="XLU", option_type="call", strike=41.0,
             expiration=EXP, dte=35, bid=0.46, ask=0.48, mark=0.47, delta=0.30,
             open_interest=238, spread_pct=4.3, cost_usd=48.0)
    d.update(kw)
    return Candidate(**d)


def run(c, **kw):
    state = dict(account_value=150.0, buying_power=150.0, spent=0.0, n_open=0,
                 now_et=NOW)
    state.update(kw)
    ok, bad = validate_open(c, CFG, **state)
    return ok, " | ".join(bad)


def test_happy_path():
    ok, why = run(cand())
    assert ok is True, why


def test_rejects_non_whitelisted_underlying():
    ok, why = run(cand(underlying="TSLA"))
    assert not ok and "V1" in why


def test_rejects_non_option_type():
    ok, why = run(cand(option_type="future"))
    assert not ok and "V2" in why


def test_rejects_dte_outside_window():
    ok, why = run(cand(expiration=dt.date(2026, 10, 2)))
    assert not ok and "V3" in why


def test_recomputes_dte_and_ignores_a_lying_field():
    """The candidate's own dte field is not trusted."""
    ok, why = run(cand(expiration=dt.date(2027, 6, 1), dte=35))
    assert not ok and "V3" in why


def test_rejects_delta_outside_band():
    ok, why = run(cand(delta=0.80))
    assert not ok and "V4" in why


def test_recomputes_spread_and_ignores_a_lying_field():
    """spread_pct claims 1% while bid/ask say 70%."""
    ok, why = run(cand(bid=0.45, ask=0.94, spread_pct=1.0, cost_usd=94.0))
    assert not ok and "V5" in why


def test_rejects_low_open_interest():
    ok, why = run(cand(open_interest=10))
    assert not ok and "V6" in why


def test_rejects_when_slots_are_full():
    ok, why = run(cand(), n_open=2)
    assert not ok and "V7" in why


def test_rejects_when_cost_exceeds_deployable():
    ok, why = run(cand(bid=0.88, ask=0.90, cost_usd=90.0))
    assert not ok and "V8" in why


def test_rejects_cost_field_disagreeing_with_ask():
    ok, why = run(cand(cost_usd=1.0))
    assert not ok and "disagrees" in why


def test_rejects_when_lifetime_cap_reached():
    ok, why = run(cand(), spent=2000.0)
    assert not ok and "V8" in why


def test_rejects_when_buying_power_is_zero():
    """Your account tonight: value $149.94, nothing settled."""
    ok, why = run(cand(), buying_power=0.0)
    assert not ok and "buying power" in why


def test_rejects_outside_market_window():
    night = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
    ok, why = run(cand(), now_et=night)
    assert not ok and "V9" in why


def test_multiple_violations_all_reported():
    ok, bad = validate_open(cand(underlying="TSLA", delta=0.9, open_interest=1),
                            CFG, account_value=150.0, buying_power=150.0,
                            spent=0.0, n_open=5, now_et=NOW)
    assert not ok and len(bad) >= 4
