"""Refusal path, determinism, classifier, and Layer-0 behavior tests."""
import pytest

from sizer_engine import (
    EdgeEstimate,
    EdgeSource,
    FieldConfidence,
    Instrument,
    RealizedResults,
    RefusalError,
    SizeRequest,
    TradeStructure,
    TradeType,
    size,
)


def req(**over) -> SizeRequest:
    kw = dict(
        bankroll=50_000,
        trade_type=TradeType.trading,
        edge_estimate=EdgeEstimate(win_probability=0.55, payoff_ratio=1.5),
        edge_source=EdgeSource.live_track_record,
        sample_size=400,
        trade=TradeStructure(direction="long", entry_price=100, stop_price=96),
        instrument=Instrument(instrument_id="TEST", volatility_atr=3.0, adv=1e8,
                              liquidity_tier="deep"),
    )
    kw.update(over)
    return SizeRequest(**kw)


class TestRefusals:
    def test_target_below_entry_long(self):
        with pytest.raises(RefusalError) as e:
            size(req(trade=TradeStructure(direction="long", entry_price=100,
                                          stop_price=96, target_price=90)))
        assert e.value.refusal.refusal_code == "contradictory_inputs"

    def test_open_risk_exceeding_bankroll(self):
        from sizer_engine import OpenPosition
        with pytest.raises(RefusalError) as e:
            size(req(open_positions=[OpenPosition(instrument_id="x", open_risk=60_000)]))
        assert e.value.refusal.refusal_code == "contradictory_inputs"

    def test_no_stop_no_structural_loss(self):
        with pytest.raises(RefusalError) as e:
            size(req(trade=TradeStructure(direction="long", entry_price=100)))
        assert e.value.refusal.refusal_code == "risk_undefined"

    def test_uncertain_edge_with_aggressive_kelly(self):
        with pytest.raises(RefusalError) as e:
            size(req(edge_source=EdgeSource.guess, sample_size=0, kelly_fraction=0.5))
        assert e.value.refusal.refusal_code == "edge_too_uncertain_for_aggression"
        # The refusal explains what would unlock sizing.
        assert any("track record" in n or "exploration" in n
                   for n in e.value.refusal.what_is_needed)

    def test_same_guess_at_default_kelly_is_sized_not_refused(self):
        # "Never refuses to size a new strategy" — without aggressive intent
        # the same edge gets an exploration-scale answer.
        resp = size(req(edge_source=EdgeSource.guess, sample_size=0))
        assert resp.status == "ok"
        assert resp.explanation.binding_constraint == "exploration"

    def test_thin_market_unresolved_capacity_reject_policy(self):
        with pytest.raises(RefusalError) as e:
            size(req(instrument=Instrument(instrument_id="ILLIQ", volatility_atr=3.0,
                                           liquidity_tier="thin"),
                     constraints={"capacity_policy": "reject"}))
        assert e.value.refusal.refusal_code == "capacity_unresolvable"

    def test_position_without_downside_estimate(self):
        with pytest.raises(RefusalError) as e:
            size(req(trade_type=TradeType.position,
                     trade=TradeStructure(direction="long", entry_price=100,
                                          expected_time_in_trade_days=180)))
        assert e.value.refusal.refusal_code == "unbounded_downside"

    def test_refusal_is_structured(self):
        try:
            size(req(trade=TradeStructure(direction="long", entry_price=100, stop_price=105)))
        except RefusalError as e:
            r = e.refusal
            assert r.status == "refusal"
            assert r.reasoning
            assert r.what_is_needed
            assert r.meta is not None and r.meta.input_hash


class TestDeterminism:
    def test_identical_requests_identical_outputs(self):
        a = size(req()).model_dump(exclude={"meta": {"timestamp"}})
        b = size(req()).model_dump(exclude={"meta": {"timestamp"}})
        assert a == b

    def test_seed_derived_from_input_hash(self):
        r1, r2 = size(req()), size(req())
        assert r1.diagnostics.drawdown_paths.seed == r2.diagnostics.drawdown_paths.seed
        assert r1.diagnostics.drawdown_paths.worst_5pct_path == \
            r2.diagnostics.drawdown_paths.worst_5pct_path

    def test_explicit_seed_respected(self):
        r = size(req(mc_seed=42))
        assert r.diagnostics.drawdown_paths.seed == 42

    def test_different_inputs_different_hash(self):
        assert size(req()).meta.input_hash != size(req(bankroll=60_000)).meta.input_hash


class TestClassifier:
    def test_binary_infers_prediction(self):
        r = req(trade_type="auto", market_price=0.4,
                edge_estimate=EdgeEstimate(win_probability=0.5),
                trade=TradeStructure(entry_price=0.4))
        assert size(r).meta.trade_type_used == TradeType.prediction

    def test_low_winrate_big_payoff_infers_lottery(self):
        r = req(trade_type="auto",
                edge_estimate=EdgeEstimate(win_probability=0.15, payoff_ratio=8.0),
                trade=TradeStructure(structural_max_loss=100))
        resp = size(r)
        assert resp.meta.trade_type_used == TradeType.lottery
        # Streak illustration mandatory for lottery.
        assert resp.diagnostics.losing_streaks is not None

    def test_intraday_infers_shortterm(self):
        r = req(trade_type="auto",
                trade=TradeStructure(direction="long", entry_price=100, stop_price=98,
                                     expected_time_in_trade_days=0.2))
        assert size(r).meta.trade_type_used == TradeType.shortterm

    def test_long_hold_no_stop_infers_position(self):
        r = req(trade_type="auto",
                trade=TradeStructure(direction="long", entry_price=100,
                                     structural_max_loss=40,
                                     expected_time_in_trade_days=270))
        assert size(r).meta.trade_type_used == TradeType.position

    def test_mismatch_flagged(self):
        r = req(trade_type=TradeType.lottery)  # structure says trading
        resp = size(r)
        assert resp.meta.type_mismatch
        assert any(w.code == "trade_type_mismatch" for w in resp.diagnostics.warnings)


class TestLayer0:
    def test_backtest_discounted_half(self):
        resp = size(req(edge_source=EdgeSource.backtest, sample_size=1000))
        we = resp.explanation.working_edge
        assert we.expectancy_r == pytest.approx(0.5 * we.raw_expectancy_r, rel=1e-9)

    def test_related_experience_similarity_scales_discount(self):
        hi = size(req(edge_source=EdgeSource.related_experience, similarity=1.0))
        lo = size(req(edge_source=EdgeSource.related_experience, similarity=0.0))
        assert hi.explanation.working_edge.expectancy_r == pytest.approx(
            0.7 * hi.explanation.working_edge.raw_expectancy_r, rel=1e-9)
        assert lo.explanation.working_edge.expectancy_r == pytest.approx(
            0.5 * lo.explanation.working_edge.raw_expectancy_r, rel=1e-9)

    def test_track_record_blend_shifts_with_sample(self):
        def r(n):
            return size(req(
                sample_size=n,
                realized_results=RealizedResults(n_trades=n, win_rate=0.50,
                                                 avg_win_r=1.5, avg_loss_r=1.0),
            )).explanation.working_edge.expectancy_r
        # Claimed 0.375R (p=.55,b=1.5); realized 0.25R. More data -> closer to realized.
        assert r(300) < r(50)
        assert abs(r(300) - 0.25) < abs(r(50) - 0.25)
        # By 300 trades realized dominates (>80% weight).
        assert r(300) == pytest.approx(0.25, abs=0.03)

    def test_exploration_gates_progression(self):
        def stage(n):
            return size(req(edge_source=EdgeSource.backtest, sample_size=n)
                        ).meta.exploration_stage
        assert stage(0) == "exploration"
        assert stage(50) == "quarter_kelly"
        assert stage(150) == "half_kelly"
        assert stage(400) is None

    def test_gate_caps_enforced(self):
        r50 = size(req(edge_source=EdgeSource.backtest, sample_size=50))
        assert r50.recommendation.risk_pct_bankroll <= 0.01 + 1e-12
        r150 = size(req(edge_source=EdgeSource.backtest, sample_size=150))
        assert r150.recommendation.risk_pct_bankroll <= 0.02 + 1e-12

    def test_non_user_stated_edge_flagged_and_haircut(self):
        stated = size(req())
        inferred = size(req(field_confidence={"edge_estimate": FieldConfidence.inferred}))
        assert "edge_estimate" in inferred.meta.confirm_fields
        assert any(w.code == "unconfirmed_critical_fields" for w in inferred.diagnostics.warnings)
        assert inferred.explanation.working_edge.expectancy_r < \
            stated.explanation.working_edge.expectancy_r

    def test_equity_throttle(self):
        r = size(req(peak_equity=60_000,  # 50k/60k = 16.7% drawdown -> flat per default schedule
                     constraints={"equity_throttle_schedule": [[0.05, 1.0], [0.10, 0.75],
                                                               [0.15, 0.5], [1.0, 0.0]]}))
        assert r.recommendation.risk_dollars == 0
        r2 = size(req(peak_equity=52_000,  # 3.8% drawdown -> full size
                      constraints={"equity_throttle_schedule": [[0.05, 1.0], [0.10, 0.75],
                                                                [0.15, 0.5], [1.0, 0.0]]}))
        assert r2.explanation.multipliers["equity_throttle"] == 1.0
