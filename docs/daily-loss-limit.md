# Daily loss limit (Layer 2, shortterm)

A halt-for-the-day threshold for `shortterm` traders. Supply
`constraints.daily_loss_limit` and today's `intraday_pnl`; once the day's
losses breach the limit, the engine recommends **zero** — binding constraint
`daily_loss_limit` — regardless of how good the next setup looks.

The rationale is regime detection and tilt control: a day that has already
taken your limit is evidence that today's market or today's you is not the
one your edge was measured on.
