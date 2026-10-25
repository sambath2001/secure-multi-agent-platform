"""LLM access, usage tracking, and a local spending guard.

The spending guard here is an estimate that stops a run early. The hard cap is
the monthly limit you set in the provider's billing dashboard. Set both.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",  # example only, check your account for current cheap models
    "ollama": "llama3.1:8b",  # example only, needs a tool-calling capable local model
}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False  # True if the provider returned no usage and we guessed from text length

    def snapshot(self) -> "Usage":
        return Usage(self.calls, self.input_tokens, self.output_tokens, self.estimated)

    def minus(self, other: "Usage") -> "Usage":
        return Usage(
            self.calls - other.calls,
            self.input_tokens - other.input_tokens,
            self.output_tokens - other.output_tokens,
            self.estimated,
        )


class Budget:
    def __init__(
        self,
        max_total_tokens: int | None = None,
        max_usd: float | None = None,
        price_in_per_mtok: float | None = None,
        price_out_per_mtok: float | None = None,
    ):
        self.max_total_tokens = max_total_tokens
        self.max_usd = max_usd
        self.price_in = price_in_per_mtok
        self.price_out = price_out_per_mtok
        self.usage = Usage()

    @classmethod
    def from_env(cls) -> "Budget":
        def _num(name: str, cast):
            raw = os.getenv(name, "").strip()
            return cast(raw) if raw else None

        return cls(
            max_total_tokens=_num("MAX_TOTAL_TOKENS", int) or 1_500_000,
            max_usd=_num("MAX_USD", float),
            price_in_per_mtok=_num("PRICE_IN_PER_MTOK", float),
            price_out_per_mtok=_num("PRICE_OUT_PER_MTOK", float),
        )

    def estimated_usd(self) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return (self.usage.input_tokens * self.price_in + self.usage.output_tokens * self.price_out) / 1_000_000

    def check(self) -> None:
        total = self.usage.input_tokens + self.usage.output_tokens
        if self.max_total_tokens is not None and total >= self.max_total_tokens:
            raise BudgetExceeded(f"token budget reached ({total} >= {self.max_total_tokens})")
        usd = self.estimated_usd()
        if self.max_usd is not None and usd is not None and usd >= self.max_usd:
            raise BudgetExceeded(f"estimated spend reached ${usd:.2f} (cap ${self.max_usd:.2f})")


class ChatClient(Protocol):
    usage: Usage

    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage: ...


def text_of(message: BaseMessage) -> str:
    """Flatten message content (string or list of content blocks) to plain text."""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


class LangChainClient:
    """Thin wrapper over a LangChain chat model with budget checks and usage counting."""

    def __init__(self, model, budget: Budget, timeout_s: float = 90.0):
        self.model = model
        self.budget = budget
        self.timeout_s = timeout_s

    @property
    def usage(self) -> Usage:
        return self.budget.usage

    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage:
        self.budget.check()
        runnable = self.model.bind_tools(tools) if tools else self.model
        response = await asyncio.wait_for(runnable.ainvoke(messages), timeout=self.timeout_s)
        meta = getattr(response, "usage_metadata", None) or {}
        in_tok, out_tok = int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))
        if not in_tok and not out_tok:
            in_tok = sum(len(text_of(m)) for m in messages) // 4
            out_tok = len(text_of(response)) // 4
            self.budget.usage.estimated = True
        self.budget.usage.calls += 1
        self.budget.usage.input_tokens += in_tok
        self.budget.usage.output_tokens += out_tok
        return response


def build_client(budget: Budget) -> LangChainClient:
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    model_name = os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, "")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(model=model_name, temperature=temperature, max_tokens=max_tokens)
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model=model_name, temperature=temperature, max_tokens=max_tokens)
    elif provider == "ollama":
        from langchain_ollama import ChatOllama

        model = ChatOllama(
            model=model_name,
            temperature=temperature,
            num_predict=max_tokens,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    else:
        raise SystemExit(f"unknown LLM_PROVIDER '{provider}' (anthropic | openai | ollama)")
    return LangChainClient(model, budget)


def describe_model() -> dict:
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    return {
        "provider": provider,
        "model": os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, ""),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
    }
