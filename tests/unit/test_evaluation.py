from __future__ import annotations

import pytest

from app.services.evaluation import (
    binary_f1,
    cohen_kappa,
    evidence_verbatim_rate,
    kendall_tau,
    recall_at_k,
)


def test_evaluation_metrics_report_perfect_results() -> None:
    metrics = binary_f1([True, False, True], [True, False, True])

    assert metrics.f1 == 1.0
    assert recall_at_k({"resume-1", "resume-3"}, ["resume-1", "resume-2", "resume-3"], 3) == 1.0
    assert kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert cohen_kappa(["met", "missing"], ["met", "missing"]) == 1.0
    assert evidence_verbatim_rate("Python and PostgreSQL", ["Python", "PostgreSQL"]) == 1.0


def test_evaluation_metrics_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        binary_f1([True], [])
    with pytest.raises(ValueError):
        recall_at_k({"a"}, ["a"], 0)
    with pytest.raises(ValueError):
        kendall_tau(["a"], ["b"])
    with pytest.raises(ValueError):
        cohen_kappa(["met"], [])
