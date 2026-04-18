"""TaskDone action — signal task completion with optional test gate."""
from __future__ import annotations

from midas_agent.stdlib.action import Action

DONE_SENTINEL = "<<TASK_DONE_CONFIRMED>>"


class TaskDoneAction(Action):
    """Signals task completion, optionally running tests first.

    When *test_runner* is provided (training mode), the test gate runs
    FAIL_TO_PASS and PASS_TO_PASS tests before confirming submission.
    If tests fail, the return value starts with the ``TEST_GATE_CONTINUE``
    sentinel so the agent loop knows NOT to terminate — giving the agent
    a chance to fix the issue.

    After *max_review_rounds* consecutive failures, the patch is submitted
    anyway to avoid infinite loops.

    When *test_runner* is ``None`` (production / inference mode), task_done
    confirms immediately — preserving backward compatibility.
    """

    def __init__(
        self,
        test_runner=None,
        max_review_rounds: int = 2,
    ) -> None:
        self._test_runner = test_runner
        self._max_review_rounds = max_review_rounds
        self._review_count = 0

    @property
    def name(self) -> str:
        return "task_done"

    @property
    def description(self) -> str:
        return (
            "Signals that the current task is complete and submits your changes "
            "for evaluation. Make sure you have edited source files and verified "
            "your fix before calling this."
        )

    @property
    def parameters(self) -> dict:
        return {}

    def execute(self, **kwargs) -> str:
        from midas_agent.evaluation.test_runner import TEST_GATE_CONTINUE

        # Production mode — no test runner, confirm immediately
        if self._test_runner is None:
            return DONE_SENTINEL + " " + kwargs.get("summary", "Task completed.")

        # Training mode — run tests
        self._review_count += 1
        result = self._test_runner()

        if result.all_passed:
            return DONE_SENTINEL + " All tests passed. Task completed."

        if self._review_count >= self._max_review_rounds:
            return DONE_SENTINEL + " Max review rounds reached. Submitting current patch."

        # Tests failed — return feedback so agent can fix
        return (
            f"{TEST_GATE_CONTINUE} ({result.passed}/{result.total} passed). "
            f"Fix the issues and call task_done again.\n\n"
            f"Failures:\n{result.failure_output}"
        )
