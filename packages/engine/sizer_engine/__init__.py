"""sizer_engine: universal position sizing.

Pure, deterministic, transport-agnostic. Public surface:

    from sizer_engine import size, SizeRequest, SizeResponse, RefusalError
"""
from .config import DEFAULT_CONFIG, EngineConfig
from .engine import compute_input_hash, size
from .kelly import (
    binary_kelly,
    continuous_kelly,
    generalized_kelly,
    kelly_fraction_from_drawdown_tolerance,
)
from .schemas import (
    CapacityPolicy,
    EdgeEstimate,
    EdgeSource,
    FieldConfidence,
    Instrument,
    LiquidityTier,
    OpenPosition,
    Outcome,
    PayoffStructure,
    RealizedResults,
    Recommendation,
    RefusalError,
    SizeRequest,
    SizeResponse,
    SizingRefusal,
    TailProfile,
    TradeStructure,
    TradeType,
)
from .version import ENGINE_VERSION, METHODOLOGY_VERSION

__all__ = [
    "size", "compute_input_hash", "SizeRequest", "SizeResponse", "SizingRefusal",
    "RefusalError", "EngineConfig", "DEFAULT_CONFIG",
    "binary_kelly", "continuous_kelly", "generalized_kelly",
    "kelly_fraction_from_drawdown_tolerance",
    "TradeType", "EdgeSource", "EdgeEstimate", "Outcome", "RealizedResults",
    "OpenPosition", "Instrument", "TradeStructure", "PayoffStructure",
    "LiquidityTier", "TailProfile", "CapacityPolicy", "FieldConfidence",
    "Recommendation", "ENGINE_VERSION", "METHODOLOGY_VERSION",
]
