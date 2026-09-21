import json
import datetime as dt
import pytest
from pathlib import Path
from ebot.prices import fetch_year, fetch_all_years, load_bars, ALLOWED_TOOLS
from ebot.config import load_config


def cfg_for(tmp_path, **kw):
    c = load_config(Path("config.example.yaml"))
    return c.model_copy(update={"cache_dir": tmp_path, **kw})


def payload(year):
    return json.dumps({"bars": [
        {"date": f"{year}-01-02", "open": 1.0, "high": 2.0, "low": 0.5,
         "close": 1.5, "volume": 100},
        {"date": f"{year}-01-03", "open": 1.5, "high": 2.5, "low": 1.0,
         "close": 2.0, "volume": 200},
    ]})


def test_allowlist_is_read_only():
    assert ALLOWED_TOOLS == ["mcp__robinhood-trading__get_equity_historicals"]
    joined = " ".join(ALLOWED_TOOLS).lower()
    for banned in ("place_", "cancel_", "order", "exercise"):
        assert banned not in joined, f"forbidden tool family {banned!r} in allowlist"


def test_argv_never_contains_order_tool(tmp_path):
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return payload(2020)

    fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)
    flat = " ".join(seen["argv"])
    assert "place_equity_order" not in flat
    assert "--allowedTools" in flat


def test_request_window_is_bounded_to_the_year(tmp_path):
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return payload(2020)

    fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)
    flat = " ".join(seen["argv"])
    assert "2020-01-01" in flat and "2020-12-31" in flat


def test_parses_and_caches(tmp_path):
    calls = []

    def runner(argv):
        calls.append(argv)
        return payload(2020)

    c = cfg_for(tmp_path)
    bars = fetch_year("AAPL", 2020, c, runner=runner)
    assert len(bars) == 2
    assert bars[0].date == dt.date(2020, 1, 2) and bars[0].close == 1.5
    assert len(load_bars("AAPL", c)) == 2
    assert len(calls) == 1


def test_fetch_all_years_skips_cached_years(tmp_path):
    calls = []

    def runner(argv):
        calls.append(argv)
        year = next(a for a in argv if "-01-01" in a)
        return payload(year.split("-")[0][-4:])

    c = cfg_for(tmp_path, price_floor=dt.date(2020, 1, 1))
    fetch_all_years("AAPL", c, runner=runner)
    n_first = len(calls)
    assert n_first >= 2
    fetch_all_years("AAPL", c, runner=runner)
    # only the current year is refetched; prior years come from cache
    assert len(calls) == n_first + 1


def test_rejects_unparseable_output(tmp_path):
    def runner(argv):
        return "I could not find that data, sorry!"

    with pytest.raises(ValueError):
        fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)


def test_rejects_bars_outside_requested_year(tmp_path):
    def runner(argv):
        return json.dumps({"bars": [
            {"date": "2019-06-01", "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1}]})

    with pytest.raises(ValueError, match="outside requested year"):
        fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)


def test_load_bars_returns_sorted(tmp_path):
    def runner(argv):
        return json.dumps({"bars": [
            {"date": "2020-03-05", "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1},
            {"date": "2020-01-02", "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1}]})

    c = cfg_for(tmp_path)
    fetch_year("AAPL", 2020, c, runner=runner)
    dates = [b.date for b in load_bars("AAPL", c)]
    assert dates == sorted(dates)
