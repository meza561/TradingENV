from dataclasses import dataclass
import datetime as dt


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class Event:
    """An 8-K Item 2.02 filing. accepted_at is tz-aware US/Eastern."""
    ticker: str
    cik: str
    accession: str
    accepted_at: dt.datetime


@dataclass(frozen=True)
class Trade:
    """Entry price is the T+1 CLOSE per spec 6.1, not the open."""
    ticker: str
    accepted_at: dt.datetime
    t0: dt.date
    entry_date: dt.date
    exit_date: dt.date
    entry_px: float
    exit_px: float
    ret: float
    spy_ret: float
    excess: float
