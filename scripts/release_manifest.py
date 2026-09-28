"""Write + upload the release manifest: the "model registry" record for a deploy.

Ties together everything that determines behaviour, so any production review can be
traced back to exactly what produced it, and any release can be rolled back to.

Usage: python scripts/release_manifest.py --bucket ARTIFACTS --image URI --env prod
"""
import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--env", required=True)
    p.add_argument("--report", default="evals/reports/latest.json")
    a = p.parse_args()

    report = json.loads(Path(a.report).read_text())
    sha = os.environ.get("GITHUB_SHA", report["versions"]["git_sha"])[:12]
    manifest = {
        "released_at": datetime.now(UTC).isoformat(),
        "environment": a.env,
        "image": a.image,
        "git_sha": sha,
        "versions": report["versions"],          # model, prompts hash, kb hash, provider
        "eval_metrics": report["metrics"],       # the gate this release passed
        "run_url": f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
                   f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
    }
    s3 = boto3.client("s3")
    body = json.dumps(manifest, indent=2).encode()
    s3.put_object(Bucket=a.bucket, Key=f"releases/{a.env}/{sha}.json", Body=body)
    s3.put_object(Bucket=a.bucket, Key=f"releases/{a.env}/latest.json", Body=body)
    s3.put_object(Bucket=a.bucket, Key=f"evals/{sha}.json", Body=Path(a.report).read_bytes())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
