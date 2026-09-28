"""Each agent in isolation."""
from pr_review_agent.agents.fixer_agent import FixerAgent
from pr_review_agent.agents.retriever_agent import RetrieverAgent
from pr_review_agent.agents.reviewer_agent import ReviewerAgent
from pr_review_agent.agents.verifier_agent import VerifierAgent, static_checks
from pr_review_agent.integrations.github import load_fixture
from pr_review_agent.rag.retriever import get_retriever

PR = "data/fixtures/sample_pr.json"


def test_retriever_uses_rag_and_returns_only_real_rules():
    context, _, res = RetrieverAgent().retrieve(load_fixture(PR))
    ids = {c.rule.id for c in context}
    assert {"SEC-002", "BUG-001"} <= ids               # a standard AND a past bug pattern
    assert any("search_knowledge_base" in t for t in res.trace)


def test_reviewer_only_cites_retrieved_rules():
    pr = load_fixture(PR)
    only_sql = [c for c in RetrieverAgent().retrieve(pr)[0] if c.rule.id == "SEC-002"]
    findings, *_ = ReviewerAgent().review(pr, only_sql)
    assert findings and {f.rule_id for f in findings} == {"SEC-002"}


def test_fixer_and_verifier():
    pr = load_fixture(PR)
    context = RetrieverAgent().retrieve(pr)[0]
    findings, *_ = ReviewerAgent().review(pr, context)
    for i, f in enumerate(findings, 1):
        f.id = f"F{i}"
    fixes, *_ = FixerAgent().propose(pr, findings)
    assert fixes and all(f.finding_id in {x.id for x in findings if x.fixable} for f in fixes)
    VerifierAgent().verify(fixes, {f.path: f for f in pr.files}, {f.id: f for f in findings},
                           {c.rule.id: c.rule for c in context})
    assert all(f.verdict and f.verdict.verified for f in fixes)


def test_verifier_rejects_fix_that_keeps_violation():
    from pr_review_agent.models import Fix
    pr = load_fixture(PR)
    users = pr.files[0]
    orig = "    cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")"
    bad = Fix(finding_id="F1", file=users.path, start_line=8, end_line=8, original=orig,
              replacement="    cur.execute(f\"SELECT * FROM users WHERE name = {name!r}\")")
    checks = static_checks(bad, users, get_retriever().get("SEC-002"))
    assert checks["original_matches"] == "pass" and checks["rule_resolved"] == "fail"
