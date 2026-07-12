"""Sizer MCP server (stdio). Exposes the shared tool definitions; every call
routes through the HTTP API for consistent auth, audit, and versioning.

Run:  SIZER_API_URL=http://127.0.0.1:8000 SIZER_API_KEY=... sizer-mcp
"""
from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .client import SizerAPIClient
from .dispatch import dispatch
from .tools import TOOLS


def build_server(client: SizerAPIClient | None = None) -> Server:
    server = Server("sizer")
    api = client or SizerAPIClient()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
                annotations=types.ToolAnnotations(readOnlyHint=t["read_only"]),
            )
            for t in TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = await asyncio.to_thread(dispatch, name, arguments or {}, api)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def run() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
