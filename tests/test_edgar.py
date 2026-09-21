import json
import pytest
from pathlib import Path
from ebot.edgar import resolve_cik
from ebot.config import load_config

FAKE_TICKERS = json.dumps({
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}).encode()


def cfg_for(tmp_path):
    c = load_config(Path("config.example.yaml"))
    return c.model_copy(update={"cache_dir": tmp_path})


def test_resolves_and_zero_pads(tmp_path):
    calls = []

    def fake(url, ua):
        calls.append(url)
        return FAKE_TICKERS

    assert resolve_cik("AAPL", cfg_for(tmp_path), fetch=fake) == "0000320193"
    assert len(calls) == 1


def test_second_call_uses_cache(tmp_path):
    calls = []

    def fake(url, ua):
        calls.append(url)
        return FAKE_TICKERS

    c = cfg_for(tmp_path)
    resolve_cik("AAPL", c, fetch=fake)
    resolve_cik("AAPL", c, fetch=fake)
    assert len(calls) == 1, "second resolve must hit cache, not network"


def test_sibling_ticker_also_cached_from_one_fetch(tmp_path):
    calls = []

    def fake(url, ua):
        calls.append(url)
        return FAKE_TICKERS

    c = cfg_for(tmp_path)
    resolve_cik("AAPL", c, fetch=fake)
    assert resolve_cik("MSFT", c, fetch=fake) == "0000789019"
    assert len(calls) == 1, "whole registry is cached in one pass"


def test_unknown_ticker_raises(tmp_path):
    def fake(url, ua):
        return FAKE_TICKERS

    with pytest.raises(KeyError):
        resolve_cik("NOSUCH", cfg_for(tmp_path), fetch=fake)


def test_lowercase_input_normalized(tmp_path):
    def fake(url, ua):
        return FAKE_TICKERS

    assert resolve_cik("  aapl ", cfg_for(tmp_path), fetch=fake) == "0000320193"
