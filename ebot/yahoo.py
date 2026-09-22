"""Bulk historical prices from Yahoo's chart endpoint.

Primary source for BACKTEST data only. The live bot still reads prices
through the authenticated Robinhood MCP; this path exists because public
historical bars need no broker auth, and routing them through `claude -p`
spends the operator's model budget to move CSV-shaped data.

Uses indicators.quote (split-adjusted, matching spec 5.2's
adjustment_type="split"), NOT adjclose, which also folds in dividends.
"""
import datetime as dt
import json
import threading
import time
import urllib.request
from zoneinfo import ZoneInfo

from ebot.cache import get_conn
from ebot.config import Config
from ebot.types import Bar

ET = ZoneInfo("US/Eastern")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
       "?period1={p1}&period2={p2}&interval=1d")
_last = [0.0]
_LOCK = threading.Lock()


def _fetch(url: str) -> bytes:
    with _LOCK:
        elapsed = time.monotonic() - _last[0]
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def parse_yahoo(payload: dict, symbol: str) -> list[Bar]:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"{symbol}: yahoo error {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ValueError(f"{symbol}: yahoo returned no result")
    r = results[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for i, t in enumerate(ts):
        vals = (q.get("open"), q.get("high"), q.get("low"),
                q.get("close"), q.get("volume"))
        if any(v is None or i >= len(v) or v[i] is None for v in vals):
            continue                       # halted/missing session
        o, h, lo, c, v = (x[i] for x in vals)
        out.append(Bar(symbol=symbol,
                       date=dt.datetime.fromtimestamp(t, tz=ET).date(),
                       open=float(o), high=float(h), low=float(lo),
                       close=float(c), volume=int(v)))
    return sorted(out, key=lambda b: b.date)


def fetch_yahoo(symbol: str, start: dt.date, end: dt.date, fetch=None) -> list[Bar]:
    fetch = fetch or _fetch
    p1 = int(dt.datetime.combine(start, dt.time(0, 0), tzinfo=ET).timestamp())
    p2 = int(dt.datetime.combine(end, dt.time(23, 59), tzinfo=ET).timestamp())
    raw = fetch(URL.format(symbol=symbol, p1=p1, p2=p2))
    bars = parse_yahoo(json.loads(raw), symbol)
    if not bars:
        raise ValueError(f"{symbol}: yahoo returned zero usable bars")
    return bars


def fetch_and_cache(symbol: str, cfg: Config, fetch=None) -> list[Bar]:
    bars = fetch_yahoo(symbol, cfg.price_floor, dt.date.today(), fetch)
    conn = get_conn(cfg.cache_dir, "prices")
    conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?)",
                     [(b.symbol, b.date.isoformat(), b.open, b.high, b.low,
                       b.close, b.volume) for b in bars])
    conn.commit()
    conn.close()
    return bars
