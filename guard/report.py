"""Compact ledger digest.

Reading raw JSONL costs tokens proportional to history; this is bounded at
roughly 20 lines however long the ledger gets. Key names alone are ~47% of a
raw record, and they repeat on every line.
"""
import argparse
import collections
import datetime as dt
from pathlib import Path

from guard import ledger, paper
from guard.optconfig import load_option_config

RECENT = 6
COUNT_ORDER = ("paper_open", "opened", "paper_close", "closed", "declined",
               "refused", "no_candidates", "skipped", "halted", "error")


def _unrealized(cfg, held, runner=None):
    """Costs one quote call, so it is opt-in."""
    from guard import broker_opt
    marks = {q.get("instrument_id"): q for q in
             broker_opt.quotes([p["option_id"] for p in held], runner)}
    total, rows = 0.0, []
    for p in held:
        try:
            mark = float(marks.get(p["option_id"], {}).get("mark_price") or 0)
            entry = float(p.get("average_price") or 0)
            qty = int(p.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            rows.append((p, None, None)); continue
        if entry <= 0 or mark <= 0:
            rows.append((p, None, None)); continue
        total += (mark - entry) * 100 * qty
        rows.append((p, mark, (mark / entry - 1) * 100))
    return round(total, 2), rows


def digest(cfg, today: dt.date | None = None, marks: bool = False,
           runner=None) -> str:
    today = today or dt.date.today()
    path = cfg.ledger_path
    rows = ledger.read_all(path)
    if not rows:
        return f"guard · {cfg.mode} · no activity yet ({path.name})"

    out = [f"guard · {cfg.mode} · {len(rows)} records · {path.name}"]
    held = paper.open_positions(path)
    spent = paper.deployed(path)
    out.append(f"open {len(held)}/{cfg.max_open_positions}   "
               f"deployed ${spent:,.2f} of ${cfg.max_lifetime_usd:,.0f}")

    live_rows = {}
    if held and marks:
        try:
            unreal, mrows = _unrealized(cfg, held, runner)
            live_rows = {id(p): (m, pct) for p, m, pct in mrows}
            out[-1] += f"   unrealised {unreal:+,.2f}"
        except Exception as e:
            out.append(f"  (live marks unavailable: {e!r:.60})")

    if held:
        out.append("")
        for p in held:
            try:
                dte = (dt.date.fromisoformat(str(p["expiration"])) - today).days
            except (ValueError, TypeError, KeyError):
                dte = "?"
            line = (f"  {p.get('underlying')} {p.get('strike')}"
                    f"{str(p.get('option_type', 'c'))[0].upper()}"
                    f"  exp {p.get('expiration')}  {dte} DTE"
                    f"  entry ${float(p.get('average_price', 0)):.2f}")
            m, pct = live_rows.get(id(p), (None, None))
            if m is not None:
                line += f"  now ${m:.2f}  {pct:+.1f}%"
            out.append(line)

    trades = paper.closed_trades(path)
    if trades:
        total, wins, losses = paper.realized(path)
        out.append("")
        out.append(f"closed: {len(trades)} trades   "
                   f"realised {total:+,.2f}   ({wins} win, {losses} loss)")
        for t in trades[-3:]:
            out.append(f"  {t['underlying']} {t['strike']}  "
                       f"${t['entry']:.2f} -> ${t['exit']:.2f}  "
                       f"{t['pnl_usd']:+.2f} ({t['pnl_pct']:+.1f}%)  "
                       f"{str(t['reason'])[:32]}")

    counts = collections.Counter(r.get("kind") for r in rows)
    shown = [f"{k} {counts[k]}" for k in COUNT_ORDER if counts.get(k)]
    other = [f"{k} {v}" for k, v in counts.items() if k not in COUNT_ORDER]
    out.append("")
    out.append("counts: " + "  ".join(shown + other))

    interesting = [r for r in rows if r.get("kind") != "skipped"]
    if interesting:
        out.append("")
        out.append(f"last {min(RECENT, len(interesting))}:")
        for r in interesting[-RECENT:]:
            when = str(r.get("ts", ""))[5:16].replace("T", " ")
            bits = [r.get("underlying") or "", str(r.get("strike") or "")]
            if r.get("cost_usd"):
                bits.append(f"${float(r['cost_usd']):.2f}")
            if r.get("reason"):
                bits.append(str(r["reason"])[:44])
            if r.get("reasons"):
                bits.append("; ".join(r["reasons"])[:44])
            if r.get("rationale"):
                bits.append(f'"{str(r["rationale"])[:40]}"')
            out.append(f"  {when}  {r.get('kind','?'):<13} "
                       + " ".join(b for b in bits if b))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("options.yaml"))
    ap.add_argument("--marks", action="store_true",
                    help="fetch live marks for open positions (1 broker call)")
    a = ap.parse_args(argv)
    print(digest(load_option_config(a.config), marks=a.marks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
