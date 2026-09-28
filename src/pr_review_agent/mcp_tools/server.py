"""MCP server exposing the PR-review tools.

Run:  python -m pr_review_agent.mcp_tools.server        (stdio transport)
Try:  npx @modelcontextprotocol/inspector python -m pr_review_agent.mcp_tools.server
"""
from mcp.server.mcpserver import MCPServer

from pr_review_agent.mcp_tools import tools

mcp = MCPServer("pr-review-tools")


@mcp.tool()
def search_knowledge_base(query: str, kind: str | None = None, k: int = 5) -> str:
    """Search coding standards and past bug patterns. kind: 'standard' | 'bug_pattern' | null."""
    return tools.search_knowledge_base(query, kind, k)


@mcp.tool()
def get_rule(rule_id: str) -> str:
    """Get the full text of one rule by ID, e.g. SEC-002 or BUG-001."""
    return tools.get_rule(rule_id)


@mcp.tool()
def get_file_content(repo: str, path: str, ref: str = "main") -> str:
    """Fetch the full content of a repository file for extra context."""
    return tools.get_file_content(repo, path, ref)


@mcp.tool()
def check_python_syntax(code: str) -> str:
    """Check whether a Python snippet parses. Returns 'ok' or 'syntax error'."""
    return tools.check_python_syntax(code)


# TODO(mcp): add run_linter (ruff/eslint on the patched file) and run_tests tools so the
#   Verifier can execute checks in a sandbox instead of only parsing.

if __name__ == "__main__":
    mcp.run()
