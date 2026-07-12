"""Trade-type classification: infer the type from trade structure and flag
mismatches against a declared type.

Heuristics (in priority order):
  1. binary payoff or market_price in (0,1)          -> prediction
  2. capped upside + high win prob + small payoff     -> premium (short options shape)
  3. low win prob + large payoff / unbounded upside   -> lottery (long convexity)
  4. months-long hold, no stop, thesis structure      -> position
  5. intraday holding period                          -> shortterm
  6. otherwise                                        -> trading
"""
from __future__ import annotations

from dataclasses import dataclass

from .schemas import PayoffStructure, SizeRequest, TradeType


@dataclass
class Classification:
    inferred: TradeType
    used: TradeType
    declared: str
    mismatch: bool
    detail: str


def infer_trade_type(req: SizeRequest) -> tuple[TradeType, str]:
    t = req.trade
    e = req.edge_estimate
    p = e.win_probability if e.win_probability is not None else e.win_rate
    b = e.payoff_ratio

    if e.outcomes and (p is None or b is None):
        wins = [o for o in e.outcomes if o.r > 0]
        losses = [o for o in e.outcomes if o.r < 0]
        if wins and losses:
            pw = sum(o.probability for o in wins)
            avg_w = sum(o.probability * o.r for o in wins) / pw
            pl = sum(o.probability for o in losses)
            avg_l = -sum(o.probability * o.r for o in losses) / pl
            p = p if p is not None else pw
            b = b if b is not None else (avg_w / avg_l if avg_l else None)

    if t.payoff_structure == PayoffStructure.binary or req.market_price is not None:
        return TradeType.prediction, "binary payoff / market price in (0,1)"

    if p is not None and b is not None:
        if p >= 0.70 and b <= 0.5:
            return TradeType.premium, (
                f"high win rate ({p:.0%}) with small wins vs large losses (payoff {b:.2f}) "
                "is a premium-collection shape"
            )
        if p <= 0.35 and b >= 3.0:
            return TradeType.lottery, (
                f"low win rate ({p:.0%}) with large payoff ({b:.1f}R) is a long-convexity shape"
            )

    days = t.expected_time_in_trade_days
    if days is not None and days >= 60 and t.stop_price is None:
        return TradeType.position, "months-long hold with no stop: thesis position"
    if days is not None and days <= 1:
        return TradeType.shortterm, "intraday holding period"

    return TradeType.trading, "continuous market trade with a stop (default)"


def classify(req: SizeRequest) -> Classification:
    inferred, detail = infer_trade_type(req)
    if req.trade_type == "auto":
        return Classification(
            inferred=inferred, used=inferred, declared="auto",
            mismatch=False, detail=detail,
        )
    declared = TradeType(req.trade_type)
    mismatch = declared != inferred
    note = ""
    if mismatch:
        note = (f"declared '{declared.value}' but the trade structure looks like "
                f"'{inferred.value}' ({detail}); sized as declared — confirm the type")
        # Safety exception: a trade declared lottery/trading whose structure is
        # premium gets sized as premium. Under-recognized short-vol is the
        # classic blowup; the reverse mistakes are conservative.
        if inferred == TradeType.premium and declared != TradeType.premium:
            return Classification(
                inferred=inferred, used=TradeType.premium, declared=declared.value,
                mismatch=True,
                detail=(f"declared '{declared.value}' but payoff shape is premium collection "
                        "(small frequent wins, rare large losses); sized as premium for safety"),
            )
    return Classification(
        inferred=inferred, used=declared, declared=declared.value,
        mismatch=mismatch, detail=note or detail,
    )
