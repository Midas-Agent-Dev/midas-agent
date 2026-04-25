"""Failure analyzer — extracts abstract failure reasons from failed traces."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from midas_agent.llm.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

FAILURE_ANALYSIS_PROMPT = """\
You are analyzing a failed coding agent trace. The agent attempted to fix \
a GitHub issue but the gold-standard test failed (score=0).

## Issue summary
{issue_summary}

## Agent trace (condensed)
{trace}

<<<<<<< HEAD
=======
## What the agent actually changed (str_replace edits)
{patch_summary}

## Gold test that failed
{gold_test_info}

## Gold test output (what the test actually checked)
{test_output}

>>>>>>> 860a91e (Wire gold test output into failure analyzer)
## Task
1. Which step went wrong? Choose from: {step_ids}
2. What is the ABSTRACT lesson? Do NOT include issue-specific details \
(no file names, function names, variable names). The lesson must be \
general enough to help on OTHER issues.

## Format
Respond in exactly this format:
STEP: <step_id>
LESSON: <one sentence abstract lesson>

Example:
STEP: fix
LESSON: When the issue describes a misleading error message, fix the \
message text, not the underlying condition logic.\
"""


@dataclass
class FailureAnalysis:
    step_id: str
    lesson: str


class FailureAnalyzer:
    """Extract abstract failure reasons from failed agent traces."""

    def __init__(
        self,
        system_llm: Callable[[LLMRequest], LLMResponse],
    ) -> None:
        self._system_llm = system_llm

    def analyze(
        self,
        issue_summary: str,
        trace: str,
        step_ids: list[str],
<<<<<<< HEAD
=======
        gold_test_names: list[str] | None = None,
        patch: str | None = None,
        test_output: str | None = None,
>>>>>>> 860a91e (Wire gold test output into failure analyzer)
    ) -> FailureAnalysis | None:
        """Analyze a failed trace and return the step that failed + abstract lesson.

        Args:
            issue_summary: brief description of the issue (first 200 chars)
            trace: condensed execution trace
            step_ids: list of step IDs in the DAG config
<<<<<<< HEAD

        Returns:
            FailureAnalysis or None if analysis fails
        """
        prompt = FAILURE_ANALYSIS_PROMPT.format(
            issue_summary=issue_summary[:500],
            trace=trace[:3000],
=======
            gold_test_names: FAIL_TO_PASS test names from SWE-bench
            patch: the agent's actual git diff (if available)
            test_output: SWE-bench test output showing what failed and why
        """
        rich_trace = _build_rich_trace(trace)
        patch_summary = _extract_patch_summary(trace)

        # Build gold test info
        if gold_test_names:
            gold_test_info = "Tests that must pass: " + ", ".join(gold_test_names)
        else:
            gold_test_info = "(gold test names not available)"

        if patch:
            gold_test_info += f"\n\nAgent's patch:\n{patch[:2000]}"

        # Gold test output — shows exactly what the test asserted and why it failed
        test_output_section = test_output[:3000] if test_output else "(test output not available)"

        prompt = FAILURE_ANALYSIS_PROMPT.format(
            issue_summary=issue_summary[:1000],
            trace=rich_trace,
            patch_summary=patch_summary,
            gold_test_info=gold_test_info,
            test_output=test_output_section,
>>>>>>> 860a91e (Wire gold test output into failure analyzer)
            step_ids=", ".join(step_ids),
        )

        try:
            resp = self._system_llm(
                LLMRequest(messages=[{"role": "user", "content": prompt}], model="default"),
            )
            return self._parse_response(resp.content or "", step_ids)
        except Exception as e:
            logger.warning("Failure analysis failed: %s", e)
            return None

    @staticmethod
    def _parse_response(text: str, step_ids: list[str]) -> FailureAnalysis | None:
        step_id = ""
        lesson = ""

        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("STEP:"):
                step_id = line[5:].strip().lower()
            elif line.upper().startswith("LESSON:"):
                lesson = line[7:].strip()

        if not step_id or not lesson:
            return None

        # Match to closest valid step_id
        if step_id not in step_ids:
            for sid in step_ids:
                if step_id in sid or sid in step_id:
                    step_id = sid
                    break
            else:
                step_id = step_ids[-1]  # default to last step (usually fix/validate)

        return FailureAnalysis(step_id=step_id, lesson=lesson)
