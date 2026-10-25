import pytest

from secure_agents.policy import ToolPolicy, find_secrets, redact_secrets

KEY = "hxo_live_7Qm2ZsK9vT4aWb81LdRx"


def test_role_allowlist():
    researcher = ToolPolicy("researcher")
    assert not researcher.check("write_note", {"title": "t", "content": "c"}).allowed
    assert researcher.check("search_dataset", {"query": "x"}).allowed
    assert not ToolPolicy("executor").check("read_file", {"path": "docs/faq.md"}).allowed
    assert not ToolPolicy("planner").check("search_dataset", {"query": "x"}).allowed
    assert not ToolPolicy("unknown-role").check("search_dataset", {"query": "x"}).allowed


@pytest.mark.parametrize(
    "path",
    ["private/credentials.txt", "docs/../private/credentials.txt", "./private/credentials.txt",
     "../../etc/passwd", "/etc/passwd", "docs/.hidden", "notes/x.md", "docs\\..\\private\\credentials.txt"],
)
def test_read_scope_denies(path):
    decision = ToolPolicy("researcher").check("read_file", {"path": path})
    assert not decision.allowed and decision.rule == "read_scope"


@pytest.mark.parametrize("path", ["docs/incidents.md", "docs/./incidents.md", "docs/../docs/faq.md"])
def test_read_scope_allows_docs(path):
    assert ToolPolicy("researcher").check("read_file", {"path": path}).allowed


def test_dlp_blocks_secret_in_note():
    decision = ToolPolicy("executor").check("write_note", {"title": "Answer", "content": f"key is {KEY}"})
    assert not decision.allowed and decision.rule == "dlp_secret"


def test_dlp_known_limit_encoded_secret_passes_the_regex():
    # Documented limitation: pattern-based DLP does not see base64 or hyphen-split secrets.
    import base64

    encoded = base64.b64encode(KEY.encode()).decode()
    assert ToolPolicy("executor").check("write_note", {"title": "Answer", "content": encoded}).allowed
    assert ToolPolicy("executor").check("write_note", {"title": "Answer", "content": "-".join(KEY)}).allowed


def test_note_title_charset():
    assert not ToolPolicy("executor").check("write_note", {"title": "../../x", "content": "c"}).allowed


def test_call_limits():
    policy = ToolPolicy("executor")
    assert policy.check("write_note", {"title": "A", "content": "c"}).allowed
    assert policy.check("write_note", {"title": "B", "content": "c"}).rule == "call_limit"
    researcher = ToolPolicy("researcher")
    for _ in range(6):
        assert researcher.check("search_dataset", {"query": "x"}).allowed
    assert researcher.check("search_dataset", {"query": "x"}).rule == "call_limit"


def test_denied_calls_do_not_consume_budget():
    policy = ToolPolicy("researcher")
    for _ in range(10):
        policy.check("read_file", {"path": "private/credentials.txt"})
    assert policy.check("read_file", {"path": "docs/faq.md"}).allowed


def test_secret_helpers():
    assert find_secrets(f"x {KEY} y") == ["api_key_like"]
    cleaned, hits = redact_secrets(f"x {KEY} y")
    assert KEY not in cleaned and hits == ["api_key_like"]
    assert find_secrets("The deploy window is Friday.") == []
