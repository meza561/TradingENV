"""Spec 16 stage 1: test all k hypotheses on already-examined data."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from ebot.config import load_config
from ebot.edgar import fetch_events
from ebot.prices import load_bars
from ebot.run_backtest import write_report
from ebot.search import HYPOTHESES, SEARCH_T, run_hypothesis
from ebot.stats import evaluate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    names = list(cfg.whitelist) + list(cfg.expansion)
    bars = {s: load_bars(s, cfg) for s in names + [cfg.benchmark]}
    missing = [s for s, b in bars.items() if not b]
    if missing:
        print(f"no cached bars for {missing}", file=sys.stderr)
        return 1

    events = []
    for t in names:
        events.extend(fetch_events(t, cfg))
    print(f"{len(names)} names, {len(events)} events, "
          f"search window < {cfg.train_test_split}\n", file=sys.stderr)

    results, rows = {}, []
    for h in HYPOTHESES:
        trades = [t for t in run_hypothesis(events, bars, bars[cfg.benchmark], cfg, h)
                  if t.entry_date < cfg.train_test_split]
        ev = evaluate([t.excess for t in trades])
        ev["advances"] = ev["t_stat"] >= SEARCH_T
        results[h.name] = ev
        rows.append((h.name, ev))
        print(f"  {h.name}  n={ev['n']:4d}  mean={ev['mean']:+.4%}  "
              f"t={ev['t_stat']:+.2f}  hit={ev['hit_rate']:.1%}  "
              f"{'ADVANCES' if ev['advances'] else '-'}")

    advancing = [n for n, e in rows if e["advances"]]
    best = max(rows, key=lambda r: r[1]["t_stat"])
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stage": "spec-16 search (2014 to train_test_split)",
        "bar": {"t_threshold": SEARCH_T, "reason": "Bonferroni p<0.05/5"},
        "results": results,
        "best": best[0],
        "advancing": advancing,
        "note": ("Spec 16.2: at most ONE advances to the never-examined "
                 "2004-2013 holdout. None advancing is a complete result "
                 "(16.6)."),
    }
    write_report(Path("reports") / f"search-{dt.date.today()}.json", payload)

    print(f"\nbar: t >= {SEARCH_T} (Bonferroni, k=5)")
    print(f"best: {best[0]} at t={best[1]['t_stat']:+.2f}")
    if advancing:
        print(f"ADVANCING: {advancing}  -> one run on the 2004-2013 holdout")
    else:
        print("NONE ADVANCE. Holdout stays untouched. Spec 16.6: complete result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
