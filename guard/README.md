# guard — autonomous long-option trading, paper by default

Buys at most one option contract at a time from a whitelist, on a schedule,
and refuses everything else. Exits are deterministic and are never delegated.

**Read this first:** three pre-registered experiments in this repo found no
edge accessible to a small retail account. Leverage without an edge multiplies
costs, not returns. The expected outcome is losing most of what is deployed.
The caps bound the loss; the decision quality is unproven.

## What decides what

| Decision | Owner |
|---|---|
| **Entry** | a headless Claude, read-only tools, picks from a pre-filtered menu |
| **Exit** | deterministic code: +50% / −50% / close at 14 DTE |
| **Permission** | a validator that assumes the analyst is wrong |
| **Execution** | marketable limit orders, then field-by-field verification |

The analyst cannot place an order — its tool allowlist has none — and cannot
name a contract that is not already on the menu the selector built.

## Setup

```bash
cp options.example.yaml options.yaml     # gitignored
# edit: account_number, caps, underlyings
.venv/bin/python -m pytest tests_guard/ -q
```

## Running it

```bash
.venv/bin/python ops/make_plist.py       # plist generated FROM options.yaml
cp ops/com.guard.options.local.plist ~/Library/LaunchAgents/com.guard.options.plist
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.guard.options.plist
launchctl list | grep guard
```

The destination filename must match the Label; a bare directory target keeps
the `.local` name and bootstrap fails with `5: Input/output error`.

```bash
launchctl bootout gui/$UID/com.guard.options      # stop
touch HALT                                        # freeze without unloading
```

## Checking on it

```bash
.venv/bin/python -m guard.report
```

Bounded at ~20 lines however long the ledger gets.

## Going live — three keys, all manual

1. `mode: live` in `options.yaml`
2. `touch LIVE_ENABLED`
3. remove `place_equity_order` from the deny list in `.claude/settings.json`

Any one missing means paper. The third is enforced by the Claude Code harness,
outside this code entirely.

**The live order path has never executed.** Every test uses a mock.

## What it refuses

Sells, spreads, 0DTE, rolling, averaging down, anything off the whitelist,
anything over a cap, anything outside 09:45–15:50 ET, anything while `HALT`
exists, and any contract whose bid/ask spread exceeds the configured fraction
of mid.

## Call budget

| | calls |
|---|---|
| cold (first run of a 5-day window) | 8 |
| warm | 1 |
| slots full | 0 |

`structure_ttl_days` controls the window. Spot prices are fetched lazily and a
warm run needs none.

## Known gaps

- The live order path is unexercised.
- No P&L: the digest shows entry price, not current value or realised gain.
- Expiration selection takes the **first** qualifying date (≈30 DTE) rather
  than mid-window, so slightly more theta decay than intended.
- Market holidays are not modelled; the window check is weekday plus clock.
- Auth is a Keychain token. If it expires, cycles fail loudly and need
  `/login` in an interactive Claude Code session.
