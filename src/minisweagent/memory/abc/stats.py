"""Paired statistics for the A/B/C comparison.

The unit of analysis is the task.  Outcomes are binary (the official grading
resolved or not), so the primary test is exact McNemar on the discordant pairs
and the interval is a task-bootstrap percentile interval for the risk
difference.  No normal approximation is used with small discordant counts.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


def mcnemar_exact(gained: int, lost: int) -> float:
    """Two-sided exact McNemar p-value for ``gained`` and ``lost`` discordant pairs."""
    total = gained + lost
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, index) for index in range(min(gained, lost) + 1)) / 2**total
    return min(1.0, 2 * tail)


@dataclass(frozen=True)
class PairedResult:
    tasks: int
    gained: int
    lost: int
    both_resolved: int
    neither_resolved: int
    difference: float
    ci_low: float
    ci_high: float
    p_value: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tasks": self.tasks,
            "gained": self.gained,
            "lost": self.lost,
            "both_resolved": self.both_resolved,
            "neither_resolved": self.neither_resolved,
            "difference": round(self.difference, 4),
            "ci95_low": round(self.ci_low, 4),
            "ci95_high": round(self.ci_high, 4),
            "mcnemar_exact_p": round(self.p_value, 6),
        }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_result(
    control: dict[str, bool],
    treatment: dict[str, bool],
    *,
    bootstrap: int = 10_000,
    seed: int = 0,
) -> PairedResult:
    """Compare two arms on the same tasks.

    ``control`` and ``treatment`` must cover exactly the same task IDs.  The
    difference is treatment minus control; positive means the treatment resolved
    more tasks.
    """
    if set(control) != set(treatment):
        missing = sorted(set(control) ^ set(treatment))
        raise ValueError(f"arms cover different tasks: {missing[:5]}")
    if not control:
        raise ValueError("no tasks to compare")

    tasks = sorted(control)
    gained = sum(1 for task in tasks if treatment[task] and not control[task])
    lost = sum(1 for task in tasks if control[task] and not treatment[task])
    both = sum(1 for task in tasks if control[task] and treatment[task])
    neither = sum(1 for task in tasks if not control[task] and not treatment[task])
    difference = (gained - lost) / len(tasks)

    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(bootstrap):
        delta = 0
        for _ in range(len(tasks)):
            task = tasks[rng.randrange(len(tasks))]
            delta += int(treatment[task]) - int(control[task])
        samples.append(delta / len(tasks))
    low = _percentile(samples, 0.025)
    high = _percentile(samples, 0.975)

    return PairedResult(
        tasks=len(tasks),
        gained=gained,
        lost=lost,
        both_resolved=both,
        neither_resolved=neither,
        difference=difference,
        ci_low=low,
        ci_high=high,
        p_value=mcnemar_exact(gained, lost),
    )
