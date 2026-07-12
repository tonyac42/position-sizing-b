"""Engine configuration: every threshold that the spec calls a "default" or a
"configurable constant" lives here, so nothing in the sizing path is a magic
number. An `EngineConfig` instance is passed through the whole layer stack;
tests construct modified copies to probe behavior.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExplorationGateConfig(BaseModel):
    """Sample-size gates for strategies without an established track record.

    Stage boundaries are trade counts on the strategy (realized, logged
    trades). Sizes are risk fractions of bankroll (0.005 == 0.5%).
    """

    stage1_max_trades: int = 30
    stage1_min_risk: float = 0.0025   # 0.25% — small enough that a wrong edge is cheap
    stage1_max_risk: float = 0.005    # 0.5%  — large enough to matter
    stage2_max_trades: int = 100
    stage2_kelly_fraction: float = 0.25
    stage2_risk_cap: float = 0.01
    stage3_max_trades: int = 300
    stage3_kelly_fraction: float = 0.5
    stage3_risk_cap: float = 0.02


class ShrinkageConfig(BaseModel):
    backtest_discount: float = 0.5          # real edge assumed ~half of backtested
    guess_discount: float = 0.5
    related_min_discount: float = 0.3       # similarity=1.0 -> 30% discount
    related_max_discount: float = 0.5       # similarity=0.0 -> 50% discount
    # Bayesian blend for live track records: weight on realized data is
    # n / (n + track_record_prior_strength). At n=300 realized weight is ~0.83,
    # i.e. "realized dominates by ~300 trades".
    track_record_prior_strength: float = 60.0
    # prediction type: shrink user probability toward market price.
    prediction_default_market_weight: float = 0.5   # halfway by default
    prediction_calibrated_market_weight: float = 0.25  # documented calibration data
    prediction_unstructured_market_weight: float = 0.75  # bare guess, no reasoning
    # Confidence-interval floors on expectancy per unit risk (R), by source.
    ci_z: float = 1.6449  # ~90% two-sided
    ci_floor_backtest: float = 0.25
    ci_floor_related: float = 0.30
    ci_floor_guess: float = 0.50


class RiskCapConfig(BaseModel):
    per_trade_risk_cap: float = 0.02        # max bankroll fraction lost at stop
    per_trade_risk_hard_ceiling: float = 0.10
    volatility_cap: float = 0.01            # max bankroll fraction moved by 1 ATR
    portfolio_heat_cap: float = 0.20
    correlation_bucket_cap: float = 0.06
    # Equity-curve throttle default schedule: (drawdown_from_peak, size multiplier)
    equity_throttle_schedule: list[tuple[float, float]] = Field(
        default=[(0.05, 1.0), (0.10, 0.75), (0.15, 0.5), (1.0, 0.0)]
    )


class CapacityConfig(BaseModel):
    # Linear impact model: edge intact up to decay_start*ADV, zero at decay_zero*ADV.
    # Expected profit ~ s * edge(s) is maximized at s = decay_zero/2 under this
    # model, so the impact-optimal order is optimal_fraction_of_zero * decay_zero.
    adv_decay_start: float = 0.01
    adv_decay_zero: float = 0.10
    # Order sizes above this fraction of the impact-optimal size trigger a
    # "capacity approach" warning even when capacity is not binding.
    approach_warning_ratio: float = 0.5


class TailConfig(BaseModel):
    factor_discrete: float = 1.0        # resolved binaries, settled bets, dice
    factor_liquid_normal: float = 1.3   # liquid continuous markets (range 1.2-1.5)
    factor_moderate: float = 1.5
    factor_gap_event: float = 2.5       # earnings/binary catalysts (range 2-3)
    factor_premium_min: float = 3.0     # premium selling mandatory minimum
    factor_premium_heavy: float = 4.0
    factor_extreme: float = 5.0         # pegged currencies, structural tail bombs
    # Stop reliability haircut by liquidity tier: effective stop loss distance
    # multiplier. "none" means stops are unusable -> structural max loss.
    stop_multiplier_deep: float = 1.2
    stop_multiplier_moderate: float = 1.5
    stop_multiplier_thin: float = 2.5
    # Premium stressed-distribution injection: a synthetic tail outcome with
    # this probability and loss = tail factor x observed worst loss.
    premium_tail_probability: float = 0.02


class DynamicsConfig(BaseModel):
    # Capital lockup: multiplier = max(floor, 1 - rate * years_locked), applied
    # to long-dated prediction/position trades in concentrated bankrolls.
    lockup_discount_rate_per_year: float = 0.30
    lockup_discount_floor: float = 0.5
    lockup_min_days: int = 30           # no discount for short lockups
    # "Concentrated": trade would lock up more than this fraction of bankroll,
    # or bankroll is not segregated play-money.
    lockup_concentration_threshold: float = 0.02


class KellyConfig(BaseModel):
    default_kelly_fraction: float = 0.25
    min_kelly_fraction: float = 0.10
    max_kelly_fraction: float = 0.50
    # Drawdown-tolerance mapping: P(ever hitting drawdown D) target used when
    # deriving a Kelly fraction from a tolerable drawdown (see kelly.py).
    drawdown_breach_probability: float = 0.10


class RefusalConfig(BaseModel):
    # Refuse when the shrunk-edge CI lower bound is below this (in R) while the
    # request still implies aggressive sizing.
    deep_negative_expectancy: float = -0.5
    aggressive_kelly_fraction: float = 0.5


class MonteCarloConfig(BaseModel):
    n_paths: int = 1000
    n_trades: int = 100
    max_path_points: int = 101  # equity points returned per illustrative path


class EngineConfig(BaseModel):
    exploration: ExplorationGateConfig = ExplorationGateConfig()
    shrinkage: ShrinkageConfig = ShrinkageConfig()
    risk: RiskCapConfig = RiskCapConfig()
    capacity: CapacityConfig = CapacityConfig()
    tail: TailConfig = TailConfig()
    dynamics: DynamicsConfig = DynamicsConfig()
    kelly: KellyConfig = KellyConfig()
    refusal: RefusalConfig = RefusalConfig()
    montecarlo: MonteCarloConfig = MonteCarloConfig()


DEFAULT_CONFIG = EngineConfig()
