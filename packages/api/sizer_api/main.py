"""Sizer HTTP API: a thin, audited, versioned layer over sizer_engine.

Error discipline:
    400 — malformed input (field-level errors)
    401 — missing/unknown API key
    403 — key lacks the required scope
    409 — account pinned to a methodology this server doesn't serve
    422 — valid-but-unsafe request: the engine's structured refusal object
    429 — rate limited
    500 — faults

Every sizing call is audited (input hash, response, interface, versions).
"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from sizer_engine import (
    ENGINE_VERSION,
    METHODOLOGY_VERSION,
    RefusalError,
    SizeRequest,
    size,
)

from .instruments import StaticProvider
from .store import ALL_SCOPES, Store


# --------------------------------------------------------------------------- #
# Request models (API-surface only; the engine schema stays canonical)
# --------------------------------------------------------------------------- #

class SizeEnvelope(BaseModel):
    mode: Literal["stateless", "account"] = "stateless"
    request: dict[str, Any]


class PositionIn(BaseModel):
    instrument_id: str
    direction: Literal["long", "short"] = "long"
    open_risk: float = Field(gt=0)
    correlation_bucket: str = "default"


class TrackRecordIn(BaseModel):
    strategy_id: str
    results_r: list[float] = Field(min_length=1, description="realized R-multiples")
    claimed_edge: dict[str, Any] | None = None
    edge_source: str | None = None


class AccountIn(BaseModel):
    bankroll: float | None = Field(default=None, gt=0)
    peak_equity: float | None = Field(default=None, gt=0)
    preferences: dict[str, Any] | None = None


class CompareIn(BaseModel):
    requests: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    labels: list[str] | None = None


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #

def create_app(db_path: str | None = None, rate_limit_per_min: int = 120) -> FastAPI:
    app = FastAPI(title="Sizer API", version=ENGINE_VERSION)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    store = Store(db_path)
    instruments = StaticProvider()
    buckets: dict[str, list[float]] = {}  # key -> [tokens, last_refill]
    app.state.store = store

    # ---- auth & rate limiting -------------------------------------------- #

    def auth(x_api_key: str = Header(default="")) -> dict:
        rec = store.key_record(x_api_key)
        if rec is None:
            raise HTTPException(401, "unknown or missing API key (X-API-Key header)")
        b = buckets.setdefault(x_api_key, [float(rate_limit_per_min), time.monotonic()])
        now = time.monotonic()
        b[0] = min(float(rate_limit_per_min), b[0] + (now - b[1]) * rate_limit_per_min / 60.0)
        b[1] = now
        if b[0] < 1.0:
            raise HTTPException(429, "rate limit exceeded")
        b[0] -= 1.0
        rec["scopes"] = rec["scopes"].split()
        return rec

    def need(scope: str):
        def dep(key: dict = Depends(auth)) -> dict:
            if scope not in key["scopes"]:
                raise HTTPException(403, f"API key lacks required scope '{scope}'")
            return dep_check_pin(key)
        return dep

    def dep_check_pin(key: dict) -> dict:
        pin = key.get("pinned_methodology")
        if pin and pin != METHODOLOGY_VERSION:
            raise HTTPException(
                409, f"account is pinned to methodology {pin} but this server runs "
                     f"{METHODOLOGY_VERSION}; unpin or use a matching deployment")
        return key

    # ---- error discipline ------------------------------------------------- #

    @app.exception_handler(RequestValidationError)
    async def malformed(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={
            "error": "malformed_input",
            "field_errors": [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ],
        })

    def field_errors_response(exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={
            "error": "malformed_input",
            "field_errors": [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ],
        })

    # ---- meta -------------------------------------------------------------- #

    @app.get("/v1/meta")
    def meta():
        return {"engine_version": ENGINE_VERSION,
                "methodology_version": METHODOLOGY_VERSION,
                "scopes": ALL_SCOPES}

    # ---- sizing ------------------------------------------------------------ #

    def _hydrate_account_mode(raw: dict, key: dict) -> dict:
        acct = store.account(key["account_id"])
        merged = dict(raw)
        if merged.get("bankroll") is None:
            if acct["bankroll"] is None:
                raise HTTPException(400, "account mode: no bankroll on file; "
                                         "PUT /v1/account first or supply bankroll")
            merged["bankroll"] = acct["bankroll"]
        if acct.get("peak_equity") and merged.get("peak_equity") is None:
            merged["peak_equity"] = acct["peak_equity"]
        if not merged.get("open_positions"):
            merged["open_positions"] = [
                {"instrument_id": p["instrument_id"], "direction": p["direction"],
                 "open_risk": p["open_risk"], "correlation_bucket": p["correlation_bucket"]}
                for p in store.positions(key["account_id"])
            ]
        prefs = acct["preferences"]
        for pref in ("kelly_fraction",):
            if merged.get(pref) is None and prefs.get(pref) is not None:
                merged[pref] = prefs[pref]
        if prefs.get("constraints") and not merged.get("constraints"):
            merged["constraints"] = prefs["constraints"]
        sid = merged.get("strategy_id")
        if sid and not merged.get("realized_results"):
            tr = store.track_record(key["account_id"], sid)
            if tr:
                merged["realized_results"] = tr
                merged["sample_size"] = max(merged.get("sample_size") or 0, tr["n_trades"])
        # Instrument enrichment from the catalog when only an id was given.
        inst = merged.get("instrument") or {}
        cat = instruments.get(inst.get("instrument_id", "")) if inst else None
        if cat:
            enriched = {k: v for k, v in cat.items() if k != "name"}
            enriched.update({k: v for k, v in inst.items() if v is not None})
            merged["instrument"] = enriched
        return merged

    def _run_size(raw: dict, key: dict, interface: str) -> tuple[int, dict]:
        try:
            req = SizeRequest.model_validate(raw)
        except ValidationError as exc:
            raise _FieldErrors(exc)
        try:
            resp = size(req)
            body = resp.model_dump(mode="json")
            code = 200
        except RefusalError as exc:
            body = exc.refusal.model_dump(mode="json")
            code = 422
        store.audit(key["account_id"], interface,
                    body.get("meta", {}).get("input_hash", "") if body.get("meta") else "",
                    raw, body, body.get("status", "ok"), ENGINE_VERSION, METHODOLOGY_VERSION)
        return code, body

    class _FieldErrors(Exception):
        def __init__(self, exc: ValidationError):
            self.exc = exc

    @app.exception_handler(_FieldErrors)
    async def _field_errors_handler(request: Request, exc: _FieldErrors):
        return field_errors_response(exc.exc)

    @app.post("/v1/size")
    def size_endpoint(
        body: dict[str, Any],
        key: dict = Depends(need("size:read")),
        idempotency_key: str | None = Header(default=None),
        x_interface: str = Header(default="api"),
    ):
        if idempotency_key:
            cached = store.idempotency_get(key["account_id"], idempotency_key)
            if cached:
                import json as _json
                return JSONResponse(status_code=cached["status_code"],
                                    content=_json.loads(cached["response_json"]),
                                    headers={"X-Idempotency-Replay": "true"})
        if "request" in body:  # envelope form
            env = SizeEnvelope.model_validate(body)
            raw = env.request
            if env.mode == "account":
                raw = _hydrate_account_mode(raw, key)
        else:  # canonical schema directly = stateless
            raw = body
        code, out = _run_size(raw, key, x_interface)
        if idempotency_key:
            store.idempotency_put(key["account_id"], idempotency_key,
                                  out.get("meta", {}).get("input_hash", "") if out.get("meta") else "",
                                  out, code)
        return JSONResponse(status_code=code, content=out)

    @app.post("/v1/scenarios/compare")
    def compare(body: CompareIn, key: dict = Depends(need("size:read")),
                x_interface: str = Header(default="api")):
        results = []
        for i, raw in enumerate(body.requests):
            try:
                code, out = _run_size(raw, key, x_interface)
                results.append({"index": i, "status_code": code, "result": out})
            except _FieldErrors as exc:
                results.append({"index": i, "status_code": 400, "result": {
                    "error": "malformed_input",
                    "field_errors": [
                        {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                        for e in exc.exc.errors()],
                }})
        if body.labels:
            for r, label in zip(results, body.labels):
                r["label"] = label
        return {"results": results}

    # ---- instruments ------------------------------------------------------- #

    @app.get("/v1/instruments/{instrument_id}")
    def instrument(instrument_id: str, key: dict = Depends(need("instruments:read"))):
        data = instruments.get(instrument_id)
        if data is None:
            raise HTTPException(404, f"unknown instrument '{instrument_id}'")
        return data

    # ---- track record ------------------------------------------------------ #

    @app.post("/v1/track-record")
    def track_record(body: TrackRecordIn, key: dict = Depends(need("trackrecord:write"))):
        store.upsert_strategy(key["account_id"], body.strategy_id,
                              body.claimed_edge, body.edge_source)
        store.log_trades(key["account_id"], body.strategy_id, body.results_r)
        summary = store.track_record(key["account_id"], body.strategy_id)
        from sizer_engine.config import DEFAULT_CONFIG
        g = DEFAULT_CONFIG.exploration
        n = summary["n_trades"]
        if n < g.stage1_max_trades:
            stage = "exploration"
        elif n < g.stage2_max_trades:
            stage = "quarter_kelly"
        elif n < g.stage3_max_trades:
            stage = "half_kelly"
        else:
            stage = "graduated"
        return {"strategy_id": body.strategy_id, "realized": summary,
                "exploration_stage": stage,
                "progress": f"{n} of {g.stage3_max_trades} trades until full sizing"}

    @app.get("/v1/track-record/{strategy_id}")
    def get_track_record(strategy_id: str, key: dict = Depends(need("size:read"))):
        s = store.strategy(key["account_id"], strategy_id)
        summary = store.track_record(key["account_id"], strategy_id)
        if s is None and summary is None:
            raise HTTPException(404, f"unknown strategy '{strategy_id}'")
        import json as _json
        return {"strategy_id": strategy_id,
                "claimed_edge": _json.loads(s["claimed_edge"]) if s and s["claimed_edge"] else None,
                "edge_source": s["edge_source"] if s else None,
                "realized": summary}

    # ---- portfolio / account ------------------------------------------------ #

    @app.get("/v1/portfolio")
    def portfolio(key: dict = Depends(need("portfolio:read"))):
        acct = store.account(key["account_id"])
        positions = store.positions(key["account_id"])
        open_risk = sum(p["open_risk"] for p in positions)
        by_bucket: dict[str, float] = {}
        for p in positions:
            by_bucket[p["correlation_bucket"]] = \
                by_bucket.get(p["correlation_bucket"], 0.0) + p["open_risk"]
        return {"bankroll": acct["bankroll"], "peak_equity": acct["peak_equity"],
                "preferences": acct["preferences"], "positions": positions,
                "open_risk_total": open_risk, "open_risk_by_bucket": by_bucket}

    @app.post("/v1/portfolio/position", status_code=201)
    def add_position(body: PositionIn, key: dict = Depends(need("portfolio:write"))):
        pid = store.add_position(key["account_id"], body.instrument_id, body.direction,
                                 body.open_risk, body.correlation_bucket)
        return {"position_id": pid}

    @app.delete("/v1/portfolio/position/{position_id}")
    def delete_position(position_id: str, key: dict = Depends(need("portfolio:write"))):
        if not store.delete_position(key["account_id"], position_id):
            raise HTTPException(404, "unknown position id")
        return {"deleted": position_id}

    @app.put("/v1/account")
    def update_account(body: AccountIn, key: dict = Depends(need("portfolio:write"))):
        store.update_account(key["account_id"], body.bankroll, body.peak_equity,
                             body.preferences)
        return store.account(key["account_id"])

    @app.get("/v1/audit")
    def audit(limit: int = 50, key: dict = Depends(need("size:read"))):
        return {"entries": store.audit_entries(key["account_id"], limit)}

    return app


app = create_app()
