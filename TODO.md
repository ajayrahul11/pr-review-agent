# PR Review Agent — Build Plan

Scope: given a GitHub PR, a **Retriever** agent pulls relevant coding standards and past bug
patterns (RAG). A **Reviewer** agent reviews the diff against them. A **Fixer** agent proposes
fixes for simple violations. A **Verifier** agent checks each fix before it's posted as a PR
comment. All of this is gated by an eval suite and deployed with a small MLOps pipeline on
Bedrock.

✅ = scaffolded and working in mock mode. Each phase ends with a check you can run.

---

## Phase 0 — Local skeleton ✅
- [x] 4-agent pipeline runs end to end offline (`make review`)
- [x] Eval suite and gate (`make gate`), 13 tests (`make test`)
- [x] API and human-in-the-loop flow (`make run`, `pr-review approve`)
- ✔ **Check:** `make test gate` is green

## Phase 1 — Real model locally
- [ ] Get Claude access (Anthropic API key, or Bedrock model access) and run `make review` with `LLM_PROVIDER=anthropic|bedrock`
- [ ] Run `make gate` against the real model. Read `evals/reports/latest.json` to see which agent's metric fails
- [ ] Tune `src/pr_review_agent/prompts/*.md`, one agent at a time, re-running the gate after each change
- [ ] Tune per-agent effort (`RETRIEVER_EFFORT`, ...) for cost against quality. Try `low` on the Retriever first
- [ ] Add prompt caching: the diff is sent to Retriever and Reviewer, so put it in a cached prefix
- ✔ **Check:** `make gate` passes on a real model

## Phase 2 — Agent 1: Retriever (RAG)
- [ ] Replace the sample `knowledge_base/` with your team's real standards (`## ID: title` + `severity/fixable/detect`)
- [ ] Mine past incidents and postmortems, plus bug-fix PRs, into `knowledge_base/bug_patterns/`
- [ ] Add a `detect:` regex to every fixable rule. The Verifier re-runs it on each fix
- [ ] Measure `retrieval_recall`, and try hybrid search (BM25 + embeddings) if it's below 0.9
- ✔ **Check:** `retrieval_recall` ≥ 0.9 on 20+ PRs

## Phase 3 — Agent 2: Reviewer
- [ ] Large PRs: split per file or hunk, run the Reviewer in parallel, and merge the results
- [ ] Let the Reviewer fetch the full file (`get_file_content`) for context when the diff is ambiguous
- [ ] Use the confidence scores: calibrate `MIN_CONFIDENCE_TO_POST` against human decisions
- ✔ **Check:** `review_precision` ≥ 0.85 and `review_recall` ≥ 0.8

## Phase 4 — Agents 3 + 4: Fixer and Verifier
- [ ] Support multi-line fixes (`start_line..end_line`) and non-Python files (JS/TS syntax check)
- [ ] MCP tools `run_linter` and `run_tests` so the Verifier can execute checks in a sandbox (`TODO(mcp)`)
- [ ] Add a bad fix to `verifier_cases.jsonl` for every new way a fix can fail
- [ ] Record why the Verifier rejects fixes and feed the patterns back into the Fixer prompt
- ✔ **Check:** `verifier_accuracy` = 1.0 and `fix_success_rate` ≥ 0.8

## Phase 5 — Eval suite (the release gate)
- [ ] Grow `golden.jsonl` to 50+ real PRs (≥ 30% clean PRs, so false positives are measured)
- [ ] Export human decisions from HITL as new labelled cases (`TODO(hitl)`)
- [ ] Add cost per review (tokens → $) and p90 latency to the report and thresholds
- [ ] Optionally run evals against the Bedrock KB (`RAG_BACKEND=bedrock_kb`) in the deploy gate
- ✔ **Check:** a deliberately worse prompt is blocked by `make gate`

## Phase 6 — Guardrails and human in the loop
- [ ] Add Bedrock Guardrails (`ApplyGuardrail`) on PR text and comment text (`TODO(guardrails)`)
- [ ] Cap comments per PR, and skip generated and vendored files
- [ ] Build a reviewer UI or Slack approve buttons, authenticate reviewers, and record who approved
- [ ] Switch to `HITL_MODE=unverified_only` once precision is proven in production
- ✔ **Check:** a prompt-injection PR always lands in `pending_approval`

## Phase 7 — MLOps on AWS (see `infra/aws/README.md`)
- [ ] Deploy `bootstrap.yaml` (ECR, S3, OIDC deploy role)
- [ ] Create the Bedrock Knowledge Base (S3 data source, **no chunking**) and run `scripts/sync_kb.py`
- [ ] Create the app secret, the GitHub environments (`staging`, `production` with required reviewers) and the repo variables
- [ ] Push to `main`: eval gate → build → staging → smoke test → approve → prod → release manifest
- [ ] Point the GitHub webhook at `https://<prod>/webhooks/github`
- [ ] Before real traffic: HTTPS listener (ACM), private subnets + NAT, IAM scoped to model and KB ARNs
- [ ] Practise a rollback: `deploy.yml` with `image_tag=<previous sha>`
- ✔ **Check:** opening a PR on a test repo produces a review with a verified ```` ```suggestion ````

## Phase 8 — Operate
- [ ] Watch the dashboard: latency, tokens, fixes verified/proposed, human approval rate
- [ ] Human-approval drift alarm fires → triage → add cases to golden set → fix prompt/KB → gate → release
- [ ] Nightly Bedrock eval (`ci.yml` schedule) catches model or KB drift before users do
- [ ] Before switching `AGENT_MODEL` to a new model, run the gate on it and compare with the release manifest
