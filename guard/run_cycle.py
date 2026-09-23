"""One cycle. Idempotent: safe to run every 15 minutes."""
import argparse
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from guard import ledger
from guard.config import load_config
from guard.executor import execute
from guard.guards import halted, is_live
from guard.plan import plan_order
from guard.validator import validate

ET = ZoneInfo("US/Eastern")
OK, HALTED, CONFIG_ERROR = 0, 2, 3


def _codes(reasons: list[str]) -> list[str]:
    """Leading rule code of each reason, e.g. 'G6'.

    Dedup must key on the CODE, not the whole string: the market-window
    reason embeds the current clock ("now 22:40"), so comparing full strings
    would make every cycle look new and write ~96 records a day.
    """
    return sorted({r.split()[0] for r in reasons if r})


def _log_skip(path: Path, period: str, reasons: list[str], mode: str) -> None:
    """One skip record per (period, reason codes), not one per cycle."""
    codes = _codes(reasons)
    rows = ledger.read_all(path)
    if rows:
        last = rows[-1]
        if (last.get("kind") == "skipped" and last.get("period") == period
                and last.get("codes") == codes):
            return
    ledger.append(path, {"kind": "skipped", "period": period, "codes": codes,
                         "reasons": reasons, "mode": mode})


def run(root: Path, config_path: Path, now_et=None, runner=None) -> int:
    now = (now_et or dt.datetime.now(ET)).astimezone(ET)
    cfg = load_config(config_path)

    stopped, why = halted(root)
    if stopped:
        print(f"HALT: {why}", file=sys.stderr)
        return HALTED

    live = is_live(cfg, root)
    intent = plan_order(cfg, now)
    ok, reasons = validate(intent, cfg, now)

    if not ok:
        _log_skip(cfg.ledger_path, intent.period, reasons,
                  "live" if live else "paper")
        print(f"skip [{intent.period}]: {'; '.join(reasons)}")
        return OK

    rec = execute(intent, cfg, root, live, runner)
    tag = "LIVE" if live else "paper"
    print(f"{tag} {rec['kind']}: {intent.symbol} ${intent.amount_usd:.2f} "
          f"[{intent.period}]")
    return HALTED if (Path(root) / "HALT").exists() else OK


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("guard.yaml"))
    ap.add_argument("--root", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    try:
        return run(a.root, a.config)
    except Exception as e:
        print(f"config/startup failure: {e}", file=sys.stderr)
        return CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
