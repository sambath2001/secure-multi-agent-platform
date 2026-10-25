from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_is_ignored_and_example_is_not():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in lines
    assert "!.env.example" in lines


def test_env_example_contains_no_real_keys():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith(("ANTHROPIC_API_KEY=", "OPENAI_API_KEY=")):
            assert line.split("=", 1)[1] == "", line
