"""FastAPI app: trigger reviews, inspect them, and approve/reject (human-in-the-loop)."""
import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from pr_review_agent.config import get_settings
from pr_review_agent.hitl.store import get_store
from pr_review_agent.integrations import github
from pr_review_agent.models import PullRequest, Review, ReviewStatus
from pr_review_agent.workflow import orchestrator

logging.basicConfig(level=logging.INFO, format="%(message)s")
app = FastAPI(title="PR Review Agent", version="0.1.0")
store = get_store()


def require_api_key(x_api_key: str = Header("")) -> None:
    """Protects /reviews/* when API_KEY is set (always set it when deployed)."""
    key = get_settings().api_key
    if key and not hmac.compare_digest(key, x_api_key):
        raise HTTPException(401, "invalid api key")


auth = [Depends(require_api_key)]


class ReviewRequest(BaseModel):
    repo: str | None = None
    number: int | None = None
    pull_request: PullRequest | None = None     # pass a PR inline for local testing


class Decision(BaseModel):
    approve: bool
    note: str | None = None
    drop_findings: list[str] = []      # finding IDs, e.g. ["F3"]


@app.get("/health")
def health():
    from pr_review_agent import prompts
    s = get_settings()
    return {"status": "ok", "environment": s.environment, "llm_provider": s.llm_provider,
            "model": s.agent_model, "rag_backend": s.rag_backend,
            "prompt_version": prompts.prompt_version()}


@app.post("/reviews", response_model=Review, dependencies=auth)
def create_review(req: ReviewRequest):
    if req.pull_request:
        pr = req.pull_request
    elif req.repo and req.number:
        pr = github.fetch_pull_request(req.repo, req.number)
    else:
        raise HTTPException(400, "Provide pull_request, or repo + number")
    return orchestrator.run_review(pr, store)


@app.get("/reviews", response_model=list[Review], dependencies=auth)
def list_reviews(status: ReviewStatus | None = None):
    return store.list(status)


@app.get("/reviews/{review_id}", response_model=Review, dependencies=auth)
def get_review(review_id: str):
    review = store.get(review_id)
    if not review:
        raise HTTPException(404) from None
    return review


@app.post("/reviews/{review_id}/decision", response_model=Review, dependencies=auth)
def decide(review_id: str, d: Decision):
    # TODO(hitl): authenticate the human reviewer (Cognito / GitHub OAuth) and record who decided.
    try:
        return orchestrator.decide(review_id, d.approve, d.note, d.drop_findings, store)
    except KeyError:
        raise HTTPException(404) from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/webhooks/github", status_code=202)
async def github_webhook(request: Request, background: BackgroundTasks,
                         x_hub_signature_256: str = Header(""), x_github_event: str = Header("")):
    body = await request.body()
    secret = get_settings().github_webhook_secret
    if secret:
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(401, "bad signature")
    payload = await request.json()
    if x_github_event == "pull_request" and payload.get("action") in ("opened", "synchronize"):
        repo, number = payload["repository"]["full_name"], payload["number"]
        background.add_task(lambda: orchestrator.run_review(github.fetch_pull_request(repo, number), store))
        return {"queued": True}
    return {"ignored": x_github_event}
