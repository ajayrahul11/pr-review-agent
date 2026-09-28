from pr_review_agent.mcp_tools.provider import MCPToolProvider


def test_mcp_server_lists_and_calls_tools():
    p = MCPToolProvider()
    names = {t["name"] for t in p.schemas()}
    assert {"search_knowledge_base", "get_rule", "get_file_content", "check_python_syntax"} <= names
    assert "SEC-002" in p.call("get_rule", {"rule_id": "SEC-002"})
