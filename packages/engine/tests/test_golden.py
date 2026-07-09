"""Golden-scenario tests: one per archetype user. Each asserts both the
recommended size range AND the binding constraint, per spec Part 6.

Scenario 1 (dice) note: with the spec's literal numbers ($1,000 bankroll,
55/45 even money, $500 counterparty limit) full Kelly is $100/bet, so a
correct engine reports Kelly-bound, not capacity-bound — the $500 limit has
5x headroom. The capacity story the spec intends appears as the bankroll
grows: past $5,000, Kelly wants more than the counterparty will book. The
test covers both states. See DECISIONS.md #1.
"""
import pytest

from sizer_engine import (
    DEFAULT_CONFIG,
    EdgeEstimate,
    EdgeSource,
    Instrument,
    OpenPosition,
    RealizedResults,
    SizeRequest,
    TradeStructure,
    TradeType,
    generalized_kelly,
    size,
)
from sizer_engine.config import EngineConfig
from sizer_engine.schemas import Outcome, PayoffStructure


def dice_request(bankroll: float) -> SizeRequest:
    return SizeRequest(
        bankroll=bankroll,
        bankroll_segregated=True,
        kelly_fraction=1.0,  # exact_math edge: full Kelly is defensible
        trade_type=TradeType.prediction,
        edge_estimate=EdgeEstimate(win_probability=0.55, payoff_ratio=1.0),
        edge_source=EdgeSource.exact_math,
        trade=TradeStructure(payoff_structure=PayoffStructure.binary),
        instrument=Instrument(instrument_id="theater-dice", max_fill=500.0),
        # Segregated one-game entertainment bankroll: the diversification caps
        # are meaningless here, so the user lifts them (see DECISIONS.md #1).
        constraints={"per_trade_risk_cap": 0.5, "portfolio_heat_cap": 0.5,
                     "correlation_bucket_cap": 0.5},
    )


DICE_CONFIG = EngineConfig.model_validate(
    {**DEFAULT_CONFIG.model_dump(), "risk": {**DEFAULT_CONFIG.risk.model_dump(),
                                             "per_trade_risk_hard_ceiling": 1.0}}
)


class TestGolden1Dice:
    def test_small_bankroll_kelly_bound_capacity_inert(self):
        resp = size(dice_request(1_000), DICE_CONFIG)
        # Full Kelly at 55/45 even money is exactly 10% -> $100.
        assert resp.explanation.full_kelly_risk_pct == pytest.approx(0.10, abs=1e-9)
        assert resp.recommendation.risk_dollars == pytest.approx(100.0, abs=0.01)
        assert resp.explanation.binding_constraint == "fractional_kelly"
        capacity_row = next(c for c in resp.explanation.cap_table if c.constraint == "capacity")
        assert capacity_row.risk_dollars == pytest.approx(500.0)
        assert not capacity_row.binding
        # exact_math: no shrinkage, no exploration.
        assert resp.explanation.working_edge.expectancy_r == pytest.approx(0.10)
        assert resp.explanation.working_edge.ci_expectancy_r.low == pytest.approx(0.10)
        assert resp.meta.exploration_stage is None
        assert resp.explanation.tail_factor == 1.0

    def test_grown_bankroll_capacity_bound_not_risk_bound(self):
        resp = size(dice_request(8_000), DICE_CONFIG)
        assert resp.explanation.binding_constraint == "capacity"
        assert resp.recommendation.risk_dollars == pytest.approx(500.0, abs=0.01)
        assert any(w.code == "capacity_limited" for w in resp.diagnostics.warnings)
        assert any("different strategies" in s for s in resp.diagnostics.suggestions)
        # Risk caps are NOT what limited this bet.
        risk_row = next(c for c in resp.explanation.cap_table
                        if c.constraint == "per_trade_risk_cap")
        assert not risk_row.binding


class TestGolden2FuturesDayTrader:
    def request(self) -> SizeRequest:
        return SizeRequest(
            bankroll=50_000,
            trade_type=TradeType.shortterm,
            edge_estimate=EdgeEstimate(win_probability=0.40, payoff_ratio=2.5),
            edge_source=EdgeSource.live_track_record,
            sample_size=500,
            realized_results=RealizedResults(
                n_trades=500, win_rate=0.40, avg_win_r=2.5, avg_loss_r=1.0),
            strategy_id="es-orb",
            trade=TradeStructure(direction="long", entry_price=5000, stop_price=4990,
                                 expected_time_in_trade_days=0.2),
            instrument=Instrument(instrument_id="ES", point_value=50, volatility_atr=6,
                                  adv=2e9, liquidity_tier="deep",
                                  correlation_bucket="us_equity_index"),
            constraints={"daily_loss_limit": 1_500},
            intraday_pnl=-300,
        )

    def test_risk_cap_binds_capacity_inert(self):
        resp = size(self.request())
        assert resp.explanation.binding_constraint == "per_trade_risk_cap"
        assert resp.explanation.binding_layer == "layer2_risk"
        # 2% cap under a 1.3x tail factor admits ~1.54% of bankroll.
        assert resp.recommendation.risk_pct_bankroll == pytest.approx(0.02 / 1.3, rel=1e-6)
        capacity_row = next(c for c in resp.explanation.cap_table if c.constraint == "capacity")
        assert not capacity_row.binding
        assert capacity_row.risk_pct > 1.0  # orders of magnitude of headroom: inert
        assert resp.meta.sizing_model_applied == "continuous_kelly"
        # 500-trade record: exploration graduated.
        assert resp.meta.exploration_stage is None
        # Streak illustration is mandatory for shortterm.
        assert resp.diagnostics.losing_streaks is not None
        assert resp.diagnostics.losing_streaks.expected_max_streak >= 5

    def test_daily_loss_limit_halts(self):
        req = self.request()
        req.intraday_pnl = -1_600
        resp = size(req)
        assert resp.recommendation.risk_dollars == 0
        assert resp.explanation.binding_constraint == "daily_loss_limit"
        assert any(w.code == "daily_loss_limit_hit" and w.severity == "danger"
                   for w in resp.diagnostics.warnings)


class TestGolden3SportsBettor:
    B = 100 / 110  # -110 american odds payoff

    def request(self, open_positions: list[OpenPosition]) -> SizeRequest:
        return SizeRequest(
            bankroll=200_000,
            trade_type=TradeType.prediction,
            edge_estimate=EdgeEstimate(win_probability=0.54, payoff_ratio=self.B),
            edge_source=EdgeSource.live_track_record,
            sample_size=1_200,
            user_calibration_data=True,
            market_price=110 / 210,  # vig-implied break-even probability
            trade=TradeStructure(payoff_structure=PayoffStructure.binary,
                                 expected_time_in_trade_days=1),
            instrument=Instrument(instrument_id="cbb-sides", max_fill=10_000,
                                  correlation_bucket="saturday_slate"),
            open_positions=open_positions,
        )

    def test_single_bet_kelly_bound(self):
        resp = size(self.request([]))
        assert resp.explanation.binding_constraint == "fractional_kelly"
        # Quarter Kelly of a ~2.5% full-Kelly edge: several hundred to ~$1.5K.
        assert 800 <= resp.recommendation.risk_dollars <= 1_600
        assert resp.recommendation.risk_dollars < 10_000  # inside book limit
        assert resp.explanation.tail_factor == 1.0  # settled bets: discrete outcomes

    def test_slate_becomes_bucket_bound(self):
        open_pos: list[OpenPosition] = []
        bindings, risks = [], []
        for i in range(10):
            resp = size(self.request(open_pos))
            bindings.append(resp.explanation.binding_constraint)
            risks.append(resp.recommendation.risk_dollars)
            open_pos.append(OpenPosition(
                instrument_id=f"game-{i}", open_risk=resp.recommendation.risk_dollars,
                correlation_bucket="saturday_slate"))
        assert bindings[0] == "fractional_kelly"
        assert bindings[-1] == "correlation_bucket"
        # Slate total pinned to the 6% bucket cap, not 10x the single-bet size.
        assert sum(risks) <= 0.06 * 200_000 + 1e-6
        last = size(self.request(open_pos))
        assert any(w.code == "correlation_concentration"
                   for w in last.diagnostics.warnings)


class TestGolden4PredictionMarket:
    def request(self) -> SizeRequest:
        return SizeRequest(
            bankroll=10_000,
            trade_type=TradeType.prediction,
            edge_estimate=EdgeEstimate(win_probability=0.50),
            edge_source=EdgeSource.guess,
            market_price=0.30,
            trade=TradeStructure(entry_price=0.30, payoff_structure=PayoffStructure.binary,
                                 hold_to_resolution=True, expected_time_in_trade_days=180),
            instrument=Instrument(instrument_id="election-2026-A",
                                  correlation_bucket="election-2026"),
            constraints={"per_trade_risk_cap": 0.05},
        )

    def test_shrinkage_quarter_kelly_lockup(self):
        resp = size(self.request())
        # Guess shrunk halfway toward the 0.30 market: 0.50 -> 0.40.
        assert resp.explanation.working_edge.win_probability == pytest.approx(0.40)
        # Binary Kelly at p=0.40, b=7/3: f* = 1/7.
        assert resp.explanation.full_kelly_risk_pct == pytest.approx(1 / 7, abs=1e-6)
        assert resp.explanation.kelly_fraction_used == 0.25
        # Quarter Kelly x ~0.85 lockup discount: ~3% of bankroll.
        assert resp.recommendation.risk_pct_bankroll == pytest.approx(0.030, abs=0.003)
        assert resp.explanation.multipliers["lockup"] < 0.90
        # Explanation names shrinkage and lockup.
        assert "market" in resp.explanation.working_edge.shrinkage_applied
        assert any(w.code == "capital_lockup" for w in resp.diagnostics.warnings)
        assert "shrink" in resp.human_readable_summary.lower() \
            or "market" in resp.human_readable_summary.lower()
        # Max loss is the premium: size in contracts at $0.30 each.
        assert resp.recommendation.size_units == pytest.approx(
            resp.recommendation.risk_dollars / 0.30)


class TestGolden5PremiumSeller:
    def request(self) -> SizeRequest:
        return SizeRequest(
            bankroll=100_000,
            trade_type=TradeType.premium,
            edge_estimate=EdgeEstimate(win_probability=0.90, payoff_ratio=0.20),
            edge_source=EdgeSource.live_track_record,
            sample_size=200,
            realized_results=RealizedResults(
                n_trades=200, win_rate=0.90, avg_win_r=0.20, avg_loss_r=1.0),
            trade=TradeStructure(structural_max_loss=2_000,
                                 expected_time_in_trade_days=30),
            instrument=Instrument(instrument_id="spx-put-credit",
                                  correlation_bucket="short_vol"),
        )

    def test_tail_multiplier_crushes_observed_kelly(self):
        resp = size(self.request())
        observed_kelly = generalized_kelly([
            Outcome(probability=0.90, r=0.20), Outcome(probability=0.10, r=-1.0)])
        assert observed_kelly == pytest.approx(0.40, abs=0.01)  # seductive and wrong
        # Stressed full Kelly is a small fraction of the observed-distribution Kelly.
        assert resp.explanation.full_kelly_risk_pct < 0.15 * observed_kelly
        # Final size well below even quarter-Kelly-of-observed (10%).
        assert resp.recommendation.risk_pct_bankroll < 0.01
        assert resp.explanation.tail_factor >= 3.0
        assert resp.meta.sizing_model_applied == "generalized_kelly_stressed"
        codes = {w.code for w in resp.diagnostics.warnings}
        assert "premium_tail" in codes
        assert "no_tail_in_sample" in codes
        assert any(w.severity == "danger" for w in resp.diagnostics.warnings)

    def test_covered_call_declared_lottery_is_resized_as_premium(self):
        req = self.request()
        req.trade_type = TradeType.lottery  # user misdeclares a premium shape
        resp = size(req)
        assert resp.meta.trade_type_used == TradeType.premium
        assert resp.meta.type_mismatch
        assert "premium" in resp.meta.type_mismatch_detail


class TestGolden6NewStrategy:
    def request(self) -> SizeRequest:
        return SizeRequest(
            bankroll=20_000,
            trade_type=TradeType.trading,
            edge_estimate=EdgeEstimate(win_probability=0.50, payoff_ratio=1.8),
            edge_source=EdgeSource.guess,
            sample_size=0,
            strategy_id="new-idea",
            trade=TradeStructure(direction="long", entry_price=100, stop_price=95),
            instrument=Instrument(instrument_id="XYZ", volatility_atr=4, adv=5e7,
                                  liquidity_tier="deep"),
        )

    def test_exploration_size_and_binding(self):
        resp = size(self.request())
        assert resp.explanation.binding_constraint == "exploration"
        assert 0.0025 <= resp.recommendation.risk_pct_bankroll <= 0.005
        assert resp.meta.exploration_stage == "exploration"
        assert any("exploration" in s.lower() or "strategy_id" in s
                   for s in resp.diagnostics.suggestions)
        # Guess: edge discounted 50% and CI is wide.
        we = resp.explanation.working_edge
        assert we.expectancy_r == pytest.approx(0.5 * we.raw_expectancy_r, rel=1e-6)
        assert we.ci_expectancy_r.low < 0 < we.ci_expectancy_r.high

    def test_override_on_zero_evidence_guess_is_refused(self):
        # Demanding full sizing on a zero-sample guess is exactly the
        # "low-confidence number presented as confident" the refusal path
        # exists to prevent.
        from sizer_engine import RefusalError
        req = self.request()
        req.exploration_override = True
        with pytest.raises(RefusalError) as exc:
            size(req)
        assert exc.value.refusal.refusal_code == "edge_too_uncertain_for_aggression"
        assert exc.value.refusal.what_is_needed
