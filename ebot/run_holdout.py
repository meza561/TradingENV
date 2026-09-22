"""Spec 16 stage 2: ONE hypothesis, ONE run, on the never-examined window."""
import argparse
import datetime as dt
import sys
from pathlib import Path

from ebot.config import load_config
from ebot.edgar import fetch_events
from ebot.prices import load_bars
from ebot.run_backtest import write_report
from ebot.search import HYPOTHESES, run_hypothesis
from ebot.stats import evaluate
from ebot.validate_bars import validate_bars, FATAL_KINDS

HOLDOUT_START = dt.date(2004, 1, 1)
HOLDOUT_END = dt.date(2014, 1, 2)      # exclusive; 2014+ was already examined


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = ap.parse_args(argv)
    cfg = load_config(args.config).model_copy(update={"price_floor": HOLDOUT_START})
    h = next((x for x in HYPOTHESES if x.name == args.hypothesis), None)
    if h is None:
        print(f"unknown hypothesis {args.hypothesis}", file=sys.stderr)
        return 1

    names = list(cfg.whitelist) + list(cfg.expansion)
    bars = {s: load_bars(s, cfg) for s in names + [cfg.benchmark]}
    issues = [i for s in bars for i in validate_bars(bars[s], cfg)]
    fatal = [i for i in issues if i.kind in FATAL_KINDS]
    if fatal:
        for i in fatal[:10]:
            print(f"  FATAL [{i.kind}] {i.symbol} {i.date}: {i.detail}", file=sys.stderr)
        print(f"{len(fatal)} fatal data issues; refusing to run.", file=sys.stderr)
        return 2

    events = []
    for t in names:
        events.extend(fetch_events(t, cfg))
    trades = [t for t in run_hypothesis(events, bars, bars[cfg.benchmark], cfg, h)
              if HOLDOUT_START <= t.entry_date < HOLDOUT_END]
    ev = evaluate([t.excess for t in trades])

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stage": "spec-16 holdout (never examined)",
        "hypothesis": h.name,
        "window": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
        "result": ev,
        "n_events_in_window": len(events),
        "data_warnings": len(issues),
        "known_bias": ("Spec 16.4: H4 enters 5 sessions before the filing using "
                       "the actual acceptance date, not the previously announced "
                       "date. Bias favours H4. Disclosed, not corrected."),
    }
    write_report(Path("reports") / f"holdout-{h.name}-{dt.date.today()}.json", payload)

    print(f"\nHOLDOUT {h.name}  {HOLDOUT_START} .. {HOLDOUT_END}  (never examined)")
    print(f"  n={ev['n']}  mean={ev['mean']:+.4%}  t={ev['t_stat']:+.2f}  "
          f"hit={ev['hit_rate']:.1%}  maxDD={ev['max_drawdown']:.1%}")
    print(f"  t>=2.0:{ev['passes_t']}  hit>50%:{ev['passes_hit']}  "
          f"dd<=25%:{ev['passes_dd']}")
    print(f"\nVERDICT: {'EDGE DETECTED' if ev['passes_all'] else 'NO EDGE'}")
    print(f"{len(issues)} non-fatal data warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
