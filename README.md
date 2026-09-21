# ebot — Phase 0: Earnings Signal Backtest

**This code places no orders.** Phase 0 is read-only research. The live
trading system (Phases 1–3) is specified but NOT built, and will only be
built if this backtest clears the bar in spec §7.4.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp config.example.yaml config.yaml
# edit config.yaml: set sec_user_agent to a real name and email.
# SEC requires this and will block requests without it.
```

## Run

```bash
.venv/bin/python -m ebot.run_backtest --fetch   # first run: populates cache
.venv/bin/python -m ebot.run_backtest           # later runs: cache-only
.venv/bin/python -m pytest tests/ -v            # full suite
```

`--fetch` shells out to `claude -p` once per symbol per calendar year, with an
allowlist containing only `get_equity_historicals`. No order tool is reachable.
Expect roughly 170 calls on a cold cache; interrupted runs resume.

## Reading the result

The runner prints a VERDICT and writes `reports/backtest-<date>.json`.

**It refuses to overwrite an existing report.** Spec §7.3 forbids re-running
with adjusted parameters to improve results. Deleting the report to re-run is a
deliberate departure from the pre-registered protocol, not an accident.

Exit codes: `0` ran, `1` no cached bars, `2` fatal data-integrity issues.

A NO EDGE verdict means *no large edge is detectable at this sample size*
(§7.5) — not that no edge exists. Results are also inflated by survivorship
bias in the fixed whitelist (§11.3) and deflated by the T+1 close entry (§6.1).

**Measured false-positive rate:** on 40 runs of pure random-walk data with
randomly placed events, the §7.4 criteria were cleared **1 time in 40 (2%)**.
Median control run produced 48 trades — close to the ~50 §7.5 predicted.

## Layout

| File | Responsibility |
|------|----------------|
| `ebot/edgar.py` | SEC 8-K Item 2.02 acceptance timestamps |
| `ebot/prices.py` | Daily OHLCV via headless Claude, year-chunked, cached |
| `ebot/validate_bars.py` | Data integrity; fatal vs warning |
| `ebot/crosscheck.py` | Independent price check against Stooq |
| `ebot/calendar.py` | Entry-timing rule (§6.1) |
| `ebot/gate.py` | Gate conditions G1–G5 (§6.2) |
| `ebot/backtest.py` | Event → trade, T+1 close to T+3-after close |
| `ebot/stats.py` | t-stat, hit rate, drawdown, §7.4 criteria |

`tests/test_integrity.py` is the file that makes the rest trustworthy: it runs
the whole pipeline on data with no edge by construction and asserts none is
found.

## Revoking broker access

`/mcp` in Claude Code disconnects `robinhood-trading`; revoke the agentic
connection in the Robinhood app under account settings.
