from __future__ import annotations

import pytest

from minisweagent.memory.abc.stats import mcnemar_exact, paired_result


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(0.0625)
    assert mcnemar_exact(4, 0) == pytest.approx(0.125)
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(3, 3) == pytest.approx(1.0)


def test_paired_result_counts_switches_and_ci_contains_the_difference():
    control = {f"t{i}": i < 6 for i in range(10)}
    treatment = {f"t{i}": i < 9 for i in range(10)}
    result = paired_result(control, treatment, bootstrap=2000, seed=7)
    assert result.tasks == 10
    assert result.gained == 3
    assert result.lost == 0
    assert result.difference == pytest.approx(0.3)
    assert result.ci_low <= result.difference <= result.ci_high
    assert result.p_value < 0.5


def test_paired_result_requires_identical_task_sets():
    with pytest.raises(ValueError):
        paired_result({"a": True}, {"b": True})


def test_paired_result_rejects_empty_input():
    with pytest.raises(ValueError):
        paired_result({}, {})
