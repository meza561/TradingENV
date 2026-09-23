"""Turn an option chain into a short list of eligible contracts.

The analyst never names a contract freely -- it picks from this list. That
makes 'hallucinated a strike' structurally impossible rather than something
the validator has to catch afterwards.
"""
import datetime as dt
import math
from dataclasses import dataclass, asdict

from guard.optconfig import OptionConfig


@dataclass(frozen=True)
class Candidate:
    option_id: str
    underlying: str
    option_type: str
    strike: float
    expiration: dt.date
    dte: int
    bid: float
    ask: float
    mark: float
    delta: float
    open_interest: int
    spread_pct: float
    cost_usd: float

    def as_dict(self) -> dict:
        d = asdict(self)
        d["expiration"] = self.expiration.isoformat()
        return d


def spread_pct_of_mid(bid: float, ask: float) -> float:
    """Percent of mid. Returns inf when unevaluable, so it fails the gate."""
    for v in (bid, ask):
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(v) or v <= 0:
            return math.inf
    if ask < bid:
        return math.inf                       # crossed book
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 100.0


def _num(row: dict, key: str, default=None):
    try:
        v = float(row.get(key))
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def select(rows: list[dict], cfg: OptionConfig, budget: float,
           today: dt.date) -> tuple[list[Candidate], list[tuple[str, str]]]:
    """Returns (eligible, rejected) where rejected is [(option_id, reason)].

    Every rejection is reported so the ledger explains why a cycle found
    nothing, rather than silently doing nothing.
    """
    eligible: list[Candidate] = []
    rejected: list[tuple[str, str]] = []

    for r in rows:
        oid = str(r.get("option_id") or r.get("instrument_id") or "?")
        und = str(r.get("underlying") or r.get("chain_symbol") or "").upper()
        if und not in cfg.underlyings:
            rejected.append((oid, f"underlying {und!r} not whitelisted"))
            continue
        if str(r.get("state", "active")) != "active" or \
                str(r.get("tradability", "tradable")) != "tradable":
            rejected.append((oid, "not tradable"))
            continue

        try:
            exp = r["expiration"] if isinstance(r.get("expiration"), dt.date) \
                else dt.date.fromisoformat(str(r.get("expiration")
                                               or r.get("expiration_date")))
        except (TypeError, ValueError):
            rejected.append((oid, "unparseable expiration"))
            continue
        dte = (exp - today).days
        if not (cfg.min_dte <= dte <= cfg.max_dte):
            rejected.append((oid, f"{dte} DTE outside {cfg.min_dte}-{cfg.max_dte}"))
            continue

        delta = _num(r, "delta")
        if delta is None:
            rejected.append((oid, "missing delta"))
            continue
        # 1e-9 epsilon: 0.45 - 0.30 == 0.15000000000000002 in binary float,
        # which would silently exclude a delta exactly at tolerance.
        if abs(abs(delta) - cfg.target_delta) > cfg.delta_tolerance + 1e-9:
            rejected.append((oid, f"delta {delta:.3f} outside "
                                  f"{cfg.target_delta}+/-{cfg.delta_tolerance}"))
            continue

        oi = int(_num(r, "open_interest", 0) or 0)
        if oi < cfg.min_open_interest:
            rejected.append((oid, f"open interest {oi} < {cfg.min_open_interest}"))
            continue

        bid, ask = _num(r, "bid"), _num(r, "ask")
        if bid is None or ask is None:
            bid, ask = _num(r, "bid_price"), _num(r, "ask_price")
        sp = spread_pct_of_mid(bid if bid is not None else 0,
                               ask if ask is not None else 0)
        if sp > cfg.max_spread_pct_of_mid:
            shown = "unevaluable" if math.isinf(sp) else f"{sp:.1f}%"
            rejected.append((oid, f"spread {shown} > {cfg.max_spread_pct_of_mid}%"))
            continue

        cost = ask * 100.0
        if cost > budget:
            rejected.append((oid, f"cost ${cost:.2f} > budget ${budget:.2f}"))
            continue

        mark = _num(r, "mark", (bid + ask) / 2.0) or (bid + ask) / 2.0
        eligible.append(Candidate(
            option_id=oid, underlying=und,
            option_type=str(r.get("option_type") or r.get("type") or "call"),
            strike=_num(r, "strike", _num(r, "strike_price", 0.0)) or 0.0,
            expiration=exp, dte=dte, bid=bid, ask=ask, mark=mark, delta=delta,
            open_interest=oi, spread_pct=round(sp, 2), cost_usd=round(cost, 2)))

    # Tightest spread first: execution cost is the one thing we can control.
    eligible.sort(key=lambda c: (c.spread_pct,
                                 abs(abs(c.delta) - cfg.target_delta)))
    return eligible, rejected
