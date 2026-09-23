"""Pre-flight checks. Every one fails closed."""
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from guard import ledger

ET = ZoneInfo("US/Eastern")
OPEN, CLOSE = dt.time(9, 30), dt.time(16, 0)
HALT_FILE = "HALT"
LIVE_FILE = "LIVE_ENABLED"


def halted(root: Path) -> tuple[bool, str]:
    p = Path(root) / HALT_FILE
    return (True, f"{HALT_FILE} present at {p}") if p.exists() else (False, "")


def is_live(cfg, root: Path) -> bool:
    """G1: BOTH keys required. Either missing means paper."""
    return cfg.mode == "live" and (Path(root) / LIVE_FILE).exists()


def market_window_ok(now_et: dt.datetime, cfg) -> tuple[bool, str]:
    # ponytail: weekday + clock only; market holidays are not modelled, so a
    # holiday order queues to the next session. Add a holiday calendar if that
    # ever matters for a buy-only scheduled tool.
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware")
    n = now_et.astimezone(ET)
    if n.weekday() >= 5:
        return False, "weekend"
    lo = (dt.datetime.combine(n.date(), OPEN)
          + dt.timedelta(minutes=cfg.open_buffer_minutes)).time()
    hi = (dt.datetime.combine(n.date(), CLOSE)
          - dt.timedelta(minutes=cfg.close_buffer_minutes)).time()
    if not (lo <= n.time() <= hi):
        return False, f"outside {lo:%H:%M}-{hi:%H:%M} ET (now {n:%H:%M})"
    return True, ""


def period_key(now_et: dt.datetime, schedule: str) -> str:
    n = now_et.astimezone(ET)
    if schedule == "weekly":
        y, w, _ = n.isocalendar()
        return f"{y}-W{w:02d}"
    return f"{n.year}-{n.month:02d}"


def already_bought(ledger_path: Path, period: str) -> bool:
    return period in ledger.periods_bought(ledger_path)
