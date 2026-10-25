"""Three-agent workflow: planner -> researcher -> executor.

    planner     no tools. Turns the task into a short plan.
    researcher  search_dataset, read_file. Produces findings.
    executor    write_note. Writes the final note.

Handoffs between agents are treated as untrusted text, because an injected
instruction can ride along inside the researcher's findings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .config import GuardConfig
from .guard import Guard
from .llm import BudgetExceeded, ChatClient, text_of
from .sandbox import open_session

MAX_STEPS = {"researcher": 6, "executor": 3}


@dataclass
class RunResult:
    task: str
    config: str
    plan: str = ""
    findings: str = ""
    final_answer: str = ""
    notes: dict[str, str] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str | None = None


def _result_text(result) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")


def _is_error(result) -> bool:
    """MCP SDK v2 uses is_error, v1 uses isError."""
    flag = getattr(result, "is_error", None)
    if flag is None:
        flag = getattr(result, "isError", False)
    return bool(flag)


async def tool_loop(
    client: ChatClient,
    guard: Guard,
    role: str,
    messages: list[BaseMessage],
    session,
    tool_defs: list[dict],
    events: list[dict],
    max_steps: int,
) -> str:
    """Run the model until it stops calling tools or the step limit is hit."""
    available = {d["function"]["name"] for d in tool_defs}
    last_text = ""
    for _ in range(max_steps):
        ai = await client.chat(messages, tool_defs)
        messages.append(ai)
        last_text = text_of(ai)
        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            return last_text
        for call in calls:
            name, args, call_id = call["name"], call.get("args") or {}, call["id"]
            event = {
                "role": role, "tool": name, "args": args,
                "executed": False, "error": False, "rule": None, "detector_hits": [],
            }
            if name not in available:
                event["rule"] = "tool_unavailable"
                content = f"ERROR: tool '{name}' is not available to you."
            else:
                decision = guard.check_call(name, args)
                if not decision.allowed:
                    event["rule"] = decision.rule
                    content = f"DENIED by policy ({decision.rule}): {decision.reason}"
                else:
                    result = await session.call_tool(name, args)
                    text = _result_text(result)
                    event["executed"] = True
                    event["error"] = _is_error(result)
                    event["raw_output"] = text[:2000]  # before any sanitizing, used to judge exposure
                    if event["error"]:
                        event["rule"] = "server_error"
                        content = f"ERROR: {text}"
                    else:
                        content = guard.process_tool_output(name, text, event)
            events.append(event)
            messages.append(ToolMessage(content=content, tool_call_id=call_id))
    return last_text


def _collect_notes(workspace: Path) -> dict[str, str]:
    notes_dir = workspace / "notes"
    if not notes_dir.exists():
        return {}
    return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(notes_dir.glob("*.md"))}


async def run_workflow(
    task: str,
    *,
    client: ChatClient,
    cfg: GuardConfig,
    workspace: Path,
    sandbox: str = "none",
) -> RunResult:
    started = time.time()
    usage_before = client.usage.snapshot()
    result = RunResult(task=task, config=cfg.name)
    events = result.events
    try:
        # 1. Planner (no tools)
        planner_guard = Guard(cfg, "planner", events)
        plan_messages: list[BaseMessage] = [
            SystemMessage(planner_guard.system_prompt()),
            HumanMessage(task),
        ]
        plan_ai = await client.chat(plan_messages, [])
        result.plan = text_of(plan_ai)

        # 2. Researcher
        researcher_guard = Guard(cfg, "researcher", events)
        plan_for_researcher = researcher_guard.process_handoff(result.plan, "agent:planner")
        research_messages: list[BaseMessage] = [
            SystemMessage(researcher_guard.system_prompt()),
            HumanMessage(f"TASK:\n{task}\n\nPLAN:\n{plan_for_researcher}"),
        ]
        async with open_session("researcher", workspace, cfg, sandbox) as (session, tool_defs):
            result.findings = await tool_loop(
                client, researcher_guard, "researcher", research_messages, session, tool_defs,
                events, MAX_STEPS["researcher"],
            )

        # 3. Executor
        executor_guard = Guard(cfg, "executor", events)
        findings_for_executor = executor_guard.process_handoff(result.findings, "agent:researcher")
        exec_messages: list[BaseMessage] = [
            SystemMessage(executor_guard.system_prompt()),
            HumanMessage(f"TASK:\n{task}\n\nRESEARCHER FINDINGS:\n{findings_for_executor}"),
        ]
        async with open_session("executor", workspace, cfg, sandbox) as (session, tool_defs):
            answer = await tool_loop(
                client, executor_guard, "executor", exec_messages, session, tool_defs,
                events, MAX_STEPS["executor"],
            )
        result.final_answer = executor_guard.finalize_output(answer)
    except BudgetExceeded:
        raise
    except Exception as exc:  # infrastructure or provider error, reported separately from task failures
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        usage = client.usage.minus(usage_before)
        result.llm_calls = usage.calls
        result.input_tokens = usage.input_tokens
        result.output_tokens = usage.output_tokens
        result.seconds = round(time.time() - started, 2)
        result.notes = _collect_notes(workspace)
    return result
