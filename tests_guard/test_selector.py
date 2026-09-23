import datetime as dt
import math
from guard.optconfig import OptionConfig
from guard.selector import select, spread_pct_of_mid, Candidate

CFG = OptionConfig(account_number="1")      # delta .30+/-.15, spread<=15%, OI>=100
TODAY = dt.date(2026, 9, 23)


def row(**kw):
    """bid tracks ask at a ~4% spread unless explicitly overridden -- setting
    a low ask while leaving bid high makes a crossed book, which the selector
    rightly rejects."""
    d = dict(option_id="o1", underlying="XLU", option_type="call", strike=41.0,
             expiration=(TODAY + dt.timedelta(days=38)).isoformat(),
             ask=0.74, delta=0.30, open_interest=238)
    d.update(kw)
    if "bid" not in d and d.get("ask"):
        d["bid"] = round(d["ask"] * 0.96, 2)
    return d


def only(rows, budget=50.0):
    return select(rows, CFG, budget, TODAY)


def test_happy_candidate_passes():
    ok, bad = only([row()], budget=200.0)
    assert len(ok) == 1 and bad == []
    assert ok[0].cost_usd == 74.0


def test_delta_exactly_at_tolerance_is_included():
    """0.45 - 0.30 == 0.15000000000000002 in binary float."""
    ok, bad = only([row(delta=0.45, ask=0.40)])
    assert len(ok) == 1, bad


def test_cost_over_budget_rejected():
    ok, bad = only([row(ask=0.74)], budget=50.0)
    assert ok == [] and "budget" in bad[0][1]


def test_cost_within_budget_accepted():
    ok, bad = only([row(ask=0.45)], budget=50.0)
    assert len(ok) == 1, bad


def test_non_whitelisted_underlying_rejected():
    ok, bad = only([row(underlying="TSLA")])
    assert ok == [] and "not whitelisted" in bad[0][1]


def test_dte_window_enforced():
    for days, should in ((20, False), (30, True), (45, True), (60, False)):
        r = row(expiration=(TODAY + dt.timedelta(days=days)).isoformat(), ask=0.40)
        ok, bad = only([r])
        assert bool(ok) is should, (days, bad)


def test_delta_band_enforced():
    for d, should in ((0.10, False), (0.16, True), (0.45, True), (0.60, False)):
        ok, bad = only([row(delta=d, ask=0.40)])
        assert bool(ok) is should, (d, bad)


def test_negative_delta_puts_use_absolute_value():
    ok, bad = only([row(delta=-0.30, option_type="put", ask=0.40)])
    assert len(ok) == 1, bad


def test_low_open_interest_rejected():
    ok, bad = only([row(open_interest=50, ask=0.40)])
    assert ok == [] and "open interest" in bad[0][1]


def test_wide_spread_rejected():
    """The XLF 56 call observed at 0.45/0.94 - a 70% spread."""
    ok, bad = only([row(bid=0.45, ask=0.94)], budget=200.0)
    assert ok == [] and "spread" in bad[0][1]


def test_crossed_or_zero_book_is_unevaluable_and_rejected():
    for bid, ask in ((0.0, 0.50), (0.50, 0.0), (0.90, 0.40)):
        ok, bad = only([row(bid=bid, ask=ask)], budget=200.0)
        assert ok == [] and "unevaluable" in bad[0][1], (bid, ask)


def test_missing_delta_rejected():
    ok, bad = only([row(delta=None, ask=0.40)])
    assert ok == [] and "missing delta" in bad[0][1]


def test_untradable_rejected():
    ok, bad = only([row(state="inactive", ask=0.40)])
    assert ok == [] and "not tradable" in bad[0][1]


def test_unparseable_expiration_rejected():
    ok, bad = only([row(expiration="soon", ask=0.40)])
    assert ok == [] and "expiration" in bad[0][1]


def test_sorted_by_spread_then_delta_distance():
    wide = row(option_id="wide", bid=0.60, ask=0.68)
    tight = row(option_id="tight", bid=0.70, ask=0.72)
    ok, _ = select([wide, tight], CFG, 200.0, TODAY)
    assert [c.option_id for c in ok][0] == "tight"


def test_every_rejection_is_explained():
    rows = [row(underlying="TSLA"), row(open_interest=1, ask=0.40),
            row(delta=0.90, ask=0.40)]
    ok, bad = only(rows)
    assert ok == [] and len(bad) == 3
    assert all(isinstance(r, str) and r for _, r in bad)


def test_spread_helper():
    assert spread_pct_of_mid(0.70, 0.72) < 3.0
    assert math.isinf(spread_pct_of_mid(0.0, 0.5))
    assert math.isinf(spread_pct_of_mid(float("nan"), 0.5))
