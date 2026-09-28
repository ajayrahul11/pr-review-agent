"""Parse the knowledge base: one `## ID: Title` section per rule, with metadata bullets."""
import hashlib
import re
from pathlib import Path

from pr_review_agent.models import Rule

_HEADING = re.compile(r"^## ([A-Z]+-\d+):\s*(.+)$", re.M)
_META = re.compile(r"^- (severity|fixable|detect):\s*(.+)$", re.M)


def parse_rules(path: Path) -> list[Rule]:
    text = path.read_text()
    kind = "bug_pattern" if "bug_patterns" in path.parts else "standard"
    matches = list(_HEADING.finditer(text))
    rules = []
    for i, m in enumerate(matches):
        body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        meta = {k: v.strip() for k, v in _META.findall(body)}
        rules.append(Rule(
            id=m.group(1), kind=kind, title=m.group(2).strip(),
            text=_META.sub("", body).strip(),
            severity=meta.get("severity", "medium"),
            fixable=meta.get("fixable", "no").lower() == "yes",
            detect=meta["detect"].strip("`") if "detect" in meta else None,
            source=str(path),
        ))
    return rules


def load_rules(kb_dir: str) -> list[Rule]:
    return [r for f in sorted(Path(kb_dir).rglob("*.md")) for r in parse_rules(f)]


def kb_version(kb_dir: str) -> str:
    h = hashlib.sha256()
    for f in sorted(Path(kb_dir).rglob("*.md")):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]
