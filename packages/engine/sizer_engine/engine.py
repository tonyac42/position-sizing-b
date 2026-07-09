"""The sizing orchestrator: routes a SizeRequest through Layers 0-5 and
assembles the full explained response.

Flow:
    validate structure -> classify type -> Layer 0 (shrinkage + exploration)
    -> Layer 4 (tail factors; needed before caps) -> trade economics
    -> Layer 1 (Kelly) -> Layer 5 multipliers -> Layer 2 caps -> Layer 3
    capacity -> min() across everything -> diagnostics -> response.

Raises RefusalError (carrying a structured SizingRefusal) when it cannot
produce a number it would stand behind.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .classify import classify
from .config import DEFAULT_CONFIG, EngineConfig
from .edge import apply_extra_discount, shrink_edge
from .exploration import ExplorationDecision, exploration_gate
from .kelly import (
    binary_kelly,
    continuous_kelly,
    generalized_kelly,
    kelly_fraction_from_drawdown_tolerance,
)
from .layers import (
    CapacityAssessment,
    TailAssessment,
    assess_capacity,
    assess_dynamics,
    assess_tail,
    daily_loss_hit,
    equity_throttle,
    risk_constraint_caps,
)
from .montecarlo import losing_streaks, simulate_drawdown_paths
from .schemas import (
    CapacityPolicy,
    Diagnostics,
    EdgeSource,
    Explanation,
    FieldConfidence,
    LayerCap,
    Outcome,
    Recommendation,
    RefusalError,
    ResponseMeta,
    SizeRequest,
    SizeResponse,
    SizingRefusal,
    TradeType,
    Warning,
)
from .version import ENGINE_VERSION, METHODOLOGY_VERSION

CRITICAL_FIELDS = ("bankroll", "edge_estimate", "stop_price", "entry_price", "structural_max_loss")

# Exploration gates apply to repeatable-strategy types. Prediction trades are
# anchored to a market price (shrinkage substitutes for a sample) and position
# trades route to portfolio-construction logic — see DECISIONS.md #4.
EXPLORATION_TYPES = {TradeType.trading, TradeType.shortterm, TradeType.lottery, TradeType.premium}


def compute_input_hash(req: SizeRequest) -> str:
    payload = req.model_dump(mode="json", exclude={"mc_seed"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta(req: SizeRequest, cls, input_hash: str, **kw) -> ResponseMeta:
    return ResponseMeta(
        trade_type_used=cls.used,
        trade_type_declared=cls.declared,
        type_mismatch=cls.mismatch,
        type_mismatch_detail=cls.detail if cls.mismatch else "",
        sizing_model_applied=kw.pop("model", "n/a"),
        engine_version=ENGINE_VERSION,
        methodology_version=METHODOLOGY_VERSION,
        timestamp=_now(),
        input_hash=input_hash,
        **kw,
    )


def _refuse(code: str, reasoning: str, needed: list[str], meta: ResponseMeta | None = None,
            warnings: list[Warning] | None = None) -> RefusalError:
    return RefusalError(SizingRefusal(
        refusal_code=code, reasoning=reasoning, what_is_needed=needed,
        partial_diagnostics=warnings or [], meta=meta,
    ))


# --------------------------------------------------------------------------- #
# Structural validation
# --------------------------------------------------------------------------- #

def _validate_structure(req: SizeRequest, meta: ResponseMeta) -> None:
    t = req.trade
    problems: list[str] = []
    if t.entry_price is not None and t.stop_price is not None:
        if t.direction == "long" and t.stop_price >= t.entry_price:
            problems.append(f"long trade with stop {t.stop_price} at/above entry {t.entry_price}")
        if t.direction == "short" and t.stop_price <= t.entry_price:
            problems.append(f"short trade with stop {t.stop_price} at/below entry {t.entry_price}")
    if t.entry_price is not None and t.target_price is not None:
        if t.direction == "long" and t.target_price <= t.entry_price:
            problems.append(f"long trade with target {t.target_price} at/below entry {t.entry_price}")
        if t.direction == "short" and t.target_price >= t.entry_price:
            problems.append(f"short trade with target {t.target_price} at/above entry {t.entry_price}")
    open_risk = sum(p.open_risk for p in req.open_positions)
    if open_risk > req.bankroll:
        problems.append(f"open risk ${open_risk:,.0f} exceeds bankroll ${req.bankroll:,.0f}")
    if problems:
        raise _refuse(
            "contradictory_inputs",
            "The request contradicts itself: " + "; ".join(problems) + ". "
            "Sizing on contradictory inputs would produce a confident-looking number "
            "with no meaning.",
            ["Correct the contradictory fields and resubmit."],
            meta,
        )


# --------------------------------------------------------------------------- #
# Trade economics
# --------------------------------------------------------------------------- #

def _trade_economics(
    req: SizeRequest, ttype: TradeType, tail: TailAssessment, meta: ResponseMeta
) -> tuple[float, float | None, list[str]]:
    """Determine effective per-unit risk dollars and per-unit notional.

    Returns (per_unit_risk, unit_notional, notes). Stake-style bets (dice,
    sports, prediction without explicit contract price) use $1 units where
    per-unit risk == $1 of stake.
    """
    t, inst = req.trade, req.instrument
    notes: list[str] = []

    if t.stop_price is not None and t.entry_price is not None and not tail.stops_unusable:
        nominal = abs(t.entry_price - t.stop_price) * inst.point_value
        eff = nominal * tail.stop_multiplier
        if tail.stop_multiplier > 1.0:
            notes.append(
                f"stop reliability: nominal ${nominal:,.2f}/unit risk treated as "
                f"${eff:,.2f}/unit ({tail.stop_rationale})")
        return eff, t.entry_price * inst.point_value, notes

    if tail.stops_unusable and t.stop_price is not None:
        if t.structural_max_loss is None and t.entry_price is None:
            raise _refuse(
                "unreliable_stop_no_structural_bound",
                "The stop cannot be trusted in this book and no structural max loss was "
                "given, so worst-case risk is unbounded from the engine's point of view.",
                ["Provide structural_max_loss (worst case per unit) or trade a deeper market."],
                meta,
            )
        notes.append(tail.stop_rationale)

    if t.structural_max_loss is not None:
        unit_notional = t.entry_price * inst.point_value if t.entry_price else None
        return t.structural_max_loss * inst.point_value, unit_notional, notes

    if ttype == TradeType.prediction:
        price = t.entry_price if t.entry_price is not None else req.market_price
        if price is not None and 0 < price < 1:
            notes.append(f"max loss per contract = price paid ({price:.2f})")
            return price, price, notes
        # Stake-style: $1 risked per $1 unit.
        return 1.0, 1.0, notes

    if ttype == TradeType.position:
        raise _refuse(
            "unbounded_downside",
            "A thesis position with no stop needs a structural downside estimate "
            "(what the position is worth if the thesis fails); without it risk per "
            "unit is undefined.",
            ["Provide structural_max_loss: per-unit loss under thesis failure."],
            meta,
        )

    raise _refuse(
        "risk_undefined",
        "Neither a stop distance nor a structural max loss was provided, so the loss "
        "per unit cannot be bounded and no defensible size exists.",
        ["Provide stop_price + entry_price, or structural_max_loss."],
        meta,
    )


# --------------------------------------------------------------------------- #
# Layer 1 dispatch
# --------------------------------------------------------------------------- #

def _premium_stress(outcomes: list[Outcome], tail_factor: float, cfg: EngineConfig) -> list[Outcome]:
    """Inject the tail event the observed sample doesn't contain."""
    tp = cfg.tail.premium_tail_probability
    worst = min(o.r for o in outcomes)
    tail_r = tail_factor * worst  # e.g. 4x the observed worst loss
    donor = max(range(len(outcomes)), key=lambda i: outcomes[i].probability)
    stressed = [
        Outcome(probability=o.probability - (tp if i == donor else 0.0), r=o.r)
        for i, o in enumerate(outcomes)
    ]
    stressed.append(Outcome(probability=tp, r=tail_r))
    return stressed


def _solve_kelly(
    ttype: TradeType, edge: EdgeResult, tail: TailAssessment,
    stop_based: bool, cfg: EngineConfig,
) -> tuple[float, str, list[Outcome]]:
    """Returns (full-Kelly risk fraction, model name, distribution used)."""
    p, b = edge.p, edge.b
    if stop_based and tail.stop_multiplier > 1.0 and p is not None and b is not None:
        # Losses realize stop_multiplier bigger than nominal: payoff ratio in
        # effective-risk currency shrinks accordingly.
        b = b / tail.stop_multiplier
    outcomes = edge.outcomes
    if b is not None and b != edge.b and p is not None:
        outcomes = [Outcome(probability=p, r=b), Outcome(probability=1 - p, r=-1.0)]

    if ttype == TradeType.premium:
        stressed = _premium_stress(outcomes, tail.factor, cfg)
        return generalized_kelly(stressed), "generalized_kelly_stressed", stressed
    if ttype == TradeType.lottery:
        return generalized_kelly(outcomes), "generalized_kelly", outcomes
    if ttype in (TradeType.prediction, TradeType.position):
        if p is not None and b is not None:
            return binary_kelly(p, b), "binary_kelly", outcomes
        return generalized_kelly(outcomes), "generalized_kelly", outcomes
    # trading / shortterm: mean-variance continuous Kelly.
    mean = sum(o.probability * o.r for o in outcomes)
    var = sum(o.probability * o.r ** 2 for o in outcomes) - mean ** 2
    return continuous_kelly(mean, var), "continuous_kelly", outcomes


# --------------------------------------------------------------------------- #
# Main entry
# --------------------------------------------------------------------------- #

def size(req: SizeRequest, cfg: EngineConfig = DEFAULT_CONFIG) -> SizeResponse:
    input_hash = compute_input_hash(req)
    cls = classify(req)
    ttype = cls.used
    confirm = [f for f in CRITICAL_FIELDS
               if req.field_confidence.get(f) not in (None, FieldConfidence.user_stated)]
    meta = _meta(req, cls, input_hash, confirm_fields=confirm, model="pending")

    _validate_structure(req, meta)

    # ---- Layer 0: edge ----
    edge = shrink_edge(req, ttype, cfg)

    # Extra caution when the edge itself wasn't user-stated (LLM interfaces).
    if req.field_confidence.get("edge_estimate") in (FieldConfidence.inferred, FieldConfidence.guessed):
        apply_extra_discount(edge, 0.75, "25% haircut (edge value was not user-stated)")

    ci = edge.working.ci_expectancy_r

    # ---- refusal: deeply uncertain edge + aggressive intent ----
    kf_requested = req.kelly_fraction or cfg.kelly.default_kelly_fraction
    if ci.low < cfg.refusal.deep_negative_expectancy and \
            (kf_requested >= cfg.refusal.aggressive_kelly_fraction or req.exploration_override):
        raise _refuse(
            "edge_too_uncertain_for_aggression",
            f"The {int(ci.confidence*100)}% confidence interval on your edge spans "
            f"[{ci.low:+.2f}R, {ci.high:+.2f}R] — deeply negative territory — while the "
            f"request asks for aggressive sizing (kelly_fraction {kf_requested:.2f}"
            f"{', exploration override' if req.exploration_override else ''}). "
            "A confident number here would be a fabrication.",
            ["Build a track record at exploration size (0.25-0.5% per trade), or",
             "provide evidence that narrows the edge estimate (sample results, calibration data), or",
             "accept a conservative kelly_fraction (<= 0.25) without exploration override."],
            meta,
        )

    # ---- Layer 4: tail (needed before economics & caps) ----
    tail = assess_tail(req, ttype, cfg)

    # ---- trade economics ----
    per_unit_risk, unit_notional, econ_notes = _trade_economics(req, ttype, tail, meta)
    stop_based = req.trade.stop_price is not None and not tail.stops_unusable

    # ---- Layer 1: Kelly ----
    f_full, model, dist_used = _solve_kelly(ttype, edge, tail, stop_based, cfg)
    meta.sizing_model_applied = model

    defaults: list[str] = []
    if req.kelly_fraction is not None:
        kf = req.kelly_fraction
        kf_src = "user preference"
    elif req.drawdown_tolerance and req.drawdown_tolerance.max_drawdown_pct:
        kf = kelly_fraction_from_drawdown_tolerance(
            req.drawdown_tolerance.max_drawdown_pct, cfg.kelly.drawdown_breach_probability)
        kf_src = (f"derived from {req.drawdown_tolerance.max_drawdown_pct:.0%} drawdown tolerance "
                  f"(target {cfg.kelly.drawdown_breach_probability:.0%} breach probability)")
    else:
        kf = cfg.kelly.default_kelly_fraction
        kf_src = "default"
        defaults.append(f"kelly_fraction = {kf} (quarter Kelly)")
    # Clamp to the configured band — except deterministic edges, where full
    # Kelly is defensible (the theater dice case).
    if req.edge_source != EdgeSource.exact_math:
        kf = max(cfg.kelly.min_kelly_fraction, min(cfg.kelly.max_kelly_fraction, kf))
    # Prediction trades sourced from a guess: quarter-Kelly ceiling.
    if ttype == TradeType.prediction and req.edge_source == EdgeSource.guess:
        kf = min(kf, 0.25)

    # ---- Layer 0b: exploration gate ----
    quarter_kelly_risk = 0.25 * f_full
    if ttype in EXPLORATION_TYPES:
        exp = exploration_gate(req, edge.forced_exploration, quarter_kelly_risk, cfg)
    else:
        exp = ExplorationDecision(
            active=False, stage="not_applicable", risk_cap=None, kelly_fraction_override=None,
            progress="", detail=f"exploration gates do not apply to {ttype.value} trades",
        )
    if exp.active and exp.kelly_fraction_override is not None:
        kf = min(kf, exp.kelly_fraction_override)

    # ---- Layer 5: multipliers ----
    throttle = equity_throttle(req, cfg)
    proposal = f_full * kf
    if throttle is not None:
        proposal *= throttle.multiplier
    dyn = assess_dynamics(req, ttype, proposal, None, cfg)
    proposal *= dyn.lockup_multiplier

    # ---- Layer 2: caps ----
    caps, cap_defaults = risk_constraint_caps(req, ttype, tail.factor, per_unit_risk, cfg)
    defaults.extend(cap_defaults)

    # ---- Layer 3: capacity ----
    capacity = assess_capacity(req, per_unit_risk, unit_notional, cfg)
    if capacity.unresolved and req.constraints.capacity_policy == CapacityPolicy.reject:
        raise _refuse(
            "capacity_unresolvable",
            capacity.detail + " (capacity_policy=reject requires resolvable capacity).",
            ["Supply instrument.adv or instrument.max_fill (book depth / limit), or "
             "switch capacity_policy to 'downsize' to size ultra-conservatively."],
            meta,
        )

    # ---- daily loss limit ----
    halted = ttype == TradeType.shortterm and daily_loss_hit(req)

    # ---- assemble the cap table and take the minimum ----
    table: list[LayerCap] = [
        LayerCap(layer="layer1_kelly", constraint="full_kelly", risk_pct=f_full,
                 detail=f"growth-optimal size for the working edge ({model})",
                 doc_slug="kelly"),
        LayerCap(layer="layer1_kelly", constraint="fractional_kelly", risk_pct=proposal,
                 detail=(f"{kf:.2f} x full Kelly ({kf_src})"
                         + (f"; equity throttle x{throttle.multiplier:.2f}" if throttle and throttle.multiplier < 1 else "")
                         + (f"; lockup x{dyn.lockup_multiplier:.2f}" if dyn.lockup_multiplier < 1 else "")),
                 doc_slug="kelly-fraction"),
    ]
    if exp.active:
        table.append(LayerCap(layer="layer0_exploration", constraint="exploration",
                              risk_pct=exp.risk_cap, detail=exp.detail, doc_slug="exploration"))
    for c in caps:
        table.append(LayerCap(layer=c.layer, constraint=c.constraint, risk_pct=c.risk_cap,
                              detail=c.detail, doc_slug=c.doc_slug))
    if capacity.risk_cap is not None:
        table.append(LayerCap(layer="layer3_capacity", constraint="capacity",
                              risk_pct=capacity.risk_cap, detail=capacity.detail,
                              doc_slug="capacity"))
    elif capacity.unresolved:
        # Downsize policy: unresolved thin-market capacity caps at exploration scale.
        table.append(LayerCap(layer="layer3_capacity", constraint="capacity_unresolved",
                              risk_pct=cfg.exploration.stage1_max_risk,
                              detail=capacity.detail + " — capped at exploration scale until "
                                     "liquidity figures are supplied",
                              doc_slug="capacity"))
    if halted:
        table.append(LayerCap(layer="layer2_risk", constraint="daily_loss_limit", risk_pct=0.0,
                              detail=(f"today's P&L ${req.intraday_pnl:,.0f} breaches the "
                                      f"${req.constraints.daily_loss_limit:,.0f} daily loss "
                                      "limit: halted for the day"),
                              doc_slug="daily-loss-limit"))

    # Heat/bucket rejection policy.
    if not halted and req.constraints.capacity_policy == CapacityPolicy.reject:
        for c in caps:
            if c.constraint in ("portfolio_heat", "correlation_bucket") and \
                    c.risk_cap is not None and proposal > c.risk_cap + 1e-12:
                raise _refuse(
                    "heat_budget_exceeded",
                    f"This trade needs {proposal:.2%} of bankroll at risk but the "
                    f"{c.constraint} budget has only {c.risk_cap:.2%} of headroom "
                    f"({c.detail}); policy is 'reject'.",
                    ["Close or reduce open positions to free heat, or",
                     "switch capacity_policy to 'downsize' to fit inside the headroom."],
                    meta,
                )

    applicable = [(t_.constraint, t_.risk_pct) for t_ in table
                  if t_.risk_pct is not None and t_.constraint != "full_kelly"]
    final_risk = min(v for _, v in applicable)
    binding = next(name for name, v in applicable if v == final_risk)
    for t_ in table:
        t_.binding = t_.constraint == binding
        t_.risk_dollars = t_.risk_pct * req.bankroll if t_.risk_pct is not None else None
    binding_layer = next(t_.layer for t_ in table if t_.binding)

    # ---- Layer 5 growth advice (now that capacity is known) ----
    dyn = assess_dynamics(req, ttype, f_full * kf, capacity.risk_cap, cfg)

    # ---- convert to units ----
    risk_dollars = final_risk * req.bankroll
    units = risk_dollars / per_unit_risk if per_unit_risk > 0 else 0.0
    notional = units * unit_notional if unit_notional else risk_dollars
    pct_full_kelly = final_risk / f_full if f_full > 0 else 0.0

    rec = Recommendation(
        size_units=units,
        size_pct_bankroll=notional / req.bankroll,
        risk_pct_bankroll=final_risk,
        risk_dollars=risk_dollars,
        notional_dollars=notional,
        pct_of_full_kelly=pct_full_kelly,
    )

    # ---- diagnostics ----
    warnings, suggestions = _diagnose(
        req, ttype, edge, tail, capacity, exp, binding, final_risk, notional, cls, dyn, halted, confirm)
    seed = req.mc_seed if req.mc_seed is not None else int(input_hash[:8], 16)
    dd = simulate_drawdown_paths(dist_used, final_risk, seed, cfg) if final_risk > 0 else None
    streaks = None
    if edge.p is not None and final_risk > 0:
        streaks = losing_streaks(edge.p, final_risk, cfg.montecarlo.n_trades)

    ignored = _ignored_fields(req, ttype)
    meta.exploration_stage = exp.stage if exp.active else None

    explanation = Explanation(
        binding_constraint=binding,
        binding_layer=binding_layer,
        full_kelly_risk_pct=f_full,
        kelly_fraction_used=kf,
        cap_table=table,
        working_edge=edge.working,
        defaults_applied=defaults,
        ignored_fields=ignored,
        tail_factor=tail.factor,
        multipliers={
            "equity_throttle": throttle.multiplier if throttle else 1.0,
            "lockup": dyn.lockup_multiplier,
            "stop_reliability": tail.stop_multiplier,
        },
    )
    if dyn.growth_advice:
        suggestions.append(dyn.growth_advice)

    summary = _summarize(req, ttype, rec, explanation, edge, tail, capacity, exp, warnings, halted)

    return SizeResponse(
        recommendation=rec,
        explanation=explanation,
        diagnostics=Diagnostics(
            warnings=warnings, suggestions=suggestions,
            drawdown_paths=dd, losing_streaks=streaks,
        ),
        meta=meta,
        human_readable_summary=summary,
    )


# --------------------------------------------------------------------------- #
# Diagnostics assembly
# --------------------------------------------------------------------------- #

def _diagnose(req, ttype, edge, tail, capacity, exp, binding, final_risk,
              notional, cls, dyn, halted, confirm) -> tuple[list[Warning], list[str]]:
    w: list[Warning] = []
    s: list[str] = []

    if halted:
        w.append(Warning(code="daily_loss_limit_hit", severity="danger",
                         message="Daily loss limit breached — recommended size is zero. "
                                 "Stop trading for the day; re-evaluate tomorrow.",
                         doc_slug="daily-loss-limit"))

    if cls.mismatch:
        w.append(Warning(code="trade_type_mismatch", severity="caution",
                         message=cls.detail, doc_slug="trade-types"))

    if ttype == TradeType.premium:
        w.append(Warning(
            code="premium_tail", severity="danger",
            message=(f"Premium collection: your observed results almost certainly contain no "
                     f"tail event. Sizing uses a {tail.factor:.1f}x stressed loss distribution, "
                     "not your observed one. The trade that ends this strategy is the one "
                     "that hasn't happened yet."),
            doc_slug="tail-risk"))
        if req.realized_results and (req.realized_results.win_rate or 0) >= 0.8:
            w.append(Warning(
                code="no_tail_in_sample", severity="danger",
                message=(f"A {req.realized_results.win_rate:.0%} observed win rate over "
                         f"{req.realized_results.n_trades} trades says nothing about the "
                         "left tail. Observed-Sharpe sizing is disabled for this type."),
                doc_slug="tail-risk"))

    if tail.advise_against:
        w.append(Warning(code="structural_tail_bomb", severity="danger",
                         message="This instrument carries structural tail risk (pegged/event-window "
                                 "exposure). Normal position sizing is not advisable; the 5x stress "
                                 "applied here is a floor, not a guarantee.",
                         doc_slug="tail-risk"))

    if binding == "capacity":
        w.append(Warning(
            code="capacity_limited", severity="info",
            message=("You are capacity-limited, not risk-limited: the market cannot absorb "
                     "your growth-optimal size without destroying the edge. Additional "
                     "bankroll should go to other strategies, not larger size here."),
            doc_slug="capacity"))
    elif capacity.notional_cap is not None and notional > 0:
        ratio = notional / capacity.notional_cap
        if ratio > 0.5:
            w.append(Warning(code="capacity_approach", severity="caution",
                             message=f"Order is {ratio:.0%} of this market's capacity ceiling "
                                     f"(${capacity.notional_cap:,.0f}); expect edge decay on fills.",
                             doc_slug="capacity"))
    if capacity.unresolved:
        w.append(Warning(code="capacity_unresolved", severity="caution",
                         message=capacity.detail, doc_slug="capacity"))

    if binding == "correlation_bucket":
        w.append(Warning(code="correlation_concentration", severity="caution",
                         message="Open risk in this correlation bucket is near its cap; these "
                                 "positions win and lose together.",
                         doc_slug="correlation-buckets"))

    ci = edge.working.ci_expectancy_r
    if ci.high > ci.low and (ci.high - ci.low) / 2 > abs(edge.working.expectancy_r):
        w.append(Warning(code="edge_uncertainty", severity="caution",
                         message=(f"The edge estimate is uncertain: {int(ci.confidence*100)}% CI "
                                  f"[{ci.low:+.2f}R, {ci.high:+.2f}R] spans zero. Size reflects "
                                  "the shrunk estimate, not the claim."),
                         doc_slug="shrinkage"))

    if tail.stop_multiplier >= 1.5 or tail.stops_unusable:
        w.append(Warning(code="stop_reliability", severity="caution",
                         message=tail.stop_rationale or "Stop execution is unreliable in this book.",
                         doc_slug="stop-reliability"))

    if confirm:
        w.append(Warning(code="unconfirmed_critical_fields", severity="caution",
                         message="These critical values were not stated by the user and should be "
                                 "confirmed before trading: " + ", ".join(confirm),
                         doc_slug="field-confidence"))

    if dyn.lockup_multiplier < 1.0:
        w.append(Warning(code="capital_lockup", severity="info",
                         message=dyn.lockup_detail, doc_slug="lockup"))

    # Suggestions: what would permit larger sizing.
    if exp.active:
        s.append(f"Log outcomes against strategy_id to graduate the exploration gates ({exp.progress}).")
    if binding == "per_trade_risk_cap":
        s.append("A tighter stop (less risk per unit) raises the unit count; raising "
                 "per_trade_risk_cap raises the dollar risk — the second changes your ruin odds.")
    if binding == "correlation_bucket":
        s.append("Free bucket headroom by closing correlated positions, or diversify into "
                 "uncorrelated markets to use the portfolio heat budget instead.")
    if binding == "portfolio_heat":
        s.append("Total open risk is the constraint: closing existing positions frees heat.")
    if binding == "volatility_cap":
        s.append("Size is volatility-capped: a calmer instrument or wider vol budget would "
                 "permit more units.")
    if edge.working.shrinkage_applied and "guess" in edge.working.shrinkage_applied:
        s.append("A documented track record or calibration data would reduce shrinkage on "
                 "your claimed edge.")
    return w, s


def _ignored_fields(req: SizeRequest, ttype: TradeType) -> list[str]:
    ignored = []
    if ttype != TradeType.shortterm:
        if req.constraints.daily_loss_limit is not None:
            ignored.append("constraints.daily_loss_limit (only used for shortterm)")
        if req.intraday_pnl is not None:
            ignored.append("intraday_pnl (only used for shortterm)")
    if ttype in (TradeType.prediction, TradeType.position) and req.instrument.volatility_atr:
        ignored.append("instrument.volatility_atr (risk is resolution/thesis failure, not daily wiggle)")
    if ttype != TradeType.prediction:
        if req.market_price is not None:
            ignored.append("market_price (only used for prediction)")
        if req.user_calibration_data:
            ignored.append("user_calibration_data (only used for prediction)")
        if req.trade.hold_to_resolution is not None:
            ignored.append("trade.hold_to_resolution (only used for prediction)")
    if req.edge_source != EdgeSource.related_experience and req.similarity is not None:
        ignored.append("similarity (only used for related_experience)")
    return ignored


def _summarize(req, ttype, rec, exp_l, edge, tail, capacity, exp, warnings, halted) -> str:
    if halted:
        return ("Recommended size: zero. Your daily loss limit has been hit — the engine "
                "recommends no further trades today regardless of edge.")
    ci = edge.working.ci_expectancy_r
    parts = [
        f"Recommended size: {rec.size_units:,.2f} units "
        f"(risking ${rec.risk_dollars:,.0f}, {rec.risk_pct_bankroll:.2%} of your "
        f"${req.bankroll:,.0f} bankroll — {rec.pct_of_full_kelly:.0%} of full Kelly)."
    ]
    b = exp_l.binding_constraint
    binding_text = {
        "fractional_kelly": "your Kelly fraction — growth math, not an external cap, sets the size",
        "full_kelly": "the growth-optimal Kelly size itself",
        "exploration": f"the exploration gate ({exp.progress})",
        "per_trade_risk_cap": "the per-trade risk cap",
        "volatility_cap": "the daily volatility budget",
        "portfolio_heat": "total portfolio heat",
        "correlation_bucket": "the correlation bucket cap",
        "capacity": "market capacity — the market can't absorb your growth-optimal size",
        "capacity_unresolved": "unresolved market capacity (liquidity data missing)",
        "daily_loss_limit": "the daily loss limit",
    }.get(b, b)
    parts.append(f"The binding constraint is {binding_text}.")
    parts.append(
        f"Working edge after shrinkage: {edge.working.expectancy_r:+.3f}R per trade "
        f"({edge.working.shrinkage_applied}); 90% CI [{ci.low:+.2f}R, {ci.high:+.2f}R]."
    )
    if tail.factor > 1.0:
        parts.append(f"A {tail.factor:.1f}x tail stress is applied to all risk caps.")
    dangers = [w for w in warnings if w.severity == "danger"]
    if dangers:
        parts.append("Critical warnings: " + " | ".join(d.message for d in dangers[:2]))
    return " ".join(parts)
