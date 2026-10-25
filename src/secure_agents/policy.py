"""Gateway policy: deterministic checks that run before a tool call reaches
the MCP server. These rules do not depend on the model behaving well."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .roles import ROLE_TOOLS
from .tools import ToolError, normalize_rel

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "api_key_like": re.compile(r"\b[a-z]{2,6}_(?:live|test|prod)_[A-Za-z0-9]{12,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "sk_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}

CALL_LIMITS = {"search_dataset": 6, "read_file": 6, "write_note": 1}
READ_ROOT = "docs/"
TITLE_RE = re.compile(r"^[A-Za-z0-9 _:,.()-]{1,120}$")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    rule: str = ""
    reason: str = ""


ALLOW = Decision(True)


def find_secrets(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def redact_secrets(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            hits.append(name)
            text = pattern.sub("[REDACTED SECRET]", text)
    return text, hits


class ToolPolicy:
    """Stateful per-agent policy: tracks call counts for the current run."""

    def __init__(self, role: str):
        self.role = role
        self.counts: Counter[str] = Counter()

    def check(self, tool: str, args: dict) -> Decision:
        if tool not in ROLE_TOOLS.get(self.role, ()):
            return Decision(False, "role_allowlist", f"role '{self.role}' may not use {tool}")
        if self.counts[tool] >= CALL_LIMITS.get(tool, 0):
            return Decision(False, "call_limit", f"{tool} call limit reached")

        if tool == "read_file":
            try:
                rel = normalize_rel(str(args.get("path", "")))
            except ToolError as exc:
                return Decision(False, "read_scope", str(exc))
            parts = rel.split("/")
            if not rel.startswith(READ_ROOT) or any(part.startswith(".") for part in parts):
                return Decision(False, "read_scope", f"reads are limited to {READ_ROOT}")

        elif tool == "write_note":
            title = str(args.get("title", ""))
            content = str(args.get("content", ""))
            if not TITLE_RE.match(title):
                return Decision(False, "note_title", "title has unsupported characters or length")
            leaked = find_secrets(title + "\n" + content)
            if leaked:
                return Decision(False, "dlp_secret", f"note looks like it contains a secret ({leaked[0]})")

        elif tool == "search_dataset":
            if len(str(args.get("query", ""))) > 200:
                return Decision(False, "query_length", "query is too long")

        self.counts[tool] += 1
        return ALLOW
