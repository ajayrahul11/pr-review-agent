"""LLM client factory.

Returns an object exposing the Anthropic SDK surface `messages.create(...)`, so
agents are provider-agnostic:

  mock      -> MockLLM (no network, deterministic; great for local dev + CI)
  anthropic -> anthropic.Anthropic()                 (Claude API)
  bedrock   -> anthropic.AnthropicBedrockMantle()    (Claude on Amazon Bedrock, Messages API)
               or anthropic.AnthropicBedrock()       (BEDROCK_CLIENT=invoke: legacy InvokeModel)
"""
from functools import lru_cache

from pr_review_agent.config import get_settings


@lru_cache
def get_llm():
    s = get_settings()
    if s.llm_provider == "mock":
        from pr_review_agent.llm.mock import MockLLM

        return MockLLM()
    if s.llm_provider == "anthropic":
        import anthropic

        return anthropic.Anthropic()
    if s.llm_provider == "bedrock":
        if s.bedrock_client == "invoke":
            from anthropic import AnthropicBedrock

            return AnthropicBedrock(aws_region=s.aws_region)
        from anthropic import AnthropicBedrockMantle

        return AnthropicBedrockMantle(aws_region=s.aws_region)
    raise ValueError(f"Unknown LLM_PROVIDER: {s.llm_provider}")


def model_id(name: str) -> str:
    """Map a first-party model ID to the Bedrock ID. IDs containing a '.' (e.g. an
    inference profile like 'us.anthropic....' or an ARN) are passed through unchanged."""
    if get_settings().llm_provider == "bedrock" and "." not in name and ":" not in name:
        return f"anthropic.{name}"
    return name
