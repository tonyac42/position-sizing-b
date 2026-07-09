"""Generate function_schema.json — the plain function-calling flavor of the
tool definitions, for LLM stacks that don't speak MCP. Run after editing
tools.py:  python -m sizer_llm.gen_schema
"""
from __future__ import annotations

import json
from pathlib import Path

from .tools import TOOLS


def build() -> dict:
    return {
        "schema_version": "1.0",
        "usage": ("Anthropic/OpenAI-style function definitions for the Sizer API. "
                  "Apply the same guardrails as the MCP server by routing calls "
                  "through sizer_llm.dispatch.dispatch()."),
        "functions": [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in TOOLS
        ],
    }


def main() -> None:
    out = Path(__file__).parent / "function_schema.json"
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
