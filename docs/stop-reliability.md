# Stop reliability (Layer 4)

A stop order is a hope, not a contract. The engine haircuts stop-based risk
by book quality:

| Book | Effective risk vs nominal stop distance |
|---|---|
| deep | 1.2x (routine slippage) |
| moderate | 1.5x |
| thin | 2.5x — stops fill far through their level |
| micro | stops treated as unavailable → sized against structural max loss |

This is why a prediction-market trade "managed with a stop" in a thin book
sizes barely better than holding to resolution: the engine prices the stop's
unreliability, not the intention. The payoff ratio is adjusted in the same
currency, so Kelly sees the slippage too.
