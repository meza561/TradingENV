"""Populate the price cache. Parallel across (symbol, year) pairs.

A serial run is ~1m43s x 169 pairs ~= 4.8h. Four workers brings it near 1.2h.
Safe to interrupt and re-run: cached years are skipped.
"""
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ebot.config import load_config
from ebot.prices import fetch_year_retrying, _cached_years

WORKERS = 3


def main():
    cfg = load_config(Path("config.yaml"))
    symbols = list(cfg.whitelist) + [cfg.benchmark]
    this_year = dt.date.today().year
    todo = []
    for s in symbols:
        have = _cached_years(s, cfg)
        for y in range(cfg.price_floor.year, this_year + 1):
            if y in have and y != this_year:
                continue
            todo.append((s, y))
    print(f"{len(todo)} (symbol, year) pairs to fetch, {WORKERS} workers",
          flush=True)
    t0, done, failed = time.time(), 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_year_retrying, s, y, cfg): (s, y) for s, y in todo}
        for f in as_completed(futs):
            s, y = futs[f]
            done += 1
            el = time.time() - t0
            try:
                n = len(f.result())
                print(f"[{done}/{len(todo)}] {s} {y}: {n} bars "
                      f"({el/60:.1f}m elapsed, ~{(el/done)*(len(todo)-done)/60:.0f}m left)",
                      flush=True)
            except Exception as e:
                failed.append((s, y, repr(e)[:160]))
                print(f"[{done}/{len(todo)}] {s} {y}: FAILED {e}", flush=True)
    print(f"\ndone in {(time.time()-t0)/60:.1f}m; {len(failed)} failures")
    for s, y, e in failed:
        print(f"  {s} {y}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
