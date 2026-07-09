# Edge shrinkage (Layer 0)

Everything downstream depends on the working edge, so the engine never takes
a claimed edge at face value. The discount depends on where the claim comes
from:

| Source | Treatment |
|---|---|
| `exact_math` | trusted fully — dice odds don't lie |
| `live_track_record` | Bayesian blend of claim and realized results; weight on realized data is n/(n+60), so by ~300 trades the record dominates |
| `backtest` | expectancy halved — real edges run about half of backtests |
| `related_experience` | discounted 30–50% depending on declared similarity |
| `guess` | expectancy halved AND exploration mode forced |

For `prediction` trades the shrinkage target is the **market price**: your
probability is pulled halfway toward it by default, less (25%) with documented
calibration data, more (75%) for an unstructured guess. The market has skin in
the game; your intuition doesn't yet.

Mechanically, win probabilities are shrunk toward the breakeven probability
(which scales expectancy exactly); full outcome distributions are translated
so the mean scales while the shape — the skew that drives lottery/premium
sizing — is preserved.

The working edge always carries a confidence interval. A wide CI doesn't stop
the engine from sizing (exploration gates handle that), but a CI reaching
deeply negative territory combined with an aggressive sizing request triggers
a [refusal](refusal.md).
