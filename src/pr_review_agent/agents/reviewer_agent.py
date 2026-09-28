"""Agent 2 - Reviewer: reviews the diff strictly against the retrieved rules."""
from pydantic import ValidationError

from pr_review_agent.agents.base import Agent, AgentResult
from pr_review_agent.diffutils import annotate
from pr_review_agent.models import Finding, PullRequest, RetrievedContext


class ReviewerAgent(Agent):
    name = "reviewer"
    prompt = "reviewer"
    allowed_tools = ("get_rule", "get_file_content")
    effort_setting = "reviewer_effort"
    submit_tool = {
        "name": "submit_findings",
        "description": "Submit all findings and a short summary. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "findings": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "severity": {"type": "string",
                                     "enum": ["info", "low", "medium", "high", "critical"]},
                        "title": {"type": "string"},
                        "detail": {"type": "string"},
                        "fixable": {"type": "boolean"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["rule_id", "file", "line", "severity", "title", "detail",
                                 "fixable", "confidence"]}},
            },
            "required": ["summary", "findings"],
        },
    }

    def review(self, pr: PullRequest, context: list[RetrievedContext]
               ) -> tuple[list[Finding], str, list[str], AgentResult]:
        rules = "\n\n".join(
            f'<rule id="{c.rule.id}" kind="{c.rule.kind}" severity="{c.rule.severity}" '
            f'fixable="{str(c.rule.fixable).lower()}">\n{c.rule.title}\n{c.rule.text}\n</rule>'
            for c in context)
        diff = "\n\n".join(annotate(f) for f in pr.files)
        res = self.run(f"<rules>\n{rules}\n</rules>\n\n<pr repo={pr.repo!r} title={pr.title!r}>\n"
                       f"<description>{pr.description}</description>\n{diff}\n</pr>")
        out = res.output or {}
        allowed = {c.rule.id: c.rule for c in context}
        findings, events = [], []
        for raw in out.get("findings", []):
            try:
                f = Finding(**raw)
            except ValidationError:
                events.append("reviewer: dropped malformed finding")
                continue
            if f.rule_id not in allowed:            # must cite a retrieved rule
                events.append(f"reviewer: dropped finding citing unretrieved rule {f.rule_id}")
                continue
            f.fixable = f.fixable and allowed[f.rule_id].fixable
            findings.append(f)
        return findings, out.get("summary", ""), events, res
