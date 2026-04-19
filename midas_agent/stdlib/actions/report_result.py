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
            "Signals that your task is complete and submits your findings. "
            "Provide a clear summary of what you found or did, including "
            "file paths and line numbers. After calling this, your session ends."
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
