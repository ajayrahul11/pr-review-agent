"""Unified-diff helpers: map patch lines to new-file line numbers.

Agents see an annotated diff ("  12 + code") so the line numbers they report are
the exact lines GitHub needs for review comments and ```suggestion blocks.
"""
import ast
import re
import textwrap
from dataclasses import dataclass

from pr_review_agent.models import ChangedFile

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class DiffLine:
    kind: str            # "+", "-", " "
    new_line: int | None
    text: str


def parse_patch(patch: str) -> list[DiffLine]:
    out, new = [], 0
    for raw in patch.splitlines():
        if m := _HUNK.match(raw):
            new = int(m.group(1))
            continue
        kind, text = (raw[:1] or " "), raw[1:]
        if kind == "-":
            out.append(DiffLine("-", None, text))
        elif kind in ("+", " "):
            out.append(DiffLine(kind, new, text))
            new += 1
    return out


def annotate(f: ChangedFile) -> str:
    rows = [f"### File: {f.path}"]
    for d in parse_patch(f.patch):
        num = f"{d.new_line:>5}" if d.new_line else "     "
        rows.append(f"{num} {d.kind} {d.text}")
    return "\n".join(rows)


def new_side(f: ChangedFile) -> dict[int, str]:
    """New-file line number -> text, for every line visible in the patch."""
    return {d.new_line: d.text for d in parse_patch(f.patch) if d.new_line}


def added_lines(f: ChangedFile) -> dict[int, str]:
    return {d.new_line: d.text for d in parse_patch(f.patch) if d.kind == "+"}


def context_window(f: ChangedFile, line: int, radius: int = 3) -> str:
    side = new_side(f)
    return "\n".join(f"{n:>5}  {side[n]}" for n in range(line - radius, line + radius + 1) if n in side)


def python_parses(code: str) -> bool:
    try:
        ast.parse(textwrap.dedent(code))
        return True
    except SyntaxError:
        return False
