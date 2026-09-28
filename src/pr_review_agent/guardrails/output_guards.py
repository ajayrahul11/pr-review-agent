"""Guardrails on Reviewer output before anything reaches the Fixer, a human or GitHub."""
from pr_review_agent.config import get_settings
from pr_review_agent.diffutils import added_lines
from pr_review_agent.guardrails.input_guards import redact_secrets
from pr_review_agent.models import Finding, PullRequest

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def check_findings(pr: PullRequest, findings: list[Finding]) -> tuple[list[Finding], list[str]]:
    s = get_settings()
    files = {f.path: f for f in pr.files}
    events, kept, seen = [], [], set()
    for f in findings:
        # 1. Grounding: must point at a line this PR actually ADDED.
        if f.file not in files or f.line not in added_lines(files[f.file]):
            events.append(f"dropped ungrounded finding {f.rule_id} at {f.file}:{f.line}")
            continue
        # 2. Confidence threshold.
        if f.confidence < s.min_confidence_to_post:
            events.append(f"dropped low-confidence finding {f.rule_id} ({f.confidence})")
            continue
        # 3. De-duplicate.
        if (key := (f.file, f.line, f.rule_id)) in seen:
            continue
        seen.add(key)
        # 4. Never echo secrets into a public PR comment.
        f.detail, _ = redact_secrets(f.detail)
        kept.append(f)
    # TODO(guardrails): cap comments per PR; tone check; Bedrock Guardrails ApplyGuardrail on text.
    kept.sort(key=lambda f: -SEVERITY_RANK[f.severity])
    return kept, events
