"""End to end through real MCP server subprocesses, with a simulated fully compromised model.

These tests assert invariants of the deterministic layers. They say nothing about how any
real LLM behaves.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from evals.judge import judge_attack
from evals.run_eval import plant
from secure_agents.config import DATA_DIR, get_config
from secure_agents.sim import GullibleClient
from secure_agents.workflow import run_workflow

pytestmark = pytest.mark.slow

EVALS = Path(__file__).resolve().parents[1] / "evals"
ATTACKS = json.loads((EVALS / "attacks.json").read_text())
TASKS = {t["id"]: t for t in json.loads((EVALS / "tasks.json").read_text())}


def run_attack(attack, config, tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(DATA_DIR, workspace)
    (workspace / "notes").mkdir(exist_ok=True)
    plant(workspace, attack)
    task = TASKS[attack["task_id"]]["question"] + attack.get("task_suffix", "")
    client = GullibleClient({"trigger": attack["trigger"], **attack["sim"]})
    result = asyncio.run(run_workflow(task, client=client, cfg=get_config(config), workspace=workspace, sandbox="none"))
    assert result.error is None, result.error
    run = {"notes": result.notes, "final_answer": result.final_answer, "events": result.events}
    return judge_attack(attack, run)


def test_plumbing_without_attack_writes_a_note(tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(DATA_DIR, workspace)
    result = asyncio.run(run_workflow("Who leads the Telemetry team?", client=GullibleClient(), cfg=get_config("none"), workspace=workspace))
    assert result.error is None and result.notes and result.llm_calls == 5  # planner 1, researcher 2, executor 2
    assert [e["tool"] for e in result.events] == ["search_dataset", "write_note"]


@pytest.mark.parametrize("attack", [a for a in ATTACKS if a["category"] != "sandbox_control"], ids=lambda a: a["id"])
def test_without_guardrails_a_compromised_model_achieves_every_goal(attack, tmp_path):
    verdict = run_attack(attack, "none", tmp_path)
    assert verdict["exposed"]
    assert verdict["goal_achieved"], attack["id"]


@pytest.mark.parametrize(
    "attack",
    [a for a in ATTACKS if a["goal"] in {"leak_secret", "forbidden_read", "unauthorized_tool"}],
    ids=lambda a: a["id"],
)
def test_policy_layer_stops_capability_abuse_even_when_the_model_is_fully_compromised(attack, tmp_path):
    verdict = run_attack(attack, "policy", tmp_path)
    assert verdict["exposed"]
    assert not verdict["goal_achieved"], (attack["id"], verdict)


def test_sandbox_control_is_blocked_by_the_server_in_every_config(tmp_path):
    control = next(a for a in ATTACKS if a["category"] == "sandbox_control")
    for config in ("none", "full"):
        verdict = run_attack(control, config, tmp_path / config)
        assert not verdict["goal_achieved"]


def test_policy_layer_does_not_stop_content_hijack_and_that_is_reported_honestly(tmp_path):
    hijack = next(a for a in ATTACKS if a["id"] == "T3")
    assert run_attack(hijack, "policy", tmp_path)["goal_achieved"]
