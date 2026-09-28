import pytest

from pr_review_agent.config import get_settings


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch, tmp_path):
    for k, v in {"LLM_PROVIDER": "mock", "MCP_MODE": "inprocess", "RAG_BACKEND": "local",
                 "HITL_BACKEND": "sqlite", "HITL_MODE": "always", "GITHUB_TOKEN": "",
                 "HITL_DB_PATH": str(tmp_path / "reviews.db")}.items():
        monkeypatch.setenv(k, v)
    from pr_review_agent.hitl.store import get_store
    from pr_review_agent.llm.client import get_llm
    from pr_review_agent.rag.retriever import get_retriever
    for fn in (get_settings, get_llm, get_retriever, get_store):
        fn.cache_clear()
    yield
    get_settings.cache_clear()
