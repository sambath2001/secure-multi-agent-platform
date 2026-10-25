"""Every task must be solvable from the corpus, and derived answers must match a recomputation."""

import json
import re
from pathlib import Path

from evals.judge import contains_token
from secure_agents.config import DATA_DIR

EVALS = Path(__file__).resolve().parents[1] / "evals"
TASKS = json.loads((EVALS / "tasks.json").read_text())
CORPUS = "\n".join(p.read_text() for p in sorted((DATA_DIR / "docs").glob("*.md")))


def table_rows(filename: str) -> list[list[str]]:
    rows = []
    for line in (DATA_DIR / "docs" / filename).read_text().splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:]  # drop header


def test_ids_unique_and_count():
    ids = [t["id"] for t in TASKS]
    assert len(ids) == len(set(ids)) == 20


def test_literal_answers_exist_in_corpus():
    for task in TASKS:
        if task["derived"]:
            continue
        for item in task["required"]:
            alternatives = item if isinstance(item, list) else [item]
            assert any(contains_token(CORPUS, alt) for alt in alternatives), (task["id"], alternatives)


def test_derived_answers_match_recomputation():
    incidents = table_rows("incidents.md")
    budget = table_rows("budget_2026.md")
    expected = {
        "N15": str(sum(int(r[4]) for r in incidents if r[2] == "telemetry-ingest")),
        "N17": str(sum(int(r[2]) + int(r[3]) for r in budget if r[0] == "Security")),
        "N18": str(sum(int(r[3]) for r in budget)),
    }
    by_id = {t["id"]: t for t in TASKS}
    for tid, value in expected.items():
        flat = [alt for item in by_id[tid]["required"] for alt in (item if isinstance(item, list) else [item])]
        assert value in flat, (tid, value, flat)


def test_multi_hop_answers_match_tables():
    services = {r[0]: r for r in table_rows("services.md")}
    teams = {r[0]: r for r in table_rows("team_directory.md")}
    incidents = {r[0]: r for r in table_rows("incidents.md")}
    longest = max(incidents.values(), key=lambda r: int(r[4]))
    lead = teams[services[longest[2]][1]][1]
    n09 = next(t for t in TASKS if t["id"] == "N09")
    assert lead in n09["required"] and "rebalance" in longest[5]
    rust = [s for s in services.values() if s[2] == "Rust"]
    assert len(rust) == 1  # N11 depends on exactly one Rust service
    assert teams[rust[0][1]][1] == "Dmitri Volkov"
