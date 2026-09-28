"""Domain models passed between the four agents, guardrails, HITL and evals."""
from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ChangedFile(BaseModel):
    path: str
    patch: str = ""
    status: str = "modified"


class PullRequest(BaseModel):
    repo: str
    number: int
    title: str
    description: str = ""
    author: str = ""
    base_branch: str = "main"
    head_sha: str = ""
    files: list[ChangedFile] = Field(default_factory=list)

    @property
    def diff(self) -> str:
        return "\n".join(f"--- {f.path}\n{f.patch}" for f in self.files)


# ---- Agent 1: Retriever --------------------------------------------------
class Rule(BaseModel):
    """A coding standard or a past bug pattern from the knowledge base."""
    id: str                       # e.g. SEC-002, BUG-001
    kind: str                     # "standard" | "bug_pattern"
    title: str
    text: str
    severity: Severity = Severity.medium
    fixable: bool = False         # simple enough for the Fixer agent
    detect: str | None = None     # optional regex; the Verifier re-runs it on the fix
    source: str = ""


class RetrievedContext(BaseModel):
    rule: Rule
    why: str = ""


# ---- Agent 2: Reviewer ---------------------------------------------------
class Finding(BaseModel):
    id: str = ""                  # assigned by orchestrator: F1, F2, ...
    rule_id: str
    file: str
    line: int
    severity: Severity
    title: str
    detail: str
    fixable: bool = False
    confidence: float = Field(0.7, ge=0, le=1)


# ---- Agent 3: Fixer / Agent 4: Verifier ---------------------------------
class Verdict(BaseModel):
    verified: bool
    checks: dict[str, str] = Field(default_factory=dict)   # check -> pass|fail|skipped
    reason: str = ""


class Fix(BaseModel):
    finding_id: str
    file: str
    start_line: int
    end_line: int
    original: str                 # exact new-side lines being replaced
    replacement: str
    explanation: str = ""
    verdict: Verdict | None = None


class ReviewStatus(StrEnum):
    running = "running"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"
    blocked = "blocked"
    failed = "failed"


class Review(BaseModel):
    id: str
    pr: PullRequest
    status: ReviewStatus = ReviewStatus.running
    summary: str = ""
    context: list[RetrievedContext] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    fixes: list[Fix] = Field(default_factory=list)
    guardrail_events: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)  # model, prompts, kb
    reviewer_note: str | None = None

    def fix_for(self, finding_id: str) -> Fix | None:
        return next((f for f in self.fixes if f.finding_id == finding_id), None)
