"""Exploration mode / sample-size gates (part of Layer 0).

The engine never refuses to size a new strategy — it sizes under uncertainty.
The gate returns a risk-fraction cap and the Kelly fraction override for the
current evidence stage. `exact_math` edges skip exploration entirely.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import EngineConfig
from .schemas import EdgeSource, SizeRequest


@dataclass
class ExplorationDecision:
    active: bool
    stage: str
    risk_cap: float | None            # bankroll fraction; None = no exploration cap
    kelly_fraction_override: float | None
    progress: str                     # e.g. "142 of 300 trades until full sizing"
    detail: str


def exploration_gate(
    req: SizeRequest, forced: bool, quarter_kelly_risk: float, cfg: EngineConfig
) -> ExplorationDecision:
    g = cfg.exploration
    if req.edge_source == EdgeSource.exact_math:
        return ExplorationDecision(
            active=False, stage="exempt", risk_cap=None, kelly_fraction_override=None,
            progress="", detail="exact_math edge: known from bet one, exploration skipped",
        )
    if req.exploration_override and not forced:
        return ExplorationDecision(
            active=False, stage="overridden", risk_cap=None, kelly_fraction_override=None,
            progress="", detail="exploration gates overridden by user",
        )

    n = max(req.sample_size, req.realized_results.n_trades if req.realized_results else 0)
    if forced and req.edge_source == EdgeSource.guess:
        n = req.realized_results.n_trades if req.realized_results else 0

    if n >= g.stage3_max_trades:
        return ExplorationDecision(
            active=False, stage="graduated", risk_cap=None, kelly_fraction_override=None,
            progress=f"{n} trades on record: full preferred sizing unlocked",
            detail="sample >= 300 trades: user's preferred Kelly fraction applies",
        )
    if n >= g.stage2_max_trades:
        return ExplorationDecision(
            active=True, stage="half_kelly",
            risk_cap=g.stage3_risk_cap, kelly_fraction_override=g.stage3_kelly_fraction,
            progress=f"{n} of {g.stage3_max_trades} trades until full sizing",
            detail=f"trades 100-300: half-Kelly against realized edge, capped at {g.stage3_risk_cap:.0%}",
        )
    if n >= g.stage1_max_trades:
        return ExplorationDecision(
            active=True, stage="quarter_kelly",
            risk_cap=g.stage2_risk_cap, kelly_fraction_override=g.stage2_kelly_fraction,
            progress=f"{n} of {g.stage3_max_trades} trades until full sizing",
            detail=f"trades 30-100: quarter-Kelly against realized edge, capped at {g.stage2_risk_cap:.0%}",
        )
    # Stage 1: fixed small exploration size, kept consistent so the sample is
    # clean. Anchor on quarter-Kelly of the shrunk edge, clamped into the band.
    size = min(g.stage1_max_risk, max(g.stage1_min_risk, quarter_kelly_risk))
    return ExplorationDecision(
        active=True, stage="exploration",
        risk_cap=size, kelly_fraction_override=None,
        progress=f"{n} of {g.stage3_max_trades} trades until full sizing",
        detail=(f"trades 0-{g.stage1_max_trades} on a new strategy: fixed exploration size "
                f"{size:.2%} of bankroll — large enough to matter, small enough that a wrong "
                "edge estimate is cheap, consistent so the sample is clean"),
    )
