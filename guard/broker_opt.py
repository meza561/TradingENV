"""Option transport. Marketable LIMIT orders only -- never market.

Equity dollar-based orders forced type=market, so the DCA tool allowed it for
broad ETFs. Options have no such constraint and much wider spreads (an XLF
call quoted 0.45/0.94 after the close), so every order here is a limit at the
marketable side of the book: buy at the ask, sell at the bid. Fills like a
market order, but the price is capped.
"""
import json
import re
import subprocess

from guard import claudebin

PLACE_TOOL = "mcp__robinhood-trading__place_option_order"
POSITIONS_TOOL = "mcp__robinhood-trading__get_option_positions"
QUOTES_TOOL = "mcp__robinhood-trading__get_option_quotes"
ORDERS_TOOL = "mcp__robinhood-trading__get_option_orders"

OPEN_PROMPT = """Call {tool} with EXACTLY these arguments and change nothing:
account_number="{account}", quantity="1", type="limit", price="{price:.2f}",
time_in_force="gfd", market_hours="regular_hours",
legs=[{{"option_id":"{oid}","side":"buy","position_effect":"open"}}],
ref_id="{ref_id}"
Reply with ONLY the tool's JSON result, no prose, no code fence."""

CLOSE_PROMPT = """Call {tool} with EXACTLY these arguments and change nothing:
account_number="{account}", quantity="{qty}", type="limit", price="{price:.2f}",
time_in_force="gfd", market_hours="regular_hours",
legs=[{{"option_id":"{oid}","side":"sell","position_effect":"close"}}],
ref_id="{ref_id}"
Reply with ONLY the tool's JSON result, no prose, no code fence."""

POSITIONS_PROMPT = """Call {tool} with account_number="{account}", nonzero=true.
Reply with ONLY a JSON object, no prose, no code fence:
{{"positions":[{{"option_id":"","chain_symbol":"","strike_price":"",
"expiration_date":"","type":"","quantity":"","average_price":""}}]}}"""

QUOTES_PROMPT = """Call {tool} with instrument_ids={ids}.
Reply with ONLY a JSON object, no prose, no code fence:
{{"quotes":[{{"instrument_id":"","bid_price":"","ask_price":"","mark_price":""}}]}}"""

ORDERS_PROMPT = """Call {tool} with account_number="{account}".
Reply with ONLY a JSON object, no prose, no code fence:
{{"orders":[{{"id":"","ref_id":"","state":"","quantity":"","price":"",
"legs":[{{"option_id":"","side":"","position_effect":""}}]}}]}}"""


def _run(argv: list[str], prompt: str) -> str:
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p exited {r.returncode}: "
                           f"stderr={r.stderr.strip()[:300]!r}")
    return r.stdout


def _argv(tool: str) -> list[str]:
    return claudebin.argv(tool)


def _json(out: str, what: str) -> dict:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise ValueError(f"no JSON in {what}: {out[:200]!r}")
    return json.loads(m.group(0))


def open_position(account: str, option_id: str, limit_price: float,
                  ref_id: str, runner=None) -> dict:
    runner = runner or _run
    if not (limit_price > 0):
        raise ValueError(f"refusing to buy at limit {limit_price!r}")
    p = OPEN_PROMPT.format(tool=PLACE_TOOL, account=account, oid=option_id,
                           price=limit_price, ref_id=ref_id)
    return _json(runner(_argv(PLACE_TOOL), p), "open_position")


def close_position(account: str, option_id: str, quantity: int,
                   limit_price: float, ref_id: str, runner=None) -> dict:
    runner = runner or _run
    if not (limit_price > 0) or quantity < 1:
        raise ValueError(f"refusing to close at {limit_price!r} x {quantity!r}")
    p = CLOSE_PROMPT.format(tool=PLACE_TOOL, account=account, oid=option_id,
                            qty=int(quantity), price=limit_price, ref_id=ref_id)
    return _json(runner(_argv(PLACE_TOOL), p), "close_position")


def positions(account: str, runner=None) -> list[dict]:
    runner = runner or _run
    p = POSITIONS_PROMPT.format(tool=POSITIONS_TOOL, account=account)
    return _json(runner(_argv(POSITIONS_TOOL), p), "positions").get("positions", [])


def quotes(option_ids: list[str], runner=None) -> list[dict]:
    runner = runner or _run
    if not option_ids:
        return []
    p = QUOTES_PROMPT.format(tool=QUOTES_TOOL, ids=json.dumps(option_ids))
    return _json(runner(_argv(QUOTES_TOOL), p), "quotes").get("quotes", [])


def orders(account: str, runner=None) -> list[dict]:
    runner = runner or _run
    p = ORDERS_PROMPT.format(tool=ORDERS_TOOL, account=account)
    return _json(runner(_argv(ORDERS_TOOL), p), "orders").get("orders", [])


PORTFOLIO_TOOL = "mcp__robinhood-trading__get_portfolio"
PORTFOLIO_PROMPT = """Call {tool} with account_number="{account}".
Reply with ONLY a JSON object, no prose, no code fence:
{{"total_value":"","buying_power":""}}"""


def portfolio(account: str, runner=None) -> tuple[float, float]:
    """Returns (account_value, buying_power). Unparseable -> (0, 0), which
    sizes every position to zero rather than guessing at real money."""
    runner = runner or _run
    p = PORTFOLIO_PROMPT.format(tool=PORTFOLIO_TOOL, account=account)
    d = _json(runner(_argv(PORTFOLIO_TOOL), p), "portfolio")
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    bp = d.get("buying_power")
    if isinstance(bp, dict):
        bp = bp.get("buying_power")
    return num(d.get("total_value")), num(bp)
