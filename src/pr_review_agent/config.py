"""Central configuration, loaded from environment / .env."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM -------------------------------------------------------------
    llm_provider: Literal["mock", "anthropic", "bedrock"] = "mock"
    aws_region: str = "us-east-1"
    bedrock_client: Literal["mantle", "invoke"] = "mantle"   # invoke = legacy InvokeModel path
    agent_model: str = "claude-opus-5"          # Bedrock: prefixed with "anthropic."
    retriever_effort: Effort = "low"
    reviewer_effort: Effort = "high"
    fixer_effort: Effort = "medium"
    verifier_effort: Effort = "high"
    max_agent_turns: int = 8

    # --- RAG -------------------------------------------------------------
    rag_backend: Literal["local", "bedrock_kb"] = "local"
    knowledge_base_dir: str = "knowledge_base"
    bedrock_kb_id: str | None = None
    rag_top_k: int = 5

    # --- GitHub ----------------------------------------------------------
    github_token: str | None = None
    github_webhook_secret: str | None = None
    api_key: str | None = None                   # required header x-api-key for /reviews

    # --- Guardrails ------------------------------------------------------
    max_diff_chars: int = 200_000
    min_confidence_to_post: float = 0.5
    max_fix_lines: int = 8                       # "simple" fixes only

    # --- Human in the loop -----------------------------------------------
    hitl_mode: Literal["always", "unverified_only", "never"] = "always"
    hitl_backend: Literal["sqlite", "dynamodb"] = "sqlite"
    hitl_db_path: str = "data/reviews.db"
    hitl_table: str = "pr-review-agent-reviews"

    # --- Tools / observability -------------------------------------------
    mcp_mode: Literal["inprocess", "stdio"] = "inprocess"
    metrics_namespace: str = "PRReviewAgent"
    environment: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
