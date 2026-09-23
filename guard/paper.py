"""Paper positions, derived from the ledger.

Paper mode uses REAL market data and REAL quotes -- only order placement is
simulated. Otherwise a clean paper run would prove nothing about the exit
rules, which is the whole point of running it.
"""
import datetime as dt

from guard import ledger


def open_positions(path) -> list[dict]:
    """Opens minus closes, by option_id."""
    held: dict[str, dict] = {}
    for r in ledger.read_all(path):
        oid = r.get("option_id")
        if not oid:
            continue
        if r.get("kind") in {"paper_open", "opened"}:
            held[oid] = {
                "option_id": oid,
                "underlying": r.get("underlying"),
                "strike": r.get("strike"),
                "expiration": r.get("expiration"),
                "option_type": r.get("option_type", "call"),
                "quantity": int(r.get("quantity", 1) or 1),
                "average_price": float(r.get("fill_price", 0) or 0),
            }
        elif r.get("kind") in {"paper_close", "closed"}:
            held.pop(oid, None)
    return list(held.values())


def deployed(path) -> float:
    """Gross deployed, counting opens only. A winning close does not refund
    the all-time cap -- that is what makes it a dead-man's switch."""
    return sum(float(r.get("cost_usd", 0) or 0)
               for r in ledger.read_all(path)
               if r.get("kind") in {"paper_open", "opened"})


def closed_trades(path) -> list[dict]:
    """Pair each open with its close, in ledger order.

    Keyed by option_id and popped on close, so the same contract reopened
    later becomes a separate trade rather than overwriting the first.
    """
    pending: dict[str, dict] = {}
    out: list[dict] = []
    for r in ledger.read_all(path):
        oid = r.get("option_id")
        if not oid:
            continue
        kind = r.get("kind")
        if kind in {"paper_open", "opened"}:
            pending[oid] = r
        elif kind in {"paper_close", "closed"}:
            o = pending.pop(oid, None)
            if o is None:
                continue                     # close without a matching open
            try:
                entry = float(o.get("fill_price") or 0)
                exit_ = float(r.get("fill_price") or 0)
                qty = int(o.get("quantity", 1) or 1)
            except (TypeError, ValueError):
                continue
            if entry <= 0 or qty <= 0:
                continue
            out.append({
                "option_id": oid,
                "underlying": o.get("underlying"),
                "strike": o.get("strike"),
                "entry": entry,
                "exit": exit_,
                "quantity": qty,
                "pnl_usd": round((exit_ - entry) * 100 * qty, 2),
                "pnl_pct": round((exit_ / entry - 1) * 100, 1),
                "reason": r.get("reason", ""),
                "closed_ts": r.get("ts", ""),
            })
    return out


def realized(path) -> tuple[float, int, int]:
    """(total_usd, wins, losses)."""
    ts = closed_trades(path)
    total = round(sum(t["pnl_usd"] for t in ts), 2)
    wins = sum(1 for t in ts if t["pnl_usd"] > 0)
    return total, wins, len(ts) - wins
