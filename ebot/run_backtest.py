import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from ebot.backtest import run_events
from ebot.config import load_config
from ebot.edgar import fetch_events
from ebot.prices import load_bars
from ebot.yahoo import fetch_and_cache
from ebot.stats import evaluate
from ebot.types import Trade
from ebot.validate_bars import validate_bars, FATAL_KINDS


def split_trades(trades: list[Trade],
                 boundary: dt.date) -> tuple[list[Trade], list[Trade]]:
    """Split by TIME, never randomly. The boundary date is in the test set."""
    train = [t for t in trades if t.entry_date < boundary]
    test = [t for t in trades if t.entry_date >= boundary]
    return train, test


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(
            f"{path} exists. Spec 7.3 forbids re-running to improve results. "
            f"Delete it by hand if you genuinely intend to re-run.")
    path.write_text(json.dumps(payload, indent=2, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--fetch", action="store_true", help="refresh price cache")
    ap.add_argument("--expansion", action="store_true",
                    help="spec 15 power-expansion experiment (cohort B primary)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    cohort_a = list(cfg.whitelist)
    cohort_b = list(cfg.expansion) if args.expansion else []
    symbols = cohort_a + cohort_b + [cfg.benchmark]
    if args.fetch:
        for s in symbols:
            print(f"fetching {s}...", file=sys.stderr)
            fetch_and_cache(s, cfg)

    bars = {s: load_bars(s, cfg) for s in symbols}
    missing = [s for s, b in bars.items() if not b]
    if missing:
        print(f"no cached bars for {missing}; run with --fetch", file=sys.stderr)
        return 1

    all_issues = [i for s in symbols for i in validate_bars(bars[s], cfg)]
    fatal = [i for i in all_issues if i.kind in FATAL_KINDS]
    for i in all_issues:
        print(f"  [{i.kind}] {i.symbol} {i.date}: {i.detail}", file=sys.stderr)
    if fatal:
        print(f"\n{len(fatal)} FATAL data issues. Refusing to backtest on bad "
              f"data. Fix the cache and re-run.", file=sys.stderr)
        return 2
    if all_issues:
        print(f"{len(all_issues)} non-fatal data warnings (above).", file=sys.stderr)

    events = []
    for t in cohort_a + cohort_b:
        events.extend(fetch_events(t, cfg))
    trades = run_events(events, bars, bars[cfg.benchmark], cfg)
    train, test = split_trades(trades, cfg.train_test_split)

    a_set, b_set = set(cohort_a), set(cohort_b)
    test_a = [t for t in test if t.ticker in a_set]
    test_b = [t for t in test if t.ticker in b_set]

    bench_bars = bars[cfg.benchmark]
    held = [b for b in bench_bars if b.date >= cfg.train_test_split]
    buy_hold = (held[-1].close / held[0].open - 1.0) if len(held) > 1 else 0.0
    test_eval = evaluate([t.excess for t in test])
    strat_total = 1.0
    for t in test:
        strat_total *= (1.0 + t.ret)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_events": len(events), "n_trades": len(trades),
        "train": evaluate([t.excess for t in train]),
        "test": test_eval,
        "cohort_b_PRIMARY": evaluate([t.excess for t in test_b]) if cohort_b else None,
        "cohort_a_restated": evaluate([t.excess for t in test_a]) if cohort_b else None,
        "cohort_note": (
            "Spec 15.4: cohort B alone is the ONLY decisive result. Combined "
            "('test') is contaminated by the 2026-09-22 look and cannot clear "
            "or fail anything. Cohort A is restated for completeness."
        ) if cohort_b else None,
        "buy_and_hold": {
            "symbol": cfg.benchmark,
            "window_start": held[0].date.isoformat() if held else None,
            "total_return": buy_hold,
            "strategy_total_return": strat_total - 1.0,
        },
        "data_warnings": [
            {"symbol": i.symbol, "date": str(i.date), "kind": i.kind,
             "detail": i.detail} for i in all_issues
        ],
        "known_limitations": {
            "survivorship_bias": (
                "The whitelist is 12 names that are large and liquid TODAY. "
                "Backtesting them over 2014+ inflates returns because their "
                "survival and growth is known in advance. Spec 11.3: "
                "disclosed, not corrected."),
            "statistical_power": (
                "Spec 7.5: at this sample size only a large edge is "
                "detectable. A negative verdict means 'no large edge "
                "detectable', not 'no edge exists'."),
            "entry_conservatism": (
                "Spec 6.1: entry is the T+1 close. The tradeable 09:45-16:00 "
                "window on T+1 is forgone because daily bars cannot model a "
                "mid-session fill, so returns understate the live system."),
        },
    }
    stem = "expansion" if args.expansion else "backtest"
    write_report(Path("reports") / f"{stem}-{dt.date.today()}.json", payload)

    if cohort_b:
        for label, block, weight in (
            ("COHORT B  (PRIMARY, never examined)", payload["cohort_b_PRIMARY"], "DECISIVE"),
            ("COHORT A  (restated, already seen)", payload["cohort_a_restated"], "not decisive"),
            ("COMBINED  (contaminated)", payload["test"], "not decisive"),
        ):
            print(f"\n{label}  [{weight}]")
            print(f"  n={block['n']:3d}  mean={block['mean']:+.4%}  "
                  f"t={block['t_stat']:+.2f}  hit={block['hit_rate']:.1%}  "
                  f"maxDD={block['max_drawdown']:.1%}")
            print(f"  t>=2.0:{block['passes_t']}  hit>50%:{block['passes_hit']}  "
                  f"dd<=25%:{block['passes_dd']}  ->  {block['passes_all']}")
        pb = payload["cohort_b_PRIMARY"]
        print(f"\nVERDICT (cohort B only): "
              f"{'EDGE DETECTED' if pb['passes_all'] else 'NO EDGE'}")
        print("Spec 15.6: a marginal pass here does NOT establish an edge.")
        return 0

    r = payload["test"]
    print(f"\nEvents: {len(events)}  Trades: {len(trades)}  "
          f"Train: {len(train)}  Test: {r['n']}")
    print(f"TEST  mean excess {r['mean']:+.4%}  t={r['t_stat']:.2f}  "
          f"hit={r['hit_rate']:.1%}  maxDD={r['max_drawdown']:.1%}")
    bh = payload["buy_and_hold"]
    print(f"Strategy total {bh['strategy_total_return']:+.2%} vs "
          f"buy-and-hold {bh['symbol']} {bh['total_return']:+.2%}")
    print(f"\nVERDICT: {'EDGE DETECTED' if r['passes_all'] else 'NO EDGE'}")
    if not r["passes_all"]:
        failed = [k for k in ("passes_t", "passes_hit", "passes_dd") if not r[k]]
        print(f"failed criteria: {', '.join(failed)}")
        print("Per spec 7.3, do NOT adjust parameters and re-run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
