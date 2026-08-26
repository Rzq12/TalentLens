"""Tests for the deterministic assessment demo used in the hiring exercise."""

from __future__ import annotations

import json


def test_demo_scores_and_ranks_the_five_sample_cvs():
    from app.demo.assessment import load_assessment_case, run_assessment

    job, candidates = load_assessment_case()
    report = run_assessment(job=job, candidates=candidates)

    assert job.title == "Junior Architect"
    assert len(report.results) == 5
    assert [result.rank for result in report.results] == [1, 2, 3, 4, 5]
    # Top should be strongest overall match; bottom the weakest
    assert report.results[0].score > report.results[-1].score


def test_demo_score_is_explainable_and_bounded():
    from app.demo.assessment import load_assessment_case, run_assessment

    job, candidates = load_assessment_case()
    report = run_assessment(job=job, candidates=candidates)

    for result in report.results:
        assert 0.0 <= result.score <= 100.0
        assert result.status in {"Strong Match", "Potential Match", "Needs Review"}
        assert result.strengths
        assert result.gaps
        assert len(result.breakdown) == len(job.criteria)
        assert round(sum(item.weight for item in result.breakdown), 6) == 1.0
        assert all(item.evidence for item in result.breakdown)


def test_minimum_experience_is_not_awarded_full_credit_when_missing():
    from app.demo.assessment import load_assessment_case, run_assessment

    job, candidates = load_assessment_case()
    report = run_assessment(job=job, candidates=candidates)
    dimas = next(result for result in report.results if result.candidate_name == "Dimas Saputra")
    experience = next(item for item in dimas.breakdown if item.criterion_key == "experience")

    assert experience.match_ratio < 0.8
    assert experience.match_ratio < 1.0
    assert any("2 years" in gap for gap in dimas.gaps)


def test_demo_json_output_is_machine_readable():
    from app.demo.assessment import load_assessment_case, report_as_dict, run_assessment

    job, candidates = load_assessment_case()
    report = run_assessment(job=job, candidates=candidates)
    encoded = json.dumps(report_as_dict(report))
    decoded = json.loads(encoded)

    assert decoded["job_title"] == "Junior Architect"
    assert decoded["candidate_count"] == 5
    assert decoded["results"][0]["rank"] == 1
