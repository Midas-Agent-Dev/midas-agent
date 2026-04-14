"""Unit tests for SWEBenchScorer."""
import pytest

from midas_agent.evaluation.swebench_scorer import SWEBenchScorer
from midas_agent.types import Issue


def _make_issue(**kwargs) -> Issue:
    defaults = dict(
        issue_id="django__django-16379",
        repo="django/django",
        description="Fix bug",
        base_commit="abc123",
        fail_to_pass=["test_a", "test_b"],
        pass_to_pass=["test_c"],
    )
    defaults.update(kwargs)
    return Issue(**defaults)


@pytest.mark.unit
class TestSWEBenchScorer:
    def test_inherits_from_execution_scorer(self):
        from midas_agent.evaluation.execution_scorer import ExecutionScorer
        scorer = SWEBenchScorer()
        assert isinstance(scorer, ExecutionScorer)

    def test_empty_patch_returns_zero(self):
        scorer = SWEBenchScorer()
        assert scorer.score("", _make_issue()) == 0.0
        assert scorer.score("   ", _make_issue()) == 0.0

    def test_parse_report_resolved(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {"resolved": True}}
        assert scorer._parse_report(report, _make_issue()) == 1.0

    def test_parse_report_patch_not_applied(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {
            "patch_successfully_applied": False,
            "resolved": False,
        }}
        assert scorer._parse_report(report, _make_issue()) == 0.0

    def test_parse_report_partial_pass(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {
            "resolved": False,
            "patch_successfully_applied": True,
            "tests_status": {
                "test_a": "PASSED",
                "test_b": "FAILED",
                "test_c": "PASSED",
            },
        }}
        assert scorer._parse_report(report, _make_issue()) == pytest.approx(0.5)

    def test_parse_report_regression_returns_zero(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {
            "resolved": False,
            "patch_successfully_applied": True,
            "tests_status": {
                "test_a": "PASSED",
                "test_b": "PASSED",
                "test_c": "FAILED",  # PASS_TO_PASS regression
            },
        }}
        assert scorer._parse_report(report, _make_issue()) == 0.0

    def test_parse_report_all_fail(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {
            "resolved": False,
            "patch_successfully_applied": True,
            "tests_status": {
                "test_a": "FAILED",
                "test_b": "FAILED",
                "test_c": "PASSED",
            },
        }}
        assert scorer._parse_report(report, _make_issue()) == 0.0

    def test_parse_report_no_fail_to_pass(self):
        scorer = SWEBenchScorer()
        report = {"django__django-16379": {
            "resolved": False,
            "patch_successfully_applied": True,
            "tests_status": {},
        }}
        issue = _make_issue(fail_to_pass=[])
        assert scorer._parse_report(report, issue) == 0.0
