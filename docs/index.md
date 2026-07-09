# Sizer documentation

Every constraint concept the engine can name in a response has a page here.
API responses reference these slugs in `doc_slug` fields; the UI links
warnings to them.

## The layer stack
- [Trade types](trade-types.md) — the six sizing philosophies and the classifier
- [Edge shrinkage](shrinkage.md) — Layer 0: why your claimed edge gets discounted
- [Exploration gates](exploration.md) — Layer 0: sizing a strategy with no track record
- [Kelly criterion](kelly.md) — Layer 1: the growth-optimal reference point
- [Kelly fraction](kelly-fraction.md) — Layer 1: fractional Kelly and the drawdown mapping
- [Per-trade risk cap](per-trade-risk.md) — Layer 2
- [Volatility cap](volatility-cap.md) — Layer 2
- [Portfolio heat](portfolio-heat.md) — Layer 2
- [Correlation buckets](correlation-buckets.md) — Layer 2
- [Daily loss limit](daily-loss-limit.md) — Layer 2
- [Market capacity](capacity.md) — Layer 3
- [Tail risk](tail-risk.md) — Layer 4
- [Stop reliability](stop-reliability.md) — Layer 4
- [Capital lockup](lockup.md) — Layer 5

## Cross-cutting
- [Refusals](refusal.md) — when the engine declines to give a number
- [Field confidence](field-confidence.md) — the LLM-interface honesty map
- [Versioning](versioning.md) — engine vs methodology versions, pinning
