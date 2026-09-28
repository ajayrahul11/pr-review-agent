"""Agent 4 - Verifier: checks every proposed fix before it can be posted.

Two layers:
 1. Deterministic checks (cheap, can't be sweet-talked):
      original_matches  - `original` is exactly the PR's new-side lines start..end
      small             - replacement is within MAX_FIX_LINES
      rule_resolved     - the rule's `detect` regex no longer fires on the replacement
      syntax            - patched hunk still parses (Python), when determinable
      no_secrets        - replacement introduces no secrets
 2. LLM review of fixes that pass layer 1 (behaviour preserved, rule truly resolved).
A fix is verified only if both layers pass.
"""
import json
import re

from pr_review_agent.agents.base import Agent, AgentResult
from pr_review_agent.config import get_settings
from pr_review_agent.diffutils import new_side, python_parses
from pr_review_agent.guardrails.input_guards import redact_secrets
from pr_review_agent.models import ChangedFile, Finding, Fix, Rule, Verdict


def static_checks(fix: Fix, file: ChangedFile, rule: Rule | None) -> dict[str, str]:
    side = new_side(file)
    checks: dict[str, str] = {}
    span = [side.get(n) for n in range(fix.start_line, fix.end_line + 1)]
    checks["original_matches"] = (
        "pass" if None not in span and "\n".join(span) == fix.original.rstrip("\n") else "fail")
    checks["small"] = ("pass" if len(fix.replacement.splitlines()) <= get_settings().max_fix_lines
                       and fix.replacement.strip() != fix.original.strip() else "fail")
    if rule and rule.detect:
        checks["rule_resolved"] = "fail" if re.search(rule.detect, fix.replacement, re.M) else "pass"
    else:
        checks["rule_resolved"] = "skipped"
    if file.path.endswith(".py") and checks["original_matches"] == "pass":
        before = "\n".join(side[n] for n in sorted(side))
        after = "\n".join(
            [side[n] for n in sorted(side) if n < fix.start_line]
            + [fix.replacement]
            + [side[n] for n in sorted(side) if n > fix.end_line])
        if python_parses(after):
            checks["syntax"] = "pass"
        else:
            checks["syntax"] = "fail" if python_parses(before) else "skipped"
    else:
        checks["syntax"] = "skipped"
    checks["no_secrets"] = "pass" if redact_secrets(fix.replacement)[1] == 0 else "fail"
    return checks


class VerifierAgent(Agent):
    name = "verifier"
    prompt = "verifier"
    allowed_tools = ("check_python_syntax", "get_rule")
    effort_setting = "verifier_effort"
    submit_tool = {
        "name": "submit_verdicts",
        "description": "Submit a verdict for every fix. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {"verdicts": {"type": "array", "items": {
                "type": "object",
                "properties": {"finding_id": {"type": "string"},
                               "approve": {"type": "boolean"},
                               "reason": {"type": "string"}},
                "required": ["finding_id", "approve", "reason"]}}},
            "required": ["verdicts"],
        },
    }

    def verify(self, fixes: list[Fix], files: dict[str, ChangedFile],
               findings: dict[str, Finding], rules: dict[str, Rule]) -> AgentResult | None:
        """Sets `fix.verdict` on every fix in place."""
        candidates = []
        for fix in fixes:
            finding = findings[fix.finding_id]
            checks = static_checks(fix, files[fix.file], rules.get(finding.rule_id))
            failed = [k for k, v in checks.items() if v == "fail"]
            fix.verdict = Verdict(verified=False, checks=checks,
                                  reason=f"failed static checks: {', '.join(failed)}" if failed else "")
            if not failed:
                candidates.append((fix, finding))
        if not candidates:
            return None

        payload = [{"finding_id": f.finding_id, "rule_id": fd.rule_id, "rule": fd.title,
                    "file": f.file, "original": f.original, "replacement": f.replacement,
                    "explanation": f.explanation} for f, fd in candidates]
        res = self.run(f"<fixes>\n{json.dumps(payload, indent=1)}\n</fixes>")
        verdicts = {v["finding_id"]: v for v in (res.output or {}).get("verdicts", [])}
        for fix, _ in candidates:
            v = verdicts.get(fix.finding_id)
            fix.verdict.checks["llm_review"] = "pass" if v and v.get("approve") else "fail"
            fix.verdict.verified = bool(v and v.get("approve"))
            fix.verdict.reason = (v or {}).get("reason", "no verdict returned")
        return res
