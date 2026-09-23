"""Append-only decision log. Every cycle writes exactly one record."""
import datetime as dt
import json
import re
from pathlib import Path

SPEND_KINDS = {"paper", "placed"}
_ACCT = re.compile(r"\b\d{6,}\b")


def _mask(value):
    """G10: never log anything account-identifying in full."""
    if isinstance(value, str):
        return _ACCT.sub(lambda m: "••••" + m.group(0)[-4:], value)
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def append(path: Path, record: dict) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = _mask(dict(record))
    out["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with path.open("a") as f:
        f.write(json.dumps(out, sort_keys=True) + "\n")
    return out


def read_all(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def spend_records(path: Path) -> list[dict]:
    return [r for r in read_all(path) if r.get("kind") in SPEND_KINDS]


def spent_in_period(path: Path, period_key: str) -> float:
    return sum(float(r.get("amount_usd", 0))
               for r in spend_records(path) if r.get("period") == period_key)


def spent_lifetime(path: Path) -> float:
    return sum(float(r.get("amount_usd", 0)) for r in spend_records(path))


def periods_bought(path: Path) -> set[str]:
    return {r["period"] for r in spend_records(path) if r.get("period")}
