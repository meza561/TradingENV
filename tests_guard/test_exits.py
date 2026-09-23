import datetime as dt
import pytest
from guard.exits import (OptionPosition, exit_decision, days_to_expiry,
                         pnl_pct, HOLD, CLOSE, HALT)
from guard.optconfig import OptionConfig

CFG = OptionConfig(account_number="1")
TODAY = dt.date(2026, 9, 23)


def pos(avg=1.00, exp_days=38, qty=1):
    return OptionPosition("oid", "XLU", 41.0,
                          TODAY + dt.timedelta(days=exp_days), qty, avg)


def test_holds_in_the_middle():
    d, why = exit_decision(pos(), 1.10, TODAY, CFG)
    assert d == HOLD, why


def test_take_profit_at_exactly_fifty():
    assert exit_decision(pos(), 1.50, TODAY, CFG)[0] == CLOSE


def test_take_profit_above():
    d, why = exit_decision(pos(), 2.00, TODAY, CFG)
    assert d == CLOSE and "take profit" in why


def test_stop_loss_at_exactly_minus_fifty():
    assert exit_decision(pos(), 0.50, TODAY, CFG)[0] == CLOSE


def test_stop_loss_below():
    d, why = exit_decision(pos(), 0.10, TODAY, CFG)
    assert d == CLOSE and "stop loss" in why


def test_closes_at_dte_threshold():
    d, why = exit_decision(pos(exp_days=14), 1.05, TODAY, CFG)
    assert d == CLOSE and "DTE" in why


def test_holds_one_day_before_dte_threshold():
    assert exit_decision(pos(exp_days=15), 1.05, TODAY, CFG)[0] == HOLD


def test_profit_target_wins_over_dte():
    """A winner on its last eligible day is taken as profit, not calendar."""
    d, why = exit_decision(pos(exp_days=14), 1.60, TODAY, CFG)
    assert d == CLOSE and "take profit" in why


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True])
def test_unevaluable_cost_basis_halts(bad):
    d, why = exit_decision(pos(avg=bad), 1.0, TODAY, CFG)
    assert d == HALT and "average_price" in why


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_unevaluable_mark_halts(bad):
    d, why = exit_decision(pos(), bad, TODAY, CFG)
    assert d == HALT and "mark" in why


def test_expired_position_halts():
    d, why = exit_decision(pos(exp_days=-1), 1.0, TODAY, CFG)
    assert d == HALT and "already passed" in why


def test_zero_quantity_halts():
    assert exit_decision(pos(qty=0), 1.0, TODAY, CFG)[0] == HALT


def test_expiry_day_itself_closes_not_halts():
    d, why = exit_decision(pos(exp_days=0), 1.0, TODAY, CFG)
    assert d == CLOSE


def test_helpers():
    assert days_to_expiry(pos(exp_days=5), TODAY) == 5
    assert pnl_pct(pos(avg=1.0), 1.25) == pytest.approx(25.0)


def test_config_rejects_close_at_dte_above_min_dte():
    """A position opened at 30 DTE with close_at_dte=31 would close instantly."""
    with pytest.raises(Exception, match="close_at_dte"):
        OptionConfig(account_number="1", min_dte=30, close_at_dte=31)


def test_config_rejects_position_cap_above_lifetime():
    with pytest.raises(Exception, match="lifetime"):
        OptionConfig(account_number="1", max_position_usd=200,
                     max_lifetime_usd=100)
