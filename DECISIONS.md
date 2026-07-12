# DECISIONS.md

Design decisions, deviations from the spec, and ambiguities resolved by
judgment rather than silently. Numbered so reviews can reference them.

## 0. Language and architecture

**Python engine (Pydantic v2), as the spec suggests.** The engine is where
correctness lives, and Python's numeric/testing ecosystem (hypothesis property
tests, trivial golden-test arithmetic) beats the marginal benefit of TS
code-sharing. The UI consumes only the API, so nothing is duplicated except
response *type declarations* (`ui/src/types.ts`), which contain zero logic.
Monorepo layout: `packages/engine` (pure library, independently publishable),
`packages/api` (FastAPI + SQLite), `packages/llm` (MCP + function schema),
`packages/ui` (Vite React). SQLite via stdlib `sqlite3` — boring on purpose;
the `Store` class is the seam where Postgres would slot in.

## 1. Golden scenario 1 (dice) — the spec's numbers don't produce its asserted outcome

With the literal inputs ($1,000 bankroll, 55/45 even money, $500 counterparty
limit), full Kelly is **10% = $100/bet**. The $500 limit has 5x headroom; a
correct engine must report Kelly-bound, and an engine that reported
"capacity-bound" here would be wrong. I did not force the assertion to pass.

The capacity story the spec intends is real, though — it appears as the
bankroll grows: past $5,000, Kelly wants more than the counterparty will book.
So golden test 1 has two parts: (a) $1,000 bankroll → Kelly-bound, capacity
row present-but-inert with its $500 headroom shown; (b) $8,000 bankroll (the
same gambler later that night) → **capacity-bound at $500**, the
"capacity-limited, not risk-limited" warning, and the Layer-5 "deploy
additional capital elsewhere" advice. This preserves the spec's intent (the
theater gambler's ceiling is the counterparty, not risk math) while keeping
the engine honest.

Two supporting choices: the dice user runs `kelly_fraction=1.0` — permitted
only for `exact_math` edges, where full Kelly is defensible (see #6) — and
lifts the heat/bucket caps to 50% via explicit constraint preferences, since
diversification caps are meaningless for a segregated one-game bankroll. The
test uses a config with the per-trade hard ceiling raised; defaults would cap
a normal account at 10%.

## 2. Golden scenario 4 (prediction) — the 2% default risk cap contradicts the ≈3% assertion

Hold-to-resolution prediction risk is structural (premium paid), so the
default 2% per-trade cap would bind *below* the asserted ≈3% (quarter-Kelly ×
lockup = 3.04%). The spec can't have both. Resolution: the golden test's user
sets `per_trade_risk_cap: 0.05` explicitly — a defensible preference for
defined-risk contracts — and the test asserts the spec's intended chain:
shrinkage 0.50→0.40, f* = 1/7, quarter-Kelly, ×0.852 lockup ≈ 3.0%, with the
explanation naming shrinkage and lockup. Deviation is in the test fixture,
not the engine: defaults still cap an unmodified request at 2%.

## 3. Exploration gates vs. golden scenario 4 — prediction trades are exempt

Spec Layer 0 says `guess` forces exploration mode (0.25–0.5% for trades
1–30); golden test 4 is a zero-history guess asserted at ≈3%. Both can't
hold. Resolution: **exploration gates apply to repeatable-strategy types
(trading, shortterm, lottery, premium) and not to `prediction` or
`position`.** Rationale: for prediction, the market price is an informative
anchor and shrink-toward-market is the uncertainty control (a guess also gets
a hard quarter-Kelly ceiling); gates keyed to "trades on this strategy" don't
map onto one-off contracts. For `position`, the spec itself says per-trade
Kelly is the wrong lens and routes to portfolio construction — a
first-thesis-bet capped at 0.5% would make the type unusable; concentration
caps and conviction shrinkage are the control instead.

## 4. Exploration override on a zero-evidence guess is refused

"Never refuses to size a new strategy" and the refusal path ("edge CI
spanning deeply negative territory with high claimed size") meet exactly
here. Resolution: a guess with no sample is always sized — at exploration
scale. Demanding aggressive sizing on it (`exploration_override` or
`kelly_fraction ≥ 0.5`) triggers `edge_too_uncertain_for_aggression` instead
of a bigger number. The promise kept is "always helps"; the promise refused
is "helps you pretend".

## 5. Golden scenario 3 — "slate portfolio-heat-bound" is implemented as the correlation bucket cap

Ten bets on one slate share a bucket; the 6% bucket cap is what bites (at bet
~10), not the 20% total-heat cap. The bucket cap *is* the portfolio-heat
mechanism for correlated risk, and the spec's own example ("three contracts
on the same election = one bucket") points there. The test asserts
`correlation_bucket` as the slate's binding constraint and that cumulative
slate risk never exceeds 6%.

## 6. Kelly fraction band is enforced except for `exact_math`

Spec range 0.1–0.5. Clamped for every uncertain source; `exact_math` edges
may run to 1.0 because with deterministic odds the classic objections to full
Kelly (edge overestimation) don't apply, and the theater scenario needs it.
Drawdown→fraction mapping uses Thorp's x^(2/c−1) drawdown law at a 10% breach
probability (documented in docs/kelly-fraction.md).

## 7. Stop reliability and tail factors interact by design

Both come from spec Layer 4. Implementation: the stop multiplier inflates
effective per-unit risk (and deflates the payoff ratio in the same currency,
so Kelly sees slippage too); the distribution tail factor divides Layer 2
caps. For a deep-book futures trade they compound modestly (1.2 × 1.3);
that's intended — one prices execution, the other prices distribution.

## 8. Premium stress mechanics

"Size against a stressed distribution" is implemented literally: a synthetic
tail outcome (default probability 2%, loss = tail_factor × observed worst
loss, mass taken from the most probable outcome) is injected before the
generalized Kelly solve, *and* the tail factor still divides the Layer 2
caps. Observed-distribution Kelly for the golden premium seller is a seductive
40%; the stressed solve lands near 5% full-Kelly and the cap chain delivers
~0.5%. Mean/variance sizing is structurally unreachable for `premium` (the
type routes to the generalized solver only).

## 9. Misdeclared premium is re-typed for safety; other mismatches are flagged only

The classifier honors the declared type except in one direction: a trade
whose structure reads as premium collection is sized as `premium` even if
declared `lottery`/`trading` (the spec's covered-call example). The reverse
mistakes are conservative, so a flag suffices.

## 10. Liquidity tiers without numbers don't produce fake capacity

A qualitative `thin`/`micro` tier with no ADV/depth cannot yield an honest
numeric capacity cap. Behavior: stop-reliability haircuts apply from the
tier; capacity is *unresolved* — policy `reject` refuses, `downsize` caps at
exploration scale until numbers are supplied. Deep/unstated tiers leave the
layer inert. Inventing a notional ceiling from a word felt like exactly the
"confident number with nothing behind it" the spec bans.

## 11. Daily-loss-limit breach is a zero recommendation, not a refusal

Spec says the engine "flags when it's been hit". A structured `size: 0` with
binding constraint `daily_loss_limit` and a danger warning is more useful to
callers than a 422 — it's a valid answer ("trade nothing today"), not an
inability to answer.

## 12. Account mode is an envelope, not a different schema

`POST /v1/size` accepts either the canonical request directly (stateless) or
`{"mode": "account", "request": {...trade specifics}}`. The server hydrates
bankroll, peak equity, open positions, preferences, and the strategy's
realized track record from stored state, then validates the same canonical
schema. One schema, one engine path, no interface-local defaults.

## 13. Methodology pinning fails closed

Only one methodology exists (1.0.0). An account pinned to anything else gets
**409**, because serving different math than the account pinned is worse than
serving an error. Multi-version dispatch is deliberately out of scope.

## 14. LLM mutation guardrails use argument-bound HMAC tokens

The confirmation token for `log_trades`/`add_position` is an HMAC over the
exact arguments with a 10-minute TTL — so a model cannot show the user one
action and execute another, and cannot mint its own token. First call returns
`show_user` text + token; only the re-call with matching arguments executes.

## 15. Recency weighting is summary-level

Spec asks shortterm edges to weight recent results more. Implemented as an
optional `recent_expectancy_r` window blended 2:1 with full-history stats
(the API computes the last-50 window automatically from logged trades). A
full exponential-decay trade-level scheme needs trade timestamps in the
engine schema; deferred, noted here.

## 16. Known scope cuts (flagged, not hidden)

- **Calibration plot** (prediction dashboard): requires logging per-trade
  claimed probabilities vs. outcomes; the track-record store currently holds
  R-multiples only. The dashboard says so. Schema change is additive.
- **`queue` capacity policy** behaves as downsize-plus-flag (the remainder is
  reported as queued in the detail text); a real order queue is out of scope.
- **Rate limiting and idempotency are in-memory/SQLite per instance** — right
  shape, single-node scale.
- **CI half-width for a zero-sample guess is honest but wide** (±0.5R floor
  can exceed the claimed edge). Intended: it reflects "we know nothing", and
  it is what arms the aggression refusal.
- **Instrument data is a static seed** behind a `Protocol`; live providers
  plug into `InstrumentProvider.get`.
- **Fractional units are returned as-is** (1.28 contracts); lot rounding is
  the caller's decision and rounding policy would be interface-local behavior
  the spec forbids.

## 17. UI conveniences that are interpretations, not defaults

When the form's edge source is `live_track_record` with a sample size, the UI
maps the stated stats into `realized_results` — for a live record, the stated
numbers *are* the realized results, and omitting them would make the engine
discount an honest record like a backtest. This is constructing the canonical
request from user intent, not adding interface-local sizing behavior.
