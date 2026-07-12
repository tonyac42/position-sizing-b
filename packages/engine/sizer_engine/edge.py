"""Layer 0: edge normalization, shrinkage, and confidence intervals.

Everything downstream depends on the working edge produced here. The claimed
edge arrives in one of several formats; it is normalized to a canonical
internal form (a binary-equivalent (p, b) pair plus a discrete outcome
distribution), then shrunk according to how trustworthy its source is, and
annotated with a confidence interval whose width drives exploration gates and
the refusal path.

Shrinkage mechanics
-------------------
For (p, b) edges we shrink the win probability toward the breakeven
probability p_be = 1/(1+b), which scales expectancy exactly:

    p' = p_be + d * (p - p_be)   =>   E'[R] = d * E[R]

For full outcome distributions we translate every outcome by the removed
expectancy (r_i' = r_i - (1-d) * EV), which preserves the distribution's
shape (skew, tails) while scaling its mean — important for lottery/premium
where the shape is the whole point.

For prediction-type trades the shrinkage target is the market price rather
than a generic discount: p' = (1-w) * p_user + w * p_market.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import EngineConfig
from .schemas import (
    ConfidenceInterval,
    EdgeSource,
    Outcome,
    SizeRequest,
    TradeType,
    WorkingEdge,
)


@dataclass
class NormalizedEdge:
    """Canonical internal edge representation, pre-shrinkage."""
    p: float | None            # binary-equivalent win probability
    b: float | None            # binary-equivalent payoff ratio (avg win / avg loss, R)
    outcomes: list[Outcome]    # discrete distribution in R-multiples
    expectancy_r: float
    notes: list[str] = field(default_factory=list)


@dataclass
class EdgeResult:
    """Layer 0 output: working edge + provenance."""
    working: WorkingEdge
    outcomes: list[Outcome]            # post-shrinkage distribution
    p: float | None
    b: float | None
    effective_sample_size: int
    forced_exploration: bool
    notes: list[str] = field(default_factory=list)


def _two_point(p: float, b: float) -> list[Outcome]:
    return [Outcome(probability=p, r=b), Outcome(probability=1.0 - p, r=-1.0)]


def normalize_edge(req: SizeRequest) -> NormalizedEdge:
    """Normalize any accepted edge format to (p, b) + outcome distribution."""
    e = req.edge_estimate
    notes: list[str] = []

    if e.outcomes:
        ev = sum(o.probability * o.r for o in e.outcomes)
        losses = [o for o in e.outcomes if o.r < 0]
        wins = [o for o in e.outcomes if o.r > 0]
        p = sum(o.probability for o in wins) or None
        b = None
        if p and losses:
            avg_win = sum(o.probability * o.r for o in wins) / p
            p_loss = sum(o.probability for o in losses)
            avg_loss = -sum(o.probability * o.r for o in losses) / p_loss
            b = avg_win / avg_loss if avg_loss > 0 else None
        return NormalizedEdge(p=p, b=b, outcomes=list(e.outcomes), expectancy_r=ev, notes=notes)

    if e.win_probability is not None:
        p = e.win_probability
        b = e.payoff_ratio
        if b is None:
            # For binary structures the payoff ratio is structural: buying a
            # binary contract at price c pays (1-c)/c per unit risked.
            price = req.market_price or req.trade.entry_price
            if req.trade.payoff_structure and req.trade.payoff_structure.value == "binary" \
                    and price is not None and 0 < price < 1:
                b = (1.0 - price) / price
                notes.append(f"payoff_ratio derived from binary contract price {price:.2f}: b={b:.3f}")
            else:
                b = 1.0
                notes.append("payoff_ratio absent; defaulted to 1.0 (even money)")
        ev = p * b - (1.0 - p)
        return NormalizedEdge(p=p, b=b, outcomes=_two_point(p, b), expectancy_r=ev, notes=notes)

    # expectancy_r format
    ev = float(e.expectancy_r)  # validated non-None by schema
    if e.win_rate is not None:
        p = e.win_rate
        # E = p(1+b) - 1  =>  b = (E + 1)/p - 1
        b = (ev + 1.0) / p - 1.0
        if b <= 0:
            raise ValueError(
                f"expectancy_r={ev} with win_rate={p} implies non-positive payoff ratio"
            )
        return NormalizedEdge(p=p, b=b, outcomes=_two_point(p, b), expectancy_r=ev, notes=notes)
    # Expectancy with no shape information: assume an even-money-equivalent
    # two-point distribution around the stated EV.
    p = min(0.99, max(0.01, (ev + 1.0) / 2.0))
    notes.append("edge given as bare expectancy; assumed symmetric two-point distribution")
    return NormalizedEdge(p=p, b=1.0, outcomes=_two_point(p, 1.0), expectancy_r=ev, notes=notes)


def _shrink_p_toward_breakeven(p: float, b: float, discount: float) -> float:
    p_be = 1.0 / (1.0 + b)
    return p_be + discount * (p - p_be)


def _translate_outcomes(outcomes: list[Outcome], delta: float) -> list[Outcome]:
    return [Outcome(probability=o.probability, r=o.r + delta) for o in outcomes]


def _realized_expectancy(req: SizeRequest) -> tuple[float | None, int]:
    rr = req.realized_results
    if rr is None or rr.n_trades <= 0:
        return None, 0
    if rr.expectancy_r is not None:
        base = rr.expectancy_r
    elif rr.win_rate is not None and rr.avg_win_r is not None and rr.avg_loss_r is not None:
        base = rr.win_rate * rr.avg_win_r - (1.0 - rr.win_rate) * rr.avg_loss_r
    else:
        return None, rr.n_trades
    # Recency weighting: edges decay; if a recent window is supplied, weight it
    # 2:1 against the full-history figure.
    if rr.recent_expectancy_r is not None and (rr.recent_n_trades or 0) >= 10:
        base = (2.0 * rr.recent_expectancy_r + base) / 3.0
    return base, rr.n_trades


def shrink_edge(req: SizeRequest, trade_type: TradeType, cfg: EngineConfig) -> EdgeResult:
    """Apply source-dependent shrinkage and produce the working edge + CI."""
    s = cfg.shrinkage
    norm = normalize_edge(req)
    notes = list(norm.notes)
    raw_ev = norm.expectancy_r
    p, b = norm.p, norm.b
    outcomes = norm.outcomes
    n = max(req.sample_size, req.realized_results.n_trades if req.realized_results else 0)
    forced_exploration = False
    label = ""

    src = req.edge_source

    if trade_type == TradeType.prediction and req.market_price is not None \
            and p is not None and src != EdgeSource.exact_math:
        # Prediction special rule: shrink toward the market price. Weight
        # depends on calibration evidence, overriding the generic discounts.
        if req.user_calibration_data:
            w = s.prediction_calibrated_market_weight
            label = f"prediction: shrunk {w:.0%} toward market (calibration data on file)"
        elif src == EdgeSource.guess and not req.edge_justification_structured:
            w = s.prediction_unstructured_market_weight
            label = f"prediction: shrunk {w:.0%} toward market (unstructured guess)"
        else:
            w = s.prediction_default_market_weight
            label = f"prediction: shrunk {w:.0%} toward market price"
        p_shrunk = (1.0 - w) * p + w * req.market_price
        p, outcomes = p_shrunk, _two_point(p_shrunk, b or 1.0)
        ev = p * (b or 1.0) - (1.0 - p)
        if src == EdgeSource.guess:
            forced_exploration = False  # market anchor substitutes for a sample; see DECISIONS.md
    elif src == EdgeSource.exact_math:
        ev = raw_ev
        label = "exact_math: no shrinkage (edge is deterministic)"
    elif src == EdgeSource.live_track_record:
        realized, n_real = _realized_expectancy(req)
        w = n_real / (n_real + s.track_record_prior_strength) if n_real > 0 else 0.0
        if realized is None:
            ev = raw_ev * (1.0 - s.backtest_discount)
            label = "live_track_record claimed but no realized results supplied; discounted like a backtest"
        else:
            ev = (1.0 - w) * raw_ev + w * realized
            label = (f"bayesian blend: {w:.0%} weight on {n_real} realized trades, "
                     f"{1-w:.0%} on claimed prior")
        d = ev / raw_ev if raw_ev != 0.0 else 1.0
        if p is not None and b is not None and raw_ev != 0:
            p = _shrink_p_toward_breakeven(p, b, d)
            outcomes = _two_point(p, b)
        else:
            outcomes = _translate_outcomes(outcomes, ev - raw_ev)
    elif src == EdgeSource.backtest:
        d = s.backtest_discount
        ev = raw_ev * d
        label = f"backtest: discounted {1-d:.0%} (real edges run ~half of backtests)"
        if p is not None and b is not None:
            p = _shrink_p_toward_breakeven(p, b, d)
            outcomes = _two_point(p, b)
        else:
            outcomes = _translate_outcomes(outcomes, ev - raw_ev)
    elif src == EdgeSource.related_experience:
        sim = req.similarity if req.similarity is not None else 0.5
        discount_frac = s.related_max_discount - sim * (s.related_max_discount - s.related_min_discount)
        d = 1.0 - discount_frac
        ev = raw_ev * d
        label = f"related_experience (similarity {sim:.0%}): discounted {discount_frac:.0%}"
        if p is not None and b is not None:
            p = _shrink_p_toward_breakeven(p, b, d)
            outcomes = _two_point(p, b)
        else:
            outcomes = _translate_outcomes(outcomes, ev - raw_ev)
    else:  # guess
        d = 1.0 - s.guess_discount
        ev = raw_ev * d
        forced_exploration = True
        label = f"guess: discounted {s.guess_discount:.0%} and exploration mode forced"
        if p is not None and b is not None:
            p = _shrink_p_toward_breakeven(p, b, d)
            outcomes = _two_point(p, b)
        else:
            outcomes = _translate_outcomes(outcomes, ev - raw_ev)

    # Lottery extra skepticism: claimed win probabilities on long-shot convex
    # bets get an additional haircut (people overrate rare-event odds).
    if trade_type == TradeType.lottery and src != EdgeSource.exact_math and p is not None and b is not None:
        p2 = _shrink_p_toward_breakeven(p, b, 0.8)
        notes.append(f"lottery: extra 20% expectancy shrinkage on claimed win odds "
                     f"(p {p:.3f} -> {p2:.3f})")
        p = p2
        outcomes = _two_point(p, b)
        ev = p * b - (1.0 - p)

    ci = _confidence_interval(ev, p, b, src, n, cfg)

    working = WorkingEdge(
        expectancy_r=ev,
        win_probability=p,
        payoff_ratio=b,
        ci_expectancy_r=ci,
        shrinkage_applied=label,
        raw_expectancy_r=raw_ev,
    )
    return EdgeResult(
        working=working, outcomes=outcomes, p=p, b=b,
        effective_sample_size=n, forced_exploration=forced_exploration, notes=notes,
    )


def apply_extra_discount(edge: EdgeResult, discount: float, note: str) -> None:
    """Scale the working expectancy by `discount`, keeping p/b/outcomes and the
    CI consistent. Used for e.g. the not-user-stated-edge caution haircut."""
    w = edge.working
    old_ev = w.expectancy_r
    if edge.p is not None and edge.b is not None:
        edge.p = _shrink_p_toward_breakeven(edge.p, edge.b, discount)
        edge.outcomes = _two_point(edge.p, edge.b)
        w.win_probability = edge.p
        new_ev = edge.p * edge.b - (1.0 - edge.p)
    else:
        new_ev = old_ev * discount
        edge.outcomes = _translate_outcomes(edge.outcomes, new_ev - old_ev)
    shift = new_ev - old_ev
    w.expectancy_r = new_ev
    w.ci_expectancy_r = ConfidenceInterval(
        low=w.ci_expectancy_r.low + shift,
        high=w.ci_expectancy_r.high + shift,
        confidence=w.ci_expectancy_r.confidence,
    )
    w.shrinkage_applied += " + " + note


def _confidence_interval(
    ev: float, p: float | None, b: float | None,
    src: EdgeSource, n: int, cfg: EngineConfig,
) -> ConfidenceInterval:
    s = cfg.shrinkage
    if src == EdgeSource.exact_math:
        return ConfidenceInterval(low=ev, high=ev)
    if p is not None and b is not None:
        n_eff = max(n, 1)
        se = math.sqrt(p * (1.0 - p) / n_eff) * (1.0 + b)
    else:
        se = 0.5 / math.sqrt(max(n, 1))
    floor = {
        EdgeSource.live_track_record: 0.0,
        EdgeSource.backtest: s.ci_floor_backtest,
        EdgeSource.related_experience: s.ci_floor_related,
        EdgeSource.guess: s.ci_floor_guess,
    }.get(src, 0.0)
    half = max(s.ci_z * se, floor)
    return ConfidenceInterval(low=ev - half, high=ev + half)
