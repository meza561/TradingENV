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


def digest(cfg, today: dt.date | None = None) -> str:
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

    if held:
        out.append("")
        for p in held:
            try:
                dte = (dt.date.fromisoformat(str(p["expiration"])) - today).days
            except (ValueError, TypeError, KeyError):
                dte = "?"
            out.append(f"  {p.get('underlying')} {p.get('strike')}"
                       f"{str(p.get('option_type', 'c'))[0].upper()}"
                       f"  exp {p.get('expiration')}  {dte} DTE"
                       f"  entry ${float(p.get('average_price', 0)):.2f}")

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
    a = ap.parse_args(argv)
    print(digest(load_option_config(a.config)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
