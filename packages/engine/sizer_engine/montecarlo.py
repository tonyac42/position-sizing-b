"""Monte Carlo drawdown paths and losing-streak arithmetic.

Deterministic: the seed defaults to a value derived from the input hash, so
identical requests produce identical diagnostics on every interface.
"""
from __future__ import annotations

import math
import random

from .config import EngineConfig
from .schemas import DrawdownPaths, LosingStreaks, Outcome


def _downsample(path: list[float], max_points: int) -> list[float]:
    if len(path) <= max_points:
        return path
    step = (len(path) - 1) / (max_points - 1)
    return [path[round(i * step)] for i in range(max_points)]


def _max_drawdown(path: list[float]) -> float:
    peak, worst = path[0], 0.0
    for v in path:
        peak = max(peak, v)
        worst = max(worst, 1.0 - v / peak)
    return worst


def simulate_drawdown_paths(
    outcomes: list[Outcome],
    risk_fraction: float,
    seed: int,
    cfg: EngineConfig,
) -> DrawdownPaths:
    mc = cfg.montecarlo
    rng = random.Random(seed)
    probs = [o.probability for o in outcomes]
    rs = [o.r for o in outcomes]
    paths: list[list[float]] = []
    for _ in range(mc.n_paths):
        equity = 1.0
        path = [equity]
        for _ in range(mc.n_trades):
            r = rng.choices(rs, weights=probs, k=1)[0]
            equity = max(1e-9, equity * (1.0 + risk_fraction * r))
            path.append(equity)
        paths.append(path)

    paths.sort(key=lambda p: p[-1])
    idx5 = max(0, int(0.05 * len(paths)) - 1)
    idx1 = max(0, int(0.01 * len(paths)) - 1)
    idx50 = len(paths) // 2
    dd_over_20 = sum(1 for p in paths if _max_drawdown(p) > 0.20) / len(paths)

    return DrawdownPaths(
        n_paths=mc.n_paths,
        n_trades=mc.n_trades,
        seed=seed,
        median_final_equity=paths[idx50][-1],
        worst_5pct_path=_downsample(paths[idx5], mc.max_path_points),
        worst_1pct_path=_downsample(paths[idx1], mc.max_path_points),
        median_path=_downsample(paths[idx50], mc.max_path_points),
        worst_5pct_max_drawdown=_max_drawdown(paths[idx5]),
        worst_1pct_max_drawdown=_max_drawdown(paths[idx1]),
        prob_drawdown_over_20pct=dd_over_20,
    )


def losing_streaks(
    win_probability: float, risk_fraction: float, n_trades: int
) -> LosingStreaks:
    """Streak arithmetic at the recommended size.

    Expected longest losing streak over n trades ~ ln(n) / ln(1/q) for loss
    probability q. P(a 10-loss streak appears within n trades) uses the
    standard (1 - (1 - q^10)^(n-9)) approximation.
    """
    q = max(1e-9, min(1.0 - 1e-9, 1.0 - win_probability))
    expected = max(1, round(math.log(max(n_trades, 2)) / math.log(1.0 / q)))
    p10 = 1.0 - (1.0 - q ** 10) ** max(1, n_trades - 9)
    equity_after = (1.0 - risk_fraction) ** expected
    return LosingStreaks(
        expected_max_streak=expected,
        prob_streak_10=p10,
        equity_after_expected_streak_pct=equity_after,
        note=(f"over {n_trades} trades expect a worst losing streak of ~{expected}; "
              f"at {risk_fraction:.2%} risk per trade that leaves {equity_after:.1%} "
              f"of bankroll; P(10 straight losses) = {p10:.1%}"),
    )
