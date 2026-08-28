"""Versioned deterministic evaluation runner and regression gate."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.services.evaluation import binary_f1, evidence_verbatim_rate, kendall_tau, recall_at_k

REQUIRED_METRICS = frozenset(
    {
        "classification_f1",
        "ranking_kendall_tau",
        "retrieval_recall_at_20",
        "evidence_verbatim_rate",
    }
)


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from a versioned evaluation artifact."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Evaluation artifact {path} must contain a JSON object.")
    return value


def evaluate_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Compute aggregate evaluation metrics from labelled prediction cases."""
    if not cases:
        raise ValueError("Evaluation dataset must contain at least one case.")

    expected_matches = [bool(case["expected_match"]) for case in cases]
    observed_matches = [bool(case["observed_match"]) for case in cases]
    f1 = binary_f1(expected_matches, observed_matches).f1
    taus = [kendall_tau(case["expected_ranking"], case["observed_ranking"]) for case in cases]
    recalls = [
        recall_at_k(set(case["relevant_candidate_ids"]), case["retrieved_candidate_ids"], 20)
        for case in cases
    ]
    evidence_rates = [
        evidence_verbatim_rate(case["evidence_document"], case["evidence_quotes"])
        for case in cases
    ]
    return {
        "classification_f1": f1,
        "ranking_kendall_tau": sum(taus) / len(taus),
        "retrieval_recall_at_20": sum(recalls) / len(recalls),
        "evidence_verbatim_rate": sum(evidence_rates) / len(evidence_rates),
    }


def evaluate_dataset(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a versioned dataset and return a serializable report."""
    version = dataset.get("version")
    cases = dataset.get("cases")
    if not isinstance(version, str) or not isinstance(cases, list):
        raise ValueError("Dataset must contain string 'version' and list 'cases'.")
    return {"dataset_version": version, "case_count": len(cases), "metrics": evaluate_cases(cases)}


def assert_no_regression(
    report: Mapping[str, Any], baseline: Mapping[str, Any], maximum_drop: float = 0.03
) -> None:
    """Raise when any tracked metric falls more than the allowed relative drop."""
    if not 0 <= maximum_drop < 1:
        raise ValueError("maximum_drop must be at least 0 and less than 1.")
    report_metrics = report.get("metrics")
    baseline_metrics = baseline.get("metrics")
    if not isinstance(report_metrics, Mapping) or not isinstance(baseline_metrics, Mapping):
        raise ValueError("Report and baseline must each contain a metrics object.")
    if report.get("dataset_version") != baseline.get("dataset_version"):
        raise ValueError("Report and baseline dataset versions must match.")
    missing = REQUIRED_METRICS - set(report_metrics) | REQUIRED_METRICS - set(baseline_metrics)
    if missing:
        raise ValueError(f"Missing required metrics: {', '.join(sorted(missing))}.")

    regressions = []
    for metric in sorted(REQUIRED_METRICS):
        observed = float(report_metrics[metric])
        expected = float(baseline_metrics[metric])
        if observed < expected * (1 - maximum_drop):
            regressions.append(f"{metric}: {observed:.4f} < {expected * (1 - maximum_drop):.4f}")
    if regressions:
        raise ValueError("Evaluation regression exceeds threshold: " + "; ".join(regressions))
