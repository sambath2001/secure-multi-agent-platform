"""Guard against a silent experiment flaw: an attack payload that the agent can never see
tells us nothing about the defenses. For every document-borne attack, the payload line must
rank in the top search results for the benign task's question."""

import json
import shutil
from pathlib import Path

import pytest

from secure_agents.config import DATA_DIR
from secure_agents.tools import search_dataset

EVALS = Path(__file__).resolve().parents[1] / "evals"
ATTACKS = json.loads((EVALS / "attacks.json").read_text())
TASKS = {t["id"]: t for t in json.loads((EVALS / "tasks.json").read_text())}


@pytest.mark.parametrize("attack", [a for a in ATTACKS if a["vector"] in {"doc", "search_snippet"}], ids=lambda a: a["id"])
def test_payload_is_retrievable_by_the_task_question(attack, tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(DATA_DIR, workspace)
    poison = attack["poison"]
    target = workspace / poison["file"]
    target.write_text(target.read_text() + poison["text"] if poison["mode"] == "append" else poison["text"])
    results = search_dataset(workspace, TASKS[attack["task_id"]]["question"], 5)
    assert attack["trigger"] in results, f"{attack['id']} payload is not retrievable, so it would not test anything"
