import json
from pathlib import Path
from guard import ledger


def test_append_adds_timestamp_and_roundtrips(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "paper", "amount_usd": 25.0, "period": "2026-W39"})
    rows = ledger.read_all(p)
    assert len(rows) == 1 and rows[0]["kind"] == "paper" and "ts" in rows[0]


def test_read_all_on_missing_file():
    assert ledger.read_all(Path("/nonexistent/x.jsonl")) == []


def test_only_spend_kinds_count(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "refused", "amount_usd": 25.0, "period": "P"})
    ledger.append(p, {"kind": "paper", "amount_usd": 25.0, "period": "P"})
    ledger.append(p, {"kind": "placed", "amount_usd": 10.0, "period": "P"})
    assert ledger.spent_lifetime(p) == 35.0
    assert ledger.spent_in_period(p, "P") == 35.0


def test_period_isolation(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "paper", "amount_usd": 25.0, "period": "A"})
    ledger.append(p, {"kind": "paper", "amount_usd": 25.0, "period": "B"})
    assert ledger.spent_in_period(p, "A") == 25.0
    assert ledger.spent_lifetime(p) == 50.0
    assert ledger.periods_bought(p) == {"A", "B"}


def test_account_numbers_are_masked(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "placed", "account": "680370186",
                      "note": "order for 680370186"})
    raw = p.read_text()
    assert "680370186" not in raw, "G10: account number leaked into the ledger"
    assert "0186" in raw


def test_masking_recurses_into_nested_structures(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "placed",
                      "resp": {"orders": [{"account_number": "680370186"}]}})
    assert "680370186" not in p.read_text()


def test_appends_never_rewrite(tmp_path):
    p = tmp_path / "l.jsonl"
    for i in range(3):
        ledger.append(p, {"kind": "paper", "amount_usd": 1.0, "period": f"P{i}"})
    assert len(p.read_text().strip().splitlines()) == 3
