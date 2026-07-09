"""Property tests: structural guarantees of the layer stack."""
import pytest
from hypothesis import given, settings, strategies as st

from sizer_engine import (
    EdgeEstimate,
    EdgeSource,
    Instrument,
    RefusalError,
    SizeRequest,
    TradeStructure,
    TradeType,
    size,
)


def base_request(**over) -> SizeRequest:
    kw = dict(
        bankroll=100_000,
        trade_type=TradeType.trading,
        edge_estimate=EdgeEstimate(win_probability=0.55, payoff_ratio=1.5),
        edge_source=EdgeSource.live_track_record,
        sample_size=400,
        trade=TradeStructure(direction="long", entry_price=100, stop_price=96),
        instrument=Instrument(instrument_id="TEST", volatility_atr=3.0,
                              adv=1e8, liquidity_tier="deep"),
    )
    kw.update(over)
    return SizeRequest(**kw)


@settings(max_examples=40, deadline=None)
@given(cap=st.floats(min_value=0.001, max_value=0.05))
def test_size_never_exceeds_per_trade_cap(cap):
    resp = size(base_request(constraints={"per_trade_risk_cap": cap}))
    for row in resp.explanation.cap_table:
        if row.risk_pct is not None and row.constraint != "full_kelly":
            assert resp.recommendation.risk_pct_bankroll <= row.risk_pct + 1e-12


@settings(max_examples=25, deadline=None)
@given(caps=st.lists(st.floats(min_value=0.001, max_value=0.05), min_size=2, max_size=2))
def test_monotone_in_risk_cap(caps):
    lo, hi = sorted(caps)
    r_lo = size(base_request(constraints={"per_trade_risk_cap": lo}))
    r_hi = size(base_request(constraints={"per_trade_risk_cap": hi}))
    assert r_lo.recommendation.risk_pct_bankroll <= r_hi.recommendation.risk_pct_bankroll + 1e-12


@settings(max_examples=25, deadline=None)
@given(kf=st.floats(min_value=0.10, max_value=0.50))
def test_monotone_in_kelly_fraction(kf):
    r = size(base_request(kelly_fraction=kf))
    r_full = size(base_request(kelly_fraction=0.50))
    assert r.recommendation.risk_pct_bankroll <= r_full.recommendation.risk_pct_bankroll + 1e-12


@settings(max_examples=25, deadline=None)
@given(heat=st.floats(min_value=0.0, max_value=0.18))
def test_monotone_in_open_heat(heat):
    from sizer_engine import OpenPosition
    positions = [OpenPosition(instrument_id="other", open_risk=heat * 100_000,
                              correlation_bucket="elsewhere")]
    r_loaded = size(base_request(open_positions=positions))
    r_empty = size(base_request())
    assert r_loaded.recommendation.risk_pct_bankroll <= r_empty.recommendation.risk_pct_bankroll + 1e-12


@settings(max_examples=20, deadline=None)
@given(p=st.floats(min_value=0.05, max_value=0.95),
       b=st.floats(min_value=0.2, max_value=8.0))
def test_output_bounded_and_binding_reported(p, b):
    resp = size(base_request(edge_estimate=EdgeEstimate(win_probability=p, payoff_ratio=b)))
    rec = resp.recommendation.risk_pct_bankroll
    assert 0.0 <= rec <= 1.0
    assert resp.explanation.binding_constraint
    assert any(row.binding for row in resp.explanation.cap_table)


def test_tighter_tail_profile_never_increases_size():
    sizes = []
    for profile in ("normal", "moderate", "heavy"):
        resp = size(base_request(
            instrument=Instrument(instrument_id="TEST", volatility_atr=3.0, adv=1e8,
                                  liquidity_tier="deep", tail_profile=profile)))
        sizes.append(resp.recommendation.risk_pct_bankroll)
    assert sizes == sorted(sizes, reverse=True)


def test_refusal_on_contradictory_stop():
    with pytest.raises(RefusalError) as exc:
        size(base_request(trade=TradeStructure(direction="long", entry_price=100,
                                               stop_price=105)))
    assert exc.value.refusal.refusal_code == "contradictory_inputs"
    assert exc.value.refusal.what_is_needed
