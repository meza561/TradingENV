from ebot.stats import t_stat, hit_rate, max_drawdown, evaluate


def test_t_stat_zero_for_symmetric_data():
    assert abs(t_stat([-1.0, 1.0, -1.0, 1.0])) < 1e-9


def test_t_stat_positive_for_consistent_gains():
    assert t_stat([0.01, 0.012, 0.009, 0.011, 0.010]) > 2.0


def test_t_stat_needs_two_points():
    assert t_stat([0.01]) == 0.0
    assert t_stat([]) == 0.0


def test_t_stat_zero_variance_returns_zero():
    assert t_stat([0.01, 0.01, 0.01]) == 0.0


def test_hit_rate():
    assert hit_rate([1.0, -1.0, 1.0, 1.0]) == 0.75
    assert hit_rate([]) == 0.0


def test_hit_rate_excludes_exact_zero():
    assert hit_rate([0.0, 1.0]) == 0.5


def test_max_drawdown_on_compounded_equity():
    assert abs(max_drawdown([0.10, -0.50, 0.10]) - 0.50) < 1e-9


def test_max_drawdown_zero_when_monotonic():
    assert max_drawdown([0.01, 0.01, 0.01]) == 0.0


def test_max_drawdown_empty():
    assert max_drawdown([]) == 0.0


def test_evaluate_fails_when_any_criterion_fails():
    assert evaluate([0.01, -0.02, 0.03, -0.04])["passes_all"] is False


def test_evaluate_reports_all_three_flags():
    r = evaluate([0.01] * 10)
    assert {"passes_t", "passes_hit", "passes_dd", "passes_all"} <= set(r)
    assert r["n"] == 10


def test_evaluate_on_empty_does_not_pass():
    r = evaluate([])
    assert r["n"] == 0 and r["passes_all"] is False
