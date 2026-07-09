# Sizer — universal position sizing

One engine that answers **"how much should I bet/trade?"** for radically
different users — a dice gambler with known odds, a futures day trader, a
sports bettor against book limits, a prediction-market trader, a thesis
investor, a fund hitting capacity — by finding **which constraint is binding**
and saying so. The number matters less than the explanation.

Position sizing here is Kelly growth optimization modulated by a stack of
real-world constraints. Classical retail rules (Van Tharp percent-risk /
percent-volatility) fall out as the special cases where their layer binds.

```
Layer 0  edge shrinkage + confidence interval + exploration gates
Layer 1  Kelly solvers (binary / continuous / generalized) × Kelly fraction
Layer 2  risk caps: per-trade, volatility, portfolio heat, correlation
         buckets, equity throttle, daily loss limit
Layer 3  market capacity (ADV impact model, hard fill limits)
Layer 4  tail overlay (stressed distributions, stop-reliability haircuts)
Layer 5  bankroll dynamics (anti-martingale, lockup discount, growth advice)
                    ↓
final size = min across layers, with the binding layer named —
or a structured refusal when no defensible number exists
```

## Monorepo layout

| Package | What | Tests |
|---|---|---|
| `packages/engine` | pure, deterministic sizing library (`sizer_engine`) — no HTTP, no UI, no LLM | 60 |
| `packages/api` | FastAPI layer: auth+scopes, rate limiting, idempotency, audit log, account state (SQLite), all `/v1` endpoints | 18 |
| `packages/llm` | MCP server + plain function-calling schema with anti-hallucination guardrails, routed through the API | 18 |
| `packages/ui` | React+TS app: wizard/expert forms, constraint-stack waterfall, Monte Carlo drawdown paths, scenarios, dashboards | e2e smoke |
| `docs/` | one page per constraint concept; API responses reference these slugs | — |

`DECISIONS.md` records every deviation from the build spec and every
ambiguity resolved by judgment.

## Quickstart

```bash
# engine + API + LLM packages (Python 3.11+)
pip install -e packages/engine -e packages/api -e packages/llm

# run everything's tests
pytest packages/engine packages/api packages/llm

# start the API (seeds a dev key: sizer-dev-key)
uvicorn sizer_api.main:app --port 8000

# size a trade
curl -s localhost:8000/v1/size -H 'X-API-Key: sizer-dev-key' -H 'Content-Type: application/json' -d '{
  "bankroll": 50000,
  "trade_type": "trading",
  "edge_estimate": {"win_probability": 0.55, "payoff_ratio": 1.5},
  "edge_source": "backtest", "sample_size": 200,
  "trade": {"direction": "long", "entry_price": 100, "stop_price": 96},
  "instrument": {"instrument_id": "XYZ", "volatility_atr": 3, "adv": 1e8, "liquidity_tier": "deep"}
}' | python3 -m json.tool

# UI (proxies /v1 to :8000)
cd packages/ui && npm install && npm run dev

# MCP server for LLM clients
SIZER_API_URL=http://127.0.0.1:8000 SIZER_API_KEY=sizer-dev-key sizer-mcp
```

## The parts worth reading first

- `packages/engine/sizer_engine/kelly.py` — the three solvers, including the
  generalized `E[log(1+fX)]` maximizer that premium/lottery sizing hangs on.
- `packages/engine/sizer_engine/engine.py` — the layer orchestration and the
  refusal paths.
- `packages/engine/tests/test_golden.py` — the six archetype users, each
  asserting both the size range *and* the binding constraint.
- `packages/llm/sizer_llm/tools.py` — tool descriptions written as prompts,
  with the guardrails that reject guessed critical values.
- `docs/index.md` — the constraint concepts.

## Honesty properties

- Deterministic: same input → same output; Monte Carlo seeds derive from the
  input hash. Identical inputs give identical answers on API, UI, and MCP.
- Every response names its binding constraint, lists every default applied
  and every field ignored, and carries engine + methodology versions and an
  input hash. Every call is audited.
- When the engine can't stand behind a number — contradictory inputs,
  hopelessly uncertain edge with aggressive intent, unresolvable capacity —
  it returns a structured refusal (HTTP 422) saying what's needed, never a
  low-confidence number presented as confident.
