"""Versioned agent prompts. The prompt hash is recorded on every review, eval report
and release manifest, so a quality change can be traced to a prompt change."""
import hashlib
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache
def load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text().strip()


def prompt_version() -> str:
    h = hashlib.sha256()
    for f in sorted(_DIR.glob("*.md")):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]
