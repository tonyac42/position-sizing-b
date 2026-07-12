# Trade types

The engine routes every request to one of six sizing philosophies. Declaring
the type is optional (`trade_type: "auto"` classifies from structure), but a
mismatch between the declared type and the trade's shape is flagged — and one
mismatch is corrected for safety: a trade whose payoff shape is premium
collection (high win rate, small wins, rare large losses) is **always sized as
`premium`** regardless of declaration, because under-recognized short-vol is
the classic account-ender.

| Type | Shape | Solver | What dominates the sizing |
|---|---|---|---|
| `lottery` | low win rate, large payoffs | generalized Kelly | surviving losing streaks; extra shrinkage on claimed win odds |
| `premium` | high win rate, rare catastrophes | generalized Kelly on a **stressed** distribution | the tail event your sample doesn't contain |
| `position` | months-long thesis holds | binary Kelly on thesis odds | concentration (bucket caps), lockup discount — not stop distance |
| `shortterm` | many small-edge intraday trades | continuous (mean/variance) Kelly | per-trade risk cap, daily loss limit, streak warnings |
| `prediction` | binary contracts, known max loss | binary Kelly | shrinkage toward the market price, lockup, thin-book capacity |
| `trading` | continuous market with stops | continuous Kelly | the Tharp caps: percent-risk and percent-volatility, min of the two |
