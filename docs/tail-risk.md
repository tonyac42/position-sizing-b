# Tail risk overlay (Layer 4)

Observed distributions understate what markets do occasionally. Before Layer
2 caps are checked, effective per-trade risk is multiplied by a tail factor:

| Situation | Factor |
|---|---|
| Discrete resolved outcomes (prediction held to resolution, settled bets, dice) | 1.0 |
| Liquid continuous markets, normal conditions | 1.3 |
| Moderate tail profile | 1.5 |
| Gap/event exposure (earnings, binary catalysts) | 2.5 |
| `premium` type | 3–4x **mandatory minimum** |
| Structural tail bombs (pegged currencies, event-window trades) | 5x, plus advice against normal sizing |

## Premium selling gets special treatment

A 90% win rate over 200 trades says nothing about the left tail — the sample
almost certainly does not contain the event that defines the strategy's true
distribution. So for `premium`:

- Kelly runs on a **stressed distribution**: a synthetic tail outcome
  (default 1–2% probability, loss = tail factor × observed worst loss) is
  injected before optimization.
- Observed-Sharpe/mean-variance sizing is structurally disabled.
- The danger-severity tail warning always fires. It is not noise; it is the
  product.
