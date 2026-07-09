"""API contract tests: auth, scopes, error discipline, idempotency, account
mode, portfolio flow, track record, scenario comparison, audit trail."""
import pytest
from fastapi.testclient import TestClient

from sizer_api.main import create_app
from sizer_api.store import DEV_KEY

STATELESS_REQ = {
    "bankroll": 50_000,
    "trade_type": "trading",
    "edge_estimate": {"win_probability": 0.55, "payoff_ratio": 1.5},
    "edge_source": "live_track_record",
    "sample_size": 400,
    "trade": {"direction": "long", "entry_price": 100, "stop_price": 96},
    "instrument": {"instrument_id": "TEST", "volatility_atr": 3.0, "adv": 1e8,
                   "liquidity_tier": "deep"},
}


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"), rate_limit_per_min=100_000)
    return TestClient(app)


def h(**extra):
    return {"X-API-Key": DEV_KEY, **extra}


class TestAuth:
    def test_missing_key_401(self, client):
        assert client.post("/v1/size", json=STATELESS_REQ).status_code == 401

    def test_unknown_key_401(self, client):
        r = client.post("/v1/size", json=STATELESS_REQ, headers={"X-API-Key": "nope"})
        assert r.status_code == 401

    def test_scope_enforcement_403(self, client, tmp_path):
        store = client.app.state.store
        key = store.create_key("limited", "read-only", ["size:read"])
        r = client.post("/v1/portfolio/position",
                        json={"instrument_id": "ES", "open_risk": 100},
                        headers={"X-API-Key": key})
        assert r.status_code == 403
        assert "portfolio:write" in r.json()["detail"]

    def test_rate_limit_429(self, tmp_path):
        app = create_app(db_path=str(tmp_path / "rl.db"), rate_limit_per_min=2)
        c = TestClient(app)
        codes = [c.get("/v1/portfolio", headers=h()).status_code for _ in range(4)]
        assert 429 in codes

    def test_methodology_pin_mismatch_409(self, client):
        store = client.app.state.store
        key = store.create_key("pinned", "pinned", ["size:read"])
        store._conn.execute("UPDATE api_keys SET pinned_methodology='0.9.0' WHERE key=?",
                            (key,))
        store._conn.commit()
        r = client.post("/v1/size", json=STATELESS_REQ, headers={"X-API-Key": key})
        assert r.status_code == 409


class TestSizeEndpoint:
    def test_stateless_ok(self, client):
        r = client.post("/v1/size", json=STATELESS_REQ, headers=h())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["recommendation"]["risk_pct_bankroll"] > 0
        assert body["explanation"]["binding_constraint"]
        assert body["meta"]["engine_version"]
        assert body["human_readable_summary"]

    def test_malformed_400_with_field_errors(self, client):
        bad = {**STATELESS_REQ, "bankroll": -5}
        r = client.post("/v1/size", json=bad, headers=h())
        assert r.status_code == 400
        errs = r.json()["field_errors"]
        assert any("bankroll" in e["field"] for e in errs)

    def test_refusal_422_structured(self, client):
        bad = {**STATELESS_REQ,
               "trade": {"direction": "long", "entry_price": 100, "stop_price": 110}}
        r = client.post("/v1/size", json=bad, headers=h())
        assert r.status_code == 422
        body = r.json()
        assert body["status"] == "refusal"
        assert body["refusal_code"] == "contradictory_inputs"
        assert body["what_is_needed"]

    def test_idempotency_replay(self, client):
        k = {"Idempotency-Key": "abc-123"}
        r1 = client.post("/v1/size", json=STATELESS_REQ, headers=h(**k))
        r2 = client.post("/v1/size", json=STATELESS_REQ, headers=h(**k))
        assert r1.status_code == r2.status_code == 200
        assert r2.headers.get("X-Idempotency-Replay") == "true"
        assert r1.json() == r2.json()

    def test_deterministic_across_calls(self, client):
        r1 = client.post("/v1/size", json=STATELESS_REQ, headers=h()).json()
        r2 = client.post("/v1/size", json=STATELESS_REQ, headers=h()).json()
        r1["meta"].pop("timestamp"); r2["meta"].pop("timestamp")
        assert r1 == r2

    def test_audit_trail_written(self, client):
        client.post("/v1/size", json=STATELESS_REQ, headers=h())
        entries = client.get("/v1/audit", headers=h()).json()["entries"]
        assert len(entries) >= 1
        assert entries[0]["input_hash"]
        assert entries[0]["engine_version"]


class TestAccountMode:
    def test_account_mode_uses_stored_state(self, client):
        client.put("/v1/account", json={"bankroll": 80_000}, headers=h())
        client.post("/v1/portfolio/position",
                    json={"instrument_id": "ES", "open_risk": 8_000,
                          "correlation_bucket": "us_equity_index"},
                    headers=h())
        trade_only = {k: v for k, v in STATELESS_REQ.items() if k != "bankroll"}
        r = client.post("/v1/size", json={"mode": "account", "request": trade_only},
                        headers=h())
        assert r.status_code == 200
        body = r.json()
        assert body["recommendation"]["risk_dollars"] <= 0.02 * 80_000
        heat_row = next(c for c in body["explanation"]["cap_table"]
                        if c["constraint"] == "portfolio_heat")
        assert "10.0%" in heat_row["detail"]  # 8k of 80k on the books

    def test_account_mode_without_bankroll_400(self, client):
        trade_only = {k: v for k, v in STATELESS_REQ.items() if k != "bankroll"}
        r = client.post("/v1/size", json={"mode": "account", "request": trade_only},
                        headers=h())
        assert r.status_code == 400

    def test_track_record_feeds_account_mode(self, client):
        client.put("/v1/account", json={"bankroll": 50_000}, headers=h())
        r = client.post("/v1/track-record",
                        json={"strategy_id": "s1",
                              "results_r": [1.5, -1, 1.5, -1, 1.5] * 10},
                        headers=h())
        assert r.status_code == 200
        assert r.json()["realized"]["n_trades"] == 50
        assert r.json()["exploration_stage"] == "quarter_kelly"
        trade_only = {k: v for k, v in STATELESS_REQ.items() if k != "bankroll"}
        trade_only["strategy_id"] = "s1"
        trade_only["sample_size"] = 0
        r = client.post("/v1/size", json={"mode": "account", "request": trade_only},
                        headers=h())
        body = r.json()
        assert body["meta"]["exploration_stage"] == "quarter_kelly"
        assert body["recommendation"]["risk_pct_bankroll"] <= 0.01 + 1e-9


class TestOtherEndpoints:
    def test_instruments(self, client):
        r = client.get("/v1/instruments/ES", headers=h())
        assert r.status_code == 200
        assert r.json()["correlation_bucket"] == "us_equity_index"
        assert client.get("/v1/instruments/NOPE", headers=h()).status_code == 404

    def test_portfolio_crud(self, client):
        r = client.post("/v1/portfolio/position",
                        json={"instrument_id": "CL", "open_risk": 500,
                              "correlation_bucket": "energy"}, headers=h())
        pid = r.json()["position_id"]
        assert r.status_code == 201
        port = client.get("/v1/portfolio", headers=h()).json()
        assert port["open_risk_total"] == 500
        assert port["open_risk_by_bucket"]["energy"] == 500
        assert client.delete(f"/v1/portfolio/position/{pid}", headers=h()).status_code == 200
        assert client.get("/v1/portfolio", headers=h()).json()["open_risk_total"] == 0
        assert client.delete(f"/v1/portfolio/position/{pid}", headers=h()).status_code == 404

    def test_scenario_compare(self, client):
        variant = {**STATELESS_REQ, "kelly_fraction": 0.5}
        refusing = {**STATELESS_REQ,
                    "trade": {"direction": "long", "entry_price": 100, "stop_price": 110}}
        r = client.post("/v1/scenarios/compare",
                        json={"requests": [STATELESS_REQ, variant, refusing],
                              "labels": ["base", "half-kelly", "broken"]},
                        headers=h())
        assert r.status_code == 200
        results = r.json()["results"]
        assert [x["status_code"] for x in results] == [200, 200, 422]
        assert results[0]["result"]["recommendation"]["risk_pct_bankroll"] <= \
            results[1]["result"]["recommendation"]["risk_pct_bankroll"]
        assert results[2]["result"]["status"] == "refusal"
        assert results[1]["label"] == "half-kelly"

    def test_meta(self, client):
        r = client.get("/v1/meta")
        assert r.json()["methodology_version"]
