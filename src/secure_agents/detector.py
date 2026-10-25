"""Heuristic prompt-injection detector.

This is a pattern matcher, not a classifier. It catches common phrasings and
misses paraphrases, other languages, and obfuscation. The eval measures that
gap; it is not hidden. Rules were written from the dev split of the attack set
only (see docs/METRICS.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(previous|prior|above|earlier|all|your|the)\b[^.\n]{0,40}"
            r"\b(instructions?|rules?|prompts?|task)\b",
            re.I,
        ),
    ),
    ("system_override", re.compile(r"\bsystem\s+override\b|\bnew\s+instructions?\s*:", re.I)),
    (
        "tool_directive",
        re.compile(r"\b(call(?:ing)?|invoke|use|run)\b[^.\n]{0,30}\b(write_note|read_file|search_dataset)\b", re.I),
    ),
    ("private_path", re.compile(r"\bprivate/", re.I)),
    ("credentials_file", re.compile(r"\bcredentials?\.txt\b", re.I)),
    ("path_traversal", re.compile(r"\.\./|/etc/passwd", re.I)),
    (
        "addresses_ai",
        re.compile(r"\b(note to|message for|attention)\b[^.\n]{0,15}\b(ai|assistant|agent|model|llm)\b", re.I),
    ),
    ("concealment", re.compile(r"\bdo not (tell|inform|mention|reveal)\b[^.\n]{0,30}\b(user|anyone)\b", re.I)),
]


@dataclass(frozen=True)
class Hit:
    rule: str
    line_no: int


def scan(text: str) -> list[Hit]:
    hits: list[Hit] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            if pattern.search(line):
                hits.append(Hit(name, line_no))
    return hits


def sanitize(text: str) -> tuple[str, list[Hit]]:
    """Replace every line that matches a rule with a short notice."""
    hits: list[Hit] = []
    cleaned: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line_hits = [name for name, pattern in PATTERNS if pattern.search(line)]
        if line_hits:
            hits.extend(Hit(name, line_no) for name in line_hits)
            cleaned.append("[line removed by injection guardrail]")
        else:
            cleaned.append(line)
    return "\n".join(cleaned), hits
