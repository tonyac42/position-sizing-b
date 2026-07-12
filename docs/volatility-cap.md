# Volatility cap (Layer 2)

Van Tharp's "percent volatility" model: cap the bankroll fraction that one
ATR of daily movement can move. Default **1%** per ATR. Position size in
units = volatility budget ÷ (ATR × point value).

Tight-stop trading naturally binds here rather than on the risk cap: a tight
stop permits a huge unit count, but each unit still breathes with the market's
daily range, and a normal fluctuation against a position sized only by its
stop would swamp the account.

Not applicable to `prediction` and `position` trades, where the relevant risk
is resolution/thesis failure, not daily wiggle.
