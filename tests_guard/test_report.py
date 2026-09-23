import datetime as dt
from pathlib import Path
from guard import ledger
from guard.optconfig import OptionConfig
from guard.report import digest

TODAY = dt.date(2026, 9, 23)


def cfg_for(tmp_path):
    return OptionConfig(account_number="1", ledger_dir=tmp_path)


def test_empty_ledger_says_so(tmp_path):
    assert "no activity" in digest(cfg_for(tmp_path), TODAY)


def test_shows_open_position_and_caps(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {
        "kind": "paper_open", "option_id": "a", "underlying": "TLT",
        "strike": 83.0, "option_type": "call", "expiration": "2026-10-30",
        "quantity": 1, "fill_price": 0.40, "cost_usd": 40.0})
    d = digest(c, TODAY)
    assert "open 1/2" in d and "$40.00 of $2,000" in d
    assert "TLT 83.0C" in d and "37 DTE" in d


def test_stays_compact_as_the_ledger_grows(tmp_path):
    """Token cost must not scale with history."""
    c = cfg_for(tmp_path)
    for i in range(500):
        ledger.append(c.ledger_path, {"kind": "skipped", "period": f"p{i}",
                                      "codes": ["G6"]})
    d = digest(c, TODAY)
    assert len(d.splitlines()) <= 20, d
    assert "skipped 500" in d


def test_closed_position_leaves_no_open_row(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "paper_open", "option_id": "a",
                                  "underlying": "TLT", "strike": 83.0,
                                  "expiration": "2026-10-30", "quantity": 1,
                                  "fill_price": 0.4, "cost_usd": 40.0})
    ledger.append(c.ledger_path, {"kind": "paper_close", "option_id": "a",
                                  "reason": "take profit +52.0%"})
    d = digest(c, TODAY)
    assert "open 0/2" in d
    assert "deployed $40.00" in d, "a close must not refund the lifetime cap"
    assert "take profit" in d


def test_skips_are_excluded_from_recent_but_still_counted(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "declined", "rationale": "wide"})
    for i in range(10):
        ledger.append(c.ledger_path, {"kind": "skipped", "codes": ["G6"]})
    d = digest(c, TODAY)
    assert "declined" in d.split("last")[1]
    assert "skipped 10" in d


def test_bad_expiration_does_not_crash(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, {"kind": "paper_open", "option_id": "a",
                                  "underlying": "TLT", "strike": 83.0,
                                  "expiration": "garbage", "quantity": 1,
                                  "fill_price": 0.4, "cost_usd": 40.0})
    assert "? DTE" in digest(c, TODAY)


def op(oid, px, cost=40.0, **kw):
    d = dict(kind="paper_open", option_id=oid, underlying="TLT", strike=83.0,
             option_type="call", expiration="2026-10-30", quantity=1,
             fill_price=px, cost_usd=cost)
    d.update(kw); return d


def cl(oid, px, reason="take profit"):
    return dict(kind="paper_close", option_id=oid, underlying="TLT",
                fill_price=px, reason=reason, quantity=1)


def test_realized_pnl_on_a_winner(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    ledger.append(c.ledger_path, cl("a", 0.62))
    total, wins, losses = paper.realized(c.ledger_path)
    assert total == 22.0 and wins == 1 and losses == 0
    assert "realised +22.00" in digest(c, TODAY)


def test_realized_pnl_on_a_loser(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    ledger.append(c.ledger_path, cl("a", 0.19, "stop loss"))
    total, wins, losses = paper.realized(c.ledger_path)
    assert total == -21.0 and wins == 0 and losses == 1


def test_mixed_book_totals_correctly(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    for oid, entry, exit_ in (("a", 0.40, 0.62), ("b", 0.50, 0.25),
                              ("c", 1.00, 1.10)):
        ledger.append(c.ledger_path, op(oid, entry))
        ledger.append(c.ledger_path, cl(oid, exit_))
    total, wins, losses = paper.realized(c.ledger_path)
    assert total == round(22.0 - 25.0 + 10.0, 2) and wins == 2 and losses == 1


def test_same_contract_reopened_is_a_separate_trade(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    ledger.append(c.ledger_path, cl("a", 0.60))
    ledger.append(c.ledger_path, op("a", 0.30))
    ledger.append(c.ledger_path, cl("a", 0.45))
    assert len(paper.closed_trades(c.ledger_path)) == 2


def test_open_position_is_not_counted_as_realized(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    assert paper.realized(c.ledger_path) == (0.0, 0, 0)
    assert "closed:" not in digest(c, TODAY)


def test_close_without_an_open_is_ignored(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, cl("orphan", 0.60))
    assert paper.closed_trades(c.ledger_path) == []


def test_zero_entry_price_does_not_divide_by_zero(tmp_path):
    from guard import paper
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.0))
    ledger.append(c.ledger_path, cl("a", 0.60))
    assert paper.closed_trades(c.ledger_path) == []


def test_marks_show_unrealized_without_network_when_stubbed(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    import json
    runner = lambda argv, prompt: json.dumps(
        {"quotes": [{"instrument_id": "a", "mark_price": "0.52"}]})
    d = digest(c, TODAY, marks=True, runner=runner)
    assert "unrealised +12.00" in d and "now $0.52" in d and "+30.0%" in d


def test_marks_failure_degrades_gracefully(tmp_path):
    c = cfg_for(tmp_path)
    ledger.append(c.ledger_path, op("a", 0.40))
    def boom(argv, prompt):
        raise RuntimeError("session limit")
    d = digest(c, TODAY, marks=True, runner=boom)
    assert "live marks unavailable" in d and "entry $0.40" in d


def test_digest_still_bounded_with_many_closed_trades(tmp_path):
    c = cfg_for(tmp_path)
    for i in range(200):
        ledger.append(c.ledger_path, op(f"o{i}", 0.40))
        ledger.append(c.ledger_path, cl(f"o{i}", 0.50))
    assert len(digest(c, TODAY).splitlines()) <= 22
