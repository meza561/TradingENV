import json
import time
import urllib.request

from ebot.cache import get_conn
from ebot.config import Config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_last_call = [0.0]


def _fetch(url: str, ua: str) -> bytes:
    """Rate-limited to 10/sec per SEC policy."""
    elapsed = time.monotonic() - _last_call[0]
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_call[0] = time.monotonic()
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def resolve_cik(ticker: str, cfg: Config, fetch=None) -> str:
    fetch = fetch or _fetch
    ticker = ticker.strip().upper()
    conn = get_conn(cfg.cache_dir, "ciks")
    row = conn.execute("SELECT cik FROM ciks WHERE ticker = ?", (ticker,)).fetchone()
    if row:
        return row["cik"]
    raw = json.loads(fetch(TICKERS_URL, cfg.sec_user_agent))
    mapping = {e["ticker"].upper(): f"{int(e['cik_str']):010d}" for e in raw.values()}
    conn.executemany("INSERT OR REPLACE INTO ciks VALUES (?, ?)", mapping.items())
    conn.commit()
    if ticker not in mapping:
        raise KeyError(f"ticker not found in SEC registry: {ticker}")
    return mapping[ticker]
