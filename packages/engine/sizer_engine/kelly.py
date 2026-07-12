"""Layer 1: Kelly solvers.

All solvers work in R-space: the "stake" is the amount lost when the trade's
defined risk (stop distance or structural max loss) is fully realized, and the
returned f* is the fraction of bankroll to place at that defined risk. An
outcome distribution's r values are returns per unit staked, so r = -1.0 is a
full stop-out.

Three solvers:
  binary_kelly       — closed form f* = (bp - q)/b
  continuous_kelly   — mean/variance approximation for near-normal streams
  generalized_kelly  — numerical maximization of E[log(1 + f x)] over an
                       arbitrary discrete distribution (required when skew
                       breaks the mean/variance approximation)
"""
from __future__ import annotations

import math

from .schemas import Outcome


def binary_kelly(p: float, b: float) -> float:
    """Closed-form Kelly for a win-probability-p, win-b-lose-1 bet.

    f* = (b*p - q) / b. Returns 0 when the edge is non-positive.
    """
    if not 0 < p < 1 or b <= 0:
        return 0.0
    q = 1.0 - p
    f = (b * p - q) / b
    return max(0.0, f)


def continuous_kelly(mean: float, variance: float) -> float:
    """Mean/variance Kelly approximation: f* ~= mu / sigma^2.

    Appropriate for approximately normal per-trade return streams (shortterm
    day trading, continuous trading with stops). mean/variance are per unit
    staked (R-space).
    """
    if variance <= 0:
        return 0.0
    return max(0.0, mean / variance)


def _log_growth(f: float, outcomes: list[Outcome]) -> float:
    return sum(o.probability * math.log(1.0 + f * o.r) for o in outcomes)


def generalized_kelly(outcomes: list[Outcome], tol: float = 1e-10) -> float:
    """Numerically maximize E[log(1 + f*X)] over a discrete distribution.

    Golden-section search on [0, f_max) where f_max = 1/|worst loss| (the
    no-ruin boundary). E[log(1+fX)] is strictly concave in f, so the search
    converges to the global maximum. Returns 0 when EV <= 0 (the maximizer
    is at or below the boundary).
    """
    if not outcomes:
        return 0.0
    ev = sum(o.probability * o.r for o in outcomes)
    if ev <= 0:
        return 0.0
    worst = min(o.r for o in outcomes)
    if worst >= 0:
        # No losing branch: log growth increases without bound; cap at full
        # bankroll. Callers should treat this as "risk-free by claim" and let
        # shrinkage/CI logic apply the skepticism.
        return 1.0
    f_max = (1.0 / -worst) * (1.0 - 1e-9)

    lo, hi = 0.0, f_max
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    c = hi - invphi * (hi - lo)
    d = lo + invphi * (hi - lo)
    fc, fd = _log_growth(c, outcomes), _log_growth(d, outcomes)
    for _ in range(200):
        if hi - lo < tol:
            break
        if fc > fd:
            hi, d, fd = d, c, fc
            c = hi - invphi * (hi - lo)
            fc = _log_growth(c, outcomes)
        else:
            lo, c, fc = c, d, fd
            d = lo + invphi * (hi - lo)
            fd = _log_growth(d, outcomes)
    f = (lo + hi) / 2.0
    # Guard: if growth at f is not better than not betting, don't bet.
    if _log_growth(f, outcomes) <= 0:
        return 0.0
    return f


def kelly_fraction_from_drawdown_tolerance(
    max_drawdown: float, breach_probability: float = 0.10
) -> float:
    """Map a tolerable drawdown to a Kelly fraction.

    Approximation used (documented in docs/kelly-fraction.md): for continuous
    Kelly betting at fraction c of full Kelly, wealth is a geometric Brownian
    motion and the probability of EVER drawing down to a fraction x of the
    high-water mark is approximately

        P(DD >= D) = x^(2/c - 1),   x = 1 - D

    (Thorp, "The Kelly Criterion in Blackjack, Sports Betting and the Stock
    Market"). Solving for c with a target breach probability q:

        c = 2 / (1 + ln(q) / ln(x))

    Defaults: q = 10% chance of ever exceeding the stated drawdown. The result
    is clamped by the caller to the configured [min, max] Kelly fraction band.
    """
    if not 0 < max_drawdown < 1:
        raise ValueError("max_drawdown must be in (0, 1)")
    x = 1.0 - max_drawdown
    c = 2.0 / (1.0 + math.log(breach_probability) / math.log(x))
    return max(0.01, min(1.0, c))
