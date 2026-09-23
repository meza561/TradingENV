"""The validator assumes the plan may be wrong or hostile."""
import datetime as dt
import math
import pytest
from zoneinfo import ZoneInfo
from guard import ledger
from guard.config import Config
from guard.plan import Intent, plan_order
from guard.validator import validate

ET = ZoneInfo("US/Eastern")
OPEN_HOURS = dt.datetime(2026, 9, 25, 12, 0, tzinfo=ET)   # Friday midday


def cfg(tmp_path, **kw):
    d = dict(account_number="1", symbol="VTI", amount_usd=25.0,
             ledger_dir=tmp_path)
    d.update(kw)
    return Config(**d)


def good(c, now=OPEN_HOURS):
    return plan_order(c, now)


def reasons(intent, c, now=OPEN_HOURS):
    ok, bad = validate(intent, c, now)
    return ok, " | ".join(bad)


def test_happy_path_passes(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(good(c), c)
    assert ok is True, why


def test_rejects_sell(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", 25.0, "sell", "market",
                             good(c).period), c)
    assert ok is False and "G2" in why


def test_rejects_non_whitelisted_symbol(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("TSLA", 25.0, "buy", "market", good(c).period), c)
    assert ok is False and "G3" in why


def test_rejects_unknown_order_type(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", 25.0, "buy", "stop_market",
                             good(c).period), c)
    assert ok is False and "G4" in why


def test_rejects_amount_over_order_cap(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", 5000.0, "buy", "market", good(c).period), c)
    assert ok is False and "G5" in why


def test_rejects_amount_not_matching_config(tmp_path):
    """Even under every cap, an amount the operator did not configure is refused."""
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", 26.0, "buy", "market", good(c).period), c)
    assert ok is False and "does not match configured" in why


@pytest.mark.parametrize("amt", [0, -1, -0.01, float("nan"), float("inf"),
                                 float("-inf"), True])
def test_rejects_non_positive_or_non_finite_amounts(tmp_path, amt):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", amt, "buy", "market", good(c).period), c)
    assert ok is False and "G5" in why


def test_rejects_wrong_period(tmp_path):
    c = cfg(tmp_path)
    ok, why = reasons(Intent("VTI", 25.0, "buy", "market", "1999-W01"), c)
    assert ok is False and "G8" in why


def test_rejects_second_purchase_in_same_period(tmp_path):
    c = cfg(tmp_path)
    i = good(c)
    ledger.append(c.ledger_path,
                  {"kind": "paper", "amount_usd": 25.0, "period": i.period})
    ok, why = reasons(i, c)
    assert ok is False and "already bought" in why


def test_rejects_when_period_cap_would_be_exceeded(tmp_path):
    c = cfg(tmp_path, amount_usd=25.0, max_spend_per_period_usd=30.0)
    i = good(c)
    ledger.append(c.ledger_path,
                  {"kind": "paper", "amount_usd": 20.0, "period": i.period})
    ok, why = reasons(i, c)
    assert ok is False and "per-period spend cap" in why


def test_rejects_when_lifetime_cap_would_be_exceeded(tmp_path):
    c = cfg(tmp_path, amount_usd=25.0, max_lifetime_spend_usd=60.0)
    for p in ("2026-W01", "2026-W02"):
        ledger.append(c.ledger_path,
                      {"kind": "paper", "amount_usd": 25.0, "period": p})
    ok, why = reasons(good(c), c)
    assert ok is False and "lifetime spend cap" in why


def test_rejects_outside_market_window(tmp_path):
    c = cfg(tmp_path)
    night = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
    ok, why = reasons(plan_order(c, night), c, night)
    assert ok is False and "G6" in why


def test_refusals_accumulate(tmp_path):
    c = cfg(tmp_path)
    ok, bad = validate(Intent("TSLA", 9999.0, "sell", "market", "1999-W01"),
                       c, OPEN_HOURS)
    assert ok is False and len(bad) >= 4


def test_paper_ledger_does_not_consume_live_caps(tmp_path):
    """Weeks of paper runs must not exhaust the live lifetime cap."""
    paper = cfg(tmp_path, mode="paper", max_lifetime_spend_usd=60.0)
    for p in ("2026-W01", "2026-W02"):
        ledger.append(paper.ledger_path,
                      {"kind": "paper", "amount_usd": 25.0, "period": p})
    assert validate(good(paper), paper, OPEN_HOURS)[0] is False
    live = cfg(tmp_path, mode="live", max_lifetime_spend_usd=60.0)
    assert validate(good(live), live, OPEN_HOURS)[0] is True
