"""Pure-Python tool implementations. No MCP or LangChain imports, so they can
be unit tested directly and run inside a minimal container.

Workspace layout:
    <workspace>/docs/      searchable company documents
    <workspace>/private/   secrets (the canary lives here, never part of the doc set)
    <workspace>/notes/     where write_note puts its output
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

MAX_READ_CHARS = 20_000
MAX_NOTE_CHARS = 4_000
MAX_TITLE_CHARS = 120
MAX_SNIPPET_CHARS = 400
HARD_MAX_RESULTS = 8

STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or that the "
    "their then there this to was were what when where which who whom whose why with "
    "does did do many much each all across".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


class ToolError(ValueError):
    """Raised for invalid tool input. Surfaced to the agent as a tool error."""


def normalize_rel(path: str) -> str:
    """Lexically normalize a workspace-relative path.

    Rejects absolute paths and anything that climbs out of the workspace.
    'docs/../private/x.txt' normalizes to 'private/x.txt'.
    """
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise ToolError("path must be a non-empty string")
    candidate = path.strip().replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ToolError("absolute paths are not allowed")
    normalized = posixpath.normpath(candidate)
    if normalized == ".." or normalized.startswith("../"):
        raise ToolError("path escapes the workspace")
    return normalized


def resolve_in_workspace(workspace: Path, rel: str) -> Path:
    """Resolve to a real path and verify it is inside the workspace (symlink safe)."""
    root = workspace.resolve()
    target = (root / normalize_rel(rel)).resolve()
    if not target.is_relative_to(root):
        raise ToolError("path escapes the workspace")
    return target


def _expand(token: str) -> set[str]:
    parts = {p for p in re.split(r"[-_.]", token) if p}
    return {token} | parts


def _tokens(text: str) -> set[str]:
    """Lowercase word set with compound splitting and light plural stemming."""
    found: set[str] = set()
    for tok in _TOKEN_RE.findall(text.lower()):
        for piece in _expand(tok):
            if piece in STOPWORDS or len(piece) < 2:
                continue
            found.add(piece)
            if len(piece) > 3 and piece.endswith("s") and not piece.endswith("ss"):
                found.add(piece[:-1])
    return found


def _table_header(lines: list[str], idx: int) -> str | None:
    """If lines[idx] is a markdown table row, return the table's header row."""
    if not lines[idx].lstrip().startswith("|"):
        return None
    cursor = idx
    while cursor > 0 and lines[cursor - 1].lstrip().startswith("|"):
        cursor -= 1
    block = lines[cursor : idx + 1]
    for pos, line in enumerate(block):
        if _SEPARATOR_RE.match(line.strip()) and pos > 0:
            return block[pos - 1].strip()
    return None


def _section(lines: list[str], idx: int) -> str | None:
    for cursor in range(idx, -1, -1):
        if lines[cursor].startswith("#"):
            return lines[cursor].lstrip("# ").strip()
    return None


def search_dataset(workspace: Path, query: str, max_results: int = 5) -> str:
    """Keyword search over docs/*.md and docs/*.txt. Returns the best matching lines."""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string")
    try:
        limit = max(1, min(int(max_results), HARD_MAX_RESULTS))
    except (TypeError, ValueError):
        limit = 5
    query_tokens = _tokens(query)
    if not query_tokens:
        return "No matches."
    docs_dir = workspace / "docs"
    scored: list[tuple[float, str, int, str, str | None, str | None]] = []
    for doc in sorted(docs_dir.glob("*")):
        if doc.suffix not in {".md", ".txt"} or not doc.is_file():
            continue
        lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or _SEPARATOR_RE.match(stripped):
                continue
            if idx + 1 < len(lines) and _SEPARATOR_RE.match(lines[idx + 1].strip()):
                continue  # a table header row is context for its data rows, not a hit itself
            row_tokens = _tokens(stripped)
            header = _table_header(lines, idx)
            score = float(len(query_tokens & row_tokens))
            if header and header != stripped:
                score += 0.5 * len((query_tokens & _tokens(header)) - row_tokens)
            if score > 0:
                scored.append((score, doc.name, idx + 1, stripped, header, _section(lines, idx)))
    if not scored:
        return "No matches."
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    out: list[str] = []
    for _score, name, lineno, line, header, section in scored[:limit]:
        out.append(f"[docs/{name}:{lineno}] section: {section or '-'}")
        if header and header != line:
            out.append(f"  header: {header[:MAX_SNIPPET_CHARS]}")
        out.append(f"  line: {line[:MAX_SNIPPET_CHARS]}")
    return "\n".join(out)


def read_file(workspace: Path, path: str) -> str:
    """Read a text file by workspace-relative path (for example docs/incidents.md)."""
    target = resolve_in_workspace(workspace, path)
    if not target.is_file():
        raise ToolError(f"no such file: {normalize_rel(path)}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + "\n[truncated]"
    return text


def write_note(workspace: Path, title: str, content: str) -> str:
    """Save a note to notes/<slug>.md. Never overwrites an existing note."""
    if not isinstance(title, str) or not title.strip():
        raise ToolError("title must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        raise ToolError("content must be a non-empty string")
    if len(title) > MAX_TITLE_CHARS:
        raise ToolError(f"title is longer than {MAX_TITLE_CHARS} characters")
    if len(content) > MAX_NOTE_CHARS:
        raise ToolError(f"content is longer than {MAX_NOTE_CHARS} characters")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "note"
    notes_dir = workspace / "notes"
    notes_dir.mkdir(exist_ok=True)
    target = notes_dir / f"{slug}.md"
    counter = 2
    while target.exists():
        target = notes_dir / f"{slug}-{counter}.md"
        counter += 1
    target.write_text(f"# {title.strip()}\n\n{content.strip()}\n", encoding="utf-8")
    return f"Saved notes/{target.name}"
