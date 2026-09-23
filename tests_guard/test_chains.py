import datetime as dt
import json
from pathlib import Path
from guard import chains
from guard.optconfig import OptionConfig

TODAY = dt.date(2026, 9, 23)


def cfg_for(tmp_path):
    return OptionConfig(account_number="1", underlyings=["TLT"],
                        ledger_dir=tmp_path)


def make_runner(counter):
    def runner(argv, prompt):
        tool = argv[-1]
        counter.append(tool)
        if "get_equity_quotes" in tool:
            return json.dumps({"quotes": [{"symbol": "TLT", "price": 80.65}]})
        if "get_option_chains" in tool:
            return json.dumps({"expiration_dates":
                               ["2026-09-25", "2026-10-30", "2027-01-15"]})
        if "get_option_instruments" in tool:
            return json.dumps({"instruments": [
                {"id": "a", "strike_price": "83.0",
                 "expiration_date": "2026-10-30", "type": "call"},
                {"id": "b", "strike_price": "200.0",   # far outside the band
                 "expiration_date": "2026-10-30", "type": "call"}]})
        return json.dumps({"quotes": [
            {"instrument_id": "a", "bid_price": "0.39", "ask_price": "0.40",
             "delta": "0.245", "open_interest": 4356}]})
    return runner


def test_returns_merged_instrument_and_quote(tmp_path):
    calls = []
    out = chains.fetch_candidates(cfg_for(tmp_path), TODAY, make_runner(calls))
    assert len(out) == 1
    c = out[0]
    assert c["option_id"] == "a" and c["underlying"] == "TLT"
    assert c["ask"] == "0.40" and c["open_interest"] == 4356


def test_only_expirations_inside_the_dte_window_are_used(tmp_path):
    calls = []
    chains.fetch_candidates(cfg_for(tmp_path), TODAY, make_runner(calls))
    # 2026-09-25 is 2 DTE, 2027-01-15 is far out; only 2026-10-30 (37) qualifies
    instr = [p for p in calls if "instruments" in p]
    assert len(instr) == 1


def test_strikes_far_from_spot_are_dropped(tmp_path):
    out = chains.fetch_candidates(cfg_for(tmp_path), TODAY, make_runner([]))
    assert [c["strike"] for c in out] == [83.0]


def test_chain_structure_is_cached_within_a_day(tmp_path):
    cfg = cfg_for(tmp_path)
    first, second = [], []
    chains.fetch_candidates(cfg, TODAY, make_runner(first))
    chains.fetch_candidates(cfg, TODAY, make_runner(second))
    n_struct = lambda c: sum(1 for t in c if "chains" in t or "instruments" in t)
    assert n_struct(first) == 2
    assert n_struct(second) == 0, "chain structure must not be refetched same-day"


def test_quotes_are_always_fresh(tmp_path):
    cfg = cfg_for(tmp_path)
    first, second = [], []
    chains.fetch_candidates(cfg, TODAY, make_runner(first))
    chains.fetch_candidates(cfg, TODAY, make_runner(second))
    assert sum(1 for t in second if "get_option_quotes" in t) == 1


def test_a_new_day_refetches_structure(tmp_path):
    cfg = cfg_for(tmp_path)
    chains.fetch_candidates(cfg, TODAY, make_runner([]))
    tomorrow = []
    chains.fetch_candidates(cfg, TODAY + dt.timedelta(days=1),
                            make_runner(tomorrow))
    assert any("instruments" in t for t in tomorrow)


def test_missing_spot_skips_the_underlying(tmp_path):
    def runner(argv, prompt):
        if "get_equity_quotes" in argv[-1]:
            return json.dumps({"quotes": []})
        raise AssertionError("must not proceed without a spot price")
    assert chains.fetch_candidates(cfg_for(tmp_path), TODAY, runner) == []


def null_runner(argv, prompt):
    """Every list field comes back as JSON null rather than absent.
    .get(k, default) returns None when the key EXISTS with a null value."""
    tool = argv[-1]
    if "get_equity_quotes" in tool:
        return json.dumps({"quotes": None})
    if "get_option_chains" in tool:
        return json.dumps({"expiration_dates": None})
    if "get_option_instruments" in tool:
        return json.dumps({"instruments": None})
    return json.dumps({"quotes": None})


def test_null_fields_do_not_crash_the_cycle(tmp_path):
    assert chains.fetch_candidates(cfg_for(tmp_path), TODAY, null_runner) == []


def test_null_expirations_are_survivable(tmp_path):
    def runner(argv, prompt):
        if "get_equity_quotes" in argv[-1]:
            return json.dumps({"quotes": [{"symbol": "TLT", "price": 80.65}]})
        return json.dumps({"expiration_dates": None})
    assert chains.fetch_candidates(cfg_for(tmp_path), TODAY, runner) == []
