import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass

from ebot.config import Config
from ebot.types import Bar

FATAL_KINDS = frozenset({"ohlc", "duplicate"})
MAX_GAP_BUSINESS_DAYS = 5
EXTREME_MOVE = 0.25
MIN_SESSIONS, MAX_SESSIONS = 220, 260


@dataclass(frozen=True)
class BarIssue:
    symbol: str
    date: dt.date | None
    kind: str
    detail: str


def _business_days(a: dt.date, b: dt.date) -> int:
    n, d = 0, a + dt.timedelta(days=1)
    while d < b:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def validate_bars(bars: list[Bar], cfg: Config) -> list[BarIssue]:
    """Structural impossibilities are fatal; statistical oddities are warnings.
    A 26% single-day drop is real (META, 2022-02-03), so it is flagged not failed."""
    issues: list[BarIssue] = []
    if not bars:
        return issues
    sym = bars[0].symbol

    for b in bars:
        bad = (b.high < b.low
               or not (b.low <= b.open <= b.high)
               or not (b.low <= b.close <= b.high)
               or min(b.open, b.high, b.low, b.close) <= 0
               or b.volume < 0)
        if bad:
            issues.append(BarIssue(sym, b.date, "ohlc",
                f"o={b.open} h={b.high} l={b.low} c={b.close} v={b.volume}"))

    for d, n in Counter(b.date for b in bars).items():
        if n > 1:
            issues.append(BarIssue(sym, d, "duplicate", f"{n} rows for {d}"))

    per_year: dict[int, int] = defaultdict(int)
    for b in bars:
        per_year[b.date.year] += 1
    current = dt.date.today().year
    for year, n in sorted(per_year.items()):
        if year == current:
            continue
        if not (MIN_SESSIONS <= n <= MAX_SESSIONS):
            issues.append(BarIssue(sym, None, "count", f"{year} has {n} sessions"))

    ordered = sorted(bars, key=lambda b: b.date)
    for prev, cur in zip(ordered, ordered[1:]):
        if _business_days(prev.date, cur.date) > MAX_GAP_BUSINESS_DAYS:
            issues.append(BarIssue(sym, cur.date, "gap", f"{prev.date} -> {cur.date}"))
        if prev.close > 0:
            move = cur.close / prev.close - 1.0
            if abs(move) > EXTREME_MOVE:
                issues.append(BarIssue(sym, cur.date, "extreme",
                                       f"{move:+.1%} from {prev.date}"))
    return issues
