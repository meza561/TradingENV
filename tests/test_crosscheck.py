import datetime as dt
from ebot.crosscheck import crosscheck_window, compare_series
from ebot.types import Bar


def series(closes, start=dt.date(2020, 1, 2), symbol="X"):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append(Bar(symbol, d, c, c, c, c, 1000))
        d += dt.timedelta(days=1)
    return out


def test_matching_prices_produce_no_issues():
    a = series([100.0, 101.0, 102.0])
    assert crosscheck_window(a, list(a), [b.date for b in a]) == []


def test_small_difference_within_tolerance_ok():
    a = series([100.0, 101.0])
    b = [Bar("X", x.date, x.open, x.high, x.low, x.close * 1.002, x.volume)
         for x in a]
    assert crosscheck_window(a, b, [x.date for x in a]) == []


def test_missed_split_is_caught():
    a = series([100.0, 101.0])
    b = [Bar("X", x.date, x.open, x.high, x.low, x.close * 4.0, x.volume)
         for x in a]
    issues = crosscheck_window(a, b, [x.date for x in a])
    assert len(issues) == 2 and all(i.kind == "crosscheck" for i in issues)


def test_date_missing_from_reference_is_reported():
    a = series([100.0])
    issues = crosscheck_window(a, [], [a[0].date])
    assert issues and "absent from reference" in issues[0].detail


def test_date_missing_from_ours_is_skipped():
    b = series([100.0])
    assert crosscheck_window([], b, [b[0].date]) == []


def test_compare_series_counts_overlap_and_exclusives():
    a = series([100.0, 101.0, 102.0])
    b = series([100.0, 101.0])
    issues, stats = compare_series(a, b)
    assert issues == []
    assert stats["compared"] == 2
    assert stats["ours_only"] == 1 and stats["ref_only"] == 0


def test_compare_series_reports_max_diff():
    a = series([100.0, 100.0])
    b = [Bar("X", x.date, x.open, x.high, x.low, x.close * 1.01, x.volume)
         for x in a]
    issues, stats = compare_series(a, b)
    assert len(issues) == 2
    assert abs(stats["max_diff"] - 0.00990099) < 1e-6


def test_compare_series_empty_inputs():
    issues, stats = compare_series([], [])
    assert issues == [] and stats["compared"] == 0 and stats["max_diff"] == 0.0
