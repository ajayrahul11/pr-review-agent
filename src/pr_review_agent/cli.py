"""CLI: `pr-review review|eval|pending|approve|reject`."""
import argparse
import json
import logging
import sys

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pr-review")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="Review a PR (fixture file or GitHub)")
    r.add_argument("--fixture")
    r.add_argument("--repo")
    r.add_argument("--number", type=int)
    e = sub.add_parser("eval", help="Run the eval suite")
    e.add_argument("--gate", action="store_true", help="exit 1 if below evals/thresholds.toml")
    e.add_argument("--report-dir", default="evals/reports")
    sub.add_parser("pending", help="List reviews awaiting human approval")
    for name in ("approve", "reject"):
        d = sub.add_parser(name)
        d.add_argument("review_id")
        d.add_argument("--note")
        d.add_argument("--drop", nargs="*", default=[], help="finding IDs to drop, e.g. F3 F7")
    args = p.parse_args()

    if args.cmd == "review":
        from pr_review_agent.integrations import github
        from pr_review_agent.workflow.orchestrator import run_review
        pr = (github.load_fixture(args.fixture) if args.fixture
              else github.fetch_pull_request(args.repo, args.number))
        _print_review(run_review(pr))
    elif args.cmd == "eval":
        from pr_review_agent.evals.runner import gate, run
        report = run(report_dir=args.report_dir)
        print(json.dumps({"metrics": report["metrics"], "versions": report["versions"]}, indent=2))
        if args.gate:
            failures = gate(report)
            print("\nEVAL GATE:", "PASSED" if not failures else "FAILED")
            for f in failures:
                print(f"  ✗ {f}")
            sys.exit(1 if failures else 0)
    elif args.cmd == "pending":
        from pr_review_agent.hitl.store import get_store
        from pr_review_agent.models import ReviewStatus
        for rv in get_store().list(ReviewStatus.pending_approval):
            print(f"{rv.id}  {rv.pr.repo}#{rv.pr.number}  {len(rv.findings)} findings  {rv.pr.title}")
    elif args.cmd in ("approve", "reject"):
        from pr_review_agent.workflow.orchestrator import decide
        rv = decide(args.review_id, args.cmd == "approve", args.note, args.drop)
        print(f"{rv.id} -> {rv.status}")
        if rv.trace and rv.trace[-1].startswith("publish"):
            print(rv.trace[-1])


def _print_review(review) -> None:
    print(f"\n=== Review {review.id}  [{review.status}]  versions={review.versions} ===")
    print("\n[Agent 1: Retriever] rules retrieved:",
          ", ".join(c.rule.id for c in review.context) or "none")
    print(f"\n[Agent 2: Reviewer] {review.summary}")
    for f in review.findings:
        print(f"  {f.id:4} {f.severity.upper():8} {f.rule_id:9} {f.file}:{f.line}  {f.title}"
              + ("  (fixable)" if f.fixable else ""))
    print("\n[Agent 3: Fixer -> Agent 4: Verifier]")
    for fx in review.fixes:
        v = fx.verdict
        mark = "VERIFIED" if v and v.verified else "REJECTED"
        print(f"  {fx.finding_id:4} {mark:8} {fx.file}:{fx.start_line}")
        print(f"         - {fx.original.strip()}")
        for line in fx.replacement.splitlines():
            print(f"         + {line.strip()}")
        if v:
            print(f"         checks: {v.checks}  {v.reason}")
    if not review.fixes:
        print("  (no fixable findings)")
    if review.guardrail_events:
        print("\nGuardrail events:")
        for ev in review.guardrail_events:
            print(f"  - {ev}")
    print("\nMetrics:", {k: v for k, v in review.metrics.items() if not k.endswith("Ms") or k == "ReviewLatencyMs"})
    if review.status == "pending_approval":
        print(f"\nAwaiting human approval:  pr-review approve {review.id} [--drop F2]  |  pr-review reject {review.id}")


if __name__ == "__main__":
    main()
