"""Layers 2-5: risk constraint caps, capacity, tail overlay, bankroll dynamics.

Common currency: every cap is expressed as a *risk fraction of bankroll* —
the fraction of bankroll lost if the trade's defined risk (stop or structural
max loss) is fully realized. The engine takes the minimum across caps and
reports the full table.

The tail overlay (Layer 4) multiplies effective per-trade risk before Layer 2
caps are checked, so a cap of 2% under a 4x tail factor admits only 0.5% of
nominal defined risk. Layer 4 also haircuts stop reliability: a stop in a
thin book cannot be trusted to lose only its nominal distance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import EngineConfig
from .schemas import (
    CapacityPolicy,
    LiquidityTier,
    SizeRequest,
    TailProfile,
    TradeType,
)


# --------------------------------------------------------------------------- #
# Layer 4 — tail overlay (computed first: Layer 2 checks need the factor)
# --------------------------------------------------------------------------- #

@dataclass
class TailAssessment:
    factor: float
    rationale: str
    stop_multiplier: float          # effective stop distance multiplier (>= 1)
    stop_rationale: str
    stops_unusable: bool            # thin/micro books: fall back to structural max loss
    advise_against: bool = False    # structural tail bombs


def assess_tail(req: SizeRequest, trade_type: TradeType, cfg: EngineConfig) -> TailAssessment:
    t = cfg.tail
    inst = req.instrument

    # Stop reliability by liquidity.
    stop_mult, stop_note, unusable = 1.0, "", False
    if req.trade.stop_price is not None:
        tier = inst.liquidity_tier
        if tier == LiquidityTier.deep or tier is None and (inst.adv or 0) > 0:
            stop_mult, stop_note = t.stop_multiplier_deep, "deep book: stop slippage ~20%"
        elif tier == LiquidityTier.moderate:
            stop_mult, stop_note = t.stop_multiplier_moderate, "moderate book: stop slippage ~50%"
        elif tier == LiquidityTier.thin:
            stop_mult = t.stop_multiplier_thin
            stop_note = ("thin book: stops fill far through their level; effective risk "
                         f"taken as {t.stop_multiplier_thin}x the nominal stop distance")
        elif tier == LiquidityTier.micro:
            unusable = True
            stop_note = ("micro liquidity: stops are effectively unavailable; sized against "
                         "structural max loss instead of the stop")
        else:
            stop_mult, stop_note = t.stop_multiplier_deep, "liquidity unstated: assumed deep-book slippage"

    # Distribution tail factor.
    if trade_type == TradeType.premium:
        factor = t.factor_premium_heavy if inst.tail_profile in (TailProfile.heavy, TailProfile.extreme) \
            else t.factor_premium_min
        rationale = ("premium collection: the observed sample almost certainly contains no tail "
                     f"event; risk stressed {factor:.1f}x (mandatory minimum {t.factor_premium_min:.1f}x)")
        if inst.tail_profile == TailProfile.extreme:
            factor = t.factor_extreme
            rationale = "premium on an extreme-tail instrument: stressed 5x"
        return TailAssessment(factor, rationale, stop_mult, stop_note, unusable,
                              advise_against=inst.tail_profile == TailProfile.extreme)

    discrete = (
        trade_type == TradeType.prediction and (req.trade.hold_to_resolution is not False)
    ) or (trade_type == TradeType.prediction and req.trade.stop_price is None)
    if discrete or (req.trade.payoff_structure and req.trade.payoff_structure.value == "binary"
                    and req.trade.stop_price is None):
        return TailAssessment(t.factor_discrete,
                              "discrete resolved outcome (held to resolution): no gap risk",
                              1.0, "", False)

    if inst.tail_profile == TailProfile.extreme:
        return TailAssessment(t.factor_extreme,
                              "structural tail bomb (pegged/event-window): 5x stress; "
                              "normal sizing inadvisable",
                              stop_mult, stop_note, unusable, advise_against=True)
    if inst.gap_risk or inst.tail_profile == TailProfile.heavy:
        return TailAssessment(t.factor_gap_event,
                              "gap/event exposure (earnings, binary catalysts): 2.5x stress",
                              stop_mult, stop_note, unusable)
    if inst.tail_profile == TailProfile.moderate:
        return TailAssessment(t.factor_moderate, "moderate tail profile: 1.5x stress",
                              stop_mult, stop_note, unusable)
    return TailAssessment(t.factor_liquid_normal,
                          "liquid continuous market, normal conditions: 1.3x stress",
                          stop_mult, stop_note, unusable)


# --------------------------------------------------------------------------- #
# Layer 2 — risk constraint caps
# --------------------------------------------------------------------------- #

@dataclass
class CapEntry:
    constraint: str
    layer: str
    risk_cap: float | None     # nominal risk fraction of bankroll; None = N/A
    detail: str
    doc_slug: str


def risk_constraint_caps(
    req: SizeRequest,
    trade_type: TradeType,
    tail_factor: float,
    per_unit_risk: float | None,
    cfg: EngineConfig,
) -> tuple[list[CapEntry], list[str]]:
    """Layer 2 caps in nominal risk-fraction terms (already tail-adjusted)."""
    r = cfg.risk
    c = req.constraints
    defaults: list[str] = []
    caps: list[CapEntry] = []

    # Per-trade risk cap.
    if c.per_trade_risk_cap is not None:
        per_trade = min(c.per_trade_risk_cap, r.per_trade_risk_hard_ceiling)
    else:
        per_trade = r.per_trade_risk_cap
        defaults.append(f"per_trade_risk_cap = {per_trade:.1%}")
    caps.append(CapEntry(
        "per_trade_risk_cap", "layer2_risk",
        per_trade / tail_factor,
        f"max {per_trade:.1%} of bankroll at the stop; tail factor {tail_factor:.1f}x "
        f"admits {per_trade / tail_factor:.2%} nominal",
        "per-trade-risk",
    ))

    # Volatility cap (needs ATR and a defined per-unit risk to translate).
    atr = req.instrument.volatility_atr
    if trade_type in (TradeType.position, TradeType.prediction):
        caps.append(CapEntry("volatility_cap", "layer2_risk", None,
                             "not applicable: risk is thesis failure / resolution, not daily wiggle",
                             "volatility-cap"))
    elif atr is not None and per_unit_risk:
        vol_cap = c.volatility_cap if c.volatility_cap is not None else r.volatility_cap
        if c.volatility_cap is None:
            defaults.append(f"volatility_cap = {vol_cap:.1%} of bankroll per ATR")
        atr_dollars = atr * req.instrument.point_value
        cap_risk = vol_cap * per_unit_risk / atr_dollars
        caps.append(CapEntry(
            "volatility_cap", "layer2_risk", cap_risk,
            f"max {vol_cap:.1%} of bankroll moved by one ATR "
            f"(ATR ${atr_dollars:,.2f}/unit vs ${per_unit_risk:,.2f} risk/unit)",
            "volatility-cap",
        ))
    else:
        caps.append(CapEntry("volatility_cap", "layer2_risk", None,
                             "no ATR supplied: volatility model unavailable", "volatility-cap"))

    # Portfolio heat.
    heat_cap = c.portfolio_heat_cap if c.portfolio_heat_cap is not None else r.portfolio_heat_cap
    if c.portfolio_heat_cap is None:
        defaults.append(f"portfolio_heat_cap = {heat_cap:.0%}")
    open_heat = sum(p.open_risk for p in req.open_positions) / req.bankroll
    available_heat = max(0.0, heat_cap - open_heat)
    caps.append(CapEntry(
        "portfolio_heat", "layer2_risk", available_heat / tail_factor,
        f"open risk {open_heat:.1%} of {heat_cap:.0%} budget; {available_heat:.1%} headroom",
        "portfolio-heat",
    ))

    # Correlation bucket.
    bucket_cap = c.correlation_bucket_cap if c.correlation_bucket_cap is not None else r.correlation_bucket_cap
    if c.correlation_bucket_cap is None:
        defaults.append(f"correlation_bucket_cap = {bucket_cap:.0%}")
    bucket = req.instrument.correlation_bucket
    bucket_open = sum(p.open_risk for p in req.open_positions
                      if p.correlation_bucket == bucket) / req.bankroll
    available_bucket = max(0.0, bucket_cap - bucket_open)
    caps.append(CapEntry(
        "correlation_bucket", "layer2_risk", available_bucket / tail_factor,
        f"bucket '{bucket}' holds {bucket_open:.1%} of its {bucket_cap:.0%} cap; "
        f"{available_bucket:.1%} headroom",
        "correlation-buckets",
    ))
    return caps, defaults


def heat_policy_violated(req: SizeRequest, proposal_risk: float, caps: list[CapEntry]) -> str | None:
    """Returns the violated constraint name if policy=reject and the proposal
    exceeds heat/bucket headroom."""
    if req.constraints.capacity_policy != CapacityPolicy.reject:
        return None
    for cap in caps:
        if cap.constraint in ("portfolio_heat", "correlation_bucket") \
                and cap.risk_cap is not None and proposal_risk > cap.risk_cap + 1e-12:
            return cap.constraint
    return None


# --------------------------------------------------------------------------- #
# Layer 2b — equity throttle & daily loss limit
# --------------------------------------------------------------------------- #

@dataclass
class ThrottleResult:
    multiplier: float
    drawdown: float
    detail: str


def equity_throttle(req: SizeRequest, cfg: EngineConfig) -> ThrottleResult | None:
    schedule = req.constraints.equity_throttle_schedule
    if schedule is None:
        return None  # opt-in feature; no default throttle
    if req.peak_equity is None or req.peak_equity <= req.bankroll:
        return ThrottleResult(1.0, 0.0, "at or above high-water mark: full size")
    dd = 1.0 - req.bankroll / req.peak_equity
    for threshold, mult in sorted(schedule):
        if dd <= threshold:
            return ThrottleResult(mult, dd, f"{dd:.1%} drawdown from peak: size x{mult:.2f}")
    return ThrottleResult(0.0, dd, f"{dd:.1%} drawdown exceeds throttle schedule: flat")


def daily_loss_hit(req: SizeRequest) -> bool:
    limit = req.constraints.daily_loss_limit
    return (limit is not None and req.intraday_pnl is not None
            and req.intraday_pnl <= -limit)


# --------------------------------------------------------------------------- #
# Layer 3 — capacity
# --------------------------------------------------------------------------- #

@dataclass
class CapacityAssessment:
    risk_cap: float | None          # risk-fraction cap; None = layer inert
    notional_cap: float | None      # currency
    binding_reason: str
    inert: bool
    unresolved: bool                # liquidity unknown for a thin market
    detail: str
    optimal_notional: float | None = None


def assess_capacity(
    req: SizeRequest,
    per_unit_risk: float | None,
    unit_notional: float | None,
    cfg: EngineConfig,
) -> CapacityAssessment:
    """Layer 3: the size at which marginal edge net of impact stops improving
    expected log growth.

    Under the linear-decay impact model (edge intact below `adv_decay_start`
    of ADV, zero at `adv_decay_zero`), expected profit s*edge(s) is maximized
    at s = adv_decay_zero/2, so that is the impact-optimal order. Hard fill
    limits (book limits, counterparty caps, visible depth) cap notional
    directly. See docs/capacity.md.
    """
    inst = req.instrument
    k = cfg.capacity
    notional_caps: list[tuple[float, str]] = []

    if inst.max_fill is not None:
        notional_caps.append((inst.max_fill, "hard fill limit (book/counterparty/depth)"))
    optimal = None
    if inst.adv is not None:
        optimal = 0.5 * k.adv_decay_zero * inst.adv
        notional_caps.append((
            optimal,
            f"impact-optimal order: edge decays past {k.adv_decay_start:.0%} of ADV, "
            f"zero at {k.adv_decay_zero:.0%}; growth-optimal fill is "
            f"{0.5 * k.adv_decay_zero:.1%} of ADV",
        ))

    if not notional_caps:
        tier = inst.liquidity_tier
        if tier in (LiquidityTier.thin, LiquidityTier.micro):
            return CapacityAssessment(
                risk_cap=None, notional_cap=None, binding_reason="",
                inert=False, unresolved=True,
                detail=(f"{tier.value} market with no depth/ADV figures: capacity cannot be "
                        "resolved; supply book depth or a max fill"),
            )
        return CapacityAssessment(
            risk_cap=None, notional_cap=None, binding_reason="", inert=True,
            unresolved=False, detail="deep market relative to bankroll: capacity layer inert",
        )

    notional_cap, reason = min(notional_caps, key=lambda x: x[0])
    risk_cap = None
    if unit_notional and per_unit_risk:
        units_cap = notional_cap / unit_notional
        risk_cap = units_cap * per_unit_risk / req.bankroll
    elif per_unit_risk:
        # Stake-style bets (dice, sports): notional == risk dollars.
        risk_cap = notional_cap / req.bankroll
    return CapacityAssessment(
        risk_cap=risk_cap, notional_cap=notional_cap, binding_reason=reason,
        inert=False, unresolved=False, detail=reason, optimal_notional=optimal,
    )


# --------------------------------------------------------------------------- #
# Layer 5 — bankroll dynamics
# --------------------------------------------------------------------------- #

@dataclass
class DynamicsResult:
    lockup_multiplier: float
    lockup_detail: str
    growth_advice: str | None


def assess_dynamics(
    req: SizeRequest,
    trade_type: TradeType,
    proposal_risk: float,
    capacity_risk_cap: float | None,
    cfg: EngineConfig,
) -> DynamicsResult:
    d = cfg.dynamics
    mult, detail = 1.0, ""

    days = req.trade.expected_time_in_trade_days
    if trade_type in (TradeType.prediction, TradeType.position) and days is not None \
            and days >= d.lockup_min_days:
        concentrated = (not req.bankroll_segregated) or \
            proposal_risk >= d.lockup_concentration_threshold
        if concentrated:
            years = days / 365.0
            mult = max(d.lockup_discount_floor, 1.0 - d.lockup_discount_rate_per_year * years)
            detail = (f"capital locked ~{days:.0f} days until resolution: opportunity-cost "
                      f"discount x{mult:.2f} (rate {d.lockup_discount_rate_per_year:.0%}/yr, "
                      f"floor x{d.lockup_discount_floor:.2f})")

    advice = None
    if capacity_risk_cap is not None and proposal_risk > capacity_risk_cap:
        advice = ("Bankroll growth has pushed the growth-optimal size past this market's "
                  "capacity ceiling. The correct response is to deploy additional capital "
                  "into different strategies or markets — not larger size here.")
    return DynamicsResult(mult, detail, advice)
