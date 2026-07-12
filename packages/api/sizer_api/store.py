"""SQLite persistence: API keys, account state, track records, audit log,
idempotency cache. Boring on purpose.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL,               -- space-separated
    pinned_methodology TEXT,            -- NULL = latest
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    bankroll REAL,
    peak_equity REAL,
    preferences TEXT NOT NULL DEFAULT '{}'   -- JSON: kelly_fraction, caps...
);
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    open_risk REAL NOT NULL,
    correlation_bucket TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategies (
    account_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    claimed_edge TEXT,                  -- JSON EdgeEstimate
    edge_source TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, strategy_id)
);
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    r_multiple REAL NOT NULL,
    logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    interface TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    methodology_version TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    account_id TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, idem_key)
);
"""

ALL_SCOPES = ["size:read", "portfolio:read", "portfolio:write", "trackrecord:write",
              "instruments:read"]

DEV_KEY = "sizer-dev-key"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("SIZER_DB", "sizer.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._seed_dev_key()

    def _seed_dev_key(self) -> None:
        """Development key so the UI/MCP work out of the box. Replace in prod."""
        with self._lock:
            row = self._conn.execute("SELECT key FROM api_keys WHERE key=?", (DEV_KEY,)).fetchone()
            if not row:
                self._conn.execute(
                    "INSERT INTO api_keys (key, account_id, name, scopes, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (DEV_KEY, "dev-account", "development", " ".join(ALL_SCOPES), _now()))
                self._conn.execute(
                    "INSERT OR IGNORE INTO accounts (account_id, bankroll) VALUES (?, NULL)",
                    ("dev-account",))
                self._conn.commit()

    # ---- keys / accounts -------------------------------------------------- #

    def key_record(self, key: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM api_keys WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def create_key(self, account_id: str, name: str, scopes: list[str]) -> str:
        key = "szr_" + secrets.token_urlsafe(24)
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_keys (key, account_id, name, scopes, created_at) VALUES (?,?,?,?,?)",
                (key, account_id, name, " ".join(scopes), _now()))
            self._conn.execute("INSERT OR IGNORE INTO accounts (account_id) VALUES (?)",
                               (account_id,))
            self._conn.commit()
        return key

    def account(self, account_id: str) -> dict:
        row = self._conn.execute("SELECT * FROM accounts WHERE account_id=?",
                                 (account_id,)).fetchone()
        if row is None:
            return {"account_id": account_id, "bankroll": None, "peak_equity": None,
                    "preferences": {}}
        d = dict(row)
        d["preferences"] = json.loads(d.get("preferences") or "{}")
        return d

    def update_account(self, account_id: str, bankroll: float | None = None,
                       peak_equity: float | None = None,
                       preferences: dict | None = None) -> None:
        acct = self.account(account_id)
        prefs = preferences if preferences is not None else acct["preferences"]
        with self._lock:
            self._conn.execute(
                "INSERT INTO accounts (account_id, bankroll, peak_equity, preferences) "
                "VALUES (?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                "bankroll=excluded.bankroll, peak_equity=excluded.peak_equity, "
                "preferences=excluded.preferences",
                (account_id,
                 bankroll if bankroll is not None else acct["bankroll"],
                 peak_equity if peak_equity is not None else acct["peak_equity"],
                 json.dumps(prefs)))
            self._conn.commit()

    # ---- positions -------------------------------------------------------- #

    def positions(self, account_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM positions WHERE account_id=?",
                                  (account_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_position(self, account_id: str, instrument_id: str, direction: str,
                     open_risk: float, correlation_bucket: str) -> str:
        pid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
                (pid, account_id, instrument_id, direction, open_risk,
                 correlation_bucket, _now()))
            self._conn.commit()
        return pid

    def delete_position(self, account_id: str, position_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM positions WHERE account_id=? AND position_id=?",
                (account_id, position_id))
            self._conn.commit()
        return cur.rowcount > 0

    # ---- strategies / track record ---------------------------------------- #

    def upsert_strategy(self, account_id: str, strategy_id: str,
                        claimed_edge: dict | None, edge_source: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO strategies (account_id, strategy_id, claimed_edge, edge_source, "
                "created_at) VALUES (?,?,?,?,?) ON CONFLICT(account_id, strategy_id) DO UPDATE "
                "SET claimed_edge=COALESCE(excluded.claimed_edge, strategies.claimed_edge), "
                "edge_source=COALESCE(excluded.edge_source, strategies.edge_source)",
                (account_id, strategy_id,
                 json.dumps(claimed_edge) if claimed_edge else None, edge_source, _now()))
            self._conn.commit()

    def strategy(self, account_id: str, strategy_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM strategies WHERE account_id=? AND strategy_id=?",
            (account_id, strategy_id)).fetchone()
        return dict(row) if row else None

    def log_trades(self, account_id: str, strategy_id: str, r_multiples: list[float]) -> int:
        with self._lock:
            for r in r_multiples:
                self._conn.execute(
                    "INSERT INTO trades VALUES (?,?,?,?,?)",
                    (str(uuid.uuid4()), account_id, strategy_id, r, _now()))
            self._conn.commit()
        return len(r_multiples)

    def track_record(self, account_id: str, strategy_id: str,
                     recent_window: int = 50) -> dict | None:
        """Realized summary stats in the engine's RealizedResults shape."""
        rows = self._conn.execute(
            "SELECT r_multiple FROM trades WHERE account_id=? AND strategy_id=? "
            "ORDER BY logged_at, trade_id",
            (account_id, strategy_id)).fetchall()
        rs = [r["r_multiple"] for r in rows]
        if not rs:
            return None
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        out = {
            "n_trades": len(rs),
            "win_rate": len(wins) / len(rs),
            "avg_win_r": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss_r": abs(sum(losses) / len(losses)) if losses else 0.0,
            "expectancy_r": sum(rs) / len(rs),
        }
        recent = rs[-recent_window:]
        if len(recent) >= 10 and len(rs) > recent_window:
            out["recent_expectancy_r"] = sum(recent) / len(recent)
            out["recent_n_trades"] = len(recent)
        return out

    # ---- audit / idempotency ---------------------------------------------- #

    def audit(self, account_id: str, interface: str, input_hash: str, request: dict,
              response: dict, status: str, engine_version: str, methodology: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (account_id, interface, input_hash, request_json, "
                "response_json, status, engine_version, methodology_version, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, interface, input_hash, json.dumps(request),
                 json.dumps(response), status, engine_version, methodology, _now()))
            self._conn.commit()

    def audit_entries(self, account_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, interface, input_hash, status, engine_version, "
            "methodology_version, timestamp FROM audit_log WHERE account_id=? "
            "ORDER BY id DESC LIMIT ?", (account_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def idempotency_get(self, account_id: str, idem_key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM idempotency WHERE account_id=? AND idem_key=?",
            (account_id, idem_key)).fetchone()
        return dict(row) if row else None

    def idempotency_put(self, account_id: str, idem_key: str, input_hash: str,
                        response: dict, status_code: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO idempotency VALUES (?,?,?,?,?,?)",
                (account_id, idem_key, input_hash, json.dumps(response), status_code, _now()))
            self._conn.commit()
