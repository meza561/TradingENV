"""One options cycle. Exits are evaluated before entries, always."""
import argparse
import datetime as dt
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from guard import analyst, broker_opt, ledger, paper
from guard.cyclelock import cycle_lock
from guard.exits import CLOSE, HALT, HOLD, OptionPosition, exit_decision
from guard.guards import HALT_FILE, halted, is_live, market_window_ok
from guard.optconfig import load_option_config
from guard.selector import select
from guard.sizing import affordable
from guard.validator_opt import validate_open

ET = ZoneInfo("US/Eastern")
OK, LOCKED, HALTED, CONFIG_ERROR = 0, 1, 2, 3


def _halt(root: Path, why: str) -> None:
    (Path(root) / HALT_FILE).write_text(f"auto-halt: {why}\n")


def _as_position(p: dict) -> OptionPosition:
    exp = p["expiration"]
    return OptionPosition(
        option_id=p["option_id"], underlying=str(p.get("underlying") or ""),
        strike=float(p.get("strike") or 0),
        expiration=exp if isinstance(exp, dt.date) else dt.date.fromisoformat(str(exp)),
        quantity=int(p.get("quantity") or 0),
        average_price=float(p.get("average_price") or 0))


def run(root: Path, config_path: Path, now_et=None, runner=None,
        candidates_fn=None) -> int:
    with cycle_lock(root) as got:
        if not got:
            print("another cycle is running; skipping", file=sys.stderr)
            return LOCKED
        return _cycle(root, config_path, now_et, runner, candidates_fn)


def _cycle(root, config_path, now_et, runner, candidates_fn) -> int:
    now = (now_et or dt.datetime.now(ET)).astimezone(ET)
    cfg = load_option_config(config_path)
    path = cfg.ledger_path

    stopped, why = halted(root)
    if stopped:
        print(f"HALT: {why}", file=sys.stderr)
        return HALTED

    in_window, wwhy = market_window_ok(now, cfg)
    if not in_window:
        print(f"skip: {wwhy}")
        return OK

    live = is_live(cfg, root)
    if live:
        try:
            positions = broker_opt.positions(cfg.account_number, runner)
        except Exception as e:
            # Unknown holdings is the dangerous state: exits would be skipped
            # and free slots miscounted. Stop rather than guess.
            _halt(root, f"cannot read holdings: {e!r:.200}")
            ledger.append(path, {"kind": "halted", "mode": "live",
                                 "reason": f"holdings unreadable: {e!r:.200}"})
            print(f"HALT: cannot read holdings: {e}", file=sys.stderr)
            return HALTED
    else:
        positions = paper.open_positions(path)

    # ---- exits first, always -------------------------------------------
    if positions:
        marks = {q.get("instrument_id"): q for q in
                 broker_opt.quotes([p["option_id"] for p in positions], runner)}
        for p in positions:
            pos = _as_position(p)
            q = marks.get(pos.option_id, {})
            try:
                mark = float(q.get("mark_price") or 0)
            except (TypeError, ValueError):
                mark = 0.0
            action, reason = exit_decision(pos, mark, now.date(), cfg)
            if action == HALT:
                _halt(root, f"{pos.option_id}: {reason}")
                ledger.append(path, {"kind": "halted", "option_id": pos.option_id,
                                     "reason": reason, "mode": "live" if live else "paper"})
                print(f"HALT on {pos.underlying}: {reason}", file=sys.stderr)
                return HALTED
            if action == CLOSE:
                bid = float(q.get("bid_price") or 0)
                rec = {"kind": "closed" if live else "paper_close",
                       "option_id": pos.option_id, "underlying": pos.underlying,
                       "reason": reason, "fill_price": bid,
                       "quantity": pos.quantity, "mode": "live" if live else "paper"}
                if live:
                    if bid <= 0:
                        _halt(root, f"cannot close {pos.option_id}: no bid")
                        return HALTED
                    rec["ref_id"] = str(uuid.uuid4())
                    rec["response"] = broker_opt.essential(
                        broker_opt.close_position(
                            cfg.account_number, pos.option_id, pos.quantity,
                            bid, rec["ref_id"], runner))
                ledger.append(path, rec)
                print(f"CLOSE {pos.underlying} {pos.strike:g}: {reason}")
                positions = [x for x in positions if x["option_id"] != pos.option_id]
            else:
                print(f"hold {pos.underlying} {pos.strike:g}: {reason}")

    # ---- entries, only if one is actually possible ----------------------
    spent = paper.deployed(path)
    acct_value, bp = _account(cfg, live, runner, path)
    budget, bwhy = affordable(acct_value, spent, bp, cfg)
    if len(positions) >= cfg.max_open_positions:
        print(f"no entry: {len(positions)} of {cfg.max_open_positions} slots used")
        return OK
    if budget <= 0:
        print(f"no entry: {bwhy}")
        return OK

    rows = (candidates_fn or _no_candidates)(cfg, now.date(), runner)
    eligible, rejected = select(rows, cfg, budget, now.date())
    if not eligible:
        ledger.append(path, {"kind": "no_candidates", "mode": "live" if live else "paper",
                             "rejected": rejected[:20], "budget": budget})
        print(f"no entry: 0 of {len(rows)} contracts eligible")
        return OK

    proposal = analyst.propose(eligible, positions, acct_value, budget, spent,
                               cfg, runner=runner)
    if proposal["action"] != "open":
        ledger.append(path, dict(proposal, kind="declined",
                                 mode="live" if live else "paper"))
        print(f"analyst declined: {proposal['rationale'][:120]}")
        return OK

    pick = next(c for c in eligible if c.option_id == proposal["option_id"])
    ok, reasons = validate_open(pick, cfg, account_value=acct_value,
                                buying_power=bp, spent=spent,
                                n_open=len(positions), now_et=now)
    if not ok:
        ledger.append(path, {"kind": "refused", "option_id": pick.option_id,
                             "reasons": reasons, "mode": "live" if live else "paper"})
        print(f"refused: {'; '.join(reasons)}")
        return OK

    rec = {"kind": "opened" if live else "paper_open", **pick.as_dict(),
           "cost_usd": pick.cost_usd, "fill_price": pick.ask, "quantity": 1,
           "rationale": proposal["rationale"], "confidence": proposal["confidence"],
           "mode": "live" if live else "paper"}
    if live:
        rec["ref_id"] = str(uuid.uuid4())
        rec["response"] = broker_opt.essential(broker_opt.open_position(
            cfg.account_number, pick.option_id, pick.ask, rec["ref_id"], runner))
    ledger.append(path, rec)
    print(f"{'LIVE' if live else 'paper'} OPEN {pick.underlying} "
          f"{pick.strike:g}{pick.option_type[0].upper()} ${pick.cost_usd:.2f} "
          f"(conf {proposal['confidence']:.2f})")
    return OK


def _no_candidates(cfg, today, runner):
    """Test seam only. main() wires the real fetcher -- defaulting to this in
    production would silently find nothing forever while looking healthy."""
    return []


def _account(cfg, live, runner, path) -> tuple[float, float]:
    """(account_value, buying_power). Live reads the broker; paper simulates a
    starting balance so sizing behaves the same in both modes."""
    if not live:
        start = cfg.paper_start_usd
        return start - paper.deployed(path), start - paper.deployed(path)
    return broker_opt.portfolio(cfg.account_number, runner)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("options.yaml"))
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    try:
        from guard.chains import fetch_candidates
        return run(a.root, a.config, candidates_fn=fetch_candidates)
    except Exception as e:
        print(f"cycle failure: {e}", file=sys.stderr)
        return CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
