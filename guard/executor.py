"""Paper logs; live places, then verifies. A mismatch writes HALT."""
import uuid
from pathlib import Path

from guard import broker, ledger
from guard.config import Config
from guard.guards import HALT_FILE
from guard.plan import Intent

VERIFY_TOL = 0.005      # cents of rounding on the dollar amount


def _write_halt(root: Path, why: str) -> None:
    (Path(root) / HALT_FILE).write_text(f"auto-halt: {why}\n")


def verify(placed: list[dict], intent: Intent, ref_id: str) -> tuple[bool, str]:
    """Field-for-field against what was validated. Absence is a mismatch."""
    mine = [o for o in placed if str(o.get("ref_id", "")) == ref_id]
    if len(mine) != 1:
        return False, f"expected exactly 1 order with ref_id={ref_id}, found {len(mine)}"
    o = mine[0]
    if str(o.get("symbol", "")).upper() != intent.symbol:
        return False, f"symbol {o.get('symbol')!r} != {intent.symbol!r}"
    if str(o.get("side", "")).lower() != intent.side:
        return False, f"side {o.get('side')!r} != {intent.side!r}"
    if str(o.get("type", "")).lower() != intent.order_type:
        return False, f"type {o.get('type')!r} != {intent.order_type!r}"
    try:
        amt = float(o.get("dollar_amount") or 0)
    except (TypeError, ValueError):
        return False, f"unparseable dollar_amount {o.get('dollar_amount')!r}"
    if abs(amt - intent.amount_usd) > VERIFY_TOL:
        return False, f"amount {amt} != {intent.amount_usd}"
    return True, ""


def execute(intent: Intent, cfg: Config, root: Path, live: bool,
            runner=None) -> dict:
    base = dict(intent.as_dict(), mode="live" if live else "paper")

    if not live:
        return ledger.append(cfg.ledger_path, dict(base, kind="paper"))

    ref_id = str(uuid.uuid4())
    try:
        resp = broker.place_order(cfg.account_number, intent.symbol,
                                  intent.amount_usd, ref_id, runner)
    except Exception as e:
        return ledger.append(cfg.ledger_path,
                             dict(base, kind="error", ref_id=ref_id,
                                  reason=f"place failed: {e!r:.200}"))
    rec = ledger.append(cfg.ledger_path,
                        dict(base, kind="placed", ref_id=ref_id,
                             response=broker.essential(resp)))

    try:
        orders = broker.get_orders(cfg.account_number, runner)
    except Exception as e:
        _write_halt(root, f"could not verify order {ref_id}: {e!r:.160}")
        ledger.append(cfg.ledger_path,
                      dict(base, kind="halted", ref_id=ref_id,
                           reason=f"verification read failed: {e!r:.160}"))
        return rec

    ok, why = verify(orders, intent, ref_id)
    ledger.append(cfg.ledger_path,
                  dict(base, kind="verified" if ok else "halted",
                       ref_id=ref_id, reason=why))
    if not ok:
        _write_halt(root, f"order {ref_id} did not match intent: {why}")
    return rec
