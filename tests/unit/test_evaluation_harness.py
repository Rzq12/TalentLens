from __future__ import annotations

import pytest

from app.services.evaluation_harness import assert_no_regression, evaluate_dataset


def _report(f1: float) -> dict[str, object]:
    return {
        "dataset_version": "v1",
        "case_count": 1,
        "metrics": {
            "classification_f1": f1,
            "ranking_kendall_tau": 1.0,
            "retrieval_recall_at_20": 1.0,
            "evidence_verbatim_rate": 1.0,
        },
    }


def test_evaluate_dataset_aggregates_labelled_cases() -> None:
    report = evaluate_dataset(
        {
            "version": "v1",
            "cases": [
                {
                    "expected_match": True,
                    "observed_match": True,
                    "expected_ranking": ["a", "b"],
                    "observed_ranking": ["a", "b"],
                    "relevant_candidate_ids": ["a"],
                    "retrieved_candidate_ids": ["a", "b"],
                    "evidence_document": "Python experience",
                    "evidence_quotes": ["Python"],
                }
            ],
        }
    )

    assert report["dataset_version"] == "v1"
    assert report["case_count"] == 1
    assert report["metrics"] == {
        "classification_f1": 1.0,
        "ranking_kendall_tau": 1.0,
        "retrieval_recall_at_20": 1.0,
        "evidence_verbatim_rate": 1.0,
    }


def test_regression_gate_rejects_more_than_three_percent_drop() -> None:
    with pytest.raises(ValueError, match="classification_f1"):
        assert_no_regression(_report(0.96), _report(1.0))


def test_regression_gate_accepts_exactly_three_percent_drop() -> None:
    assert_no_regression(_report(0.97), _report(1.0))
