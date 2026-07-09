# Per-trade risk cap (Layer 2)

The classic Van Tharp "percent risk" model: no single trade may lose more
than a fixed fraction of bankroll if its stop or structural max loss hits.
Default **2%**, with a configurable hard ceiling (default 10%).

The cap is checked against **tail-stressed** risk: under a 4x premium tail
factor, a 2% cap admits only 0.5% of nominal defined risk, because the loss
that matters is the one 4x past your stop. See [tail risk](tail-risk.md).

Wide-stop styles (trend following) naturally bind here — the stop distance is
big, so the unit count is what gives. If this cap binds you constantly,
understand what raising it buys: linearly more dollars at risk, superlinearly
worse ruin odds.
