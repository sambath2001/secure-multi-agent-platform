import asyncio

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from secure_agents.llm import Budget, BudgetExceeded, LangChainClient, text_of


class FakeToolModel(BaseChatModel):
    """Scripted LangChain chat model that reports usage like a real provider does."""

    reply: str = "ok"
    tokens_in: int = 100
    tokens_out: int = 20
    report_usage: bool = True
    bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-tool-model"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"bound_tools": list(tools)})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        meta = {"input_tokens": self.tokens_in, "output_tokens": self.tokens_out, "total_tokens": self.tokens_in + self.tokens_out}
        msg = AIMessage(content=self.reply, usage_metadata=meta if self.report_usage else None)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def run(coro):
    return asyncio.run(coro)


def test_usage_is_counted_from_provider_metadata():
    budget = Budget(max_total_tokens=10_000)
    client = LangChainClient(FakeToolModel(), budget)
    run(client.chat([HumanMessage("hi")], []))
    run(client.chat([HumanMessage("hi")], [{"type": "function", "function": {"name": "t", "description": "", "parameters": {}}}]))
    assert (client.usage.calls, client.usage.input_tokens, client.usage.output_tokens) == (2, 200, 40)
    assert not client.usage.estimated


def test_missing_usage_falls_back_to_estimate_and_is_flagged():
    client = LangChainClient(FakeToolModel(report_usage=False, reply="x" * 400), Budget())
    run(client.chat([HumanMessage("y" * 400)], []))
    assert client.usage.estimated and client.usage.input_tokens == 100 and client.usage.output_tokens == 100


def test_token_budget_stops_the_run():
    client = LangChainClient(FakeToolModel(tokens_in=600, tokens_out=0), Budget(max_total_tokens=1000))
    run(client.chat([HumanMessage("a")], []))
    run(client.chat([HumanMessage("a")], []))
    with pytest.raises(BudgetExceeded):
        run(client.chat([HumanMessage("a")], []))


def test_usd_budget_uses_configured_prices():
    budget = Budget(max_usd=0.001, price_in_per_mtok=1.0, price_out_per_mtok=5.0)
    client = LangChainClient(FakeToolModel(tokens_in=1000, tokens_out=200), budget)
    run(client.chat([HumanMessage("a")], []))  # cost 0.001 + 0.001 = 0.002
    assert budget.estimated_usd() == pytest.approx(0.002)
    with pytest.raises(BudgetExceeded):
        run(client.chat([HumanMessage("a")], []))


def test_usd_estimate_is_none_without_prices():
    assert Budget().estimated_usd() is None


def test_text_of_handles_block_lists():
    msg = AIMessage(content=[{"type": "text", "text": "hello "}, {"type": "tool_use", "id": "1", "name": "x", "input": {}}, {"type": "text", "text": "world"}])
    assert text_of(msg) == "hello world"
