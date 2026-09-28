"""The 4-agent PR review pipeline.

  PR ─► [input guardrails]
     ─► Agent 1  Retriever  : RAG over coding standards + past bug patterns (MCP tools)
     ─► Agent 2  Reviewer   : reviews the diff against ONLY the retrieved rules
     ─► [output guardrails] : grounding, confidence, dedupe, secret redaction
     ─► Agent 3  Fixer      : proposes minimal fixes for simple (fixable) violations
     ─► Agent 4  Verifier   : static checks + LLM review of every fix
     ─► [HITL gate]         : human approval (configurable)
     ─► GitHub PR review    : comments, with ```suggestion``` blocks for verified fixes
"""
import logging
import time
import uuid

from pr_review_agent import prompts
from pr_review_agent.agents.fixer_agent import FixerAgent
from pr_review_agent.agents.retriever_agent import RetrieverAgent
from pr_review_agent.agents.reviewer_agent import ReviewerAgent
from pr_review_agent.agents.verifier_agent import VerifierAgent
from pr_review_agent.config import get_settings
from pr_review_agent.guardrails.input_guards import GuardrailViolation, check_input
from pr_review_agent.guardrails.output_guards import check_findings
from pr_review_agent.hitl.store import ReviewStore, get_store
from pr_review_agent.integrations import github
from pr_review_agent.models import PullRequest, Review, ReviewStatus
from pr_review_agent.observability import emit
from pr_review_agent.rag.knowledge import kb_version

log = logging.getLogger(__name__)


def run_review(pr: PullRequest, store: ReviewStore | None = None) -> Review:
    s = get_settings()
    store = store or get_store()
    t0 = time.perf_counter()
    review = Review(id=uuid.uuid4().hex[:12], pr=pr, versions={
        "model": s.agent_model, "provider": s.llm_provider,
        "prompts": prompts.prompt_version(), "kb": kb_version(s.knowledge_base_dir)})
    tokens = [0, 0]

    def track(stage: str, res) -> None:
        if res is not None:
            review.trace += res.trace
            tokens[0] += res.input_tokens
            tokens[1] += res.output_tokens
        review.metrics[f"{stage}Ms"] = round((time.perf_counter() - t0) * 1000, 1)

    try:
        # Input guardrails
        try:
            safe_pr, events = check_input(pr)
        except GuardrailViolation as e:
            review.status, review.summary = ReviewStatus.blocked, str(e)
            review.guardrail_events.append(str(e))
            store.save(review)
            return review
        review.guardrail_events += events

        # Agent 1: Retriever
        review.context, events, res = RetrieverAgent().retrieve(safe_pr)
        review.guardrail_events += events
        track("Retrieve", res)

        # Agent 2: Reviewer (+ output guardrails)
        findings, review.summary, events, res = ReviewerAgent().review(safe_pr, review.context)
        review.guardrail_events += events
        review.findings, events = check_findings(safe_pr, findings)
        for i, f in enumerate(review.findings, 1):
            f.id = f"F{i}"
        review.guardrail_events += events
        track("Review", res)

        # Agent 3: Fixer
        review.fixes, events, res = FixerAgent().propose(safe_pr, review.findings)
        review.guardrail_events += events
        track("Fix", res)

        # Agent 4: Verifier
        res = VerifierAgent().verify(
            review.fixes, {f.path: f for f in safe_pr.files},
            {f.id: f for f in review.findings}, {c.rule.id: c.rule for c in review.context})
        track("Verify", res)
    except Exception as e:
        log.exception("review failed")
        review.status, review.summary = ReviewStatus.failed, f"pipeline error: {e}"
        store.save(review)
        return review

    verified = [f for f in review.fixes if f.verdict and f.verdict.verified]
    online = {
        "ReviewLatencyMs": round((time.perf_counter() - t0) * 1000, 1), "RulesRetrieved": len(review.context),
        "Findings": len(review.findings), "FixesProposed": len(review.fixes),
        "FixesVerified": len(verified), "InputTokens": tokens[0], "OutputTokens": tokens[1],
    }
    review.metrics.update(online)

    # HITL gate
    unverified = len(review.fixes) - len(verified)
    injection = any("prompt injection" in e for e in review.guardrail_events)
    needs_human = (s.hitl_mode == "always" or injection
                   or (s.hitl_mode == "unverified_only" and unverified > 0))
    if needs_human:
        review.status = ReviewStatus.pending_approval
    else:
        review.status = ReviewStatus.approved
        publish(review)
    store.save(review)
    emit(online, Stage="review")
    return review


def publish(review: Review) -> dict:
    result = github.post_review(review)
    if result.get("posted"):
        review.status = ReviewStatus.posted
    review.trace.append(f"publish: {result}")
    return result


def decide(review_id: str, approve: bool, note: str | None = None,
           drop_findings: list[str] | None = None, store: ReviewStore | None = None) -> Review:
    """Human decision on a pending review. `drop_findings` takes finding IDs (F1, F2...)."""
    store = store or get_store()
    review = store.get(review_id)
    if review is None:
        raise KeyError(review_id)
    if review.status != ReviewStatus.pending_approval:
        raise ValueError(f"review {review_id} is {review.status}, not pending_approval")
    review.reviewer_note = note
    dropped = set(drop_findings or [])
    review.findings = [f for f in review.findings if f.id not in dropped]
    review.fixes = [f for f in review.fixes if f.finding_id not in dropped]
    if approve:
        review.status = ReviewStatus.approved
        publish(review)
    else:
        review.status = ReviewStatus.rejected
    # Online feedback signal: approval/drop rates are the production quality metric.
    emit({"HumanApproved": int(approve), "FindingsDroppedByHuman": len(dropped)}, Stage="hitl")
    # TODO(hitl): export decisions to S3 as labelled data -> new eval cases (see TODO.md Phase 6).
    store.save(review)
    return review
