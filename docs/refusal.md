# Refusals

When the engine cannot produce a number it would stand behind, it returns a
structured refusal — HTTP 422 — with reasoning and what's needed to proceed.
This is a feature, not an error state: a low-confidence number presented
confidently is the worst output a sizing tool can emit.

Refusal codes:
- `contradictory_inputs` — stop on the wrong side of entry, target below a
  long entry, open risk exceeding bankroll…
- `risk_undefined` / `unbounded_downside` — no stop and no structural max
  loss; the loss per unit cannot be bounded.
- `edge_too_uncertain_for_aggression` — the edge CI reaches deeply negative
  territory while the request demands aggressive sizing (kelly_fraction ≥ 0.5
  or exploration override). The same edge is happily sized at exploration
  scale.
- `capacity_unresolvable` — thin market, no liquidity figures, policy=reject.
- `heat_budget_exceeded` — policy=reject and no heat/bucket headroom.

Every refusal includes `what_is_needed`: the specific evidence or corrections
that would unlock a recommendation.
