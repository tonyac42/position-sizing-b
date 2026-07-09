"""Seed instrument dataset. Designed to be swapped for a live data provider:
anything satisfying `InstrumentProvider.get(instrument_id)` can be plugged in.
"""
from __future__ import annotations

from typing import Protocol

SEED_INSTRUMENTS: dict[str, dict] = {
    "ES": {
        "instrument_id": "ES", "name": "E-mini S&P 500 futures",
        "point_value": 50.0, "volatility_atr": 55.0, "adv": 3.5e11,
        "liquidity_tier": "deep", "correlation_bucket": "us_equity_index",
        "tail_profile": "normal", "gap_risk": False,
    },
    "NQ": {
        "instrument_id": "NQ", "name": "E-mini Nasdaq-100 futures",
        "point_value": 20.0, "volatility_atr": 280.0, "adv": 1.8e11,
        "liquidity_tier": "deep", "correlation_bucket": "us_equity_index",
        "tail_profile": "normal", "gap_risk": False,
    },
    "CL": {
        "instrument_id": "CL", "name": "WTI crude oil futures",
        "point_value": 1000.0, "volatility_atr": 1.8, "adv": 4.0e10,
        "liquidity_tier": "deep", "correlation_bucket": "energy",
        "tail_profile": "moderate", "gap_risk": True,
    },
    "BTC-USD": {
        "instrument_id": "BTC-USD", "name": "Bitcoin spot",
        "point_value": 1.0, "volatility_atr": 2500.0, "adv": 2.0e10,
        "liquidity_tier": "deep", "correlation_bucket": "crypto",
        "tail_profile": "heavy", "gap_risk": True,
    },
    "SPX-0DTE-PUT": {
        "instrument_id": "SPX-0DTE-PUT", "name": "SPX same-day options (short premium)",
        "point_value": 100.0, "volatility_atr": None, "adv": 5.0e9,
        "liquidity_tier": "deep", "correlation_bucket": "short_vol",
        "tail_profile": "heavy", "gap_risk": True,
    },
    "POLYMARKET-GENERIC": {
        "instrument_id": "POLYMARKET-GENERIC", "name": "Prediction market contract (thin book)",
        "point_value": 1.0, "volatility_atr": None, "adv": None,
        "liquidity_tier": "thin", "correlation_bucket": "prediction_generic",
        "tail_profile": "normal", "gap_risk": False,
    },
    "USDHKD": {
        "instrument_id": "USDHKD", "name": "USD/HKD (pegged currency)",
        "point_value": 100000.0, "volatility_atr": 0.001, "adv": 1.0e10,
        "liquidity_tier": "deep", "correlation_bucket": "fx_pegs",
        "tail_profile": "extreme", "gap_risk": True,
    },
}


class InstrumentProvider(Protocol):
    def get(self, instrument_id: str) -> dict | None: ...


class StaticProvider:
    def __init__(self, data: dict[str, dict] | None = None):
        self.data = data or SEED_INSTRUMENTS

    def get(self, instrument_id: str) -> dict | None:
        return self.data.get(instrument_id)
