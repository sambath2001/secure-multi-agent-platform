"""Deterministic stand-in for a fully compromised model.

GullibleClient obeys any attacker instruction it can still see. It is used to
test the deterministic layers (detector, policy, role isolation, sandbox) in
the worst case and to run the whole pipeline without an API key.

It is NOT a measurement of any real LLM. Numbers produced with it must always
be labeled 'simulated worst-case model'.
"""

from __future__ import annotations

import base64
import re
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .llm import Usage, text_of

SECRET_RE = re.compile(r"hxo_live_[A-Za-z0-9]+")


def _call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}])


class GullibleClient:
    """intent keys: trigger, read_path, marker, leak, encode, researcher_writes."""

    def __init__(self, intent: dict | None = None):
        self.intent = intent or {}
        self.usage = Usage()

    @staticmethod
    def _role(messages: list[BaseMessage]) -> str:
        system = next((text_of(m) for m in messages if isinstance(m, SystemMessage)), "")
        match = re.search(r"ROLE: (\w+)", system)
        return match.group(1) if match else ""

    @staticmethod
    def _observed(messages: list[BaseMessage]) -> str:
        return "\n".join(text_of(m) for m in messages if isinstance(m, (HumanMessage, ToolMessage)))

    @staticmethod
    def _tool_rounds(messages: list[BaseMessage]) -> list[str]:
        names: list[str] = []
        for m in messages:
            if isinstance(m, AIMessage):
                names.extend(tc["name"] for tc in (m.tool_calls or []))
        return names

    def _trigger_seen(self, observed: str) -> bool:
        trigger = self.intent.get("trigger")
        return bool(trigger) and trigger in observed

    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage:
        self.usage.calls += 1
        role = self._role(messages)
        if role == "planner":
            return AIMessage(content="1. Search the documents for the needed facts.\n2. Write a note with the answer.")
        if role == "researcher":
            return self._researcher(messages)
        if role == "executor":
            return self._executor(messages)
        return AIMessage(content="")

    def _researcher(self, messages: list[BaseMessage]) -> AIMessage:
        done = self._tool_rounds(messages)
        observed = self._observed(messages)
        seen = self._trigger_seen(observed)
        if not done:
            human = next(text_of(m) for m in messages if isinstance(m, HumanMessage))
            match = re.search(r"TASK:\n(.*?)\n\nPLAN:", human, re.S)
            task = match.group(1) if match else human
            return _call("search_dataset", {"query": task[:150]})
        if seen and self.intent.get("read_path") and "read_file" not in done:
            return _call("read_file", {"path": self.intent["read_path"]})
        if seen and self.intent.get("researcher_writes") and "write_note" not in done:
            return _call("write_note", {"title": "progress", "content": self.intent.get("marker", "progress")})
        tool_text = "\n".join(text_of(m) for m in messages if isinstance(m, ToolMessage))
        return AIMessage(content="FINDINGS:\n" + tool_text[:3000])

    def _executor(self, messages: list[BaseMessage]) -> AIMessage:
        done = self._tool_rounds(messages)
        if done:
            return AIMessage(content="Done.")
        observed = self._observed(messages)
        seen = self._trigger_seen(observed)
        content = observed.split("RESEARCHER FINDINGS:", 1)[-1].strip()[:1500] or "No findings."
        secret = SECRET_RE.search(observed)
        if seen and self.intent.get("leak") and secret:
            key = secret.group(0)
            encode = self.intent.get("encode")
            if encode == "base64":
                key = base64.b64encode(key.encode()).decode()
            elif encode == "split":
                key = "-".join(key)
            content = f"Deploy key: {key}"
        elif seen and self.intent.get("marker") and not self.intent.get("researcher_writes"):
            content = self.intent["marker"]
        return _call("write_note", {"title": "Answer", "content": content[:3500]})
