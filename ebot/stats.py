import math
from statistics import fmean, stdev

T_THRESHOLD, HIT_THRESHOLD, DD_THRESHOLD = 2.0, 0.50, 0.25


def t_stat(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    s = stdev(xs)
    if s == 0.0:
        return 0.0
    return fmean(xs) / (s / math.sqrt(len(xs)))


def hit_rate(xs: list[float]) -> float:
    return sum(1 for x in xs if x > 0) / len(xs) if xs else 0.0


def max_drawdown(xs: list[float]) -> float:
    """Max peak-to-trough decline of the compounded equity curve."""
    equity, peak, worst = 1.0, 1.0, 0.0
    for x in xs:
        equity *= (1.0 + x)
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def evaluate(xs: list[float]) -> dict:
    """Spec 7.4: all three criteria required."""
    t, h, d = t_stat(xs), hit_rate(xs), max_drawdown(xs)
    passes = {"passes_t": t >= T_THRESHOLD,
              "passes_hit": h > HIT_THRESHOLD,
              "passes_dd": d <= DD_THRESHOLD}
    return {"n": len(xs), "mean": fmean(xs) if xs else 0.0,
            "t_stat": t, "hit_rate": h, "max_drawdown": d,
            **passes, "passes_all": bool(xs) and all(passes.values())}
