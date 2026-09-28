"""Eval suite: scores each agent separately so a regression points at the agent that caused it.

  retrieval_recall     Agent 1   expected rule IDs retrieved (per case, averaged)
  review_precision     Agent 2   findings matching a labelled violation (file, rule, line±2)
  review_recall        Agent 2   labelled violations found
  fix_success_rate     Agent 3+4 expected fixes that were proposed, VERIFIED, and contain the
                                 expected change
  verifier_accuracy    Agent 4   verdicts on hand-labelled good/bad fixes (bad must fail)
  guardrail_pass_rate            expected guardrail events raised

`gate()` compares against evals/thresholds.toml and is what CI / the deploy pipeline run.
"""
import json
import os
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

from pr_review_agent import prompts
from pr_review_agent.agents.verifier_agent import VerifierAgent
from pr_review_agent.config import get_settings
from pr_review_agent.hitl.store import SQLiteReviewStore
from pr_review_agent.models import ChangedFile, Finding, Fix, PullRequest
from pr_review_agent.rag.knowledge import kb_version
from pr_review_agent.rag.retriever import get_retriever
from pr_review_agent.workflow.orchestrator import run_review


def _jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _git_sha() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def eval_pipeline(cases: list[dict]) -> tuple[dict, list[dict]]:
    store = SQLiteReviewStore(str(Path(tempfile.mkdtemp()) / "evals.db"))
    rows, tp, n_found, n_expected, fix_ok, fix_total, latencies = [], 0, 0, 0, 0, 0, []
    recalls, guard_ok = [], []
    for case in cases:
        t0 = time.perf_counter()
        review = run_review(PullRequest.model_validate(case["pr"]), store)
        latencies.append((time.perf_counter() - t0) * 1000)

        got_rules = {c.rule.id for c in review.context}
        exp_rules = set(case.get("expected_rules", []))
        recalls.append(len(exp_rules & got_rules) / len(exp_rules) if exp_rules else 1.0)

        expected = case.get("expected_findings", [])
        matched = [f for f in review.findings if any(
            e["file"] == f.file and e["rule_id"] == f.rule_id and abs(e["line"] - f.line) <= 2
            for e in expected)]
        hit = [e for e in expected if any(
            e["file"] == f.file and e["rule_id"] == f.rule_id and abs(e["line"] - f.line) <= 2
            for f in review.findings)]
        tp_prec = len(matched)
        n_found += len(review.findings)
        tp += len(hit)
        n_expected += len(expected)
        case_fix_ok = 0
        for ef in case.get("expected_fixes", []):
            fix_total += 1
            for f in review.findings:
                fx = review.fix_for(f.id)
                if (f.rule_id == ef["rule_id"] and fx and fx.verdict and fx.verdict.verified
                        and ef["must_contain"] in fx.replacement):
                    case_fix_ok += 1
                    break
        fix_ok += case_fix_ok
        g = all(any(x in e for e in review.guardrail_events) for x in case.get("expect_guardrails", []))
        guard_ok.append(g)
        rows.append({"id": case["id"], "status": str(review.status), "retrieval_recall": round(recalls[-1], 2),
                     "findings": len(review.findings), "true_positives": tp_prec,
                     "expected_findings": len(expected), "fixes_ok": case_fix_ok,
                     "fixes_expected": len(case.get("expected_fixes", [])), "guardrails_ok": g,
                     "latency_ms": round(latencies[-1], 1)})
    precision_tp = sum(r["true_positives"] for r in rows)
    metrics = {
        "retrieval_recall": sum(recalls) / len(recalls),
        "review_precision": precision_tp / n_found if n_found else 1.0,
        "review_recall": tp / n_expected if n_expected else 1.0,
        "fix_success_rate": fix_ok / fix_total if fix_total else 1.0,
        "guardrail_pass_rate": sum(guard_ok) / len(guard_ok),
        "avg_latency_ms": sum(latencies) / len(latencies),
    }
    return metrics, rows


def eval_verifier(cases: list[dict]) -> tuple[dict, list[dict]]:
    retriever, rows = get_retriever(), []
    for c in cases:
        file = ChangedFile(**c["file"])
        finding = Finding(id="F1", rule_id=c["rule_id"], file=file.path, line=c["line"],
                          severity="medium", title=c["rule_id"], detail="", fixable=True)
        fix = Fix(finding_id="F1", file=file.path, **c["fix"])
        rule = retriever.get(c["rule_id"])
        VerifierAgent().verify([fix], {file.path: file}, {"F1": finding}, {rule.id: rule} if rule else {})
        rows.append({"id": c["id"], "expected": c["expected_verified"], "got": fix.verdict.verified,
                     "checks": fix.verdict.checks})
    acc = sum(r["expected"] == r["got"] for r in rows) / len(rows)
    return {"verifier_accuracy": acc}, rows


def run(golden: str = "evals/datasets/golden.jsonl",
        verifier: str = "evals/datasets/verifier_cases.jsonl",
        report_dir: str = "evals/reports") -> dict:
    s = get_settings()
    m1, pipeline_rows = eval_pipeline(_jsonl(golden))
    m2, verifier_rows = eval_verifier(_jsonl(verifier))
    report = {
        "metrics": {k: round(v, 3) for k, v in {**m1, **m2}.items()},
        "versions": {"git_sha": _git_sha(), "provider": s.llm_provider, "model": s.agent_model,
                     "prompts": prompts.prompt_version(), "kb": kb_version(s.knowledge_base_dir)},
        "pipeline_cases": pipeline_rows,
        "verifier_cases": verifier_rows,
    }
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(report, indent=2))
    return report


def gate(report: dict, thresholds: str = "evals/thresholds.toml") -> list[str]:
    """Return a list of failures (empty == pass)."""
    t = tomllib.loads(Path(thresholds).read_text())
    m, failures = report["metrics"], []
    for k, lo in t.get("min", {}).items():
        if m.get(k, 0) < lo:
            failures.append(f"{k}={m.get(k)} < {lo}")
    for k, hi in t.get("max", {}).items():
        if m.get(k, 0) > hi:
            failures.append(f"{k}={m.get(k)} > {hi}")
    return failures
