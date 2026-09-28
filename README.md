# PR Review Agent

A multi-agent system that reviews a GitHub pull request and posts verified fixes:

1. **Retriever agent** finds the relevant coding standards and past bug patterns (RAG).
2. **Reviewer agent** reviews the diff against *only* those rules.
3. **Fixer agent** proposes minimal fixes for simple violations.
4. **Verifier agent** checks every fix before it is posted as a PR comment with a GitHub
   ```` ```suggestion ```` block.

An eval suite gates every release, and a small MLOps pipeline deploys it to AWS, with Claude
running on Amazon Bedrock.

```
 GitHub PR ──► input guardrails (secret redaction, prompt-injection flags, size limit)
     │
     ▼
 ┌─────────────── Agent 1: RETRIEVER ───────────────┐   MCP tools: search_knowledge_base, get_rule
 │ queries the KB → coding standards + bug patterns │   RAG: BM25 (local) / Bedrock Knowledge Base (AWS)
 └──────────────────────────┬───────────────────────┘
                            ▼  rules (grounded: unknown IDs dropped)
 ┌─────────────── Agent 2: REVIEWER ────────────────┐   MCP tools: get_rule, get_file_content
 │ findings, each citing a retrieved rule_id         │
 └──────────────────────────┬───────────────────────┘
                            ▼  output guardrails (on an added line? confident? dedupe, redact)
 ┌─────────────── Agent 3: FIXER ───────────────────┐   MCP tools: get_file_content, check_python_syntax
 │ minimal in-place fixes for fixable findings       │
 └──────────────────────────┬───────────────────────┘
                            ▼
 ┌─────────────── Agent 4: VERIFIER ────────────────┐   1. static checks: original matches PR, rule's
 │ verdict per fix                                   │      detector no longer fires, syntax parses,
 └──────────────────────────┬───────────────────────┘      small, no secrets   2. LLM review
                            ▼
              human-in-the-loop gate (HITL_MODE) ──► PR review comment + ```suggestion``` (verified only)
```

| Requirement | Where |
|---|---|
| 4-agent workflow | `agents/{retriever,reviewer,fixer,verifier}_agent.py`, `workflow/orchestrator.py` |
| RAG (standards and past bug patterns) | `knowledge_base/{standards,bug_patterns}/`, `rag/` |
| MCP tools | `mcp_tools/`. Each agent has its own tool allowlist. |
| Eval suite gating releases | `evals/`, `src/pr_review_agent/evals/runner.py`, `evals/thresholds.toml` |
| Guardrails | `guardrails/`, the verifier's static checks, tool allowlists |
| Human in the loop | `hitl/`, `POST /reviews/{id}/decision`, `pr-review approve` |
| MLOps pipeline on Bedrock | `.github/workflows/`, `infra/aws/`, `scripts/` |

---

## 1. Run locally (no keys needed)

`LLM_PROVIDER=mock` runs all four agents offline with a deterministic stand-in for Claude.
The Retriever still makes real knowledge-base searches through the MCP tools.

```bash
make install && cp .env.example .env
make test          # 13 tests: each agent, pipeline, evals + gate, MCP, API, auth
make review        # 4-agent review of data/fixtures/sample_pr.json
make gate          # eval suite + thresholds (exactly what CI/CD runs)
make run           # API at http://localhost:8000/docs
```

`make review` prints each agent's output: retrieved rules, findings, and each fix as a diff
with its verifier checks. The review then waits for your approval:

```bash
.venv/bin/pr-review approve <review_id> --drop F7     # drop a finding, then post
.venv/bin/pr-review reject  <review_id> --note "noisy"
```

### Use real Claude

```bash
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... make review gate
LLM_PROVIDER=bedrock AWS_REGION=us-east-1 make review gate     # needs Bedrock model access
```

With the mock, the evals score 1.0 by construction, so they only test that the pipeline works.
**The real quality gate is `make gate` against Claude.** Tune the prompts in
`src/pr_review_agent/prompts/` until it passes.

### Other modes
- `MCP_MODE=stdio`: agents call tools through the MCP server (`make mcp` runs it on its own)
- `GITHUB_TOKEN=...`: `pr-review review --repo owner/repo --number 123` reviews a real PR, and approving the review posts it

## 2. Evals

`make gate` scores **each agent separately**, so a regression points at the agent that caused it:

| Metric | Agent | Threshold |
|---|---|---|
| `retrieval_recall` | Retriever | ≥ 0.90 |
| `review_precision` / `review_recall` | Reviewer | ≥ 0.85 / ≥ 0.80 |
| `fix_success_rate` (proposed, verified and correct) | Fixer + Verifier | ≥ 0.80 |
| `verifier_accuracy` (on labelled good and bad fixes) | Verifier | = 1.00 |
| `guardrail_pass_rate` | Guardrails | = 1.00 |

The datasets are `evals/datasets/golden.jsonl` (end-to-end PRs, including clean ones for false
positives) and `verifier_cases.jsonl` (hand-labelled good and bad fixes). Each report records the
git sha, model, prompt hash and knowledge-base hash.

## 3. Deploy (MLOps on Bedrock)

```
PR ─► ci.yml: ruff · pytest · offline eval gate · cfn-lint · Bedrock eval gate (+ nightly drift run)
main ─► deploy.yml: Bedrock eval gate ─► build image → ECR ─► sync KB → Bedrock KB ingestion
                    ─► staging (CloudFormation, ECS) + smoke test ─► manual approval
                    ─► prod + smoke test ─► release manifest → S3
monitoring: CloudWatch EMF metrics, dashboard, alarms (5xx, latency, human-approval drift)
rollback: ECS circuit breaker (automatic) · re-run deploy.yml with image_tag=<old sha> (manual)
```

The setup is a one-time job. See **[infra/aws/README.md](infra/aws/README.md)**.

## 4. Roadmap

**[TODO.md](TODO.md)** has the phase-by-phase plan. `grep -rn "TODO(" src` lists the places in the code where each step plugs in.

## Layout

```
src/pr_review_agent/
  agents/        base.py (tool-use loop) + the 4 agents
  prompts/       versioned system prompts (their hash is recorded on every review/eval/release)
  workflow/      orchestrator.py: pipeline, HITL gate, publish
  rag/           knowledge.py (rule parsing), retriever.py (local BM25 | Bedrock KB)
  mcp_tools/     tools.py, server.py (MCP server), provider.py (in-process | MCP client)
  guardrails/    input + output guards
  hitl/          review queue (SQLite | DynamoDB)
  evals/         runner.py (per-agent metrics + gate)
  llm/           client.py (mock | anthropic | bedrock), mock.py
  integrations/  github.py (fetch PR, post review with suggestions)
  observability.py  CloudWatch EMF metrics
  api/main.py    FastAPI: /reviews, /reviews/{id}/decision, /webhooks/github
knowledge_base/  standards/*.md, bug_patterns/*.md  (## RULE-ID: title + severity/fixable/detect)
evals/           datasets/, thresholds.toml
infra/aws/       bootstrap.yaml, service.yaml, README.md
scripts/         sync_kb.py, release_manifest.py, smoke_test.sh
.github/workflows/  ci.yml, deploy.yml
```
