# Exploration gates (Layer 0)

The tool never refuses to size a new strategy — it sizes it under uncertainty.
Until the strategy has a track record, size is capped by evidence, not by your
Kelly preference:

| Logged trades | Sizing |
|---|---|
| 0–30 | fixed exploration size, 0.25–0.5% of bankroll — large enough to matter, small enough that a wrong edge estimate is cheap, consistent so the sample is clean |
| 30–100 | quarter-Kelly against realized edge, capped at 1% |
| 100–300 | half-Kelly against realized edge, capped at 2% |
| 300+ | your preferred Kelly fraction |

Boundaries are configuration, not magic numbers.

Exemptions: `exact_math` edges (the edge is known from bet one), `prediction`
trades (the market price anchors the estimate — shrinkage is the uncertainty
control), and `position` trades (portfolio construction, not repeated
sampling, is the risk control). See DECISIONS.md #4.

Log outcomes via `POST /v1/track-record` (or the dashboard) to advance the
gates. `exploration_override: true` skips gates for graduated-adjacent cases —
but demanding full size on a zero-evidence guess is refused, not honored.
