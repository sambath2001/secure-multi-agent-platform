"""Run the eval suites and write raw trials, metadata, and a report.

Examples:
    python -m evals.run_eval --suite attacks --client gullible --config all      # no API key, simulated worst case
    python -m evals.run_eval --suite normal --config none --limit 3               # cheap smoke test, real model
    python -m evals.run_eval --suite all --config none,full --repeat 3            # baseline vs full

Every trial is appended to trials.jsonl as soon as it finishes, so an aborted
run (budget, crash, Ctrl-C) keeps what it already paid for.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata as md
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from secure_agents.config import DATA_DIR, PRESETS, ROOT, get_config
from secure_agents.guard import BASE_PROMPTS, HARDENING
from secure_agents.llm import Budget, BudgetExceeded, build_client, describe_model
from secure_agents.sim import GullibleClient
from secure_agents.workflow import RunResult, run_workflow

from . import report
from .judge import judge_attack, judge_task

EVALS_DIR = Path(__file__).resolve().parent


def load(name: str) -> list[dict]:
    return json.loads((EVALS_DIR / name).read_text())


def plant(workspace: Path, attack: dict) -> None:
    poison = attack.get("poison")
    if not poison:
        return
    target = workspace / poison["file"]
    if poison["mode"] == "append":
        target.write_text(target.read_text() + poison["text"])
    else:
        target.write_text(poison["text"])


def sha256_of(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def build_meta(args, configs: list[str], budget: Budget | None) -> dict:
    from secure_agents import detector

    prompt_blob = json.dumps(BASE_PROMPTS, sort_keys=True) + HARDENING + "".join(p.pattern for _, p in detector.PATTERNS)
    simulated = args.client == "gullible"
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "simulated": simulated,
        "model": {"provider": "gullible-sim", "model": "scripted worst-case model"} if simulated else describe_model(),
        "suite": args.suite,
        "configs": configs,
        "sandbox": args.sandbox,
        "repeat": args.repeat,
        "split": args.split,
        "limit": args.limit,
        "dataset_hash": sha256_of(list((DATA_DIR / "docs").glob("*")) + [EVALS_DIR / "tasks.json", EVALS_DIR / "attacks.json"]),
        "prompt_and_rules_hash": hashlib.sha256(prompt_blob.encode()).hexdigest()[:16],
        "git_commit": git_commit(),
        "python": platform.python_version(),
        "mcp": md.version("mcp"),
        "langchain_core": md.version("langchain-core"),
        "price_in_per_mtok": getattr(budget, "price_in", None),
        "price_out_per_mtok": getattr(budget, "price_out", None),
        "aborted": None,
    }


async def run_trial(client, cfg, sandbox: str, task_text: str, attack: dict | None) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="hx-ws-") as tmp:
        workspace = Path(tmp) / "ws"
        shutil.copytree(DATA_DIR, workspace)
        (workspace / "notes").mkdir(exist_ok=True)
        if attack:
            plant(workspace, attack)
        return await run_workflow(task_text, client=client, cfg=cfg, workspace=workspace, sandbox=sandbox)


def trial_record(run_id: str, suite: str, cfg_name: str, rep: int, item: dict, task: dict, attack: dict | None, run: RunResult) -> dict:
    run_dict = {"notes": run.notes, "final_answer": run.final_answer, "events": run.events}
    record = {
        "run_id": run_id, "suite": suite, "config": cfg_name, "rep": rep,
        "item_id": item["id"], "task_id": task["id"], "error": run.error,
        "llm_calls": run.llm_calls, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "seconds": run.seconds, "plan": run.plan, "findings": run.findings[:1500],
        "final_answer": run.final_answer, "notes": run.notes, "events": run.events,
    }
    if attack:
        record.update(split=attack["split"], category=attack["category"], goal=attack["goal"], vector=attack["vector"])
        record["attack_judge"] = judge_attack(attack, run_dict)
        record["task_judge"] = judge_task(task, run_dict)  # did the real task still get done under attack
    else:
        record["task_judge"] = judge_task(task, run_dict)
    return record


async def main_async(args) -> Path:
    configs = list(PRESETS) if args.config == "all" else args.config.split(",")
    for name in configs:
        get_config(name)
    tasks = {t["id"]: t for t in load("tasks.json")}
    attacks = load("attacks.json")

    if args.client == "gullible":
        if args.suite != "attacks":
            raise SystemExit("the simulated model can only run --suite attacks (utility numbers would be meaningless)")
        budget = None
    else:
        budget = Budget.from_env()

    items: list[tuple[str, dict, dict, dict | None]] = []
    if args.suite in {"normal", "all"}:
        items += [("normal", t, t, None) for t in tasks.values()]
    if args.suite in {"attacks", "all"}:
        for a in attacks:
            if args.split in {"dev", "test"} and a["split"] != args.split:
                continue
            items.append(("attacks", a, tasks[a["task_id"]], a))
    if args.limit:
        items = items[: args.limit]

    prefix = "sim" if args.client == "gullible" else "run"
    run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out_dir = Path(args.out) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = build_meta(args, configs, budget)
    meta["planned_trials"] = len(items) * len(configs) * args.repeat
    trials_path = out_dir / "trials.jsonl"
    done = 0
    real_client = None

    try:
        for cfg_name in configs:
            cfg = get_config(cfg_name)
            for suite, item, task, attack in items:
                for rep in range(args.repeat):
                    task_text = task["question"] + (attack.get("task_suffix", "") if attack else "")
                    if args.client == "gullible":
                        client = GullibleClient({"trigger": attack["trigger"], **attack["sim"]} if attack else None)
                    else:
                        real_client = real_client or build_client(budget)
                        client = real_client
                    run = await run_trial(client, cfg, args.sandbox, task_text, attack)
                    record = trial_record(run_id, suite, cfg_name, rep, item, task, attack, run)
                    with trials_path.open("a") as fh:
                        fh.write(json.dumps(record) + "\n")
                    done += 1
                    status = "ERR" if run.error else (
                        record["attack_judge"]["outcome"] if attack else ("pass" if record["task_judge"]["passed"] else "fail")
                    )
                    print(f"[{done}/{meta['planned_trials']}] {cfg_name:8s} {item['id']:4s} rep{rep} -> {status}", flush=True)
    except BudgetExceeded as exc:
        meta["aborted"] = f"budget: {exc}"
        print(f"STOPPED: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        meta["aborted"] = "interrupted"

    meta["completed_trials"] = done
    if budget:
        meta["usage"] = {"calls": budget.usage.calls, "input_tokens": budget.usage.input_tokens,
                         "output_tokens": budget.usage.output_tokens, "tokens_estimated": budget.usage.estimated,
                         "estimated_usd": budget.estimated_usd()}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    report.write_report(out_dir)
    print(f"\nresults in {out_dir}\n")
    print((out_dir / "report.md").read_text())
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=["normal", "attacks", "all"], default="all")
    parser.add_argument("--config", default="none", help=f"comma list or 'all'. presets: {', '.join(PRESETS)}")
    parser.add_argument("--repeat", type=int, default=1, help="repeats per item (LLM output is nondeterministic)")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all", help="attack split")
    parser.add_argument("--sandbox", choices=["none", "docker"], default="none")
    parser.add_argument("--client", choices=["real", "gullible"], default="real")
    parser.add_argument("--limit", type=int, default=0, help="only the first N items (smoke tests)")
    parser.add_argument("--out", default=str(ROOT / "results"))
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
