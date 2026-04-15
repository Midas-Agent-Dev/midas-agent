"""TaskDone action — signal task completion."""
from midas_agent.stdlib.action import Action


class TaskDoneAction(Action):
    @property
    def name(self) -> str:
        return "task_done"

    @property
    def description(self) -> str:
        return (
            "Signals that the current task is complete. Call this when you "
            "have finished making changes to resolve the issue.\n\n"
            "After calling this tool, no further actions will be executed "
            "and your workspace is submitted for evaluation.\n\n"
            "# Before calling task_done, verify:\n"
            " - You have edited the actual source files (not just written "
            "analysis scripts). Your score is based on whether the "
            "repository's tests pass, which requires changes to the source.\n"
            " - You have run the relevant tests with `bash` to confirm your "
            "fix works.\n"
            " - You have not introduced regressions (existing tests still "
            "pass).\n\n"
            "If you run out of budget without calling this, your workspace "
            "is evaluated as-is — partial fixes still receive partial credit, "
            "but no edit at all scores zero.\n\n"
            "IMPORTANT: Do not call this prematurely. A premature task_done "
            "with no source edits guarantees a score of 0. It is better to "
            "use your remaining budget to attempt a fix than to give up early."
        )

    @property
    def parameters(self) -> dict:
        return {}

    def execute(self, **kwargs) -> str:
        return kwargs.get("summary", "Task completed.")
