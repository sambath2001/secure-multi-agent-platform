"""MCP tool server (stdio). One instance is started per agent role.

Environment:
    WORKSPACE       path to the workspace directory (docs/, private/, notes/)
    AGENT_ROLE      planner | researcher | executor
    ROLE_ISOLATION  "1" (default): register only the tools the role needs.
                    "0": register every tool for every role (over-privileged baseline).

With isolation on, a tool the role does not need is not registered at all, so
it cannot be listed or called even if the agent is fully compromised.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # MCP Python SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK v1
    from mcp.server.fastmcp import FastMCP as _Server

from . import tools
from .roles import ALL_TOOLS, ROLE_TOOLS


def allowed_tools(role: str, isolate: bool) -> tuple[str, ...]:
    if not isolate:
        return ALL_TOOLS
    return ROLE_TOOLS.get(role, ())  # unknown role: fail closed, no tools


def build_server(workspace: Path, role: str, isolate: bool = True):
    server = _Server("helix-tools")
    allowed = allowed_tools(role, isolate)

    if "search_dataset" in allowed:

        @server.tool()
        def search_dataset(query: str, max_results: int = 5) -> str:
            """Keyword search over the Helix Orbital documents. Returns matching lines with file, line number, and table header."""
            return tools.search_dataset(workspace, query, max_results)

    if "read_file" in allowed:

        @server.tool()
        def read_file(path: str) -> str:
            """Read a text file by workspace-relative path, for example docs/incidents.md."""
            return tools.read_file(workspace, path)

    if "write_note" in allowed:

        @server.tool()
        def write_note(title: str, content: str) -> str:
            """Save a note with a short title and the final answer text. Returns the saved path."""
            return tools.write_note(workspace, title, content)

    return server


def main() -> None:
    workspace = Path(os.environ["WORKSPACE"])
    role = os.environ.get("AGENT_ROLE", "")
    isolate = os.environ.get("ROLE_ISOLATION", "1") == "1"
    build_server(workspace, role, isolate).run(transport="stdio")


if __name__ == "__main__":
    main()
