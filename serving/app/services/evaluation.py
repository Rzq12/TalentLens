"""Deterministic evaluation metrics for screening quality gates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryClassificationMetrics:
    """Precision, recall, and F1 for one positive label."""

    precision: float
    recall: float
    f1: float


def binary_f1(expected: Sequence[bool], predicted: Sequence[bool]) -> BinaryClassificationMetrics:
    """Calculate F1, treating ``True`` as the positive class."""
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must have equal length.")
    pairs = list(zip(expected, predicted, strict=True))
    true_positive = sum(actual and observed for actual, observed in pairs)
    false_positive = sum(not actual and observed for actual, observed in pairs)
    false_negative = sum(actual and not observed for actual, observed in pairs)
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return BinaryClassificationMetrics(precision=precision, recall=recall, f1=f1)


def recall_at_k(relevant_ids: set[str], ranked_ids: Sequence[str], k: int) -> float:
    """Calculate retrieval recall among the first ``k`` ranked ids."""
    if k < 1:
        raise ValueError("k must be positive.")
    if not relevant_ids:
        return 1.0
    return len(relevant_ids & set(ranked_ids[:k])) / len(relevant_ids)


def kendall_tau(expected: Sequence[str], predicted: Sequence[str]) -> float:
    """Calculate Kendall tau for two equal rankings with the same ids."""
    if len(expected) != len(predicted) or set(expected) != set(predicted):
        raise ValueError("Rankings must contain the same ids exactly once.")
    positions = {item: index for index, item in enumerate(predicted)}
    concordant = 0
    discordant = 0
    for left in range(len(expected)):
        for right in range(left + 1, len(expected)):
            if positions[expected[left]] < positions[expected[right]]:
                concordant += 1
            else:
                discordant += 1
    pair_count = concordant + discordant
    return (concordant - discordant) / pair_count if pair_count else 1.0


def cohen_kappa(expected: Sequence[str], observed: Sequence[str]) -> float:
    """Calculate Cohen's kappa for categorical human/model agreement."""
    if len(expected) != len(observed):
        raise ValueError("Expected and observed labels must have equal length.")
    if not expected:
        return 1.0
    labels = set(expected) | set(observed)
    actual_agreement = (
        sum(left == right for left, right in zip(expected, observed, strict=True))
        / len(expected)
    )
    expected_agreement = sum(
        expected.count(label) / len(expected) * observed.count(label) / len(observed)
        for label in labels
    )
    if expected_agreement == 1:
        return 1.0 if actual_agreement == 1 else 0.0
    return (actual_agreement - expected_agreement) / (1 - expected_agreement)


def evidence_verbatim_rate(document: str, quotes: Sequence[str]) -> float:
    """Measure the fraction of nonempty evidence quotes found verbatim."""
    valid_quotes = [quote for quote in quotes if quote]
    if not valid_quotes:
        return 1.0
    return sum(quote in document for quote in valid_quotes) / len(valid_quotes)
