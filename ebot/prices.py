import json
import re
import subprocess
import threading
import datetime as dt

from ebot.cache import get_conn
from ebot.config import Config
from ebot.types import Bar

ALLOWED_TOOLS = ["mcp__robinhood-trading__get_equity_historicals"]
_DB_LOCK = threading.Lock()

PROMPT = """Call get_equity_historicals for symbol {symbol} with
start_time="{start}T00:00:00Z", end_time="{end}T23:59:59Z", interval="day",
adjustment_type="split", bounds="regular".
Reply with ONLY a JSON object, no prose, no code fence:
{{"bars":[{{"date":"YYYY-MM-DD","open":0,"high":0,"low":0,"close":0,"volume":0}}]}}"""


def _run(argv: list[str], prompt: str) -> str:
    """Prompt goes on STDIN: --allowedTools is variadic and would otherwise
    swallow a trailing prompt argument as another tool name."""
    return subprocess.run(argv, input=prompt, capture_output=True, text=True,
                          timeout=600, check=True).stdout


def _cached_years(symbol: str, cfg: Config) -> set[int]:
    conn = get_conn(cfg.cache_dir, "prices")
    rows = conn.execute(
        "SELECT DISTINCT substr(date,1,4) AS y FROM bars WHERE symbol = ?",
        (symbol,)).fetchall()
    return {int(r["y"]) for r in rows}


def fetch_year(symbol: str, year: int, cfg: Config, runner=None) -> list[Bar]:
    """One calendar year. A full-history request returns ~555KB for a single
    symbol, large enough to exceed the tool-result limit; year chunks land
    near 45KB and are individually cacheable so an interrupted fetch resumes."""
    runner = runner or _run
    start, end = f"{year}-01-01", f"{year}-12-31"
    argv = ["claude", "-p", "--allowedTools", ",".join(ALLOWED_TOOLS)]
    prompt = PROMPT.format(symbol=symbol, start=start, end=end)
    assert not any("place_" in a or "cancel_" in a for a in argv), \
        "order tool leaked into price fetch argv"
    out = runner(argv, prompt)
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise ValueError(f"no JSON in claude output for {symbol} {year}: {out[:200]!r}")
    try:
        rows = json.loads(m.group(0))["bars"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(f"unparseable bars for {symbol} {year}: {e}") from e

    bars = []
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        if d.year != year:
            raise ValueError(f"{symbol}: bar {d} outside requested year {year}")
        bars.append(Bar(symbol=symbol, date=d, open=float(r["open"]),
                        high=float(r["high"]), low=float(r["low"]),
                        close=float(r["close"]), volume=int(r["volume"])))
    # ponytail: one global write lock, fine for ~170 fetches; switch to a
    # per-symbol lock or WAL mode if write contention ever matters.
    with _DB_LOCK:
        conn = get_conn(cfg.cache_dir, "prices")
        conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?)",
                         [(b.symbol, b.date.isoformat(), b.open, b.high, b.low,
                           b.close, b.volume) for b in bars])
        conn.commit()
        conn.close()
    return sorted(bars, key=lambda b: b.date)


def fetch_all_years(symbol: str, cfg: Config, runner=None) -> list[Bar]:
    have = _cached_years(symbol, cfg)
    this_year = dt.date.today().year
    for year in range(cfg.price_floor.year, this_year + 1):
        if year in have and year != this_year:
            continue                       # current year is always refetched
        fetch_year(symbol, year, cfg, runner)
    return load_bars(symbol, cfg)


def load_bars(symbol: str, cfg: Config) -> list[Bar]:
    conn = get_conn(cfg.cache_dir, "prices")
    rows = conn.execute(
        "SELECT * FROM bars WHERE symbol = ? ORDER BY date", (symbol,)).fetchall()
    return [Bar(symbol=r["symbol"], date=dt.date.fromisoformat(r["date"]),
                open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"]) for r in rows]
