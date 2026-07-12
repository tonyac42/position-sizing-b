"""LLM interface tests: schema validity, guardrail rejections (including the
anti-hallucination path), confirmation-token flow, end-to-end consistency
with the engine through the API."""
import json

import httpx
import pytest

from sizer_api.main import create_app
from sizer_llm.client import SizerAPIClient
from sizer_llm.dispatch import dispatch
from sizer_llm.gen_schema import build
from sizer_llm.tools import TOOLS

GOOD_ARGS = {
    "bankroll": 50_000,
    "trade_type": "trading",
    "edge_estimate": {"win_probability": 0.55, "payoff_ratio": 1.5},
    "edge_source": "live_track_record",
    "sample_size": 400,
    "trade": {"direction": "long", "entry_price": 100, "stop_price": 96},
    "instrument": {"instrument_id": "TEST", "volatility_atr": 3.0, "adv": 1e8,
                   "liquidity_tier": "deep"},
    "field_confidence": {"bankroll": "user_stated", "edge_estimate": "user_stated",
                         "stop_price": "user_stated"},
}


class _SyncASGITransport(httpx.BaseTransport):
    """Sync httpx transport over a FastAPI app, via starlette's TestClient."""

    def __init__(self, app):
        from fastapi.testclient import TestClient
        self._tc = TestClient(app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self._tc.request(
            request.method,
            request.url.path + (f"?{request.url.query.decode()}" if request.url.query else ""),
            content=request.read(),
            headers=dict(request.headers),
        )
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "llm.db"), rate_limit_per_min=100_000)
    return SizerAPIClient(base_url="http://testserver",
                          transport=_SyncASGITransport(app))


class TestSchemas:
    def test_tool_schemas_are_valid_json_schema(self):
        import jsonschema
        for t in TOOLS:
            jsonschema.Draft202012Validator.check_schema(t["input_schema"])

    def test_function_schema_file_in_sync(self):
        from pathlib import Path
        path = Path(__file__).parents[1] / "sizer_llm" / "function_schema.json"
        assert json.loads(path.read_text()) == build()

    def test_critical_fields_required_in_schema(self):
        size_tool = next(t for t in TOOLS if t["name"] == "size_position")
        req = size_tool["input_schema"]["required"]
        assert "bankroll" in req and "edge_estimate" in req
        assert "field_confidence" in req

    def test_mutations_marked_not_read_only(self):
        flags = {t["name"]: t["read_only"] for t in TOOLS}
        assert flags["size_position"] and flags["get_portfolio"]
        assert not flags["log_trades"] and not flags["add_position"]

    def test_descriptions_include_worked_examples(self):
        desc = next(t for t in TOOLS if t["name"] == "size_position")["description"]
        assert desc.count("bankroll") >= 4
        for phrase in ("Day trader", "Prediction market", "Premium seller", "Sports bettor"):
            assert phrase in desc


class TestGuardrails:
    def test_missing_bankroll_rejected_with_ask_user(self, client):
        args = {k: v for k, v in GOOD_ARGS.items() if k != "bankroll"}
        out = dispatch("size_position", args, client)
        assert out["error"] == "missing_critical_fields"
        assert any("bankroll" in q for q in out["ask_user"])

    def test_missing_risk_definition_rejected(self, client):
        args = dict(GOOD_ARGS, trade={"direction": "long", "entry_price": None})
        args["trade"] = {}
        out = dispatch("size_position", args, client)
        assert out["error"] == "missing_critical_fields"

    def test_guessed_critical_field_rejected(self, client):
        args = dict(GOOD_ARGS)
        args["field_confidence"] = {"bankroll": "guessed", "edge_estimate": "user_stated"}
        out = dispatch("size_position", args, client)
        assert out["error"] == "confirm_these_values"
        assert any("bankroll" in q for q in out["ask_user"])

    def test_missing_confidence_map_rejected(self, client):
        args = {k: v for k, v in GOOD_ARGS.items() if k != "field_confidence"}
        out = dispatch("size_position", args, client)
        assert out["error"] == "missing_field_confidence"

    def test_inferred_fields_pass_but_get_flagged(self, client):
        args = dict(GOOD_ARGS)
        args["field_confidence"] = {"bankroll": "user_stated",
                                    "edge_estimate": "inferred",
                                    "stop_price": "user_stated"}
        out = dispatch("size_position", args, client)
        assert out["status"] == "ok"
        assert "edge_estimate" in out["meta"]["confirm_fields"]
        assert any(w["code"] == "unconfirmed_critical_fields"
                   for w in out["diagnostics"]["warnings"])


class TestSizeThroughAPI:
    def test_ok_path_has_verbatim_summary(self, client):
        out = dispatch("size_position", dict(GOOD_ARGS), client)
        assert out["status"] == "ok"
        assert out["human_readable_summary"].startswith("Recommended size")

    def test_refusal_relayed_structurally(self, client):
        args = dict(GOOD_ARGS,
                    trade={"direction": "long", "entry_price": 100, "stop_price": 110})
        out = dispatch("size_position", args, client)
        assert out["status"] == "refusal"
        assert out["what_is_needed"]

    def test_compare_scenarios(self, client):
        variant = dict(GOOD_ARGS, kelly_fraction=0.5)
        out = dispatch("compare_scenarios",
                       {"requests": [dict(GOOD_ARGS), variant], "labels": ["a", "b"]},
                       client)
        assert len(out["results"]) == 2
        assert out["results"][0]["result"]["recommendation"]["risk_pct_bankroll"] <= \
            out["results"][1]["result"]["recommendation"]["risk_pct_bankroll"]

    def test_get_instrument(self, client):
        out = dispatch("get_instrument", {"instrument_id": "ES"}, client)
        assert out["correlation_bucket"] == "us_equity_index"


class TestConfirmationFlow:
    def test_mutation_without_token_returns_summary_not_effect(self, client):
        args = {"strategy_id": "s9", "results_r": [1.0, -1.0]}
        out = dispatch("log_trades", dict(args), client)
        assert out["confirmation_required"]
        assert "confirmation_token" in out
        assert "2 realized trade" in out["show_user"]
        # Nothing was written.
        port = dispatch("get_portfolio", {}, client)
        assert port["open_risk_total"] == 0

    def test_mutation_with_token_executes(self, client):
        args = {"strategy_id": "s9", "results_r": [1.0, -1.0]}
        step1 = dispatch("log_trades", dict(args), client)
        step2 = dispatch("log_trades", {**args, "confirmation_token": step1["confirmation_token"]},
                         client)
        assert step2["realized"]["n_trades"] == 2
        assert step2["exploration_stage"] == "exploration"

    def test_token_bound_to_arguments(self, client):
        step1 = dispatch("log_trades", {"strategy_id": "s9", "results_r": [1.0]}, client)
        tampered = dispatch("log_trades",
                            {"strategy_id": "s9", "results_r": [10.0, 10.0, 10.0],
                             "confirmation_token": step1["confirmation_token"]},
                            client)
        assert tampered["error"] == "bad_confirmation_token"

    def test_add_position_flow(self, client):
        args = {"instrument_id": "ES", "open_risk": 500.0,
                "correlation_bucket": "us_equity_index"}
        step1 = dispatch("add_position", dict(args), client)
        assert step1["confirmation_required"]
        step2 = dispatch("add_position",
                         {**args, "confirmation_token": step1["confirmation_token"]}, client)
        assert "position_id" in step2
        port = dispatch("get_portfolio", {}, client)
        assert port["open_risk_total"] == 500.0
