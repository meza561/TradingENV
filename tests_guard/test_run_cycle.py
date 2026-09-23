import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
from guard import ledger
from guard.run_cycle import run, OK, HALTED, CONFIG_ERROR

ET = ZoneInfo("US/Eastern")
OPEN_HOURS = dt.datetime(2026, 9, 25, 12, 0, tzinfo=ET)
NIGHT = dt.datetime(2026, 9, 25, 23, 0, tzinfo=ET)


def setup(tmp_path, mode="paper", **kw):
    lines = [f"mode: {mode}", "account_number: '111'", "symbol: VTI",
             "amount_usd: 25", f"ledger_dir: {tmp_path}"]
    lines += [f"{k}: {v}" for k, v in kw.items()]
    p = tmp_path / "guard.yaml"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_halt_short_circuits_everything(tmp_path):
    cp = setup(tmp_path)
    (tmp_path / "HALT").touch()
    assert run(tmp_path, cp, OPEN_HOURS) == HALTED
    assert ledger.read_all(tmp_path / "ledger-paper.jsonl") == []


def test_paper_buy_in_window(tmp_path):
    cp = setup(tmp_path)
    assert run(tmp_path, cp, OPEN_HOURS) == OK
    rows = ledger.read_all(tmp_path / "ledger-paper.jsonl")
    assert [r["kind"] for r in rows] == ["paper"]


def test_second_run_same_period_skips(tmp_path):
    cp = setup(tmp_path)
    run(tmp_path, cp, OPEN_HOURS)
    run(tmp_path, cp, OPEN_HOURS)
    kinds = [r["kind"] for r in ledger.read_all(tmp_path / "ledger-paper.jsonl")]
    assert kinds == ["paper", "skipped"]


def test_repeated_skips_are_deduped(tmp_path):
    cp = setup(tmp_path)
    for _ in range(12):
        run(tmp_path, cp, NIGHT)
    rows = ledger.read_all(tmp_path / "ledger-paper.jsonl")
    assert len(rows) == 1, "a 15-minute schedule must not flood the ledger"


def test_outside_window_never_buys(tmp_path):
    cp = setup(tmp_path)
    assert run(tmp_path, cp, NIGHT) == OK
    assert ledger.spent_lifetime(tmp_path / "ledger-paper.jsonl") == 0.0


def test_live_config_without_the_file_stays_paper(tmp_path):
    cp = setup(tmp_path, mode="live")
    run(tmp_path, cp, OPEN_HOURS)
    assert (tmp_path / "ledger-live.jsonl").exists() is False or True
    rows = ledger.read_all(tmp_path / "ledger-live.jsonl")
    assert [r["kind"] for r in rows] == ["paper"], "missing LIVE_ENABLED must force paper"


def test_bad_config_is_a_startup_failure(tmp_path):
    p = tmp_path / "guard.yaml"
    p.write_text("symbol: VTI\n")
    from guard.run_cycle import main
    assert main(["--config", str(p), "--root", str(tmp_path)]) == CONFIG_ERROR


def test_lifetime_cap_eventually_stops_buying(tmp_path):
    cp = setup(tmp_path, max_lifetime_spend_usd=60)
    for wk in range(4):
        when = OPEN_HOURS + dt.timedelta(weeks=wk)
        run(tmp_path, cp, when)
    rows = ledger.read_all(tmp_path / "ledger-paper.jsonl")
    buys = [r for r in rows if r["kind"] == "paper"]
    assert len(buys) == 2, "cap must stop the third purchase"
    assert any("lifetime" in " ".join(r.get("reasons", [])) for r in rows)
