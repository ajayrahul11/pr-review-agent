from pr_review_agent.evals.runner import gate, run


def test_eval_suite_passes_gate(tmp_path):
    report = run(report_dir=str(tmp_path))
    assert gate(report) == [], report["metrics"]


def test_gate_fails_on_regression():
    bad = {"metrics": {"retrieval_recall": 0.5, "review_precision": 1, "review_recall": 1,
                       "fix_success_rate": 1, "verifier_accuracy": 1, "guardrail_pass_rate": 1,
                       "avg_latency_ms": 10}}
    assert gate(bad) == ["retrieval_recall=0.5 < 0.9"]
