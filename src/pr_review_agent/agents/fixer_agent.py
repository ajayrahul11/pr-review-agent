"""Agent 3 - Fixer: proposes minimal in-place fixes for simple (fixable) violations."""
import json

from pydantic import ValidationError

from pr_review_agent.agents.base import Agent, AgentResult
from pr_review_agent.diffutils import context_window, new_side
from pr_review_agent.models import Finding, Fix, PullRequest


class FixerAgent(Agent):
    name = "fixer"
    prompt = "fixer"
    allowed_tools = ("get_file_content", "check_python_syntax")
    effort_setting = "fixer_effort"
    submit_tool = {
        "name": "submit_fixes",
        "description": "Submit proposed fixes. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {"fixes": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "original": {"type": "string"},
                    "replacement": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["finding_id", "start_line", "end_line", "original",
                             "replacement", "explanation"]}}},
            "required": ["fixes"],
        },
    }

    def propose(self, pr: PullRequest, findings: list[Finding]
                ) -> tuple[list[Fix], list[str], AgentResult | None]:
        todo = [f for f in findings if f.fixable]
        if not todo:
            return [], [], None
        files = {f.path: f for f in pr.files}
        payload = [{
            "finding_id": f.id, "rule_id": f.rule_id, "file": f.file, "line": f.line,
            "title": f.title, "detail": f.detail,
            "code": new_side(files[f.file]).get(f.line, ""),
            "context": context_window(files[f.file], f.line),
        } for f in todo if f.file in files]
        res = self.run(f"<findings>\n{json.dumps(payload, indent=1)}\n</findings>")
        by_id = {f.id: f for f in todo}
        fixes, events = [], []
        for raw in (res.output or {}).get("fixes", []):
            finding = by_id.get(raw.get("finding_id", ""))
            if finding is None:
                events.append(f"fixer: dropped fix for unknown finding {raw.get('finding_id')}")
                continue
            try:
                fixes.append(Fix(file=finding.file, **raw))
            except ValidationError:
                events.append("fixer: dropped malformed fix")
        return fixes, events, res
