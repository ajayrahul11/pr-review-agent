"""GitHub integration. Falls back to local fixtures when GITHUB_TOKEN is unset."""
import json
from pathlib import Path

import httpx

from pr_review_agent.config import get_settings
from pr_review_agent.models import ChangedFile, Finding, Fix, PullRequest, Review

API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().github_token}",
        "Accept": "application/vnd.github+json",
    }


def load_fixture(path: str) -> PullRequest:
    return PullRequest.model_validate(json.loads(Path(path).read_text()))


def fetch_pull_request(repo: str, number: int) -> PullRequest:
    with httpx.Client(base_url=API, headers=_headers(), timeout=30) as gh:
        pr = gh.get(f"/repos/{repo}/pulls/{number}").raise_for_status().json()
        files = gh.get(f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100})
        files.raise_for_status()
    return PullRequest(
        repo=repo, number=number, title=pr["title"], description=pr.get("body") or "",
        author=pr["user"]["login"], base_branch=pr["base"]["ref"], head_sha=pr["head"]["sha"],
        files=[ChangedFile(path=f["filename"], patch=f.get("patch", ""), status=f["status"])
               for f in files.json()],
    )


def fetch_file(repo: str, path: str, ref: str = "main") -> str:
    if not get_settings().github_token:
        return f"(offline mode: cannot fetch {repo}/{path}@{ref})"
    with httpx.Client(base_url=API, headers={**_headers(), "Accept": "application/vnd.github.raw"},
                      timeout=30) as gh:
        return gh.get(f"/repos/{repo}/contents/{path}", params={"ref": ref}).raise_for_status().text


def render_comment(finding: Finding, fix: Fix | None) -> str:
    body = f"**[{finding.severity}] {finding.rule_id}: {finding.title}**\n\n{finding.detail}"
    if fix and fix.verdict and fix.verdict.verified:
        body += (f"\n\n```suggestion\n{fix.replacement}\n```\n"
                 f"_{fix.explanation} Fix checked by the verifier agent "
                 f"({', '.join(k for k, v in fix.verdict.checks.items() if v == 'pass')})._")
    return body


def post_review(review: Review) -> dict:
    """Post the review with inline comments + verified ```suggestion``` fixes.

    Only called by the orchestrator after the Verifier and the HITL gate.
    """
    pr = review.pr
    comments = []
    for f in review.findings:
        fix = review.fix_for(f.id)
        verified = fix and fix.verdict and fix.verdict.verified
        c = {"path": f.file, "side": "RIGHT", "body": render_comment(f, fix),
             "line": fix.end_line if verified else f.line}
        if verified and fix.start_line != fix.end_line:
            c["start_line"], c["start_side"] = fix.start_line, "RIGHT"
        comments.append(c)
    if not get_settings().github_token:
        return {"posted": False, "reason": "offline mode (no GITHUB_TOKEN)", "comments": len(comments)}
    payload = {"body": review.summary, "event": "COMMENT", "comments": comments}
    if pr.head_sha:
        payload["commit_id"] = pr.head_sha
    with httpx.Client(base_url=API, headers=_headers(), timeout=30) as gh:
        r = gh.post(f"/repos/{pr.repo}/pulls/{pr.number}/reviews", json=payload)
        r.raise_for_status()
    return {"posted": True, "id": r.json().get("id"), "comments": len(comments)}
