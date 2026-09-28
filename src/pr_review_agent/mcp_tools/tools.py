"""Tool implementations shared by the in-process provider and the MCP server.

Each agent gets an explicit allowlist of these (see agents/*.py). Write actions such as
posting PR comments are deliberately NOT tools: only the orchestrator posts, after the
Verifier and (optionally) a human have signed off.
"""
from collections.abc import Callable
from typing import Any

from pr_review_agent.diffutils import python_parses
from pr_review_agent.integrations import github
from pr_review_agent.rag.retriever import get_retriever


def _fmt(rule) -> str:
    fx = "fixable" if rule.fixable else "not-fixable"
    return f"[{rule.id}] ({rule.kind}, {rule.severity}, {fx}) {rule.title}\n{rule.text}"


def search_knowledge_base(query: str, kind: str | None = None, k: int = 5) -> str:
    """Search coding standards and past bug patterns. kind: 'standard' | 'bug_pattern' | null."""
    hits = get_retriever().search(query, k=k, kind=kind)
    return "\n\n".join(_fmt(r) for r in hits) or "No matching rules."


def get_rule(rule_id: str) -> str:
    """Get the full text of one rule by ID, e.g. SEC-002 or BUG-001."""
    rule = get_retriever().get(rule_id)
    return _fmt(rule) if rule else f"Unknown rule {rule_id}"


def get_file_content(repo: str, path: str, ref: str = "main") -> str:
    """Fetch the full content of a repository file for extra context."""
    return github.fetch_file(repo, path, ref)[:20_000]


def check_python_syntax(code: str) -> str:
    """Check whether a Python snippet parses. Returns 'ok' or 'syntax error'."""
    return "ok" if python_parses(code) else "syntax error"


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS: dict[str, tuple[Callable[..., Any], dict]] = {
    "search_knowledge_base": (search_knowledge_base, _schema(
        {"query": {"type": "string"},
         "kind": {"type": "string", "enum": ["standard", "bug_pattern"]},
         "k": {"type": "integer"}}, ["query"])),
    "get_rule": (get_rule, _schema({"rule_id": {"type": "string"}}, ["rule_id"])),
    "get_file_content": (get_file_content, _schema(
        {"repo": {"type": "string"}, "path": {"type": "string"}, "ref": {"type": "string"}},
        ["repo", "path"])),
    "check_python_syntax": (check_python_syntax, _schema({"code": {"type": "string"}}, ["code"])),
}
