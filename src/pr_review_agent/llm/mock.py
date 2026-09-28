"""Deterministic stand-in for Claude so the whole 4-agent pipeline runs with no keys.

It mimics `client.messages.create(...)`: dispatches on the agent's `submit_*` tool,
calls real tools (the Retriever really searches the knowledge base over MCP), and
answers with tool_use blocks shaped exactly like Claude's.
"""
import json
import re
from itertools import count
from types import SimpleNamespace as NS

_ids = count(1)

# rule_id -> (regex on an added line, severity, title)
DETECTORS = {
    "SEC-001": (r"(?i)(password|secret|api_key|token)\s*=\s*['\"][^'\"]+['\"]", "critical", "Hard-coded secret"),
    "SEC-002": (r"execute\(\s*f['\"]", "high", "SQL built with an f-string"),
    "SEC-003": (r"\b(eval|exec)\(", "high", "eval/exec on untrusted input"),
    "STY-001": (r"^\s*print\(", "low", "print() instead of logging"),
    "STY-002": (r"#\s*TODO(?!\()", "info", "TODO without ticket"),
    "BUG-001": (r"except(\s+Exception)?\s*:\s*pass", "medium", "Swallowed exception (see INC-2291)"),
    "BUG-002": (r"def \w+\([^)]*=\s*(\[\]|\{\})", "medium", "Mutable default argument (see INC-1874)"),
    "BUG-003": (r"requests\.(get|post|put|delete)\((?![^)]*timeout)", "high", "HTTP call without timeout"),
}
_ADDED = re.compile(r"^\s*(\d+) \+ (.*)$")


def _tool_use(name, inp):
    return NS(type="tool_use", id=f"toolu_mock_{next(_ids)}", name=name, input=inp)


def _resp(content, stop_reason="tool_use"):
    return NS(content=content, stop_reason=stop_reason, usage=NS(input_tokens=0, output_tokens=0))


def _text(messages) -> str:
    c = messages[0]["content"]
    return c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c)


def _tool_results(messages) -> list[str]:
    out = []
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            out += [str(b.get("content", "")) for b in m["content"] if b.get("type") == "tool_result"]
    return out


def _added_lines(prompt: str):
    file = None
    for line in prompt.splitlines():
        if line.startswith("### File: "):
            file = line[10:].strip()
        elif (m := _ADDED.match(line)) and file:
            yield file, int(m.group(1)), m.group(2)


# ---- per-agent behaviour ---------------------------------------------------
def _retriever(messages):
    results = _tool_results(messages)
    if not results:  # turn 1: search the KB, one query per file per kind (parallel calls)
        by_file: dict[str, list[str]] = {}
        for file, _, code in _added_lines(_text(messages)):
            by_file.setdefault(file, []).append(code)
        calls = [_tool_use("search_knowledge_base", {"query": " ".join(codes)[:500], "kind": kind, "k": 8})
                 for codes in by_file.values() for kind in ("standard", "bug_pattern")]
        return _resp(calls)
    ids = dict.fromkeys(re.findall(r"^\[([A-Z]+-\d+)\]", "\n".join(results), re.M))
    return _resp([_tool_use("submit_context", {"items": [{"rule_id": i, "why": "matched diff"} for i in ids]})])


def _reviewer(messages):
    prompt = _text(messages)
    rules = dict(re.findall(r'<rule id="([A-Z]+-\d+)"[^>]*fixable="(\w+)"', prompt))
    findings, prev_for = [], {}
    for file, line, code in _added_lines(prompt):
        for rid, (pattern, sev, title) in DETECTORS.items():
            if rid in rules and re.search(pattern, code):
                findings.append({"rule_id": rid, "file": file, "line": line, "severity": sev,
                                 "title": title, "detail": code.strip()[:200],
                                 "fixable": rules[rid] == "true", "confidence": 0.9})
        is_for = bool(re.match(r"\s*for .+ in .+:", code))
        if is_for and prev_for.get(file) == line - 1 and "PERF-001" in rules:
            findings.append({"rule_id": "PERF-001", "file": file, "line": line, "severity": "low",
                             "title": "Nested loop membership check", "detail": code.strip(),
                             "fixable": False, "confidence": 0.7})
        if is_for:
            prev_for[file] = line
    blocking = sum(f["severity"] in ("high", "critical") for f in findings)
    summary = (f"(mock) {len(findings)} rule violation(s), {blocking} blocking. "
               + ("Request changes." if blocking else "Approve with comments." if findings else "Looks good."))
    return _resp([_tool_use("submit_findings", {"summary": summary, "findings": findings})])


def _fix_line(rule_id: str, code: str) -> str | None:
    if rule_id == "SEC-001" and (m := re.match(r"^(\s*)(\w+)\s*=\s*['\"].*['\"]\s*$", code)):
        return f'{m.group(1)}{m.group(2)} = os.environ["{m.group(2)}"]'
    if rule_id == "SEC-002" and (m := re.search(r"execute\(\s*f(['\"])(.*?)\1\s*\)", code)):
        names = re.findall(r"'?\{(\w+)\}'?", m.group(2))
        sql = re.sub(r"'?\{(\w+)\}'?", "?", m.group(2))
        return f'{code[:m.start()]}execute("{sql}", ({", ".join(names)},)){code[m.end():]}'
    if rule_id == "STY-001":
        if m := re.match(r"^(\s*)print\((['\"])(.*?)\2\s*,\s*(.+)\)\s*$", code):
            return f'{m.group(1)}log.info("{m.group(3)} %s", {m.group(4)})'
        return code.replace("print(", "log.info(", 1)
    if rule_id == "BUG-001" and (m := re.match(r"^(\s*)except(\s+\w+)?\s*:\s*pass\s*$", code)):
        ind = m.group(1)
        return f'{ind}except Exception:\n{ind}    log.exception("unexpected error")\n{ind}    raise'
    if rule_id == "BUG-003":
        return re.sub(r"(requests\.\w+\([^)]*)\)", r"\1, timeout=10)", code, count=1)
    return None


def _fixer(messages):
    findings = json.loads(re.search(r"<findings>\n(.*)\n</findings>", _text(messages), re.S).group(1))
    fixes = []
    for f in findings:
        if (new := _fix_line(f["rule_id"], f["code"])) is not None:
            fixes.append({"finding_id": f["finding_id"], "start_line": f["line"], "end_line": f["line"],
                          "original": f["code"], "replacement": new,
                          "explanation": f"Resolves {f['rule_id']}."})
    return _resp([_tool_use("submit_fixes", {"fixes": fixes})])


def _verifier(messages):
    fixes = json.loads(re.search(r"<fixes>\n(.*)\n</fixes>", _text(messages), re.S).group(1))
    return _resp([_tool_use("submit_verdicts", {"verdicts": [
        {"finding_id": f["finding_id"], "approve": True, "reason": "(mock) minimal change resolving the rule"}
        for f in fixes]})])


AGENTS = {"submit_context": _retriever, "submit_findings": _reviewer,
          "submit_fixes": _fixer, "submit_verdicts": _verifier}


class _Messages:
    def create(self, *, messages, tools=None, **_):
        for t in tools or []:
            if t["name"] in AGENTS:
                return AGENTS[t["name"]](messages)
        return _resp([NS(type="text", text="(mock) ok")], "end_turn")


class MockLLM:
    def __init__(self):
        self.messages = _Messages()
