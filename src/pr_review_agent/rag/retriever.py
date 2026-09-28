"""Retrieval backends behind one interface.

  local       BM25 over knowledge_base/ (zero deps, used locally and in CI evals)
  bedrock_kb  Amazon Bedrock Knowledge Base (production). Docs are synced one-rule-per-file
              with metadata sidecars by scripts/sync_kb.py, so each chunk == one rule.
"""
import math
import re
from collections import Counter
from functools import lru_cache
from typing import Protocol

from pr_review_agent.config import get_settings
from pr_review_agent.models import Rule
from pr_review_agent.rag.knowledge import load_rules

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    # split snake_case / punctuation so code tokens like `cur.execute(f"` match prose
    return _TOKEN.findall(text.lower().replace("_", " "))


class Retriever(Protocol):
    def search(self, query: str, k: int = 5, kind: str | None = None) -> list[Rule]: ...
    def get(self, rule_id: str) -> Rule | None: ...


class LocalBM25Retriever:
    def __init__(self, rules: list[Rule], k1: float = 1.5, b: float = 0.75):
        self.rules, self.k1, self.b = rules, k1, b
        self.by_id = {r.id: r for r in rules}
        self.docs = [Counter(_tokens(f"{r.id} {r.title} {r.text}")) for r in rules]
        self.avgdl = sum(sum(d.values()) for d in self.docs) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5, kind: str | None = None) -> list[Rule]:
        q = set(_tokens(query))
        scored = []
        for rule, d in zip(self.rules, self.docs, strict=True):
            if kind and rule.kind != kind:
                continue
            dl = sum(d.values())
            s = sum(self.idf[t] * d[t] * (self.k1 + 1)
                    / (d[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                    for t in q if t in d)
            if s > 0:
                scored.append((s, rule))
        return [r for _, r in sorted(scored, key=lambda x: -x[0])[:k]]

    def get(self, rule_id: str) -> Rule | None:
        return self.by_id.get(rule_id)


class BedrockKBRetriever:
    """Amazon Bedrock Knowledge Base via bedrock-agent-runtime `retrieve`."""

    def __init__(self, kb_id: str, region: str):
        import boto3

        self.kb_id = kb_id
        self.client = boto3.client("bedrock-agent-runtime", region_name=region)

    def _retrieve(self, query: str, k: int, flt: dict | None = None) -> list[Rule]:
        cfg: dict = {"numberOfResults": k}
        if flt:
            cfg["filter"] = flt
        res = self.client.retrieve(
            knowledgeBaseId=self.kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": cfg},
        )
        rules = []
        for r in res["retrievalResults"]:
            md = r.get("metadata", {})
            if "rule_id" not in md:
                continue
            rules.append(Rule(
                id=md["rule_id"], kind=md.get("kind", "standard"), title=md.get("title", ""),
                text=r["content"]["text"], severity=md.get("severity", "medium"),
                fixable=str(md.get("fixable", "false")).lower() == "true",
                detect=md.get("detect") or None,
                source=r.get("location", {}).get("s3Location", {}).get("uri", ""),
            ))
        return rules

    def search(self, query: str, k: int = 5, kind: str | None = None) -> list[Rule]:
        return self._retrieve(query, k, {"equals": {"key": "kind", "value": kind}} if kind else None)

    def get(self, rule_id: str) -> Rule | None:
        hits = self._retrieve(rule_id, 1, {"equals": {"key": "rule_id", "value": rule_id}})
        return hits[0] if hits else None


@lru_cache
def get_retriever() -> Retriever:
    s = get_settings()
    if s.rag_backend == "bedrock_kb":
        if not s.bedrock_kb_id:
            raise ValueError("RAG_BACKEND=bedrock_kb requires BEDROCK_KB_ID")
        return BedrockKBRetriever(s.bedrock_kb_id, s.aws_region)
    return LocalBM25Retriever(load_rules(s.knowledge_base_dir))
