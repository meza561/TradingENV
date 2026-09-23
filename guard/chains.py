"""Fetch option candidates through the broker MCP, cached daily.

Call budget matters: the transport runs ~100s per call against a 15-minute
cycle. Chain structure (expirations, strikes) does not change intraday, so it
is cached per day; only quotes are fetched fresh. Steady state is ~3 calls per
entry attempt instead of ~18.
"""
import datetime as dt
import json
import re
import subprocess

from guard import claudebin
from pathlib import Path

from guard.cache import get_conn
from guard.optconfig import OptionConfig

CHAINS_TOOL = "mcp__robinhood-trading__get_option_chains"
INSTR_TOOL = "mcp__robinhood-trading__get_option_instruments"
QUOTES_TOOL = "mcp__robinhood-trading__get_option_quotes"
EQUITY_TOOL = "mcp__robinhood-trading__get_equity_quotes"

STRIKE_BAND = 0.12          # search +/-12% around spot for the delta target
MAX_QUOTE_BATCH = 20


def _run(argv, prompt):
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {r.returncode}: "
            f"stderr={r.stderr.strip()[:300]!r} "
            f"stdout={r.stdout.strip()[:300]!r}")
    return r.stdout


def _json(out, what):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise ValueError(f"no JSON in {what}: {out[:200]!r}")
    return json.loads(m.group(0))


def _call(tool, prompt, runner):
    return _json((runner or _run)(claudebin.argv(tool), prompt), tool)


def _cached(conn, key: str, today: dt.date, ttl_days: int):
    """Strikes and expirations for a 30-45 DTE window barely move day to day,
    so a multi-day TTL turns ~12 structure calls every morning into ~12 per
    TTL window. That matters: 14 calls in one cycle exhausts the session
    limit before the analyst is ever reached."""
    row = conn.execute("SELECT payload, fetched FROM chaincache WHERE k=?",
                       (key,)).fetchone()
    if not row:
        return None
    try:
        age = (today - dt.date.fromisoformat(row["fetched"])).days
    except (ValueError, TypeError):
        return None
    if not (0 <= age < ttl_days):
        return None
    return json.loads(row["payload"])


def _store(conn, key: str, today: dt.date, payload) -> None:
    conn.execute("INSERT OR REPLACE INTO chaincache VALUES (?,?,?)",
                 (key, json.dumps(payload), today.isoformat()))
    conn.commit()


def spots(cfg: OptionConfig, runner=None) -> dict[str, float]:
    p = (f'Call {EQUITY_TOOL} with symbols={json.dumps(cfg.underlyings)}.\n'
         'Reply with ONLY JSON, no prose: {"quotes":[{"symbol":"","price":0}]}')
    out = _call(EQUITY_TOOL, p, runner).get("quotes") or []
    got = {}
    for q in out:
        try:
            got[str(q["symbol"]).upper()] = float(q["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return got


def expirations(sym: str, cfg, today, conn, runner=None) -> list[str]:
    key = f"exp:{sym}"
    hit = _cached(conn, key, today, cfg.structure_ttl_days)
    if hit is not None:
        return hit
    p = (f'Call {CHAINS_TOOL} with underlying_symbol="{sym}".\n'
         'Reply with ONLY JSON, no prose: {"expiration_dates":[]}')
    allx = _call(CHAINS_TOOL, p, runner).get("expiration_dates") or []
    keep = []
    for e in allx:
        try:
            d = (dt.date.fromisoformat(e) - today).days
        except ValueError:
            continue
        if cfg.min_dte <= d <= cfg.max_dte:
            keep.append(e)
    keep = keep[:1]                      # one expiration per underlying
    _store(conn, key, today, keep)
    return keep


def instruments(sym: str, exp: str, spot_fn, conn, today, cfg,
                runner=None) -> list[dict]:
    key = f"ins:{sym}:{exp}"
    hit = _cached(conn, key, today, cfg.structure_ttl_days)
    if hit is not None:
        return hit
    spot = spot_fn(sym)                  # only fetched on a cache miss
    if not spot:
        return []
    p = (f'Call {INSTR_TOOL} with chain_symbol="{sym}", '
         f'expiration_dates="{exp}", type="call", state="active".\n'
         'Reply with ONLY JSON, no prose: '
         '{"instruments":[{"id":"","strike_price":"","expiration_date":"",'
         '"type":"","tradability":""}]}')
    rows = _call(INSTR_TOOL, p, runner).get("instruments") or []
    lo, hi = spot * (1 - STRIKE_BAND), spot * (1 + STRIKE_BAND)
    keep = []
    for r in rows:
        try:
            k = float(r["strike_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo <= k <= hi:
            keep.append({"option_id": r.get("id"), "underlying": sym,
                         "option_type": r.get("type", "call"), "strike": k,
                         "expiration": r.get("expiration_date", exp),
                         "tradability": r.get("tradability", "tradable")})
    _store(conn, key, today, keep)
    return keep


def fetch_candidates(cfg: OptionConfig, today: dt.date, runner=None) -> list[dict]:
    conn = get_conn(Path(cfg.ledger_dir), "chaincache")

    px: dict[str, float] = {}
    fetched = []

    def spot_fn(sym: str):
        """Spot is only needed to pick a strike band, which is itself cached.
        Fetch it lazily so a fully-cached run costs zero extra calls."""
        if not fetched:
            px.update(spots(cfg, runner))
            fetched.append(True)
        return px.get(sym)

    shortlist: list[dict] = []
    for sym in cfg.underlyings:
        for exp in expirations(sym, cfg, today, conn, runner):
            shortlist += instruments(sym, exp, spot_fn, conn, today, cfg, runner)

    out: list[dict] = []
    for i in range(0, len(shortlist), MAX_QUOTE_BATCH):
        batch = shortlist[i:i + MAX_QUOTE_BATCH]
        ids = [b["option_id"] for b in batch if b.get("option_id")]
        if not ids:
            continue
        p = (f'Call {QUOTES_TOOL} with instrument_ids={json.dumps(ids)}.\n'
             'Reply with ONLY JSON, no prose: {"quotes":[{"instrument_id":"",'
             '"bid_price":"","ask_price":"","delta":"","open_interest":0}]}')
        qs = {str(q.get("instrument_id")): q
              for q in _call(QUOTES_TOOL, p, runner).get("quotes") or []}
        for b in batch:
            q = qs.get(b["option_id"])
            if not q:
                continue
            out.append({**b, "bid": q.get("bid_price"), "ask": q.get("ask_price"),
                        "delta": q.get("delta"),
                        "open_interest": q.get("open_interest", 0)})
    return out
