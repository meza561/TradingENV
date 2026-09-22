"""Cross-check the primary price source against an independent one.

Primary is Yahoo (bulk, keyless). The reference is the Robinhood MCP, which
is genuinely independent: different vendor, different adjustment pipeline.

An earlier version used Stooq, which now serves a JavaScript browser
challenge instead of CSV -- its tests passed only because they injected
fake CSV, so the check never worked against the live source.
"""
import datetime as dt

from ebot.types import Bar
from ebot.validate_bars import BarIssue

DEFAULT_TOL = 0.005


def crosscheck_window(bars: list[Bar], ref_bars: list[Bar],
                      dates: list[dt.date],
                      tol: float = DEFAULT_TOL) -> list[BarIssue]:
    """Compare closes on specific dates. 0.5% absorbs dividend-adjustment
    differences between vendors while catching a missed split (~50%+)."""
    ours = {b.date: b for b in bars}
    theirs = {b.date: b for b in ref_bars}
    issues = []
    for d in dates:
        a, b = ours.get(d), theirs.get(d)
        if a is None:
            continue
        if b is None:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                                   "date absent from reference source"))
            continue
        if b.close <= 0:
            continue
        diff = abs(a.close / b.close - 1.0)
        if diff > tol:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                f"close {a.close} vs reference {b.close} ({diff:.1%} apart)"))
    return issues


def compare_series(bars: list[Bar], ref_bars: list[Bar],
                   tol: float = DEFAULT_TOL) -> tuple[list[BarIssue], dict]:
    """Compare every overlapping date. Returns (issues, stats)."""
    overlap = sorted({b.date for b in bars} & {b.date for b in ref_bars})
    issues = crosscheck_window(bars, ref_bars, overlap, tol)
    ours = {b.date: b for b in bars}
    theirs = {b.date: b for b in ref_bars}
    diffs = [abs(ours[d].close / theirs[d].close - 1.0)
             for d in overlap if theirs[d].close > 0]
    stats = {
        "compared": len(overlap),
        "mismatches": len(issues),
        "max_diff": max(diffs) if diffs else 0.0,
        "ours_only": len({b.date for b in bars} - {b.date for b in ref_bars}),
        "ref_only": len({b.date for b in ref_bars} - {b.date for b in bars}),
    }
    return issues, stats
