"""Tool definitions shared by the MCP server and the plain function-calling
schema. One source of truth: the descriptions ARE prompts — they are written
to steer LLMs away from their known failure modes (guessing missing values,
paraphrasing math, silently mutating state).
"""
from __future__ import annotations

CRITICAL_FIELDS = ["bankroll", "edge_estimate", "stop_price", "entry_price",
                   "structural_max_loss"]

_SIZE_DESCRIPTION = """\
Compute how large a position/bet should be, with the binding constraint explained.

RULES FOR YOU, THE CALLING MODEL — read carefully:
1. NEVER invent values. bankroll, the edge estimate, and the trade's risk
   definition (stop_price or structural_max_loss) must come from the user.
   If any is missing, ASK the user — do not call this tool with a guess.
2. Fill `field_confidence` honestly for every value you pass:
   "user_stated" (the user said it), "inferred" (you derived it from context,
   e.g. computed a payoff ratio from odds the user gave), "guessed" (you made
   it up). Calls where a critical field is "guessed" are REJECTED with a
   confirm_these_values error — relay that error's questions to the user.
3. Relay `human_readable_summary` from the response VERBATIM. Do not
   re-derive or paraphrase the math; the summary is written to be repeated.
4. If the response status is "refusal", tell the user exactly what
   `what_is_needed` says. A refusal is the tool working, not failing.
5. Be honest about edge_source. If the user says "I think I win 60% of the
   time" with no logged record, that is source "guess", not "live_track_record".
   The engine sizes guesses smaller. Do not upgrade the source to get a
   bigger number.

FIELD GUIDANCE:
- bankroll: total risk capital in account currency, not per-trade budget.
- edge_estimate: one of {win_probability [+ payoff_ratio]}, {expectancy_r
  [+ win_rate]}, or {outcomes: [{probability, r}, ...]} in R-multiples.
- edge_source: exact_math | live_track_record | backtest |
  related_experience | guess.
- trade_type: lottery | premium | position | shortterm | prediction |
  trading | auto (let the engine classify). If the user sells options or
  collects premium, the type is "premium" — never "lottery".
- stop_price null + structural_max_loss null is only valid for prediction
  contracts (max loss = price paid).
- market_price: REQUIRED for prediction-type trades — the engine shrinks the
  user's probability toward it.
- open_positions: pass what the user tells you; in account mode the server
  loads the stored portfolio automatically.

WORKED EXAMPLES:

1. Day trader ("I trade ES futures, $50k account, my logged record is 500
   trades at 40% winners averaging 2.5R, entry 5000 stop 4990"):
   {"bankroll": 50000, "trade_type": "shortterm",
    "edge_estimate": {"win_probability": 0.40, "payoff_ratio": 2.5},
    "edge_source": "live_track_record", "sample_size": 500,
    "trade": {"direction": "long", "entry_price": 5000, "stop_price": 4990,
              "expected_time_in_trade_days": 0.2},
    "instrument": {"instrument_id": "ES", "point_value": 50,
                   "volatility_atr": 6, "adv": 2e9, "liquidity_tier": "deep"},
    "field_confidence": {"bankroll": "user_stated", "edge_estimate": "user_stated",
                         "stop_price": "user_stated"}}

2. Prediction market ("$10k bankroll, contract at 30 cents, I think it's
   50/50, holding to resolution in 6 months"):
   {"bankroll": 10000, "trade_type": "prediction",
    "edge_estimate": {"win_probability": 0.50}, "edge_source": "guess",
    "market_price": 0.30,
    "trade": {"entry_price": 0.30, "payoff_structure": "binary",
              "hold_to_resolution": true, "expected_time_in_trade_days": 180},
    "field_confidence": {"bankroll": "user_stated", "edge_estimate": "user_stated",
                         "entry_price": "user_stated"}}

3. Premium seller ("I sell put spreads, win 90% of the time, average winner
   0.2R, $100k account, max loss $2000 per spread"):
   {"bankroll": 100000, "trade_type": "premium",
    "edge_estimate": {"win_probability": 0.90, "payoff_ratio": 0.20},
    "edge_source": "live_track_record", "sample_size": 200,
    "trade": {"structural_max_loss": 2000},
    "field_confidence": {"bankroll": "user_stated", "edge_estimate": "user_stated",
                         "structural_max_loss": "user_stated"}}
   Expect a danger-severity tail warning in the response — show it to the user.

4. Sports bettor ("$200k roll, I hit 54% at -110, book takes $10k a side"):
   {"bankroll": 200000, "trade_type": "prediction",
    "edge_estimate": {"win_probability": 0.54, "payoff_ratio": 0.909},
    "edge_source": "live_track_record", "sample_size": 1200,
    "market_price": 0.524,
    "trade": {"payoff_structure": "binary", "expected_time_in_trade_days": 1},
    "instrument": {"instrument_id": "nfl-sides", "max_fill": 10000},
    "field_confidence": {"bankroll": "user_stated", "edge_estimate": "user_stated"}}
   (payoff_ratio 0.909 and market_price 0.524 are derived from "-110": mark
   them "inferred", not "user_stated".)
"""

# JSON schema for the canonical request, kept in sync with
# sizer_engine.schemas.SizeRequest (subset: the fields an LLM should supply).
SIZE_REQUEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "bankroll": {"type": "number", "exclusiveMinimum": 0,
                     "description": "Total risk capital, account currency. CRITICAL: must be user-stated."},
        "bankroll_segregated": {"type": "boolean", "default": False},
        "kelly_fraction": {"type": "number", "minimum": 0.0, "maximum": 1.0,
                           "description": "Preferred fraction of full Kelly (default 0.25)."},
        "drawdown_tolerance": {
            "type": "object",
            "properties": {"max_drawdown_pct": {"type": "number"},
                           "max_drawdown_dollars": {"type": "number"}},
        },
        "trade_type": {"type": "string",
                       "enum": ["lottery", "premium", "position", "shortterm",
                                "prediction", "trading", "auto"],
                       "default": "auto"},
        "edge_estimate": {
            "type": "object",
            "description": "CRITICAL: must come from the user. One of the three formats.",
            "properties": {
                "win_probability": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                "payoff_ratio": {"type": "number", "exclusiveMinimum": 0},
                "expectancy_r": {"type": "number"},
                "win_rate": {"type": "number"},
                "outcomes": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"probability": {"type": "number"}, "r": {"type": "number"}},
                    "required": ["probability", "r"]}},
            },
        },
        "edge_source": {"type": "string",
                        "enum": ["exact_math", "live_track_record", "backtest",
                                 "related_experience", "guess"],
                        "description": "Be honest; do not upgrade a guess."},
        "sample_size": {"type": "integer", "minimum": 0, "default": 0},
        "realized_results": {
            "type": "object",
            "properties": {"n_trades": {"type": "integer"}, "win_rate": {"type": "number"},
                           "avg_win_r": {"type": "number"}, "avg_loss_r": {"type": "number"},
                           "expectancy_r": {"type": "number"}},
            "required": ["n_trades"],
        },
        "similarity": {"type": "number", "minimum": 0, "maximum": 1,
                       "description": "related_experience only: domain similarity."},
        "user_calibration_data": {"type": "boolean", "default": False},
        "market_price": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1,
                         "description": "prediction: current market probability. Required for prediction."},
        "trade": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["long", "short"]},
                "entry_price": {"type": "number"},
                "stop_price": {"type": ["number", "null"],
                               "description": "null = no stop (hold to resolution/thesis)."},
                "target_price": {"type": ["number", "null"]},
                "expected_time_in_trade_days": {"type": "number"},
                "payoff_structure": {"type": "string",
                                     "enum": ["binary", "continuous", "capped", "unbounded"]},
                "structural_max_loss": {"type": "number",
                                        "description": "worst-case loss per unit."},
                "hold_to_resolution": {"type": "boolean"},
            },
        },
        "instrument": {
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string"},
                "point_value": {"type": "number"},
                "volatility_atr": {"type": "number"},
                "adv": {"type": "number"},
                "max_fill": {"type": "number",
                             "description": "book limit / counterparty cap / visible depth ($)."},
                "liquidity_tier": {"type": "string", "enum": ["deep", "moderate", "thin", "micro"]},
                "correlation_bucket": {"type": "string"},
                "tail_profile": {"type": "string", "enum": ["normal", "moderate", "heavy", "extreme"]},
                "gap_risk": {"type": "boolean"},
            },
        },
        "open_positions": {"type": "array", "items": {
            "type": "object",
            "properties": {"instrument_id": {"type": "string"},
                           "direction": {"type": "string", "enum": ["long", "short"]},
                           "open_risk": {"type": "number"},
                           "correlation_bucket": {"type": "string"}},
            "required": ["instrument_id", "open_risk"]}},
        "constraints": {
            "type": "object",
            "properties": {
                "per_trade_risk_cap": {"type": "number"},
                "volatility_cap": {"type": "number"},
                "portfolio_heat_cap": {"type": "number"},
                "correlation_bucket_cap": {"type": "number"},
                "capacity_policy": {"type": "string", "enum": ["reject", "downsize", "queue"]},
                "daily_loss_limit": {"type": "number"},
            },
        },
        "intraday_pnl": {"type": "number"},
        "peak_equity": {"type": "number"},
        "strategy_id": {"type": "string"},
        "exploration_override": {"type": "boolean", "default": False},
        "field_confidence": {
            "type": "object",
            "description": "REQUIRED honesty map: for each value you pass, how you know it.",
            "additionalProperties": {"type": "string",
                                     "enum": ["user_stated", "inferred", "guessed"]},
        },
    },
    "required": ["bankroll", "edge_estimate", "edge_source", "field_confidence"],
}

TOOLS: list[dict] = [
    {
        "name": "size_position",
        "description": _SIZE_DESCRIPTION,
        "input_schema": SIZE_REQUEST_SCHEMA,
        "read_only": True,
    },
    {
        "name": "compare_scenarios",
        "description": (
            "Size up to 10 variants of a trade in one call (e.g. different stops, "
            "kelly fractions, or bankrolls) and compare side by side. Each request "
            "follows the size_position schema and the same guardrails apply. Use "
            "when the user asks 'what if' questions, instead of calling "
            "size_position repeatedly."),
        "input_schema": {
            "type": "object",
            "properties": {
                "requests": {"type": "array", "minItems": 1, "maxItems": 10,
                             "items": SIZE_REQUEST_SCHEMA},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["requests"],
        },
        "read_only": True,
    },
    {
        "name": "get_instrument",
        "description": ("Look up instrument metadata (point value, ATR, liquidity, "
                        "correlation bucket, tail profile) from the catalog so you don't "
                        "have to ask the user for it. Try this BEFORE asking the user for "
                        "instrument details."),
        "input_schema": {
            "type": "object",
            "properties": {"instrument_id": {"type": "string"}},
            "required": ["instrument_id"],
        },
        "read_only": True,
    },
    {
        "name": "get_portfolio",
        "description": ("Read the account's stored state: bankroll, open positions, "
                        "portfolio heat, per-bucket risk. Read-only."),
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    {
        "name": "log_trades",
        "description": (
            "MUTATION — record realized trade outcomes (R-multiples) against a "
            "strategy_id, advancing its track record and exploration gates. Requires a "
            "confirmation_token: first call WITHOUT the token to receive a summary and "
            "token, show the summary to the user, and only after the user explicitly "
            "confirms, call again WITH the token. Never fabricate results."),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string"},
                "results_r": {"type": "array", "items": {"type": "number"}, "minItems": 1},
                "confirmation_token": {"type": "string"},
            },
            "required": ["strategy_id", "results_r"],
        },
        "read_only": False,
    },
    {
        "name": "add_position",
        "description": (
            "MUTATION — register an open position so heat/bucket caps see it. Requires "
            "a confirmation_token (same two-step flow as log_trades: call without token, "
            "show the returned summary to the user, get explicit confirmation, re-call "
            "with the token)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["long", "short"], "default": "long"},
                "open_risk": {"type": "number", "exclusiveMinimum": 0},
                "correlation_bucket": {"type": "string", "default": "default"},
                "confirmation_token": {"type": "string"},
            },
            "required": ["instrument_id", "open_risk"],
        },
        "read_only": False,
    },
]
