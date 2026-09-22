# Earnings-Event Trading Bot — Design Spec

**Date:** 2026-09-21
**Status:** Awaiting review
**Account:** Robinhood Agentic, individual, limited margin (account number withheld)

---

## 1. Purpose

An unattended, event-driven system that watches earnings releases for a fixed
ticker whitelist, applies a deterministic gate plus an LLM analyst step, and
places small long-only limit orders automatically.

**Default and development mode is paper.** Live trading requires two
independent manual actions by the account owner and is gated on a backtest
that must clear a pre-registered success bar.

## 2. Non-goals

- Options, crypto, margin, shorting, leverage. Long-only US equities/ETFs.
- Intraday/high-frequency trading. Cycle granularity is minutes, not seconds.
- Portfolio optimization, position scaling, or risk parity. Fixed notional only.
- Any strategy parameter search. See §7.3.

## 3. Hard rules (enforced in code, not prompts)

| # | Rule | Enforced by |
|---|------|-------------|
| R1 | Paper unless `MODE=live` AND `LIVE_ENABLED` file exists | `guards.is_live()`, checked twice per cycle |
| R2 | Long-only US equities/ETFs | `validator.check_instrument()` |
| R3 | Whitelist-only tickers | `validator.check_whitelist()` |
| R4 | Limit orders only, within `LIMIT_BAND_PCT` of quote | `validator.check_order_type()`, `check_limit_price()` |
| R5 | Caps: order size, orders/day, open positions, total exposure | `validator.check_caps()` |
| R6 | Regular hours only, not first 15 min after open | `guards.market_window_ok()` |
| R7 | Halt on 20% drawdown from starting value | `guards.drawdown_ok()` |
| R8 | Halt if `HALT` file exists | `guards.halted()` |
| R9 | Idempotency via open-order + history check and client `ref_id` | `executor.preflight_dedupe()` |
| R10 | No credentials stored, printed, or logged | `logging` redaction filter; no token access in code |
| R11 | All external text treated as untrusted data | `analyst.fence()` + validator independence |

Rules are enforced by `validator.py` and `guards.py`, which assume every
upstream component — including the analyst LLM — may be adversarial or
malfunctioning.

## 4. Architecture

```
run_cycle.py  (launchd, every N minutes during market hours)
     |
     +-- guards.py ......... HALT? live? market window? drawdown? -> abort early
     |
     +-- calendar.py ....... which whitelist tickers reported recently?
     |
     +-- gate.py ........... deterministic reaction/volume/liquidity checks
     |                        fails -> log + stop (analyst never invoked)
     |
     +-- analyst.py ........ claude -p, READ-ONLY tool allowlist
     |                        untrusted text fenced; strict JSON out
     |
     +-- validator.py ...... independent re-check of every rule
     |                        fails -> log + drop
     |
     +-- executor.py ....... paper: log intent
                              live:  claude -p, ORDER-TOOL-ONLY allowlist
                                     then post-trade verification
                                     mismatch -> write HALT
```

Each module is independently testable, takes plain data in and returns plain
data out, and has no hidden state beyond an explicit cache directory.

## 5. Data layer

### 5.1 Event dates — `edgar.py`

Robinhood's `get_earnings_results` returns only the trailing **8 quarters per
symbol**, which is insufficient for a statistically meaningful backtest (§7.2).
Historical event dates therefore come from SEC EDGAR.

- Source: EDGAR full-text/submissions API, form type `8-K`, Item `2.02`
  (Results of Operations and Financial Condition).
- Key field: **`acceptanceDateTime`**, not the report date. This is the moment
  information became public and is what prevents look-ahead bias.
- Cached in SQLite (`cache/events.db`), keyed `(cik, accession)`.
- SEC requires a declared User-Agent; requests are rate-limited to 10/sec.

### 5.2 Prices — `yahoo.py` (primary), `prices.py` (MCP reference)

**Amended 2026-09-22.** Bulk history comes from Yahoo's chart endpoint;
the Robinhood MCP is the independent cross-check.

- Primary: Yahoo `v8/finance/chart`, `interval=1d`, using `indicators.quote`
  (split-adjusted, matching the original `adjustment_type=split` choice) and
  NOT `adjclose`, which also folds in dividends.
- Reference: `get_equity_historicals` via `claude -p`, unchanged.
- Verified depth: **2014-01-02 to present**, 3,199 bars per symbol.
- Cached in SQLite (`cache/prices.db`), keyed `(symbol, date)`.

**Why amended.** Routing 166 bulk price requests through `claude -p` exhausted
the operator's session limit mid-run (154 of 166 failed with "You've hit your
session limit"), took ~103s per call, and competed with their own Claude Code
usage. The spec's reasoning — the MCP is OAuth-backed, so the LLM process is
the only authenticated client — is correct for the *order* path but was
over-applied to *public historical prices*, which need no broker auth at all.
Yahoo returns the same data in 6.5 seconds total at zero model cost.

**Verification.** 3,693 overlapping bars compared between the two sources:
**0 mismatches**, max close difference 0.098% (SPY exactly 0.000%), against a
0.5% tolerance. Stooq, originally named as the cross-check source, now serves
a JavaScript browser challenge and was never functional against live data —
its tests passed only because they injected fake CSV.

**Residual risk.** Yahoo's endpoint is unofficial and may change without
notice. Acceptable for a one-time research pull; the live bot (Phase 1) still
reads prices through the authenticated MCP.

### 5.3 Whitelist

`AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, WMT, COST, HD, NFLX`

Selected for liquidity and long filing history. Twelve names x ~50 quarters of
EDGAR history is on the order of 500-600 events before gating.

## 6. Signal definition — PRE-REGISTERED

This section is fixed **before** any backtest is executed. It is the contract
that makes the eventual result meaningful.

### 6.1 Event and entry timing

Defined as an exhaustive rule over the `acceptanceDateTime` (ET) of the 8-K, so
that exactly one case applies to every filing:

| Filing accepted on day D | T0 | T+1 (observation bar) |
|---|---|---|
| After 16:00 (post-close) | D | D+1 |
| During session, 09:30-16:00 | D | D+1 |
| Before 09:30 (pre-open) | D-1 (prior session) | D |

The intraday case deliberately forgoes the same-day move: the system does not
assume it could have traded a reaction that began while the filing was landing.

**Entry: the close of T+1.**

R6 forbids live trading in the first 15 minutes after the open, so a fill at the
T+1 open is unreachable by the live system; modeling it would measure a strategy
the bot cannot execute. The T+1 close is reachable, and is approximated live by a
limit order placed in the final 15 minutes of the session, with error bounded by
`LIMIT_BAND_PCT`.

**Gate inputs are frozen at the T+1 open.** No gate condition may read T+1's
high, low, close, or volume. The entry price *is* the T+1 close; admitting it as
a gate input would be circular. This is asserted by test, not just stated.

**Disclosed conservatism.** The window 09:45-16:00 on T+1 is legally tradeable
under R6, but daily bars cannot model a mid-session fill, so this rule forgoes
it. Measured returns therefore understate what the live system could capture.
Correcting it would require intraday bars (roughly 78x the data volume); that
trade was considered and declined on 2026-09-21.

If D+1 is not a trading day, T+1 is the next trading session. If the required
prior-20-session or SMA50 history is unavailable, the event is dropped rather
than computed on partial data.

### 6.2 Gate conditions (ALL must hold)

Every input is computed **only from bars strictly before entry**.

| ID | Condition | Rationale |
|----|-----------|-----------|
| G1 | `abs(open(T+1)/close(T0) - 1) >= 0.02` | A real reaction occurred |
| G2 | `open(T+1) > close(T0)` | Long-only; positive reactions only |
| G3 | `volume(T0) >= 1.5 * median(volume, prior 20 sessions)` | Confirmation |
| G4 | `median(close*volume, prior 20 sessions) >= $50M` | Tradeable liquidity |
| G5 | `close(T0) <= 1.15 * SMA50(T0)` | Not already extended |

### 6.3 Position and exit

- Fixed **$25 notional**, equal weight, no scaling.
- Entry at the **close of T+1** (see 6.1).
- **Primary exit: the close of the third session after T+1.** Fixed in advance.
- Returns at +1 and +5 sessions after entry are reported as secondary
  diagnostics only and **may not be used to select the primary horizon.**

This makes the measured quantity post-earnings *drift* rather than the initial
reaction — the standard formulation of the PEAD anomaly. It is expected to lower
measured returns relative to an open-entry model, making 7.4 harder to clear.
That is intended: an edge that survives is one the live system can capture.

### 6.4 Benchmarks

- SPY return over the identical holding window (excess return is the metric).
- Buy-and-hold VTI over the full period (the real-world alternative).

## 7. Backtest

### 7.1 Look-ahead prevention

1. Event timestamps come from `acceptanceDateTime`, not report date.
2. All features use bars strictly prior to the entry bar.
3. Split adjustment applied uniformly across the whole series.
4. The whitelist is fixed for the entire period — this **does** introduce
   survivorship bias, which is disclosed rather than corrected (§11.3).

### 7.2 Out-of-sample split

Split by **time**, never randomly:

- **Train / inspect:** events before `2021-01-01`
- **Test / held out:** events from `2021-01-01` onward

The test set is not examined until the train set is finalized.

### 7.3 Stopping rule — binding

The signal (§6) and the success criteria (§7.4) are fixed before execution.
The backtest runs **once** against the test set. Results are reported as they
come out.

**No parameter will be adjusted and re-run to improve the result.** If the
result is negative, the finding is "no detectable edge" and the project stops
at Phase 0. This rule only has force because it binds before results are seen.

### 7.4 Success criteria — all three required

| Criterion | Threshold |
|-----------|-----------|
| Mean excess return vs SPY, test set | > 0 with t-statistic >= 2.0 |
| Hit rate, test set | > 50% |
| Max drawdown of the event-return series | <= 25% |

Failing any one means no edge. Phase 1 is not built.

### 7.5 Statistical power — known limitation

The test window (2021-01-01 onward) holds roughly 274 raw events across twelve
names. Gate conditions G1-G5 are expected to pass on the order of 20-25% of
them, leaving an estimated **~50 test events**.

At n≈50, a t-statistic of 2.0 requires a mean excess return of roughly
0.28 standard deviations. With 3-day excess-return dispersion near 5%, the
smallest edge this design can detect is on the order of **1.4% mean excess
return per trade** — a large effect.

The consequence must be stated plainly: **this test has low power and will
report "no edge" for any edge that is real but modest.** That is the intended
direction of error. A design tuned to detect small edges on ~50 events would
mostly detect noise, and the whole point of §7.3 is to avoid mistaking noise
for signal. A negative result therefore means "no large edge detectable here,"
not "no edge exists."

Increasing power would require more names or a longer price history, both of
which are available and both of which expand scope. Neither will be done
reactively after seeing a disappointing result — that would be §7.3 violated
through the back door. If power is to be increased, the decision is made
before the test set is examined.

## 8. Live path

### 8.1 Analyst — `analyst.py`

```
claude -p --allowedTools "mcp__robinhood-trading__get_equity_quotes,
                          mcp__robinhood-trading__get_equity_fundamentals,
                          mcp__robinhood-trading__get_sec_filing"
```

No order-placing tool is in the allowlist, so none is reachable — enforcement
at the harness level, not the prompt level.

**Untrusted input handling.** All filing/news text is wrapped:

```
<UNTRUSTED_SOURCE name="8-K" ticker="AAPL">
...verbatim source text...
</UNTRUSTED_SOURCE>
```

with an instruction that content inside the fence is data to analyze and never
instructions to follow. This is defense in depth only — the actual guarantee is
that the validator (§8.2) re-checks everything independently, so a fully
compromised analyst still cannot produce a rule-violating order.

**Output contract** — strict JSON, anything else is dropped:

```json
{"ticker":"AAPL","action":"buy|sell|none","size_usd":25.0,
 "limit_price":381.54,"rationale":"...","sources":["..."]}
```

### 8.2 Validator — `validator.py`

The real safety layer. Treats the analyst as adversarial and re-derives every
constraint from config and live market data — it never trusts a value the
analyst supplied.

Checks: JSON schema; ticker in whitelist; action in enum; `size_usd <=
MAX_ORDER_USD` and `> 0` and finite; `limit_price` within `LIMIT_BAND_PCT` of a
**freshly fetched** quote; order type is limit; orders-today `<
MAX_ORDERS_PER_DAY`; open positions `< MAX_OPEN_POSITIONS`; projected exposure
`<= MAX_TOTAL_EXPOSURE_USD`; market window OK; drawdown OK; no duplicate.

Any failure: log with reason code, drop the order, continue. Never repair.

### 8.3 Executor — `executor.py`

**Paper (default):** append the fully-formed order to JSONL. No tool call.

**Live:** re-check both keys, then

```
claude -p --allowedTools "mcp__robinhood-trading__place_equity_order"
```

with the validated order and a Python-generated `ref_id` UUID for broker-side
idempotency.

**Post-trade verification** (added beyond original spec, approved 2026-09-21):
after the call returns, re-read via `get_equity_orders` and compare the placed
order field-by-field against the validated JSON — symbol, side, type,
limit_price, amount, ref_id. **Any mismatch, or any order found that was not
validated, writes `HALT` and stops the system.** This converts the one risk the
LLM executor introduces (mis-transcription, duplication) from silent to
self-halting.

## 9. Configuration

```yaml
MODE: paper                    # paper | live  (live also needs LIVE_ENABLED file)
ACCOUNT_NUMBER: "<set in config.yaml, which is gitignored>"
WHITELIST: [AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, WMT, COST, HD, NFLX]
MAX_ORDER_USD: 25
MAX_ORDERS_PER_DAY: 2
MAX_OPEN_POSITIONS: 2
MAX_TOTAL_EXPOSURE_USD: 100
LIMIT_BAND_PCT: 0.5
DRAWDOWN_HALT_PCT: 20
STARTING_VALUE_USD: null       # captured on first run, then immutable
OPEN_BUFFER_MINUTES: 15
CYCLE_MINUTES: 15
```

Validated by Pydantic at import. A malformed or missing config is a startup
failure, never a fallback to defaults.

**Effective exposure note:** with `MAX_ORDER_USD=25` and
`MAX_ORDERS_PER_DAY=2`, reaching `MAX_TOTAL_EXPOSURE_USD=100` takes a minimum
of four trading days. The caps are mutually consistent.

## 10. Operations

### 10.1 Scheduling

macOS **launchd** (not cron): survives reboot, handles sleep/wake correctly,
and logs failures. Plist runs `run_cycle.py` every `CYCLE_MINUTES` between
09:45 and 16:00 ET on weekdays. Each cycle is independent and idempotent; a
missed cycle has no consequence.

### 10.2 Logging

Append-only JSONL, one record per cycle, capturing: cycle id, timestamp, guard
results, candidate events, gate verdict per ticker, analyst raw output,
validator verdict with reason codes, executor action, order id. A redaction
filter strips anything resembling a token before write.

Daily summary report plus a buy-and-hold benchmark comparison.

### 10.3 Kill switch

```bash
touch HALT      # stop everything
rm HALT         # resume
```

Checked first in every cycle. Reason logged on every halted cycle.

### 10.4 Going live (two independent steps)

```bash
# 1. edit config
MODE: live
# 2. create the second key by hand
touch LIVE_ENABLED
```

Neither will be done by the assistant. Missing either one means paper.

### 10.5 Revoking access

`/mcp` in Claude Code to disconnect `robinhood-trading`, and revoke the agentic
connection in the Robinhood app under account settings. Revoking makes every
order tool fail closed.

## 11. Testing

### 11.1 Unit — validator and gate (exhaustive)

Adversarial analyst outputs: over-size orders; non-whitelist tickers;
`action:"short"`; negative, zero, NaN, and Infinity sizes; limit prices far off
quote; market order type; unicode ticker lookalikes (`АAPL` with Cyrillic А);
JSON with trailing prose; null bytes; deeply nested JSON; missing fields; extra
fields; duplicate order ids.

### 11.2 Prompt injection corpus

Filing text containing: "ignore previous instructions"; fake `</UNTRUSTED_SOURCE>`
closing tags attempting fence escape; simulated system prompts; instructions to
raise `MAX_ORDER_USD`; embedded JSON impersonating validator output;
instructions to place an order in a different account.

**Assertion pattern:** injection may corrupt the analyst's output; the test
asserts the validator drops it regardless. Defense is structural, not textual.

### 11.3 Backtest integrity tests

- Shuffled-labels control: the same pipeline on randomized event dates must
  produce no edge. If it does, there is a look-ahead bug.
- Survivorship-bias disclosure: the fixed whitelist is twelve names that are
  large and liquid *today*. This inflates historical returns. Reported as a
  known limitation, not corrected.

### 11.4 Executor tests

Run against a mock exclusively. **No test invokes a real order tool.** A test
asserts that order tools are unreachable from the analyst's allowlist.

## 12. Phasing

| Phase | Contents | Gate to next |
|-------|----------|--------------|
| **0** | `edgar.py`, `prices.py`, `backtest.py`, integrity tests | §7.4 criteria met on held-out test set |
| **1** | config, guards, gate, analyst, validator, executor, tests | All tests green; owner review |
| **2** | run_cycle, launchd, logging, reporting | Paper-mode soak |
| **3** | Live — owner action only | Owner sets both keys, funds account |

Phase 0 failing is a legitimate and expected outcome (§13.6), and the project
stops there with a written finding.

## 13. Assumptions and unverified items

1. **EDGAR 8-K Item 2.02 coverage and parse reliability** — unproven until
   built. Note the binding constraint on sample size is **price** history
   (verified back to 2014-01-02), not EDGAR, which goes back further. Events
   before 2014 are unusable regardless of filing coverage. Poor 8-K parse
   reliability within the 2014+ window would shrink the sample further and
   could cause Phase 0 to fail for data reasons rather than strategy reasons;
   the report will distinguish the two.
2. **`eps.estimate` point-in-time status** — unverifiable. Cannot determine
   whether it is as-of-report-date consensus or a later revision. Therefore
   excluded from the signal entirely.
3. **`claude -p --allowedTools` as a hard boundary for MCP tools** — assumed,
   will be asserted by test before being relied upon.
4. **Robinhood MCP rate limits** — undocumented. Mitigated with exponential
   backoff and aggressive caching.
5. **OAuth durability under unattended headless runs** — unknown whether the
   token survives indefinitely or needs periodic interactive re-auth. If it
   expires mid-run the bot stops trading; this will be a loud logged failure,
   but periodic manual re-auth should be expected.
6. **Prior on finding an edge is low.** Post-earnings announcement drift is
   among the most heavily researched and arbitraged anomalies in equities. The
   system is built to measure honestly, not to succeed.
7. **Account funding.** As of 2026-09-21 the account holds $150 entirely in
   VTI, $0 cash. Live mode requires the owner to free cash first. No sale will
   be executed as part of this build; it is a separate, separately confirmed
   order at the owner's initiative.

## 14. Open items for owner

- Confirm the whitelist (currently the proposed starter set).
- Confirm `CYCLE_MINUTES: 15` is acceptable polling frequency.
- Decide whether Phase 2 paper soak has a minimum duration before Phase 3.

---

## 15. Amendment 2026-09-22 — Power expansion (PRE-REGISTERED)

**Written and committed BEFORE any expansion data was fetched.** Commit order
is the evidence that this is a test and not a search.

### 15.1 Why

The 2026-09-22 run returned **NO EDGE**: test n=68, t=1.96 against a 2.0 bar,
hit 63.2%, maxDD 12.8%. Two of three criteria cleared. The operator elected
to increase statistical power under §7.5, which permits it only when decided
before a new test set is examined.

**This decision was made after seeing t=1.96.** That is a selection effect and
it is disclosed here rather than hidden. The design below exists to contain it.

### 15.2 Why more history would be useless

The train/test boundary is fixed at 2021-01-01 and does not move. Extending
history backward adds **only train events**; test n stays 68 and test power is
unchanged. Only additional tickers raise test-set power. The boundary is part
of the pre-registration; moving it would reclassify already-examined train
events as held-out, which is laundering.

### 15.3 Cohort B — frozen list

Selected by rule: largest US large-caps by market capitalization, continuously
listed since 2014, not already in the whitelist. **No ticker was selected for
any property of its returns.**

```
TSLA UNH  XOM  JNJ  V    MA   PG   LLY
ORCL CVX  MRK  ABBV KO   PEP  BAC  CRM
TMO  MCD  CSCO ACN  ABT  ADBE TXN  VZ
DIS  INTC QCOM CAT
```

A ticker with unusable EDGAR data is **dropped and recorded as dropped**, never
swapped for a replacement.

### 15.4 What is decisive

| Result | Status |
|---|---|
| **Cohort B alone, test window (2021+)** | **PRIMARY.** Never examined. Clean replication. |
| Cohort A ∪ B combined, test window | Secondary. Contaminated by the first look. **Cannot clear or fail anything.** |
| Cohort A alone | Already reported (t=1.96). Restated for completeness only. |

### 15.5 What does not change

The signal definition (§6) and all three success criteria (§7.4) are
**unchanged**. Not one threshold moves. §7.3 still binds: one run, one report,
no tuning and re-running.

### 15.6 Interpretation set in advance

A Cohort B result near the threshold **does not establish an edge**. One
marginal result followed by another marginal result, on correlated names in
the same market regime, is weak evidence. A pass here warrants at most
"worth a further pre-registered test", never "deploy capital".

Survivorship bias is **worse** at 40 names than at 12: every name is large
today. Disclosed, not corrected.
