import pytest
from pathlib import Path
from guard.config import Config, load_config


def base(**kw):
    d = dict(account_number="123456789", symbol="VTI", amount_usd=25.0)
    d.update(kw)
    return d


def test_minimal_config_loads():
    c = Config(**base())
    assert c.mode == "paper" and c.symbol == "VTI"


def test_symbol_uppercased_and_checked_against_whitelist():
    assert Config(**base(symbol=" vti ")).symbol == "VTI"
    with pytest.raises(Exception, match="not in the whitelist"):
        Config(**base(symbol="TSLA"))


def test_rejects_unknown_field():
    with pytest.raises(Exception):
        Config(**base(bogus=1))


def test_rejects_bad_mode_and_schedule():
    with pytest.raises(Exception):
        Config(**base(mode="yolo"))
    with pytest.raises(Exception):
        Config(**base(schedule="hourly"))


def test_rejects_amount_over_order_cap():
    with pytest.raises(Exception, match="max_order_usd"):
        Config(**base(amount_usd=100.0, max_order_usd=50.0))


def test_rejects_amount_over_period_cap():
    with pytest.raises(Exception, match="per_period"):
        Config(**base(amount_usd=60.0, max_order_usd=100.0,
                      max_spend_per_period_usd=50.0))


def test_rejects_lifetime_below_period_cap():
    with pytest.raises(Exception, match="lifetime"):
        Config(**base(max_spend_per_period_usd=100.0,
                      max_lifetime_spend_usd=50.0))


def test_rejects_nonpositive_amount():
    with pytest.raises(Exception):
        Config(**base(amount_usd=0))
    with pytest.raises(Exception):
        Config(**base(amount_usd=-5))


def test_ledger_path_is_per_mode():
    """Paper spending must never consume the live lifetime cap."""
    p = Config(**base(mode="paper")).ledger_path
    l = Config(**base(mode="live")).ledger_path
    assert p != l
    assert p.name == "ledger-paper.jsonl" and l.name == "ledger-live.jsonl"


def test_config_is_frozen():
    c = Config(**base())
    with pytest.raises(Exception):
        c.amount_usd = 999


def test_load_config_from_file(tmp_path):
    p = tmp_path / "guard.yaml"
    p.write_text("account_number: '123456789'\nsymbol: VOO\namount_usd: 10\n")
    assert load_config(p).symbol == "VOO"


def test_missing_required_field_is_a_startup_failure(tmp_path):
    p = tmp_path / "guard.yaml"
    p.write_text("symbol: VTI\n")
    with pytest.raises(Exception):
        load_config(p)
