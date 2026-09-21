import bisect
import datetime as dt
from zoneinfo import ZoneInfo

from ebot.types import Bar

ET = ZoneInfo("US/Eastern")
OPEN, CLOSE = dt.time(9, 30), dt.time(16, 0)


def sessions_from_bars(bars: list[Bar]) -> list[dt.date]:
    return sorted({b.date for b in bars})


def _prev_session(d: dt.date, sessions: list[dt.date]) -> dt.date | None:
    i = bisect.bisect_left(sessions, d)
    return sessions[i - 1] if i > 0 else None


def _next_session(d: dt.date, sessions: list[dt.date]) -> dt.date | None:
    i = bisect.bisect_right(sessions, d)
    return sessions[i] if i < len(sessions) else None


def resolve_timing(accepted_at: dt.datetime,
                   sessions: list[dt.date]) -> tuple[dt.date, dt.date] | None:
    """Spec 6.1. Returns (t0, t1) or None if unresolvable.

    t1 is the OBSERVATION bar. The entry price is t1's CLOSE, not its open --
    R6 forbids live trading in the first 15 minutes, so an open fill is
    unreachable. Callers must not read t1's high/low/close as a gate input.
    """
    if accepted_at.tzinfo is None:
        raise ValueError("accepted_at must be timezone-aware")
    et = accepted_at.astimezone(ET)
    d, t = et.date(), et.time()
    is_session = d in set(sessions)

    if is_session and t < OPEN:
        t0 = _prev_session(d, sessions)       # pre-open: T0 is the prior session
        t1 = d
    else:
        # intraday, post-close, or non-session day
        t0 = d if is_session else _prev_session(d, sessions)
        t1 = _next_session(t0, sessions) if t0 else None
    if t0 is None or t1 is None:
        return None
    return (t0, t1)
