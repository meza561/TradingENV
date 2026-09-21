import csv
import io
import datetime as dt
import time
import urllib.request

from ebot.types import Bar
from ebot.validate_bars import BarIssue

STOOQ = "https://stooq.com/q/d/l/?s={sym}.us&d1={d1}&d2={d2}&i=d"
_last = [0.0]


def _fetch(url: str) -> str:
    elapsed = time.monotonic() - _last[0]
    if elapsed < 0.5:
        time.sleep(0.5 - elapsed)
    _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "ebot-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def parse_stooq_csv(text: str, symbol: str) -> list[Bar]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(Bar(symbol=symbol,
                           date=dt.date.fromisoformat(row["Date"]),
                           open=float(row["Open"]), high=float(row["High"]),
                           low=float(row["Low"]), close=float(row["Close"]),
                           volume=int(float(row["Volume"]))))
        except (ValueError, TypeError, KeyError):
            continue                       # blank or N/A row
    return sorted(out, key=lambda b: b.date)


def fetch_stooq(symbol: str, start: dt.date, end: dt.date, fetch=None) -> list[Bar]:
    fetch = fetch or _fetch
    url = STOOQ.format(sym=symbol.lower(),
                       d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d"))
    return parse_stooq_csv(fetch(url), symbol)


def crosscheck_window(bars: list[Bar], ref_bars: list[Bar],
                      dates: list[dt.date], tol: float = 0.005) -> list[BarIssue]:
    """Prices and event dates both arrive through one vendor, so a systematic
    adjustment error would be invisible to internal validation. 0.5% absorbs
    dividend-adjustment differences while catching a missed split (~50%+)."""
    ours = {b.date: b for b in bars}
    theirs = {b.date: b for b in ref_bars}
    issues = []
    for d in dates:
        a, b = ours.get(d), theirs.get(d)
        if a is None:
            continue
        if b is None:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                                   "date absent from reference source"))
            continue
        if b.close <= 0:
            continue
        diff = abs(a.close / b.close - 1.0)
        if diff > tol:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                f"close {a.close} vs reference {b.close} ({diff:.1%} apart)"))
    return issues
