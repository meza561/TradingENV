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
