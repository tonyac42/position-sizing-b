# The Kelly criterion (Layer 1)

Kelly answers: what fraction of bankroll, staked repeatedly at these odds,
maximizes long-run compound growth? Bet more and volatility drag eats you;
enough more and ruin is certain. It is the ceiling on rational sizing — every
other layer only pushes the number down.

Three solvers, chosen by trade type:

- **Binary** — `f* = (bp − q)/b` for win/lose payoffs (prediction contracts,
  sports bets, dice).
- **Continuous** — `f* ≈ mean/variance` of per-trade returns, for
  approximately normal streams (day trading, stop-based trading).
- **Generalized** — numerical maximization of `E[log(1 + f·X)]` over an
  arbitrary discrete outcome distribution. Required where skew breaks the
  mean/variance approximation: lottery-shaped and premium-shaped trades. For
  premium, the distribution being maximized is the *stressed* one — see
  [tail risk](tail-risk.md).

All solvers work in R-space: `f*` is the fraction of bankroll lost if the
trade's defined risk (stop or structural max loss) is fully realized.
