# Capital lockup (Layer 5)

A prediction contract that resolves in six months, or a thesis position with
a year horizon, locks capital that can't chase other opportunities. For
long-dated `prediction`/`position` trades in concentrated bankrolls, size is
discounted by an opportunity cost multiplier:

    multiplier = max(0.5, 1 − 0.30 × years_locked)

(30%/year rate and 0.5 floor are configuration; no discount under 30 days or
for segregated bankrolls with immaterial stake sizes.)

Layer 5 is also where anti-martingale recalculation lives — sizes are always
computed against current total equity, so they shrink in drawdowns and grow
with the bankroll automatically — and where the growth-vs-capacity advice
comes from: when your bankroll outgrows a market's capacity ceiling, the
answer is more strategies, not more size.
