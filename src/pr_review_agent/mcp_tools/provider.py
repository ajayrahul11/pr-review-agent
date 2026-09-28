"""ToolProvider: how agents discover and call tools.

- InProcessToolProvider: calls Python functions directly (default, fastest locally).
- MCPToolProvider: talks to any MCP server over stdio (our own or third-party, e.g.
  the GitHub MCP server), so new tools can be plugged in without code changes.
"""
import asyncio
import sys
from typing import Protocol

from pr_review_agent.config import get_settings
from pr_review_agent.mcp_tools.tools import TOOLS


class ToolProvider(Protocol):
    def schemas(self) -> list[dict]: ...
    def call(self, name: str, args: dict) -> str: ...


class InProcessToolProvider:
    def schemas(self) -> list[dict]:
        return [{"name": n, "description": (fn.__doc__ or "").strip(), "input_schema": schema}
                for n, (fn, schema) in TOOLS.items()]

    def call(self, name: str, args: dict) -> str:
        fn, _ = TOOLS[name]
        return str(fn(**args))


class MCPToolProvider:
    """Minimal synchronous wrapper over an MCP stdio client (one session per call).

    TODO(mcp): keep a long-lived session, support multiple servers, and add a
    streamable-HTTP transport for remote MCP servers when deployed on AWS.
    """

    def __init__(self, command: str = sys.executable,
                 args: tuple[str, ...] = ("-m", "pr_review_agent.mcp_tools.server")):
        self.command, self.args = command, list(args)
        self._schemas: list[dict] | None = None

    async def _with_session(self, fn):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.command, args=self.args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    def schemas(self) -> list[dict]:
        if self._schemas is None:
            async def _list(session):
                res = await session.list_tools()
                return [{"name": t.name, "description": t.description or "",
                         "input_schema": t.input_schema} for t in res.tools]
            self._schemas = asyncio.run(self._with_session(_list))
        return self._schemas

    def call(self, name: str, args: dict) -> str:
        async def _call(session):
            res = await session.call_tool(name, args)
            return "\n".join(getattr(c, "text", "") for c in res.content)
        return asyncio.run(self._with_session(_call))


def get_tool_provider() -> ToolProvider:
    return MCPToolProvider() if get_settings().mcp_mode == "stdio" else InProcessToolProvider()
