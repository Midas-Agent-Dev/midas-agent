"""Unit tests for TaskDoneAction with test gate."""
import pytest

from midas_agent.evaluation.test_runner import TestResult, TEST_GATE_CONTINUE
from midas_agent.stdlib.actions.task_done import TaskDoneAction


class _MockTestRunner:
    """Mock test runner with configurable results per call."""

    def __init__(self, results: list[TestResult]):
        self._results = results
        self._call_index = 0

    def __call__(self) -> TestResult:
        idx = self._call_index
        self._call_index += 1
        return self._results[idx] if idx < len(self._results) else self._results[-1]

    @property
    def call_count(self) -> int:
        return self._call_index


@pytest.mark.unit
class TestTaskDoneGate:
    """Tests for TaskDoneAction with the test gate feature."""

    def test_no_test_runner_immediate_completion(self):
        """Without a test_runner, task_done returns immediately."""
        action = TaskDoneAction()
        result = action.execute(summary="Done")
        assert "Task completed" in result or "Done" in result
        # Should NOT start with the continue sentinel
        assert not result.startswith(TEST_GATE_CONTINUE)

    def test_all_tests_pass_completion(self):
        """When all tests pass, task_done confirms completion."""
        runner = _MockTestRunner([
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        action = TaskDoneAction(test_runner=runner)
        result = action.execute()
        assert "All tests passed" in result
        assert not result.startswith(TEST_GATE_CONTINUE)

    def test_tests_fail_returns_feedback(self):
        """When tests fail, result starts with TEST_GATE_CONTINUE sentinel."""
        runner = _MockTestRunner([
            TestResult(
                all_passed=False, passed=3, total=5,
                failure_output="FAILED test_foo.py::test_bar",
            ),
        ])
        action = TaskDoneAction(test_runner=runner)
        result = action.execute()
        assert result.startswith(TEST_GATE_CONTINUE)
        assert "3/5" in result
        assert "FAILED test_foo.py::test_bar" in result

    def test_fail_then_pass_on_retry(self):
        """First call returns failure, second call (after fix) returns pass."""
        runner = _MockTestRunner([
            TestResult(all_passed=False, passed=3, total=5, failure_output="err"),
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        action = TaskDoneAction(test_runner=runner)

        # First call — failure
        result1 = action.execute()
        assert result1.startswith(TEST_GATE_CONTINUE)

        # Second call — pass
        result2 = action.execute()
        assert "All tests passed" in result2
        assert not result2.startswith(TEST_GATE_CONTINUE)

    def test_max_review_rounds_forced_completion(self):
        """After max_review_rounds failures, submits anyway."""
        fail_result = TestResult(
            all_passed=False, passed=0, total=5, failure_output="err",
        )
        runner = _MockTestRunner([fail_result, fail_result, fail_result])
        action = TaskDoneAction(test_runner=runner, max_review_rounds=2)

        # First failure — continue
        result1 = action.execute()
        assert result1.startswith(TEST_GATE_CONTINUE)

        # Second failure — max reached, forced completion
        result2 = action.execute()
        assert "Max review rounds" in result2
        assert not result2.startswith(TEST_GATE_CONTINUE)

    def test_review_count_tracks_correctly(self):
        """Review count increments with each call to execute."""
        fail_result = TestResult(
            all_passed=False, passed=0, total=5, failure_output="err",
        )
        runner = _MockTestRunner([fail_result] * 5)
        action = TaskDoneAction(test_runner=runner, max_review_rounds=3)

        action.execute()
        assert action._review_count == 1
        action.execute()
        assert action._review_count == 2
        action.execute()  # max reached
        assert action._review_count == 3

    def test_custom_max_review_rounds(self):
        """Custom max_review_rounds is respected."""
        fail_result = TestResult(
            all_passed=False, passed=0, total=5, failure_output="err",
        )
        runner = _MockTestRunner([fail_result] * 10)
        action = TaskDoneAction(test_runner=runner, max_review_rounds=5)

        for _ in range(4):
            result = action.execute()
            assert result.startswith(TEST_GATE_CONTINUE)

        # 5th call — forced completion
        result = action.execute()
        assert "Max review rounds" in result
        assert not result.startswith(TEST_GATE_CONTINUE)
