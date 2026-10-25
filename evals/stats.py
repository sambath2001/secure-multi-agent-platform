"""Small statistics helpers. Every reported rate carries n and a 95% interval."""

from __future__ import annotations

import math


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def rate(successes: int, n: int) -> dict:
    lo, hi = wilson(successes, n)
    return {"k": successes, "n": n, "rate": (successes / n) if n else 0.0, "lo": lo, "hi": hi}


def fmt(r: dict) -> str:
    """Format as '7/10 = 70% (95% CI 40-89%)'."""
    if r["n"] == 0:
        return "n/a (0 trials)"
    return f"{r['k']}/{r['n']} = {r['rate']*100:.0f}% (95% CI {r['lo']*100:.0f}-{r['hi']*100:.0f}%)"
