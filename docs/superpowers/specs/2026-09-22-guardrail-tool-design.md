# Guardrail Tool — Design Spec

**Date:** 2026-09-22
**Status:** Approved, v1 in progress
**Purpose:** Make agent-mediated investing safe for a small account.

---

## 1. What this is

A deterministic guardrail layer between a scheduled investing rule and a
brokerage account reached through an OAuth-backed agent connection.

Its job is **refusal**, not return. Three pre-registered experiments
(`2026-09-21-earnings-bot-design.md`) found no edge accessible to a small
retail account. The conclusion drawn here: for someone not investing much, a
tool's value lies entirely in not doing damage — caps, defaults and refusals.

**Default behaviour is the boring evidence-backed one:** a fixed-dollar
purchase of a whitelisted broad-market ETF on a schedule.

## 2. Non-goals

- Finding, predicting or timing anything. No signal, no strategy, no forecast.
- Individual stocks, options, crypto, margin, shorting, selling.
- Advice. It executes a rule the operator wrote; it never recommends.
- Holding anyone else's credentials. v1 is personal: one operator, one account.

## 3. The LLM makes no decisions

Every decision is deterministic Python the operator can read. The agent
connection exists solely because the broker's MCP is remote and OAuth-backed,
so an LLM process is the only authenticated client (see the earnings spec
§8.3). It is a transport, constrained by `--allowedTools` to one tool per call.

```
run_cycle
  guards     HALT? live keys? market window? already bought this period?
  plan       deterministic: amount + symbol from config
  validator  independent re-check; assumes plan may be wrong
  executor   paper -> ledger only;  live -> place, then verify the fill
  ledger     append-only JSONL, including refusals
```

## 4. Hard rules

| # | Rule | Enforced by |
|---|---|---|
| G1 | Paper unless `MODE=live` **and** `LIVE_ENABLED` exists | `guards.is_live()`, checked twice per cycle |
| G2 | Buy only. Never sells, never closes a position | `validator` rejects any non-buy |
| G3 | Whitelisted broad ETFs only | `validator.check_symbol()` |
| G4 | Dollar-based market orders **only** for whitelisted ETFs in regular hours; anything else must be a limit order | `validator.check_order_type()` |
| G5 | Per-order, per-period and lifetime spend caps | `validator.check_caps()` |
| G6 | Regular hours only, with open/close buffers | `guards.market_window_ok()` |
| G7 | `HALT` file stops everything | `guards.halted()` |
| G8 | One purchase per period, ever | `guards.already_bought()` + ledger |
| G9 | Post-trade verification; mismatch writes `HALT` | `executor.verify()` |
| G10 | No credential is stored, printed or logged | ledger redaction; no token access in code |

### 4.1 Why G4 replaces the earnings spec's "limit orders only"

Dollar-based fractional orders require `type=market` — the broker enforces it,
and at $25 with VTI near $381 a whole-share limit order cannot be placed at all.
The original rule guarded against bad fills on illiquid names; a broad ETF
trading on a ~2 cent spread is not that case. The intent is preserved and
narrowed to where it applies.

### 4.2 Why there is no drawdown halt

In a trading bot a 20% drawdown means something is wrong. In a
dollar-cost-averaging tool it means the market fell — precisely when continuing
to buy matters most. A drawdown halt would automate buying high and stopping
low, under the banner of safety.

Guards here are **spend-triggered, not loss-triggered**: per-period and lifetime
caps bound what a bug can cost without flinching at normal market behaviour.
The `HALT` file remains: a human stopping it is always valid.

## 5. Success criteria

Not returns — it buys an index fund, so returns are the market's. The tool
performs well when, over a review period:

1. Every scheduled purchase that should have happened, did.
2. No cap was ever exceeded.
3. Every placed order matched its validated intent field-for-field.
4. Every refusal was correct and is explained in the ledger.

The ledger records exactly these, so the operator judges the right thing.

## 6. Configuration

```yaml
mode: paper                 # paper | live (live also needs LIVE_ENABLED)
account_number: "..."       # real config is gitignored
symbol: VTI
amount_usd: 25
schedule: weekly            # weekly | monthly
whitelist: [VTI, VOO, SPY, ITOT, IVV, BND, AOR]
max_order_usd: 50
max_spend_per_period_usd: 50
max_lifetime_spend_usd: 500
open_buffer_minutes: 15
close_buffer_minutes: 10
```

Validated at import; a malformed or missing config is a startup failure, never
a fallback to defaults.

## 7. Known limitations (v1)

- **Market holidays are not modelled.** The window check is weekday plus time.
  On a holiday an order would queue to the next session rather than being
  refused. Documented; acceptable for a buy-only scheduled tool.
- **Quotes are not used.** Dollar-based market orders need no limit price, so
  no quote is fetched and no staleness risk exists.
- **One account, one operator.** No multi-user support, no credential handling.
- **OAuth durability is unproven** for long unattended operation. Token
  expiry stops trading; this is a loud logged failure, not a silent one.
- **Not audited.** Personal tool. Anyone else running it does so as an operator
  of their own account, with their own credentials, at their own risk.
