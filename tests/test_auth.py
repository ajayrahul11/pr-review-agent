from fastapi.testclient import TestClient


def test_api_key_required_when_configured(monkeypatch):
    from pr_review_agent.api import main
    from pr_review_agent.config import get_settings
    monkeypatch.setenv("API_KEY", "s3cret")
    get_settings.cache_clear()
    client = TestClient(main.app)
    assert client.get("/reviews").status_code == 401
    assert client.get("/reviews", headers={"x-api-key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200
