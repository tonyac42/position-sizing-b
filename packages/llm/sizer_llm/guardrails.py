"""Anti-hallucination guardrails, applied identically by the MCP server and
any plain function-calling deployment (via `dispatch`).

Three checks, in order:
1. Required-field discipline: critical fields must be present.
2. Confidence discipline: a field_confidence map must be supplied, and no
   critical field may carry "guessed" confidence — the model gets back a
   structured confirm_these_values error to relay to the user.
3. Mutation discipline: state-changing tools need a confirmation token that
   the model can only sensibly obtain by showing the user a summary.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import secrets
import time

CRITICAL_ALWAYS = ["bankroll", "edge_estimate"]
# One of these must be present to define risk (any confidence, checked below).
RISK_DEFINITION_FIELDS = ["stop_price", "structural_max_loss", "entry_price", "market_price"]
CRITICAL_CONFIDENCE = ["bankroll", "edge_estimate", "stop_price", "entry_price",
                       "structural_max_loss"]

_TOKEN_SECRET = secrets.token_bytes(32)
TOKEN_TTL_SECONDS = 600


class GuardrailError(Exception):
    """Structured, machine-relayable rejection."""

    def __init__(self, code: str, message: str, ask_user: list[str]):
        self.payload = {"error": code, "message": message, "ask_user": ask_user}
        super().__init__(message)


def validate_size_request(raw: dict) -> None:
    missing = [f for f in CRITICAL_ALWAYS if raw.get(f) in (None, {}, "")]
    trade = raw.get("trade") or {}
    if not any(trade.get(f) or raw.get(f) for f in RISK_DEFINITION_FIELDS):
        missing.append("stop_price or structural_max_loss (or a prediction contract price)")
    if missing:
        raise GuardrailError(
            "missing_critical_fields",
            "These values define the user's risk and must come from the user, "
            "not from you: " + ", ".join(missing),
            [f"Ask the user for: {m}" for m in missing],
        )

    fc = raw.get("field_confidence")
    if not isinstance(fc, dict) or not fc:
        raise GuardrailError(
            "missing_field_confidence",
            "You must pass field_confidence declaring how you know each value "
            "(user_stated | inferred | guessed).",
            ["Re-call with an honest field_confidence map."],
        )
    guessed = [f for f in CRITICAL_CONFIDENCE if fc.get(f) == "guessed"]
    if guessed:
        raise GuardrailError(
            "confirm_these_values",
            "Critical values were guessed rather than provided by the user: "
            + ", ".join(guessed) + ". Sizing math on invented numbers produces "
            "confident-looking nonsense.",
            [f"Confirm the value of '{f}' with the user, then re-call with "
             f"field_confidence['{f}'] = 'user_stated'." for f in guessed],
        )


def issue_confirmation_token(tool: str, args: dict) -> dict:
    """First-call response for a mutation: a summary for the user + a token
    bound to these exact arguments (so the model can't confirm one thing and
    execute another)."""
    body = _canonical(tool, args)
    ts = str(int(time.time()))
    sig = hmac.new(_TOKEN_SECRET, f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()[:32]
    token = f"{ts}.{sig}"
    return {
        "confirmation_required": True,
        "confirmation_token": token,
        "expires_in_seconds": TOKEN_TTL_SECONDS,
        "show_user": _mutation_summary(tool, args),
        "instructions": ("Show `show_user` to the user. Only after the user explicitly "
                         "confirms, call this tool again with the same arguments plus "
                         "confirmation_token."),
    }


def check_confirmation_token(tool: str, args: dict, token: str) -> None:
    try:
        ts, sig = token.split(".", 1)
        age = time.time() - int(ts)
    except ValueError:
        raise GuardrailError("bad_confirmation_token", "Malformed confirmation token.",
                             ["Re-call without a token to get a fresh one."])
    body = _canonical(tool, args)
    expect = hmac.new(_TOKEN_SECRET, f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expect):
        raise GuardrailError(
            "bad_confirmation_token",
            "Token does not match these arguments — the confirmed action and the "
            "requested action differ.",
            ["Re-call without a token, show the new summary, and confirm again."])
    if age > TOKEN_TTL_SECONDS:
        raise GuardrailError("confirmation_token_expired", "Confirmation token expired.",
                             ["Re-call without a token and re-confirm with the user."])


def _canonical(tool: str, args: dict) -> str:
    clean = {k: v for k, v in args.items() if k != "confirmation_token"}
    return tool + ":" + json.dumps(clean, sort_keys=True)


def _mutation_summary(tool: str, args: dict) -> str:
    if tool == "log_trades":
        rs = args.get("results_r", [])
        return (f"Log {len(rs)} realized trade result(s) totalling {sum(rs):+.2f}R "
                f"against strategy '{args.get('strategy_id')}'? This permanently "
                "updates the track record used for sizing.")
    if tool == "add_position":
        return (f"Register an open {args.get('direction', 'long')} position in "
                f"{args.get('instrument_id')} risking ${args.get('open_risk'):,.0f} "
                f"(bucket '{args.get('correlation_bucket', 'default')}')? This reduces "
                "available heat for future trades.")
    return f"Execute {tool} with {json.dumps(args)}?"
