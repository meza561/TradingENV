import pytest
from guard.optconfig import OptionConfig
from guard.sizing import size_position, remaining_lifetime, affordable

CFG = OptionConfig(account_number="1")   # 50 floor, 100 ceiling, 0.33, 2000 life


def test_small_account_gets_the_floor():
    assert size_position(150.0, CFG) == 50.0     # 0.33*150 = 49.5 -> floor


def test_scales_with_account_value():
    assert size_position(210.0, CFG) == pytest.approx(69.3)


def test_hits_the_ceiling():
    assert size_position(1000.0, CFG) == 100.0
    assert size_position(100000.0, CFG) == 100.0


def test_account_below_the_floor_does_not_trade():
    assert size_position(40.0, CFG) == 0.0


def test_account_exactly_at_the_floor_trades():
    assert size_position(50.0, CFG) == 50.0


@pytest.mark.parametrize("bad", [0, -100, float("nan"), float("inf"), True])
def test_invalid_account_value_sizes_to_zero(bad):
    assert size_position(bad, CFG) == 0.0


def test_remaining_lifetime():
    assert remaining_lifetime(0.0, CFG) == 2000.0
    assert remaining_lifetime(1950.0, CFG) == 50.0
    assert remaining_lifetime(2500.0, CFG) == 0.0


def test_affordable_happy_path():
    amt, why = affordable(150.0, 0.0, 150.0, CFG)
    assert amt == 50.0 and why == ""


def test_lifetime_cap_stops_everything():
    amt, why = affordable(150.0, 2000.0, 150.0, CFG)
    assert amt == 0.0 and "a human must raise it" in why


def test_partial_headroom_below_floor_refuses():
    """$30 of headroom cannot buy a sane contract, so it does not try."""
    amt, why = affordable(150.0, 1970.0, 150.0, CFG)
    assert amt == 0.0 and "below the" in why


def test_headroom_trims_the_position():
    cfg = OptionConfig(account_number="1", max_lifetime_usd=2000.0)
    amt, why = affordable(1000.0, 1940.0, 5000.0, cfg)
    assert amt == 60.0, why     # would be 100, trimmed to remaining headroom


def test_insufficient_buying_power_refuses():
    amt, why = affordable(150.0, 0.0, 20.0, CFG)
    assert amt == 0.0 and "buying power" in why


def test_unsettled_cash_scenario():
    """Account worth $150 but nothing settled yet -- must not trade."""
    amt, why = affordable(150.0, 0.0, 0.0, CFG)
    assert amt == 0.0 and "buying power" in why


def test_config_rejects_floor_above_ceiling():
    with pytest.raises(Exception, match="min_position_usd"):
        OptionConfig(account_number="1", min_position_usd=200,
                     max_position_usd=100)
