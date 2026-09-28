.PHONY: install run review eval gate test lint mcp docker cfn-lint

install:          ## Create venv and install deps
	uv venv && uv pip install -e ".[dev]"

run:              ## Start API server on :8000
	.venv/bin/uvicorn pr_review_agent.api.main:app --reload --port 8000

review:           ## Run the 4-agent pipeline on the sample PR
	.venv/bin/pr-review review --fixture data/fixtures/sample_pr.json

eval:             ## Run the eval suite (report -> evals/reports/latest.json)
	.venv/bin/pr-review eval

gate:             ## Eval suite + threshold gate (what CI/CD runs)
	.venv/bin/pr-review eval --gate

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests scripts

cfn-lint:
	uvx cfn-lint infra/aws/*.yaml

mcp:              ## Run the MCP tool server over stdio
	.venv/bin/python -m pr_review_agent.mcp_tools.server

docker:
	docker build -t pr-review-agent:local .
