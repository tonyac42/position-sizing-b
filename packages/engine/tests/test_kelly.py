"""Kelly solver unit tests against known analytical results."""
import math

import pytest

from sizer_engine import (
    binary_kelly,
    continuous_kelly,
    generalized_kelly,
    kelly_fraction_from_drawdown_tolerance,
)
from sizer_engine.schemas import Outcome


class TestBinaryKelly:
    def test_classic_55_45_even_money(self):
        # Textbook: f* = p - q at even money = 0.10
        assert binary_kelly(0.55, 1.0) == pytest.approx(0.10)

    def test_thorp_example_2_to_1(self):
        # p=0.5, b=2: f* = (2*0.5 - 0.5)/2 = 0.25
        assert binary_kelly(0.5, 2.0) == pytest.approx(0.25)

    def test_prediction_contract(self):
        # Buy at 0.30 with true p=0.40: b = 7/3, f* = (bp - q)/b = 1/7
        b = 0.7 / 0.3
        assert binary_kelly(0.40, b) == pytest.approx((b * 0.4 - 0.6) / b)
        assert binary_kelly(0.40, b) == pytest.approx(0.142857, abs=1e-5)

    def test_no_edge_returns_zero(self):
        assert binary_kelly(0.5, 1.0) == 0.0

    def test_negative_edge_returns_zero(self):
        assert binary_kelly(0.45, 1.0) == 0.0

    def test_degenerate_inputs(self):
        assert binary_kelly(0.0, 1.0) == 0.0
        assert binary_kelly(1.0, 1.0) == 0.0
        assert binary_kelly(0.55, 0.0) == 0.0


class TestContinuousKelly:
    def test_mean_over_variance(self):
        assert continuous_kelly(0.1, 0.04) == pytest.approx(2.5)

    def test_zero_variance(self):
        assert continuous_kelly(0.1, 0.0) == 0.0

    def test_negative_mean(self):
        assert continuous_kelly(-0.1, 0.04) == 0.0


class TestGeneralizedKelly:
    def test_matches_binary_closed_form(self):
        # Generalized solver on a two-point distribution must reproduce the
        # binary closed form across a grid of (p, b).
        for p in (0.3, 0.4, 0.55, 0.7, 0.9):
            for b in (0.5, 1.0, 2.0, 5.0):
                expected = binary_kelly(p, b)
                got = generalized_kelly([
                    Outcome(probability=p, r=b),
                    Outcome(probability=1 - p, r=-1.0),
                ])
                assert got == pytest.approx(expected, abs=1e-6), (p, b)

    def test_published_example_three_outcome(self):
        # Win 2R with p=0.3, scratch 0 with p=0.4, lose 1R with p=0.3.
        # Stationarity: 0.6/(1+2f) = 0.3/(1-f)  =>  f = 0.25 exactly.
        outcomes = [
            Outcome(probability=0.3, r=2.0),
            Outcome(probability=0.4, r=0.0),
            Outcome(probability=0.3, r=-1.0),
        ]
        f = generalized_kelly(outcomes)
        deriv = 0.3 * 2 / (1 + 2 * f) - 0.3 / (1 - f)
        assert abs(deriv) < 1e-6
        assert f == pytest.approx(0.25, abs=1e-6)

    def test_negative_ev_returns_zero(self):
        outcomes = [Outcome(probability=0.4, r=1.0), Outcome(probability=0.6, r=-1.0)]
        assert generalized_kelly(outcomes) == 0.0

    def test_never_bets_past_ruin_boundary(self):
        # Worst loss -2R: f must stay below 0.5 regardless of edge.
        outcomes = [Outcome(probability=0.95, r=1.0), Outcome(probability=0.05, r=-2.0)]
        f = generalized_kelly(outcomes)
        assert 0 < f < 0.5

    def test_skewed_lottery_distribution(self):
        # 10% chance of +15R, 90% lose 1R: EV = +0.6R. Kelly stays modest
        # because losses dominate the path.
        outcomes = [Outcome(probability=0.10, r=15.0), Outcome(probability=0.90, r=-1.0)]
        f = generalized_kelly(outcomes)
        expected = binary_kelly(0.10, 15.0)  # two-point => closed form applies
        assert f == pytest.approx(expected, abs=1e-6)
        assert f < 0.05  # (bp-q)/b = (1.5-0.9)/15 = 0.04

    def test_log_growth_positive_at_solution(self):
        outcomes = [Outcome(probability=0.55, r=1.0), Outcome(probability=0.45, r=-1.0)]
        f = generalized_kelly(outcomes)
        growth = 0.55 * math.log(1 + f) + 0.45 * math.log(1 - f)
        assert growth > 0


class TestDrawdownMapping:
    def test_formula(self):
        # c = 2 / (1 + ln(q)/ln(1-D)); D=20%, q=10%
        c = kelly_fraction_from_drawdown_tolerance(0.20, 0.10)
        expected = 2.0 / (1.0 + math.log(0.10) / math.log(0.80))
        assert c == pytest.approx(expected)

    def test_monotone_in_tolerance(self):
        # More drawdown tolerance -> larger Kelly fraction.
        cs = [kelly_fraction_from_drawdown_tolerance(d, 0.10) for d in (0.1, 0.2, 0.3, 0.5)]
        assert cs == sorted(cs)

    def test_rejects_bad_input(self):
        with pytest.raises(ValueError):
            kelly_fraction_from_drawdown_tolerance(1.5)
