import pytest, datetime as dt
from pathlib import Path
from ebot.config import load_config, Config
from ebot.types import Bar, Event, Trade


def test_loads_example_config():
    cfg = load_config(Path("config.example.yaml"))
    assert isinstance(cfg, Config)
    assert "AAPL" in cfg.whitelist
    assert len(cfg.whitelist) == 12
    assert cfg.train_test_split == dt.date(2021, 1, 1)
    assert cfg.price_floor == dt.date(2014, 1, 2)


def test_rejects_unknown_field(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("whitelist: [AAPL]\nsec_user_agent: x\nbogus_field: 1\n")
    with pytest.raises(Exception):
        load_config(p)


def test_rejects_empty_whitelist(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("whitelist: []\nsec_user_agent: x\n")
    with pytest.raises(Exception):
        load_config(p)


def test_rejects_duplicate_tickers(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("whitelist: [AAPL, aapl]\nsec_user_agent: x\n")
    with pytest.raises(Exception):
        load_config(p)


def test_bar_is_frozen():
    b = Bar(symbol="AAPL", date=dt.date(2026, 1, 2), open=1.0, high=2.0,
            low=0.5, close=1.5, volume=100)
    with pytest.raises(Exception):
        b.close = 99.0
