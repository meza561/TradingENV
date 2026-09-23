# guard — a guardrail layer for agent-mediated investing

Buys a fixed dollar amount of a whitelisted broad-market ETF on a schedule,
and refuses everything else.

**Its job is refusal, not return.** Three pre-registered experiments in this
repo found no edge accessible to a small retail account, so the value of a
tool here is in not doing damage: caps, defaults, and saying no.

**The LLM makes no decisions.** Every decision is deterministic Python you can
read. A `claude -p` process is used only as transport, because the broker's MCP
is OAuth-backed and Python cannot authenticate to it directly. It is restricted
to one tool per call by `--allowedTools`, enforced by the harness.

## Setup

```bash
cp guard.example.yaml guard.yaml     # gitignored
# edit: account_number, symbol, amount_usd, caps
.venv/bin/python -m pytest tests_guard/ -q
```

## Run

```bash
.venv/bin/python -m guard.run_cycle                  # one cycle
.venv/bin/python -m guard.run_cycle --config guard.yaml --root .
```

Safe to run every 15 minutes. It buys at most once per period and dedupes its
own skip records, so a frequent schedule does not flood the ledger.

Exit codes: `0` ran (bought or skipped), `2` halted, `3` config failure.

## Stopping it

```bash
touch HALT      # nothing runs
rm HALT         # resume
```

## Going live — three keys, all manual

1. `mode: live` in `guard.yaml`
2. `touch LIVE_ENABLED`
3. Remove `mcp__robinhood-trading__place_equity_order` from the `deny` list in
   `.claude/settings.json`

Any one missing means no live order is placed. Keys 1 and 2 are the tool's;
key 3 is the Claude Code harness refusing the tool outright, which is a
stronger guarantee than anything this code does. **Live mode also needs
settled cash in the account** — a fully-invested account has $0 buying power.

## What it refuses

| | |
|---|---|
| G1 | Anything live without both keys |
| G2 | Any sell. It only buys. |
| G3 | Any symbol outside the whitelist |
| G4 | Market orders for non-whitelisted symbols |
| G5 | Per-order, per-period and lifetime spend caps |
| G6 | Outside regular hours, plus open/close buffers |
| G7 | Anything at all while `HALT` exists |
| G8 | More than one purchase per period |
| G9 | Continuing after a placed order fails verification — writes `HALT` |
| G10 | Logging anything account-identifying |

## Reading the ledger

`ledger-paper.jsonl` and `ledger-live.jsonl` are append-only, one JSON object
per line. Paper and live are separate files on purpose: weeks of paper runs
must not consume the live lifetime cap.

Judge the tool on these, not on returns — it buys an index fund, so returns are
the market's:

1. Every scheduled purchase that should have happened, did.
2. No cap was ever exceeded.
3. Every placed order matched its validated intent field-for-field.
4. Every refusal was correct and is explained.

## Known limitations

- **Market holidays are not modelled.** Weekday plus clock only; a holiday
  order would queue to the next session.
- **One account, one operator.** No multi-user support, no credential handling.
- **Not audited.** A personal tool. Anyone else running it does so on their own
  account, with their own credentials, at their own risk.
- **OAuth expiry stops trading.** Loudly logged, not silent, but it stops.

## Installing the scheduler

The plist filename must match the Label inside it, so name the destination
explicitly -- a bare directory target keeps the `.local` source name and
`launchctl bootstrap` then fails with the unhelpful `5: Input/output error`.

```bash
# options cycle
cp ops/com.guard.options.local.plist ~/Library/LaunchAgents/com.guard.options.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.guard.options.plist
launchctl list | grep guard

# stop it
launchctl bootout gui/$UID/com.guard.options
```

The DCA cycle installs the same way with `com.guard.cycle`.
