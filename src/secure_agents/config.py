"""Guardrail presets. Each layer can be switched on its own so the eval can
measure what every layer contributes (ablation)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


@dataclass(frozen=True)
class GuardConfig:
    name: str
    hardened_prompt: bool  # security rules in the system prompt + untrusted-data tags
    detector: bool  # heuristic injection scanner on tool output and agent handoffs
    gateway_policy: bool  # per-role allowlist, path scope, call limits, secret (DLP) filter
    role_isolation: bool  # server registers only the tools the role needs (and, in docker, minimal mounts)


PRESETS: dict[str, GuardConfig] = {
    "none": GuardConfig("none", False, False, False, False),
    "prompt": GuardConfig("prompt", True, False, False, False),
    "detector": GuardConfig("detector", False, True, False, False),
    "policy": GuardConfig("policy", False, False, True, True),
    "full": GuardConfig("full", True, True, True, True),
}


def get_config(name: str) -> GuardConfig:
    try:
        return PRESETS[name]
    except KeyError as exc:
        raise SystemExit(f"unknown config '{name}'. choose from: {', '.join(PRESETS)}") from exc
