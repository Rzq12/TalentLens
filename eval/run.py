"""Run the deterministic golden-set evaluation and enforce its baseline gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.evaluation_harness import assert_no_regression, evaluate_dataset, load_json


def parse_args() -> argparse.Namespace:
    """Parse evaluation artifact paths and the permitted regression threshold."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("eval/golden_set.v1.json"))
    parser.add_argument("--baseline", type=Path, default=Path("eval/baseline.v1.json"))
    parser.add_argument("--report", type=Path, default=Path("eval/report.json"))
    parser.add_argument("--maximum-drop", type=float, default=0.03)
    return parser.parse_args()


def main() -> None:
    """Write the current report, then fail if quality regresses past the gate."""
    args = parse_args()
    report = evaluate_dataset(load_json(args.dataset))
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert_no_regression(report, load_json(args.baseline), args.maximum_drop)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
