import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_review_and_decision_flow():
    from pr_review_agent.api import main
    from pr_review_agent.hitl.store import SQLiteReviewStore
    main.store = SQLiteReviewStore()
    client = TestClient(main.app)
    assert client.get("/health").json()["prompt_version"]
    pr = json.loads(Path("data/fixtures/sample_pr.json").read_text())
    r = client.post("/reviews", json={"pull_request": pr})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    d = client.post(f"/reviews/{r.json()['id']}/decision", json={"approve": True, "drop_findings": ["F7"]})
    assert d.status_code == 200 and d.json()["status"] == "approved"
