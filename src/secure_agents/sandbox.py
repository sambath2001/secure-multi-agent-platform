"""Starts one MCP tool server per agent role and connects to it over stdio.

Two modes:
    none    the server runs as a local subprocess (fast, used for tests and ablations)
    docker  the server runs in its own locked-down container

Design note: the LLM loop stays on the host. The API key never enters a
container, and the containers have no network at all. The container is the
sandbox for tool execution, which is where injected instructions turn into
real actions (file reads and writes).
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import GuardConfig

DOCKER_IMAGE = os.getenv("TOOL_IMAGE", "secure-agents-tools:latest")


def _schema_of(tool) -> dict:
    """MCP SDK v2 uses input_schema, v1 uses inputSchema."""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")


def docker_run_args(role: str, workspace: Path, cfg: GuardConfig) -> list[str]:
    """Build the `docker run` argument list. Pure function so it can be unit tested."""
    args = [
        "run", "--rm", "-i",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "64",
        "--memory", "256m",
        "--cpus", "0.5",
        "--user", "65534:65534",
        "--tmpfs", "/tmp:rw,size=16m",
        "-e", "WORKSPACE=/workspace",
        "-e", f"AGENT_ROLE={role}",
        "-e", f"ROLE_ISOLATION={'1' if cfg.role_isolation else '0'}",
    ]
    ws = workspace.resolve()
    if cfg.role_isolation:
        # Least privilege: docs read-only, no private/ at all, notes writable only for the executor.
        if role in {"researcher"}:
            args += ["-v", f"{ws / 'docs'}:/workspace/docs:ro"]
        if role == "executor":
            args += ["-v", f"{ws / 'notes'}:/workspace/notes:rw"]
    else:
        # Over-privileged baseline: the whole workspace, writable.
        args += ["-v", f"{ws}:/workspace:rw"]
    return args + [DOCKER_IMAGE]


def server_params(role: str, workspace: Path, cfg: GuardConfig, sandbox: str) -> StdioServerParameters:
    if sandbox == "docker":
        (workspace / "notes").mkdir(exist_ok=True)
        return StdioServerParameters(command="docker", args=docker_run_args(role, workspace, cfg))
    if sandbox != "none":
        raise ValueError(f"unknown sandbox mode: {sandbox}")
    # Only pass what the server needs. The parent environment (and its API keys) is not forwarded.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "secure_agents.mcp_server"],
        env={
            "WORKSPACE": str(workspace),
            "AGENT_ROLE": role,
            "ROLE_ISOLATION": "1" if cfg.role_isolation else "0",
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
        },
    )


@asynccontextmanager
async def open_session(role: str, workspace: Path, cfg: GuardConfig, sandbox: str):
    """Yield (session, tool_definitions) for one role. Tool defs use the OpenAI function format."""
    params = server_params(role, workspace, cfg, sandbox)
    with open(os.devnull, "w") as quiet:
        async with stdio_client(params, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_defs = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": _schema_of(tool),
                        },
                    }
                    for tool in listed.tools
                ]
                yield session, tool_defs
