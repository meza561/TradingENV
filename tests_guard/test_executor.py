"""No test here may invoke a real order tool."""
import json
import pytest
from pathlib import Path
from guard import ledger
from guard.config import Config
from guard.executor import execute, verify
from guard.plan import Intent

INTENT = Intent("VTI", 25.0, "buy", "market", "2026-W39")


def cfg(tmp_path, **kw):
    d = dict(account_number="111", symbol="VTI", amount_usd=25.0,
             ledger_dir=tmp_path)
    d.update(kw)
    return Config(**d)


def order(ref, **kw):
    o = dict(id="o1", symbol="VTI", side="buy", type="market",
             state="filled", ref_id=ref, dollar_amount="25.00")
    o.update(kw)
    return o


def fake(place_resp=None, orders=None):
    """One runner standing in for both calls, keyed off the tool in argv."""
    def runner(argv, prompt):
        if argv[-1].endswith("place_equity_order"):
            return json.dumps(place_resp or {"order": {"id": "o1"}})
        return json.dumps({"orders": orders if orders is not None else []})
    return runner


def test_paper_mode_logs_and_never_calls_the_broker(tmp_path):
    called = []

    def runner(argv, prompt):
        called.append(argv)
        raise AssertionError("paper mode must not reach the broker")

    c = cfg(tmp_path)
    rec = execute(INTENT, c, tmp_path, live=False, runner=runner)
    assert rec["kind"] == "paper" and called == []
    assert ledger.spent_lifetime(c.ledger_path) == 25.0


def test_live_places_and_verifies(tmp_path):
    c = cfg(tmp_path, mode="live")
    captured = {}

    def runner(argv, prompt):
        if argv[-1].endswith("place_equity_order"):
            captured["ref"] = prompt.split('ref_id="')[1].split('"')[0]
            return json.dumps({"order": {"id": "o1"}})
        return json.dumps({"orders": [order(captured["ref"])]})

    execute(INTENT, c, tmp_path, live=True, runner=runner)
    kinds = [r["kind"] for r in ledger.read_all(c.ledger_path)]
    assert "placed" in kinds and "verified" in kinds
    assert not (tmp_path / "HALT").exists()


@pytest.mark.parametrize("bad", [
    {"symbol": "TSLA"}, {"side": "sell"}, {"type": "limit"},
    {"dollar_amount": "250.00"}, {"dollar_amount": "not-a-number"},
])
def test_mismatch_writes_halt(tmp_path, bad):
    c = cfg(tmp_path, mode="live")
    captured = {}

    def runner(argv, prompt):
        if argv[-1].endswith("place_equity_order"):
            captured["ref"] = prompt.split('ref_id="')[1].split('"')[0]
            return json.dumps({"order": {"id": "o1"}})
        return json.dumps({"orders": [order(captured["ref"], **bad)]})

    execute(INTENT, c, tmp_path, live=True, runner=runner)
    assert (tmp_path / "HALT").exists(), f"no HALT for mismatch {bad}"
    assert "halted" in [r["kind"] for r in ledger.read_all(c.ledger_path)]


def test_missing_order_is_a_mismatch(tmp_path):
    c = cfg(tmp_path, mode="live")
    execute(INTENT, c, tmp_path, live=True, runner=fake(orders=[]))
    assert (tmp_path / "HALT").exists()


def test_duplicate_ref_id_is_a_mismatch(tmp_path):
    c = cfg(tmp_path, mode="live")
    captured = {}

    def runner(argv, prompt):
        if argv[-1].endswith("place_equity_order"):
            captured["ref"] = prompt.split('ref_id="')[1].split('"')[0]
            return json.dumps({"order": {"id": "o1"}})
        r = captured["ref"]
        return json.dumps({"orders": [order(r), order(r, id="o2")]})

    execute(INTENT, c, tmp_path, live=True, runner=runner)
    assert (tmp_path / "HALT").exists(), "a duplicate order must halt"


def test_verification_read_failure_halts(tmp_path):
    """Unknown state after placing is the dangerous case: fail loud."""
    c = cfg(tmp_path, mode="live")

    def runner(argv, prompt):
        if argv[-1].endswith("place_equity_order"):
            return json.dumps({"order": {"id": "o1"}})
        raise RuntimeError("network died")

    execute(INTENT, c, tmp_path, live=True, runner=runner)
    assert (tmp_path / "HALT").exists()


def test_place_failure_logs_error_and_does_not_halt(tmp_path):
    """Nothing was placed, so there is nothing to be unsure about."""
    c = cfg(tmp_path, mode="live")

    def runner(argv, prompt):
        raise RuntimeError("session limit")

    rec = execute(INTENT, c, tmp_path, live=True, runner=runner)
    assert rec["kind"] == "error"
    assert not (tmp_path / "HALT").exists()
    assert ledger.spent_lifetime(c.ledger_path) == 0.0


def test_failed_place_does_not_consume_the_cap(tmp_path):
    c = cfg(tmp_path, mode="live")
    execute(INTENT, c, tmp_path, live=True,
            runner=lambda a, p: (_ for _ in ()).throw(RuntimeError("x")))
    assert ledger.spent_lifetime(c.ledger_path) == 0.0


def test_verify_is_case_insensitive_on_broker_fields():
    ok, why = verify([order("r1", symbol="vti", side="BUY", type="Market")],
                     INTENT, "r1")
    assert ok is True, why
