"""Offline check of the heuristic detector on the attack payload text. No LLM, no API key.

Reports recall on the dev split (rules were written from these) and on the test split
(rules were not), plus false positives on the clean document set.

Author bias warning: the same person wrote the rules and the attacks. Treat the test
number as a stress test of paraphrase and obfuscation, not as a field estimate.
"""

from __future__ import annotations

import json
from pathlib import Path

from secure_agents import detector
from secure_agents.config import DATA_DIR

from .stats import fmt, rate


def main() -> None:
    attacks = json.loads((Path(__file__).parent / "attacks.json").read_text())
    scanned = [a for a in attacks if a["vector"] in {"doc", "search_snippet"}]
    skipped = [a["id"] for a in attacks if a["vector"] == "task_embedded"]
    print("Detector recall on attack payload text (doc and search-snippet attacks only)")
    for split in ("dev", "test"):
        subset = [a for a in scanned if a["split"] == split]
        flagged = [a["id"] for a in subset if detector.scan(a["poison"]["text"])]
        missed = [a["id"] for a in subset if a["id"] not in flagged]
        print(f"  {split:4s}: {fmt(rate(len(flagged), len(subset)))}  missed: {', '.join(missed) or 'none'}")
    print(f"  not scanned by design (text arrives in the user task, a trusted channel): {', '.join(skipped)}")

    total_lines, flagged_lines = 0, 0
    for doc in sorted((DATA_DIR / "docs").glob("*.md")):
        text = doc.read_text()
        total_lines += len([l for l in text.splitlines() if l.strip()])
        flagged_lines += len({h.line_no for h in detector.scan(text)})
    print(f"\nFalse positives on the clean corpus: {flagged_lines} of {total_lines} non-empty lines flagged")


if __name__ == "__main__":
    main()
