"""Agent 1 - Retriever: finds relevant coding standards + past bug patterns via RAG."""
from pr_review_agent.agents.base import Agent, AgentResult
from pr_review_agent.diffutils import annotate
from pr_review_agent.models import PullRequest, RetrievedContext
from pr_review_agent.rag.retriever import get_retriever


class RetrieverAgent(Agent):
    name = "retriever"
    prompt = "retriever"
    allowed_tools = ("search_knowledge_base", "get_rule")
    effort_setting = "retriever_effort"
    submit_tool = {
        "name": "submit_context",
        "description": "Submit the IDs of relevant rules. Call exactly once when done.",
        "input_schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {"rule_id": {"type": "string"}, "why": {"type": "string"}},
                "required": ["rule_id", "why"]}}},
            "required": ["items"],
        },
    }

    def retrieve(self, pr: PullRequest) -> tuple[list[RetrievedContext], list[str], AgentResult]:
        diff = "\n\n".join(annotate(f) for f in pr.files)
        res = self.run(f"<pr title={pr.title!r}>\n{diff}\n</pr>")
        retriever, events, context, seen = get_retriever(), [], [], set()
        for item in (res.output or {}).get("items", []):
            rid = item.get("rule_id", "")
            rule = retriever.get(rid)
            if rule is None:                       # grounding: only real KB rules pass
                events.append(f"retriever: dropped unknown rule id '{rid}'")
            elif rid not in seen:
                seen.add(rid)
                context.append(RetrievedContext(rule=rule, why=item.get("why", "")))
        return context, events, res

