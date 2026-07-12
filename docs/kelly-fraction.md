# Kelly fraction

Full Kelly is growth-optimal and emotionally uninhabitable: it routinely sits
in 30–50% drawdowns. Everyone sane bets a fraction. Default here: **0.25**
(quarter Kelly), user-settable in 0.1–0.5. Exception: `exact_math` edges may
run up to 1.0 — when the odds are literally known, full Kelly is a defensible
choice for a segregated bankroll.

## Deriving the fraction from drawdown tolerance

If you state a tolerable drawdown instead, the engine maps it to a fraction
using the standard continuous-Kelly result (Thorp): betting fraction `c` of
Kelly, the probability of *ever* drawing down to fraction `x` of your
high-water mark is approximately

    P(DD ≥ D) = x^(2/c − 1),   x = 1 − D

Solving for `c` at a 10% breach probability:

    c = 2 / (1 + ln(0.10) / ln(1 − D))

Example: tolerating a 20% drawdown gives c ≈ 0.18. This is an approximation —
it assumes continuous, normal-ish returns — and it is deliberately
conservative for discrete, skewed trades.
