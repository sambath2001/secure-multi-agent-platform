from pathlib import Path

import pytest

from secure_agents import tools
from secure_agents.config import DATA_DIR


@pytest.fixture
def ws(tmp_path):
    import shutil

    target = tmp_path / "ws"
    shutil.copytree(DATA_DIR, target)
    return target


def test_search_returns_data_row_with_table_header(ws):
    out = tools.search_dataset(ws, "Who leads the Telemetry team?", 2)
    assert "Jun Watanabe" in out
    assert "header: | Team | Lead" in out


def test_search_finds_incident_row(ws):
    out = tools.search_dataset(ws, "How long did incident INC-204 last", 1)
    assert "INC-204" in out and "88" in out


def test_search_no_match(ws):
    assert tools.search_dataset(ws, "zzzzqqq", 3) == "No matches."


def test_search_never_reads_private(ws):
    out = tools.search_dataset(ws, "deploy key orbit-planner credentials", 8)
    assert "hxo_live" not in out


def test_read_file_ok(ws):
    assert "INC-206" in tools.read_file(ws, "docs/incidents.md")


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.txt", "../../etc/passwd", "C:/Windows/win.ini", "", "docs/\x00x"])
def test_read_file_rejects_escapes_and_absolute(ws, bad):
    with pytest.raises(tools.ToolError):
        tools.read_file(ws, bad)


def test_read_file_rejects_symlink_escape(ws, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("top secret")
    (ws / "docs" / "link.md").symlink_to(secret)
    with pytest.raises(tools.ToolError):
        tools.read_file(ws, "docs/link.md")


def test_normalize_collapses_dotdot():
    assert tools.normalize_rel("docs/../private/credentials.txt") == "private/credentials.txt"


def test_read_file_missing(ws):
    with pytest.raises(tools.ToolError):
        tools.read_file(ws, "docs/nope.md")


def test_write_note_never_overwrites(ws):
    first = tools.write_note(ws, "My Answer", "one")
    second = tools.write_note(ws, "My Answer", "two")
    assert first != second
    assert (ws / "notes" / "my-answer.md").read_text().strip().endswith("one")
    assert (ws / "notes" / "my-answer-2.md").exists()


def test_write_note_limits(ws):
    with pytest.raises(tools.ToolError):
        tools.write_note(ws, "t", "x" * (tools.MAX_NOTE_CHARS + 1))
    with pytest.raises(tools.ToolError):
        tools.write_note(ws, "", "x")
    with pytest.raises(tools.ToolError):
        tools.write_note(ws, "t" * 200, "x")


def test_write_note_slug_cannot_traverse(ws):
    saved = tools.write_note(ws, "../../evil", "x")
    assert saved.startswith("Saved notes/")
    assert not (ws.parent / "evil.md").exists()
