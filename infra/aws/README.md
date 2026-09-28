# Deploying to AWS (Claude on Amazon Bedrock)

## What gets deployed

| Piece | AWS service | Defined in |
|---|---|---|
| LLM for all 4 agents | Claude on **Amazon Bedrock** | `LLM_PROVIDER=bedrock` (`llm/client.py`) |
| RAG (standards + bug patterns) | **Bedrock Knowledge Base** (S3 source) | console, one-time (step 3) + `scripts/sync_kb.py` |
| API + agents | **ECS Fargate** behind an ALB | `service.yaml` |
| HITL review queue | **DynamoDB** | `service.yaml` |
| Secrets (GitHub token, webhook secret, API key) | **Secrets Manager** | one-time (step 4) |
| Images | **ECR** (immutable tags = git sha) | `bootstrap.yaml` |
| Eval reports + release manifests | **S3** (versioned) | `bootstrap.yaml` |
| CI/CD | **GitHub Actions** with OIDC (no AWS keys stored) | `.github/workflows/` |
| Monitoring | **CloudWatch** EMF metrics, dashboard, alarms | `observability.py`, `service.yaml` |

## One-time setup

### 1. Bedrock model access
Bedrock console → **Model access** → enable the Claude model in `AGENT_MODEL` (default
`claude-opus-5`, which becomes `anthropic.claude-opus-5`). Check it from your laptop:
```bash
LLM_PROVIDER=bedrock AWS_REGION=us-east-1 make review gate
```
If your account needs a cross-region inference profile, set `AGENT_MODEL` to the profile ID
(IDs containing a `.` are passed through unchanged). If the default Mantle (Messages API) client
fails in your account, set `BEDROCK_CLIENT=invoke` to use the legacy InvokeModel client.

### 2. Bootstrap stack
```bash
aws cloudformation deploy --stack-name pr-review-agent-bootstrap \
  --template-file infra/aws/bootstrap.yaml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubRepo=<owner>/<repo> CreateOidcProvider=true
aws cloudformation describe-stacks --stack-name pr-review-agent-bootstrap --query "Stacks[0].Outputs"
```

### 3. Bedrock Knowledge Base
In the Bedrock console, create a Knowledge Base:
- Data source: S3 → `KnowledgeBaseBucketName` (from the outputs), prefix `rules/`
- **Chunking: No chunking.** Each rule is its own document with a `.metadata.json` sidecar
- Vector store: the quick-create default is fine

Then run the first ingestion:
```bash
.venv/bin/python scripts/sync_kb.py --bucket <KnowledgeBaseBucketName> --kb-id <KB_ID> --data-source-id <DS_ID>
```

### 4. App secret
```bash
aws secretsmanager create-secret --name pr-review-agent/staging --secret-string \
  '{"GITHUB_TOKEN":"ghp_...","GITHUB_WEBHOOK_SECRET":"...","API_KEY":"<random>"}'
# repeat for pr-review-agent/prod
```

### 5. GitHub configuration
Create two **environments**: `staging` and `production`. Give `production` **required
reviewers**; that is the manual approval step before prod.

| Where | Name | Value |
|---|---|---|
| repo variable | `AWS_REGION` | e.g. `us-east-1` |
| repo variable | `AWS_DEPLOY_ROLE_ARN` | `GitHubDeployRoleArn` output |
| repo variable | `CFN_EXEC_ROLE_ARN` | `CfnExecutionRoleArn` output |
| repo variable | `ECR_REPOSITORY_URI` | `EcrRepositoryUri` output |
| repo variable | `ARTIFACTS_BUCKET` | `ArtifactsBucketName` output |
| repo variable | `KB_ID`, `KB_DATA_SOURCE_ID`, `KB_BUCKET` | from step 3 |
| repo variable | `VPC_ID`, `PUBLIC_SUBNET_IDS` | e.g. the default VPC and 2 subnets (comma-separated) |
| repo variable | `BEDROCK_EVALS` | `true` (enables Bedrock evals in CI) |
| repo variable (optional) | `AGENT_MODEL`, `HITL_MODE`, `ALARM_EMAIL` | |
| env variable (each env) | `ENV_NAME` | `staging` / `prod` |
| env variable (each env) | `APP_SECRET_ARN` | ARN from step 4 |
| env secret (each env) | `API_KEY` | same value as in the app secret (used by the smoke test) |

### 6. Ship it
Push to `main`. `deploy.yml` then runs these steps:
1. **Eval gate on Bedrock.** The release is blocked if any metric is below `evals/thresholds.toml`
2. **Build** the image and push it to ECR, tagged with the git sha
3. **KB sync.** `knowledge_base/` is re-ingested into the Bedrock Knowledge Base
4. **Staging.** CloudFormation deploy, then a smoke test that runs one real review through all 4 agents
5. **Manual approval** in the GitHub `production` environment
6. **Prod.** Deploy, smoke test, and write a **release manifest** to `s3://<artifacts>/releases/prod/<sha>.json` (image, model, prompt hash, KB hash, eval metrics)

### 7. Connect GitHub
Repo or GitHub App webhook → `http://<ServiceUrl>/webhooks/github`, content type JSON, secret =
`GITHUB_WEBHOOK_SECRET`, event *Pull requests*. The token needs `pull_requests: write` and
`contents: read`.

## Operating

- **Dashboard:** `DashboardUrl` stack output. Shows findings, fixes proposed and verified, latency, tokens, and human approval rate
- **Alarms (SNS → `ALARM_EMAIL`):** API 5xx, p90 latency, and the human approval rate falling below 60% (quality drift)
- **Nightly:** `ci.yml` re-runs the Bedrock eval, which catches model or KB drift
- **Rollback:** a failed deploy rolls back automatically (ECS circuit breaker). To go back manually, run `deploy.yml` with `image_tag=<previous sha>`, taken from `releases/prod/`

## Before real traffic (hardening)
- [ ] HTTPS listener with an ACM certificate (`service.yaml` has a `TODO`)
- [ ] Private subnets + NAT (or VPC endpoints for Bedrock, ECR, Logs, DynamoDB, Secrets Manager)
- [ ] Scope `Resource: "*"` on Bedrock actions to specific model, inference-profile and KB ARNs. Check which IAM actions the Bedrock Messages (Mantle) endpoint needs in your account
- [ ] Queue webhooks through SQS so long reviews don't hold HTTP requests open
- [ ] Alternative hosting: **Bedrock AgentCore Runtime** can host this container instead of ECS
