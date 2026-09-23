"""Transport to the broker. The only component that talks to an LLM.

The broker's MCP is remote and OAuth-backed, so a `claude -p` process is the
only authenticated client available. It carries a fully-formed order and is
restricted to ONE tool per call by --allowedTools, enforced by the harness
rather than by prompt text.
"""
import json
import re
import subprocess

from guard import claudebin

PLACE_TOOL = "mcp__robinhood-trading__place_equity_order"
READ_TOOL = "mcp__robinhood-trading__get_equity_orders"

PLACE_PROMPT = """Call {tool} with EXACTLY these arguments and change nothing:
account_number="{account}", symbol="{symbol}", side="buy", type="market",
dollar_amount="{amount:.2f}", market_hours="regular_hours",
time_in_force="gfd", ref_id="{ref_id}"
Reply with ONLY the tool's JSON result, no prose, no code fence."""

READ_PROMPT = """Call {tool} with account_number="{account}".
Reply with ONLY a JSON object, no prose, no code fence:
{{"orders":[{{"id":"","symbol":"","side":"","type":"","state":"",
"ref_id":"","dollar_amount":"","average_price":""}}]}}"""


def _run(argv: list[str], prompt: str) -> str:
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p exited {r.returncode}: "
                           f"stderr={r.stderr.strip()[:300]!r}")
    return r.stdout


def _argv(tool: str) -> list[str]:
    argv = claudebin.argv(tool)
    # A read call must never carry the order tool.
    if tool == READ_TOOL:
        assert PLACE_TOOL not in argv, "order tool leaked into a read call"
    return argv


def _json(out: str, what: str) -> dict:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise ValueError(f"no JSON in {what} output: {out[:200]!r}")
    return json.loads(m.group(0))


def place_order(account: str, symbol: str, amount: float, ref_id: str,
                runner=None) -> dict:
    runner = runner or _run
    prompt = PLACE_PROMPT.format(tool=PLACE_TOOL, account=account,
                                 symbol=symbol, amount=amount, ref_id=ref_id)
    return _json(runner(_argv(PLACE_TOOL), prompt), "place_order")


def get_orders(account: str, runner=None) -> list[dict]:
    runner = runner or _run
    prompt = READ_PROMPT.format(tool=READ_TOOL, account=account)
    return _json(runner(_argv(READ_TOOL), prompt), "get_orders").get("orders", [])
