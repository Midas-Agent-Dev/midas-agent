"""SWE-bench execution scorer — real Docker-based evaluation via swebench."""
from __future__ import annotations

import json
import logging
import tempfile

from midas_agent.evaluation.execution_scorer import ExecutionScorer
from midas_agent.types import Issue

logger = logging.getLogger(__name__)


class SWEBenchScorer(ExecutionScorer):
    """Evaluates patches using the official SWE-bench harness (Docker).

    Requires: Docker installed, ``pip install swebench``.
    """

    def __init__(self, timeout: int = 1800) -> None:
        super().__init__(docker_image="", timeout=timeout)
        self._timeout = timeout

    def score(self, patch: str, issue: Issue) -> float:
        """Apply patch in a SWE-bench Docker container and run tests.

        Returns S_exec: FAIL_TO_PASS pass rate. Returns 0.0 on regression
        (any PASS_TO_PASS test fails) or if patch fails to apply.
        """
        if not patch or not patch.strip():
            return 0.0

        try:
            from swebench.harness.run_evaluation import run_instance
            from swebench.harness.test_spec import make_test_spec
        except ImportError:
            logger.warning(
                "swebench not installed, falling back to stub scorer"
            )
            return super().score(patch, issue)

        # Build prediction dict in the format swebench expects.
        prediction = {
            "instance_id": issue.issue_id,
            "model_patch": patch,
            "model_name_or_path": "midas-agent",
        }

        try:
            # Get the test spec for this instance from the dataset.
            from datasets import load_dataset

            ds = load_dataset(
                "princeton-nlp/SWE-bench_Verified",
                split="test",
            )
            instance = None
            for row in ds:
                if row["instance_id"] == issue.issue_id:
                    instance = dict(row)
                    break

            if instance is None:
                logger.error("Instance %s not found in SWE-bench", issue.issue_id)
                return 0.0

            test_spec = make_test_spec(instance)
            result = run_instance(test_spec, prediction, timeout=self._timeout)

            return self._parse_result(result, issue)

        except Exception as e:
            logger.error("SWE-bench evaluation failed for %s: %s", issue.issue_id, e)
            return 0.0

    def _parse_result(self, result: dict, issue: Issue) -> float:
        """Parse swebench run_instance result into S_exec score."""
        # result contains test outcomes keyed by status.
        resolved = result.get("resolved", False)
        if resolved:
            return 1.0

        # Check for partial FAIL_TO_PASS success.
        test_results = result.get("tests_status", {})
        fail_to_pass = issue.fail_to_pass
        pass_to_pass = issue.pass_to_pass

        if not fail_to_pass:
            return 0.0

        # Any PASS_TO_PASS regression → 0.0
        for test in pass_to_pass:
            status = test_results.get(test, "PASSED")
            if status == "FAILED":
                return 0.0

        # Count FAIL_TO_PASS that now pass.
        passed = sum(
            1 for test in fail_to_pass
            if test_results.get(test, "FAILED") == "PASSED"
        )
        return passed / len(fail_to_pass)
