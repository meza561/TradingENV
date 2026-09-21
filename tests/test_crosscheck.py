import datetime as dt
from ebot.crosscheck import parse_stooq_csv, crosscheck_window, fetch_stooq
from ebot.types import Bar

CSV = """Date,Open,High,Low,Close,Volume
2020-01-02,100.0,101.0,99.0,100.5,1000000
2020-01-03,100.5,102.0,100.0,101.0,1100000
"""


def test_parses_stooq_csv():
    bars = parse_stooq_csv(CSV, "X")
    assert len(bars) == 2
    assert bars[0].date == dt.date(2020, 1, 2) and bars[0].close == 100.5
    assert bars[1].volume == 1100000


def test_parse_ignores_blank_and_malformed_rows():
    assert len(parse_stooq_csv(CSV + "\n\nN/A,N/A,N/A,N/A,N/A,N/A\n", "X")) == 2


def test_matching_prices_produce_no_issues():
    ours = parse_stooq_csv(CSV, "X")
    assert crosscheck_window(ours, list(ours), [dt.date(2020, 1, 2)]) == []


def test_small_difference_within_tolerance_ok():
    ours = parse_stooq_csv(CSV, "X")
    theirs = [Bar("X", b.date, b.open, b.high, b.low, b.close * 1.002, b.volume)
              for b in ours]
    assert crosscheck_window(ours, theirs, [dt.date(2020, 1, 2)]) == []


def test_missed_split_is_caught():
    ours = parse_stooq_csv(CSV, "X")
    theirs = [Bar("X", b.date, b.open, b.high, b.low, b.close * 4.0, b.volume)
              for b in ours]
    issues = crosscheck_window(ours, theirs, [dt.date(2020, 1, 2)])
    assert len(issues) == 1 and issues[0].kind == "crosscheck"


def test_date_missing_from_reference_is_reported():
    ours = parse_stooq_csv(CSV, "X")
    issues = crosscheck_window(ours, [], [dt.date(2020, 1, 2)])
    assert issues and issues[0].kind == "crosscheck"


def test_date_missing_from_ours_is_skipped():
    theirs = parse_stooq_csv(CSV, "X")
    assert crosscheck_window([], theirs, [dt.date(2020, 1, 2)]) == []


def test_fetch_stooq_builds_expected_url():
    seen = {}

    def fake(url):
        seen["url"] = url
        return CSV

    fetch_stooq("AAPL", dt.date(2020, 1, 1), dt.date(2020, 12, 31), fetch=fake)
    assert "aapl.us" in seen["url"]
    assert "d1=20200101" in seen["url"] and "d2=20201231" in seen["url"]
