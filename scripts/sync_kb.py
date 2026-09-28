"""Sync knowledge_base/ to a Bedrock Knowledge Base (the RAG data pipeline).

1. Split every markdown file into one document per rule, plus a `<doc>.metadata.json`
   sidecar (rule_id, kind, severity, fixable, detect). This lets the retriever filter
   by rule_id/kind and keeps one rule per chunk. Create the KB data source with chunking
   strategy NONE.
2. Upload to s3://$KB_BUCKET/rules/ (removing deleted rules).
3. Start an ingestion job and wait for it to finish.

Usage: python scripts/sync_kb.py --bucket my-kb-bucket --kb-id KB123 --data-source-id DS123
"""
import argparse
import json
import sys
import time

import boto3

from pr_review_agent.rag.knowledge import kb_version, load_rules


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True)
    p.add_argument("--kb-id", required=True)
    p.add_argument("--data-source-id", required=True)
    p.add_argument("--kb-dir", default="knowledge_base")
    p.add_argument("--region")
    a = p.parse_args()

    s3 = boto3.client("s3", region_name=a.region)
    rules = load_rules(a.kb_dir)
    keep = set()
    for r in rules:
        key = f"rules/{r.id}.md"
        keep |= {key, f"{key}.metadata.json"}
        s3.put_object(Bucket=a.bucket, Key=key, Body=f"# {r.id}: {r.title}\n\n{r.text}".encode())
        meta = {"metadataAttributes": {"rule_id": r.id, "kind": r.kind, "title": r.title,
                                       "severity": str(r.severity), "fixable": r.fixable,
                                       "detect": r.detect or ""}}
        s3.put_object(Bucket=a.bucket, Key=f"{key}.metadata.json", Body=json.dumps(meta).encode())
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=a.bucket, Prefix="rules/"):
        for obj in page.get("Contents", []):
            if obj["Key"] not in keep:
                s3.delete_object(Bucket=a.bucket, Key=obj["Key"])
    print(f"uploaded {len(rules)} rules (kb version {kb_version(a.kb_dir)})")

    agent = boto3.client("bedrock-agent", region_name=a.region)
    job = agent.start_ingestion_job(knowledgeBaseId=a.kb_id, dataSourceId=a.data_source_id,
                                    description=f"kb {kb_version(a.kb_dir)}")["ingestionJob"]
    while job["status"] in ("STARTING", "IN_PROGRESS"):
        time.sleep(10)
        job = agent.get_ingestion_job(knowledgeBaseId=a.kb_id, dataSourceId=a.data_source_id,
                                      ingestionJobId=job["ingestionJobId"])["ingestionJob"]
    print(f"ingestion {job['status']}: {job.get('statistics')}")
    sys.exit(0 if job["status"] == "COMPLETE" else 1)


if __name__ == "__main__":
    main()
