import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from guard import ledger
from guard.run_opt import run, OK, LOCKED, HALTED

ET = ZoneInfo("US/Eastern")
OPEN_HOURS = dt.datetime(2026, 9, 25, 12, 0, tzinfo=ET)
NIGHT = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
EXP = (OPEN_HOURS.date() + dt.timedelta(days=35)).isoformat()


def setup(tmp_path, **kw):
    lines = ["account_number: '111'", "mode: paper", f"ledger_dir: {tmp_path}"]
    lines += [f"{k}: {v}" for k, v in kw.items()]
    p = tmp_path / "options.yaml"
    p.write_text("\n".join(lines) + "\n")
    return p


def candidate_rows(cfg, today, runner):
    return [dict(option_id="oid-1", underlying="XLU", option_type="call",
                 strike=41.0, expiration=EXP, bid=0.46, ask=0.48,
                 delta=0.30, open_interest=238)]


def no_rows(cfg, today, runner):
    return []


def runner_for(decision, quotes=None):
    def runner(argv, prompt):
        tool = argv[-1]
        if "get_option_quotes" in tool:
            return json.dumps({"quotes": quotes or []})
        if "get_option_positions" in tool:
            return json.dumps({"positions": []})
        return json.dumps(decision)          # the analyst
    return runner


LD = tmp = None


def test_halt_short_circuits(tmp_path):
    cp = setup(tmp_path)
    (tmp_path / "HALT").touch()
    assert run(tmp_path, cp, OPEN_HOURS, runner_for({}), candidate_rows) == HALTED


def test_outside_window_does_nothing(tmp_path):
    cp = setup(tmp_path)
    assert run(tmp_path, cp, NIGHT, runner_for({}), candidate_rows) == OK
    assert ledger.read_all(tmp_path / "opt-ledger-paper.jsonl") == []


def test_paper_open_is_recorded(tmp_path):
    cp = setup(tmp_path)
    r = runner_for({"action": "open", "option_id": "oid-1",
                    "rationale": "ok", "confidence": 0.3})
    assert run(tmp_path, cp, OPEN_HOURS, r, candidate_rows) == OK
    rows = ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")
    assert [x["kind"] for x in rows] == ["paper_open"]
    assert rows[0]["cost_usd"] == 48.0


def test_analyst_decline_is_recorded(tmp_path):
    cp = setup(tmp_path)
    r = runner_for({"action": "none", "rationale": "spreads"})
    run(tmp_path, cp, OPEN_HOURS, r, candidate_rows)
    rows = ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")
    assert rows[0]["kind"] == "declined"


def test_no_eligible_contracts_is_recorded_with_reasons(tmp_path):
    cp = setup(tmp_path)

    def bad_rows(cfg, today, runner):
        return [dict(option_id="x", underlying="XLU", option_type="call",
                     strike=41.0, expiration=EXP, bid=0.45, ask=0.94,
                     delta=0.30, open_interest=238)]

    run(tmp_path, cp, OPEN_HOURS, runner_for({}), bad_rows)
    rows = ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")
    assert rows[0]["kind"] == "no_candidates"
    assert "spread" in json.dumps(rows[0]["rejected"])


def test_slots_fill_and_block_further_entries(tmp_path):
    cp = setup(tmp_path, max_open_positions=1)
    r = runner_for({"action": "open", "option_id": "oid-1",
                    "rationale": "ok", "confidence": 0.3},
                   quotes=[{"instrument_id": "oid-1", "mark_price": "0.50",
                            "bid_price": "0.49"}])
    run(tmp_path, cp, OPEN_HOURS, r, candidate_rows)
    run(tmp_path, cp, OPEN_HOURS, r, candidate_rows)
    kinds = [x["kind"] for x in ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")]
    assert kinds.count("paper_open") == 1, "a filled slot must block a second open"


def test_exit_closes_on_profit_target(tmp_path):
    cp = setup(tmp_path, max_open_positions=1)
    opened = runner_for({"action": "open", "option_id": "oid-1",
                         "rationale": "ok", "confidence": 0.3})
    run(tmp_path, cp, OPEN_HOURS, opened, candidate_rows)
    # next cycle: mark is +50% over the 0.48 fill
    r = runner_for({"action": "none"},
                   quotes=[{"instrument_id": "oid-1", "mark_price": "0.72",
                            "bid_price": "0.71"}])
    run(tmp_path, cp, OPEN_HOURS, r, no_rows)
    rows = ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")
    closed = [x for x in rows if x["kind"] == "paper_close"]
    assert len(closed) == 1 and "take profit" in closed[0]["reason"]


def test_exit_closes_on_stop(tmp_path):
    cp = setup(tmp_path, max_open_positions=1)
    run(tmp_path, cp, OPEN_HOURS,
        runner_for({"action": "open", "option_id": "oid-1", "rationale": "x",
                    "confidence": 0.2}), candidate_rows)
    r = runner_for({"action": "none"},
                   quotes=[{"instrument_id": "oid-1", "mark_price": "0.20",
                            "bid_price": "0.19"}])
    run(tmp_path, cp, OPEN_HOURS, r, no_rows)
    closed = [x for x in ledger.read_all(tmp_path / "opt-ledger-paper.jsonl")
              if x["kind"] == "paper_close"]
    assert closed and "stop loss" in closed[0]["reason"]


def test_unevaluable_mark_halts_the_system(tmp_path):
    cp = setup(tmp_path, max_open_positions=1)
    run(tmp_path, cp, OPEN_HOURS,
        runner_for({"action": "open", "option_id": "oid-1", "rationale": "x",
                    "confidence": 0.2}), candidate_rows)
    r = runner_for({"action": "none"},
                   quotes=[{"instrument_id": "oid-1", "mark_price": "0"}])
    assert run(tmp_path, cp, OPEN_HOURS, r, no_rows) == HALTED
    assert (tmp_path / "HALT").exists()


def test_deployed_counts_opens_only(tmp_path):
    """A winning close must not refund the all-time cap."""
    from guard import paper
    p = tmp_path / "l.jsonl"
    ledger.append(p, {"kind": "paper_open", "option_id": "a", "cost_usd": 48.0})
    ledger.append(p, {"kind": "paper_close", "option_id": "a", "fill_price": 0.9})
    assert paper.deployed(p) == 48.0
    assert paper.open_positions(p) == []


def test_lock_blocks_a_concurrent_cycle(tmp_path):
    cp = setup(tmp_path)
    from guard.cyclelock import cycle_lock
    with cycle_lock(tmp_path) as got:
        assert got
        assert run(tmp_path, cp, OPEN_HOURS, runner_for({}), candidate_rows) == LOCKED


def test_paper_balance_shrinks_as_capital_is_deployed(tmp_path):
    """Paper must not offer infinite money: deployed capital reduces it."""
    from guard.run_opt import _account
    from guard.optconfig import load_option_config
    cp = setup(tmp_path, paper_start_usd=150)
    cfg = load_option_config(cp)
    v0, _ = _account(cfg, False, None, cfg.ledger_path)
    ledger.append(cfg.ledger_path, {"kind": "paper_open", "option_id": "a",
                                    "cost_usd": 50.0})
    v1, _ = _account(cfg, False, None, cfg.ledger_path)
    assert v0 == 150.0 and v1 == 100.0


def test_main_wires_the_real_chain_fetcher(tmp_path, monkeypatch):
    """A stub default would find nothing forever while looking healthy."""
    from guard import run_opt, chains
    seen = {}

    def fake_run(root, config, now_et=None, runner=None, candidates_fn=None):
        seen["fn"] = candidates_fn
        return OK

    monkeypatch.setattr(run_opt, "run", fake_run)
    cp = setup(tmp_path)
    run_opt.main(["--config", str(cp), "--root", str(tmp_path)])
    assert seen["fn"] is chains.fetch_candidates


def test_live_halts_when_holdings_cannot_be_read(tmp_path):
    """Unknown holdings -> stop. Never skip exits or miscount free slots."""
    cp = setup(tmp_path, mode="live")
    (tmp_path / "LIVE_ENABLED").touch()

    def runner(argv, prompt):
        if "get_option_positions" in argv[-1]:
            return json.dumps({"positions": None})   # unreadable
        return json.dumps({})

    assert run(tmp_path, cp, OPEN_HOURS, runner, candidate_rows) == HALTED
    assert (tmp_path / "HALT").exists()
    rows = ledger.read_all(tmp_path / "opt-ledger-live.jsonl")
    assert rows and rows[-1]["kind"] == "halted"


def test_plist_cadence_matches_the_config(tmp_path):
    """A cadence_minutes that launchd ignores is worse than no setting."""
    import plistlib, sys
    from pathlib import Path
    sys.path.insert(0, str(Path.cwd() / "ops"))
    import make_plist
    from guard.optconfig import load_option_config
    cfg = load_option_config(Path("options.yaml"))
    d = make_plist.build(cfg)
    assert d["StartInterval"] == cfg.cadence_minutes * 60
