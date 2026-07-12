"""Transport-agnostic tool dispatch: guardrails first, then the API.

Both the MCP server and any plain function-calling deployment call
`dispatch(tool_name, args, client)` so guardrail behavior is identical
everywhere. Returns a JSON-serializable dict in every case — guardrail
rejections and engine refusals are structured payloads, not exceptions,
because the calling model needs to read them.
"""
from __future__ import annotations

from .client import SizerAPIClient
from .guardrails import (
    GuardrailError,
    check_confirmation_token,
    issue_confirmation_token,
    validate_size_request,
)


def dispatch(tool: str, args: dict, client: SizerAPIClient) -> dict:
    try:
        return _dispatch(tool, args, client)
    except GuardrailError as e:
        return e.payload


def _dispatch(tool: str, args: dict, client: SizerAPIClient) -> dict:
    if tool == "size_position":
        validate_size_request(args)
        account_mode = bool(args.pop("account_mode", False))
        code, body = client.size(args, account_mode=account_mode)
        return _wrap_size(code, body)

    if tool == "compare_scenarios":
        for r in args.get("requests", []):
            validate_size_request(r)
        code, body = client.compare(args["requests"], args.get("labels"))
        return body if code == 200 else {"error": "api_error", "detail": body}

    if tool == "get_instrument":
        code, body = client.instrument(args["instrument_id"])
        return body if code == 200 else {"error": "not_found", "detail": body}

    if tool == "get_portfolio":
        code, body = client.portfolio()
        return body if code == 200 else {"error": "api_error", "detail": body}

    if tool == "log_trades":
        token = args.get("confirmation_token")
        if not token:
            return issue_confirmation_token(tool, args)
        check_confirmation_token(tool, args, token)
        code, body = client.log_trades(args["strategy_id"], args["results_r"])
        return body if code == 200 else {"error": "api_error", "detail": body}

    if tool == "add_position":
        token = args.get("confirmation_token")
        if not token:
            return issue_confirmation_token(tool, args)
        check_confirmation_token(tool, args, token)
        code, body = client.add_position(
            args["instrument_id"], args.get("direction", "long"),
            args["open_risk"], args.get("correlation_bucket", "default"))
        return body if code == 201 else {"error": "api_error", "detail": body}

    return {"error": "unknown_tool", "message": f"no tool named '{tool}'"}


def _wrap_size(code: int, body: dict) -> dict:
    if code == 200:
        return body
    if code == 422:  # structured refusal: a feature, relay it
        return body
    if code == 400:
        return {"error": "malformed_input", "detail": body,
                "ask_user": ["Fix the listed fields; ask the user if a value is unknown."]}
    return {"error": "api_error", "status_code": code, "detail": body}
