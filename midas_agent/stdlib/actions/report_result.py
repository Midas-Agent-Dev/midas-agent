"""ReportResult action — hired agent reports back (Graph Emergence only)."""
from __future__ import annotations

from typing import Callable

from midas_agent.stdlib.action import Action


class ReportResultAction(Action):
    def __init__(self, report: Callable) -> None:
        self._report = report

    @property
    def name(self) -> str:
        return "task_done"

    @property
    def description(self) -> str:
        return (
            "Signals that your task is complete and submits your findings.\n\n"
            "Usage:\n"
            " - Call this exactly once when your assigned task is complete.\n"
            " - Write a clear, actionable summary: what you found, what "
            "files are relevant, what the root cause is, and what fix you "
            "recommend.\n"
            " - Include specific file paths and line numbers when "
            "referencing code.\n"
            " - After calling this, your session ends. No further actions "
            "will be executed.\n\n"
            "IMPORTANT: Do not just say 'done' or 'task complete'. Provide "
            "enough detail so that your findings can be acted on without "
            "having to redo your work."
        )

    @property
    def parameters(self) -> dict:
        return {
            "result": {"type": "string", "required": True, "description": "Clear, actionable summary of your findings. Include file paths and line numbers."},
        }

    def execute(self, **kwargs) -> str:
        result = kwargs.get("result") or kwargs.get("summary") or str(kwargs) or "(no result provided)"
        self._report(result)
        return "Result reported."
