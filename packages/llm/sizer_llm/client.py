"""HTTP client to the Sizer API. The LLM layer never imports the engine —
routing through the API keeps auth, audit, and versioning consistent across
interfaces (spec Part 4)."""
from __future__ import annotations

import os
from typing import Any

import httpx


class SizerAPIClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url or os.environ.get("SIZER_API_URL", "http://127.0.0.1:8000")
        self.api_key = api_key or os.environ.get("SIZER_API_KEY", "sizer-dev-key")
        self._client = httpx.Client(
            base_url=self.base_url, transport=transport, timeout=30.0,
            headers={"X-API-Key": self.api_key, "X-Interface": "mcp"})

    def size(self, raw: dict, account_mode: bool = False) -> tuple[int, dict]:
        body: dict[str, Any] = {"mode": "account", "request": raw} if account_mode else raw
        r = self._client.post("/v1/size", json=body)
        return r.status_code, r.json()

    def compare(self, requests: list[dict], labels: list[str] | None) -> tuple[int, dict]:
        r = self._client.post("/v1/scenarios/compare",
                              json={"requests": requests, "labels": labels})
        return r.status_code, r.json()

    def instrument(self, instrument_id: str) -> tuple[int, dict]:
        r = self._client.get(f"/v1/instruments/{instrument_id}")
        return r.status_code, r.json()

    def portfolio(self) -> tuple[int, dict]:
        r = self._client.get("/v1/portfolio")
        return r.status_code, r.json()

    def log_trades(self, strategy_id: str, results_r: list[float]) -> tuple[int, dict]:
        r = self._client.post("/v1/track-record",
                              json={"strategy_id": strategy_id, "results_r": results_r})
        return r.status_code, r.json()

    def add_position(self, instrument_id: str, direction: str, open_risk: float,
                     correlation_bucket: str) -> tuple[int, dict]:
        r = self._client.post("/v1/portfolio/position", json={
            "instrument_id": instrument_id, "direction": direction,
            "open_risk": open_risk, "correlation_bucket": correlation_bucket})
        return r.status_code, r.json()
