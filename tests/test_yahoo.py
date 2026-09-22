import datetime as dt
import json
import pytest
from pathlib import Path
from ebot.config import load_config
from ebot.yahoo import parse_yahoo, fetch_yahoo, fetch_and_cache, URL
from ebot.prices import load_bars


def cfg_for(tmp_path):
    return load_config(Path("config.example.yaml")).model_copy(
        update={"cache_dir": tmp_path})


def payload(n=3, with_null=False):
    base = int(dt.datetime(2020, 1, 2, 9, 30,
                           tzinfo=dt.timezone.utc).timestamp())
    ts = [base + i * 86400 for i in range(n)]
    o = [10.0 + i for i in range(n)]
    c = [10.5 + i for i in range(n)]
    v = [1000 + i for i in range(n)]
    if with_null:
        c = list(c)
        c[1] = None
    return {"chart": {"error": None, "result": [{
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": o, "high": [x + 1 for x in o],
            "low": [x - 1 for x in o], "close": c, "volume": v}]},
    }]}}


def test_parses_bars():
    bars = parse_yahoo(payload(3), "X")
    assert len(bars) == 3
    assert bars[0].open == 10.0 and bars[0].volume == 1000


def test_skips_rows_with_null_fields():
    bars = parse_yahoo(payload(3, with_null=True), "X")
    assert len(bars) == 2, "halted/missing session must be dropped, not zero-filled"


def test_raises_on_yahoo_error():
    with pytest.raises(ValueError, match="yahoo error"):
        parse_yahoo({"chart": {"error": {"code": "Not Found"}, "result": None}}, "X")


def test_raises_on_empty_result():
    with pytest.raises(ValueError, match="no result"):
        parse_yahoo({"chart": {"error": None, "result": []}}, "X")


def test_bars_sorted():
    bars = parse_yahoo(payload(5), "X")
    assert [b.date for b in bars] == sorted(b.date for b in bars)


def test_fetch_raises_when_zero_usable_bars():
    def fake(url):
        return json.dumps({"chart": {"error": None, "result": [
            {"timestamp": [], "indicators": {"quote": [{}]}}]}}).encode()

    with pytest.raises(ValueError, match="zero usable bars"):
        fetch_yahoo("X", dt.date(2020, 1, 1), dt.date(2020, 2, 1), fetch=fake)


def test_url_carries_requested_window():
    seen = {}

    def fake(url):
        seen["url"] = url
        return json.dumps(payload()).encode()

    fetch_yahoo("AAPL", dt.date(2014, 1, 2), dt.date(2026, 9, 22), fetch=fake)
    assert "AAPL" in seen["url"] and "period1=" in seen["url"]


def test_fetch_and_cache_round_trips(tmp_path):
    def fake(url):
        return json.dumps(payload(4)).encode()

    c = cfg_for(tmp_path)
    fetch_and_cache("AAPL", c, fetch=fake)
    assert len(load_bars("AAPL", c)) == 4
