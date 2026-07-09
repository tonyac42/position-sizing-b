# Field confidence

LLM interfaces pass a `field_confidence` map declaring, for each value, how
the model knows it: `user_stated`, `inferred` (derived from something the
user said, e.g. a payoff ratio computed from odds), or `guessed`.

Enforcement is layered:
- The **tool layer rejects** calls where critical fields (bankroll, edge
  estimate, stop/structural loss, entry) carry `guessed` confidence, returning
  a structured "confirm these values" error listing the exact questions to ask.
- The **engine applies extra caution** to `inferred` critical fields — a 25%
  expectancy haircut on a non-user-stated edge — and lists them in
  `meta.confirm_fields` so the model confirms before the user trades.

The goal: numbers the user never said should never silently become the basis
of a position size.
