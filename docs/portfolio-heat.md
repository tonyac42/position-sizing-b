# Portfolio heat (Layer 2)

Total open risk — the sum over open positions of what hits if every stop is
struck — capped at **20%** of bankroll by default. A new trade only gets the
headroom that's left.

The `capacity_policy` setting decides what happens when a trade wants more
than the headroom: `downsize` (default) fits it inside, `reject` refuses with
a structured error, `queue` sizes to the headroom and flags that the rest
waits for heat to free.

Heat is why the engine wants your open positions (or account mode, which
loads them from stored state): ten great trades at 2% each is a 20% single
drawdown if they're struck together.
