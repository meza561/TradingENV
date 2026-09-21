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


import datetime as dt
from zoneinfo import ZoneInfo
from ebot.edgar import fetch_events

SUBS = json.dumps({"filings": {"recent": {
    "accessionNumber": ["0001-24-01", "0001-24-02", "0001-24-03", "0001-13-99",
                        "0001-24-01"],
    "form":            ["8-K", "8-K", "10-Q", "8-K", "8-K"],
    "items":           ["2.02,7.01", "5.02", "", "2.02", "2.02,7.01"],
    "acceptanceDateTime": ["2024-05-02T16:30:12.000Z", "2024-06-01T09:00:00.000Z",
                           "2024-05-02T16:30:12.000Z", "2013-01-01T16:30:00.000Z",
                           "2024-05-02T16:30:12.000Z"],
}}}).encode()


def _fake(url, ua):
    return FAKE_TICKERS if "company_tickers" in url else SUBS


def test_keeps_only_8k_item_202(tmp_path):
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=_fake)
    assert [e.accession for e in evs] == ["0001-24-01"]


def test_drops_events_before_price_floor(tmp_path):
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=_fake)
    assert all(e.accepted_at.date() >= dt.date(2014, 1, 2) for e in evs)


def test_converts_to_eastern(tmp_path):
    e = fetch_events("AAPL", cfg_for(tmp_path), fetch=_fake)[0]
    assert e.accepted_at.tzinfo is not None
    assert e.accepted_at.astimezone(ZoneInfo("US/Eastern")).hour == 12


def test_deduplicates_by_accession(tmp_path):
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=_fake)
    assert len(evs) == len({e.accession for e in evs})


def test_item_202_matched_exactly_not_substring(tmp_path):
    """'12.02' or '2.021' must not count as Item 2.02."""
    subs = json.dumps({"filings": {"recent": {
        "accessionNumber": ["a1", "a2"],
        "form": ["8-K", "8-K"],
        "items": ["12.02", "2.022"],
        "acceptanceDateTime": ["2024-05-02T16:30:12.000Z",
                               "2024-05-02T16:30:12.000Z"],
    }}}).encode()

    def fake(url, ua):
        return FAKE_TICKERS if "company_tickers" in url else subs

    assert fetch_events("AAPL", cfg_for(tmp_path), fetch=fake) == []


def test_sorted_ascending_by_time(tmp_path):
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=_fake)
    assert evs == sorted(evs, key=lambda e: e.accepted_at)
