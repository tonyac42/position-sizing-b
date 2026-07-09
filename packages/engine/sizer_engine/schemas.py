"""Canonical request and response schemas.

`SizeRequest` is the single input object every interface (API, MCP, UI)
constructs; the engine consumes nothing else. `SizeResponse` /
`SizingRefusal` are the only outputs. All money amounts are in account
currency; all fractions are decimals (0.02 == 2%).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class TradeType(str, Enum):
    lottery = "lottery"
    premium = "premium"
    position = "position"
    shortterm = "shortterm"
    prediction = "prediction"
    trading = "trading"


class EdgeSource(str, Enum):
    exact_math = "exact_math"
    live_track_record = "live_track_record"
    backtest = "backtest"
    related_experience = "related_experience"
    guess = "guess"


class PayoffStructure(str, Enum):
    binary = "binary"
    continuous = "continuous"
    capped = "capped"
    unbounded = "unbounded"


class LiquidityTier(str, Enum):
    deep = "deep"
    moderate = "moderate"
    thin = "thin"
    micro = "micro"


class TailProfile(str, Enum):
    normal = "normal"
    moderate = "moderate"
    heavy = "heavy"
    extreme = "extreme"


class CapacityPolicy(str, Enum):
    reject = "reject"
    downsize = "downsize"
    queue = "queue"


class FieldConfidence(str, Enum):
    user_stated = "user_stated"
    inferred = "inferred"
    guessed = "guessed"


# --------------------------------------------------------------------------- #
# Request components
# --------------------------------------------------------------------------- #

class Outcome(BaseModel):
    """One branch of a discrete payoff distribution.

    `r` is the return per unit risked (R-multiple): -1.0 means losing the
    full defined risk, +2.0 means winning twice the defined risk.
    """
    probability: float = Field(gt=0, le=1)
    r: float


class EdgeEstimate(BaseModel):
    """Multi-format edge claim; the engine normalizes internally.

    Provide ONE of:
      - win_probability (+ payoff_ratio, defaulting to the trade's structural
        payoff for binary trades)
      - expectancy_r (+ optional win_rate for distribution shape)
      - outcomes (full discrete distribution in R-multiples)
    """
    win_probability: float | None = Field(default=None, gt=0, lt=1)
    payoff_ratio: float | None = Field(default=None, gt=0, description="avg win / avg loss, in R")
    expectancy_r: float | None = Field(default=None, description="EV per unit risked (R)")
    win_rate: float | None = Field(default=None, gt=0, lt=1)
    outcomes: list[Outcome] | None = None

    @model_validator(mode="after")
    def _at_least_one_format(self) -> "EdgeEstimate":
        if self.win_probability is None and self.expectancy_r is None and not self.outcomes:
            raise ValueError(
                "edge_estimate needs win_probability, expectancy_r, or outcomes"
            )
        if self.outcomes:
            total = sum(o.probability for o in self.outcomes)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"outcome probabilities sum to {total:.6f}, expected 1.0")
        return self


class RealizedResults(BaseModel):
    """Summary statistics of realized trades on this exact strategy."""
    n_trades: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    avg_win_r: float | None = Field(default=None, ge=0)
    avg_loss_r: float | None = Field(default=None, ge=0, description="magnitude, positive")
    expectancy_r: float | None = None
    # Recency weighting: expectancy over the most recent window, if tracked.
    recent_expectancy_r: float | None = None
    recent_n_trades: int | None = Field(default=None, ge=0)


class OpenPosition(BaseModel):
    instrument_id: str
    direction: Literal["long", "short"] = "long"
    open_risk: float = Field(ge=0, description="dollars lost if this position's stop/max-loss hits")
    correlation_bucket: str = "default"


class Instrument(BaseModel):
    instrument_id: str = "unspecified"
    point_value: float = Field(default=1.0, gt=0, description="currency per 1.0 price move per unit")
    volatility_atr: float | None = Field(default=None, gt=0, description="ATR in price terms")
    adv: float | None = Field(default=None, gt=0, description="average daily volume, notional currency")
    max_fill: float | None = Field(
        default=None, gt=0,
        description="hard fill limit in currency notional (book limit, counterparty cap, visible depth)",
    )
    liquidity_tier: LiquidityTier | None = None
    correlation_bucket: str = "default"
    tail_profile: TailProfile = TailProfile.normal
    gap_risk: bool = False


class TradeStructure(BaseModel):
    direction: Literal["long", "short"] = "long"
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    expected_time_in_trade_days: float | None = Field(default=None, ge=0)
    payoff_structure: PayoffStructure | None = None
    structural_max_loss: float | None = Field(
        default=None, gt=0,
        description="max loss per unit if held to worst case (premium paid, margin at risk...)",
    )
    hold_to_resolution: bool | None = Field(
        default=None, description="prediction subtype: no stop management, hold to settle"
    )


class ConstraintPreferences(BaseModel):
    per_trade_risk_cap: float | None = Field(default=None, gt=0, le=1)
    volatility_cap: float | None = Field(default=None, gt=0, le=1)
    portfolio_heat_cap: float | None = Field(default=None, gt=0, le=1)
    correlation_bucket_cap: float | None = Field(default=None, gt=0, le=1)
    capacity_policy: CapacityPolicy = CapacityPolicy.downsize
    equity_throttle_schedule: list[tuple[float, float]] | None = None
    daily_loss_limit: float | None = Field(default=None, gt=0, description="currency")


class DrawdownTolerance(BaseModel):
    max_drawdown_pct: float | None = Field(default=None, gt=0, lt=1)
    max_drawdown_dollars: float | None = Field(default=None, gt=0)


class SizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- bettor context ---
    bankroll: float = Field(gt=0)
    bankroll_segregated: bool = False
    drawdown_tolerance: DrawdownTolerance | None = None
    kelly_fraction: float | None = Field(default=None, gt=0, le=1.0)
    open_positions: list[OpenPosition] = Field(default_factory=list)
    peak_equity: float | None = Field(
        default=None, gt=0, description="high-water mark, for the equity-curve throttle"
    )
    intraday_pnl: float | None = Field(default=None, description="today's realized P&L (shortterm)")

    # --- trade type ---
    trade_type: TradeType | Literal["auto"] = "auto"

    # --- edge ---
    edge_estimate: EdgeEstimate
    edge_source: EdgeSource
    sample_size: int = Field(default=0, ge=0, description="trades behind the claimed edge")
    realized_results: RealizedResults | None = None
    similarity: float | None = Field(
        default=None, ge=0, le=1, description="related_experience: how similar is the prior domain"
    )
    user_calibration_data: bool = False
    edge_justification_structured: bool = True
    market_price: float | None = Field(
        default=None, gt=0, lt=1, description="prediction: current market probability/price"
    )

    # --- trade structure & instrument ---
    trade: TradeStructure = Field(default_factory=TradeStructure)
    instrument: Instrument = Field(default_factory=Instrument)

    # --- constraint preferences ---
    constraints: ConstraintPreferences = Field(default_factory=ConstraintPreferences)

    # --- meta ---
    exploration_override: bool = False
    strategy_id: str | None = None
    field_confidence: dict[str, FieldConfidence] = Field(default_factory=dict)
    mc_seed: int | None = Field(default=None, description="Monte Carlo seed; default derives from input hash")


# --------------------------------------------------------------------------- #
# Response components
# --------------------------------------------------------------------------- #

class Recommendation(BaseModel):
    size_units: float
    size_pct_bankroll: float = Field(description="notional exposure / bankroll")
    risk_pct_bankroll: float = Field(description="bankroll fraction lost if stop/max-loss hits")
    risk_dollars: float
    notional_dollars: float
    pct_of_full_kelly: float


class LayerCap(BaseModel):
    layer: str
    constraint: str
    risk_pct: float | None = Field(description="cap in risk fraction of bankroll; None = not applicable")
    risk_dollars: float | None = None
    binding: bool = False
    detail: str = ""
    doc_slug: str = ""


class ConfidenceInterval(BaseModel):
    low: float
    high: float
    confidence: float = 0.90


class WorkingEdge(BaseModel):
    expectancy_r: float
    win_probability: float | None
    payoff_ratio: float | None
    ci_expectancy_r: ConfidenceInterval
    shrinkage_applied: str
    raw_expectancy_r: float


class Explanation(BaseModel):
    binding_constraint: str
    binding_layer: str
    full_kelly_risk_pct: float
    kelly_fraction_used: float
    cap_table: list[LayerCap]
    working_edge: WorkingEdge
    defaults_applied: list[str] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)
    tail_factor: float = 1.0
    multipliers: dict[str, float] = Field(default_factory=dict)


class Warning(BaseModel):
    code: str
    severity: Literal["info", "caution", "danger"] = "caution"
    message: str
    doc_slug: str = ""


class DrawdownPaths(BaseModel):
    n_paths: int
    n_trades: int
    seed: int
    median_final_equity: float
    worst_5pct_path: list[float]
    worst_1pct_path: list[float]
    median_path: list[float]
    worst_5pct_max_drawdown: float
    worst_1pct_max_drawdown: float
    prob_drawdown_over_20pct: float


class LosingStreaks(BaseModel):
    expected_max_streak: int = Field(description="expected longest losing streak over n_trades")
    prob_streak_10: float
    equity_after_expected_streak_pct: float = Field(
        description="bankroll remaining after the expected max streak at this size"
    )
    note: str = ""


class Diagnostics(BaseModel):
    warnings: list[Warning] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    drawdown_paths: DrawdownPaths | None = None
    losing_streaks: LosingStreaks | None = None


class ResponseMeta(BaseModel):
    trade_type_used: TradeType
    trade_type_declared: str
    type_mismatch: bool = False
    type_mismatch_detail: str = ""
    sizing_model_applied: str
    engine_version: str
    methodology_version: str
    timestamp: str
    input_hash: str
    exploration_stage: str | None = None
    confirm_fields: list[str] = Field(
        default_factory=list,
        description="critical fields whose values were not user_stated; confirm before trading",
    )


class SizeResponse(BaseModel):
    status: Literal["ok"] = "ok"
    recommendation: Recommendation
    explanation: Explanation
    diagnostics: Diagnostics
    meta: ResponseMeta
    human_readable_summary: str


class SizingRefusal(BaseModel):
    """Structured refusal: returned when the engine cannot produce a number it
    would stand behind. This is a feature, not an error state."""
    status: Literal["refusal"] = "refusal"
    refusal_code: str
    reasoning: str
    what_is_needed: list[str]
    partial_diagnostics: list[Warning] = Field(default_factory=list)
    meta: ResponseMeta | None = None


class RefusalError(Exception):
    """Raised internally; interfaces convert to SizingRefusal / HTTP 422."""

    def __init__(self, refusal: SizingRefusal):
        self.refusal = refusal
        super().__init__(refusal.reasoning)
