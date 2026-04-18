"""Full pipeline integration test: LLM mock → Docker container → real edits → scorer.

This test replays a known-good solution for astropy__astropy-12907 (separability_matrix bug)
through the entire training pipeline with real Docker execution. Only the LLM is mocked —
everything else (container, file I/O, git diff, SWE-bench scorer) is real.

Requires: Docker running, SWE-bench images pulled.
Run with: poetry run pytest tests/integration/test_full_pipeline_docker.py -v -s
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from midas_agent.config import MidasConfig
from midas_agent.docker.container_manager import ContainerManager
from midas_agent.llm.types import LLMRequest, LLMResponse, TokenUsage, ToolCall
from midas_agent.runtime.io_backend import DockerIO
from midas_agent.stdlib.actions.bash import BashAction
from midas_agent.stdlib.actions.search import FindFilesAction, SearchCodeAction
from midas_agent.stdlib.actions.str_replace_editor import StrReplaceEditorAction
from midas_agent.stdlib.actions.task_done import TaskDoneAction
from midas_agent.stdlib.actions.update_plan import UpdatePlanAction
from midas_agent.stdlib.plan_execute_agent import PlanExecuteAgent
from midas_agent.types import Issue


def _make_response(content=None, tool_calls=None):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        usage=TokenUsage(input_tokens=500, output_tokens=200),
    )


# The known-good fix for astropy__astropy-12907:
# In _cstack(), change `cright[-right.shape[0]:, -right.shape[1]:] = 1`
# to `cright[-right.shape[0]:, -right.shape[1]:] = right`
EDIT_OLD_STR = (
    "    if isinstance(right, Model):\n"
    "        cright = _coord_matrix(right, 'right', noutp)\n"
    "    else:\n"
    "        cright = np.zeros((noutp, right.shape[1]))\n"
    "        cright[-right.shape[0]:, -right.shape[1]:] = 1"
)

EDIT_NEW_STR = (
    "    if isinstance(right, Model):\n"
    "        cright = _coord_matrix(right, 'right', noutp)\n"
    "    else:\n"
    "        cright = np.zeros((noutp, right.shape[1]))\n"
    "        cright[-right.shape[0]:, -right.shape[1]:] = right"
)


def make_mock_llm():
    """Create a mock LLM that replays a known-good solution sequence."""
    call_count = {"n": 0}

    responses = [
        # iter 1: find the relevant file
        _make_response(tool_calls=[ToolCall(
            id="c1", name="str_replace_editor",
            arguments={"command": "view", "path": "/testbed/astropy/modeling/separable.py"},
        )]),
        # iter 2: view the _cstack function
        _make_response(tool_calls=[ToolCall(
            id="c2", name="str_replace_editor",
            arguments={"command": "view", "path": "/testbed/astropy/modeling/separable.py",
                       "view_range": [219, 260]},
        )]),
        # iter 3: make the fix
        _make_response(tool_calls=[ToolCall(
            id="c3", name="str_replace_editor",
            arguments={
                "command": "str_replace",
                "path": "/testbed/astropy/modeling/separable.py",
                "old_str": EDIT_OLD_STR,
                "new_str": EDIT_NEW_STR,
            },
        )]),
        # iter 4: verify with pytest
        _make_response(tool_calls=[ToolCall(
            id="c4", name="bash",
            arguments={"command": "cd /testbed && python -m pytest astropy/modeling/tests/test_separable.py -v --tb=short 2>&1 | tail -20"},
        )]),
        # iter 5: task_done
        _make_response(tool_calls=[ToolCall(
            id="c5", name="task_done",
            arguments={},
        )]),
        # iter 6: if test gate rejects, call task_done again (max rounds)
        _make_response(tool_calls=[ToolCall(
            id="c6", name="task_done",
            arguments={},
        )]),
        # iter 7: fallback task_done
        _make_response(tool_calls=[ToolCall(
            id="c7", name="task_done",
            arguments={},
        )]),
    ]

    def mock_llm(request: LLMRequest) -> LLMResponse:
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(responses):
            return responses[idx]
        # Fallback: keep calling task_done
        return _make_response(tool_calls=[ToolCall(
            id=f"c{idx+1}", name="task_done", arguments={},
        )])

    return mock_llm, call_count


@pytest.mark.integration
class TestFullPipelineDocker:
    """End-to-end test: mock LLM → Docker → real edits → scorer."""

    @pytest.fixture
    def issue(self):
        """Load the real astropy-12907 issue from SWE-bench."""
        try:
            from datasets import load_dataset
            ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
            for row in ds:
                if row["instance_id"] == "astropy__astropy-12907":
                    fail_to_pass = row.get("FAIL_TO_PASS", "[]")
                    pass_to_pass = row.get("PASS_TO_PASS", "[]")
                    if isinstance(fail_to_pass, str):
                        fail_to_pass = json.loads(fail_to_pass)
                    if isinstance(pass_to_pass, str):
                        pass_to_pass = json.loads(pass_to_pass)
                    return Issue(
                        issue_id=row["instance_id"],
                        repo=row["repo"],
                        description=row["problem_statement"],
                        base_commit=row.get("base_commit", ""),
                        fail_to_pass=fail_to_pass,
                        pass_to_pass=pass_to_pass,
                    )
        except Exception:
            pytest.skip("Cannot load SWE-bench dataset")
        pytest.skip("astropy__astropy-12907 not found in dataset")

    @pytest.fixture
    def docker_container(self):
        """Start a real SWE-bench Docker container."""
        try:
            cm = ContainerManager()
            # Resolve the correct SWE-bench image
            from swebench.harness.test_spec.test_spec import make_test_spec
            from datasets import load_dataset
            ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
            instance = None
            for row in ds:
                if row["instance_id"] == "astropy__astropy-12907":
                    instance = dict(row)
                    break
            if instance is None:
                pytest.skip("Instance not found")
            spec = make_test_spec(instance, namespace="swebench")
            image = spec.instance_image_key

            cid = cm.start(image=image, host_workspace=None, install_cmd=None)
            yield cid, cm
            cm.stop()
        except Exception as e:
            pytest.skip(f"Docker not available: {e}")

    def test_full_pipeline_resolves_issue(self, issue, docker_container):
        """Mock LLM replays known-good fix → real Docker execution → scorer confirms resolved."""
        cid, cm = docker_container
        mock_llm, call_count = make_mock_llm()

        # Set up IO backend
        docker_io = DockerIO(container_id=cid, workdir="/testbed")

        # Build actions with Docker IO
        cwd = "/testbed"
        actions = [
            BashAction(cwd=cwd, io=docker_io),
            StrReplaceEditorAction(cwd=cwd, io=docker_io),
            SearchCodeAction(cwd=cwd, io=docker_io),
            FindFilesAction(cwd=cwd, io=docker_io),
            UpdatePlanAction(),
            TaskDoneAction(),
        ]

        # Run agent
        agent = PlanExecuteAgent(
            system_prompt="You are a coding agent.",
            actions=actions,
            call_llm=mock_llm,
            max_iterations=20,
        )

        from midas_agent.prompts import TASK_PROMPT_TEMPLATE
        context = TASK_PROMPT_TEMPLATE.format(issue_description=issue.description)
        result = agent.run(context=context)

        # Agent should complete (not budget exhausted)
        assert result.termination_reason == "done", \
            f"Expected 'done', got '{result.termination_reason}'"

        # Should complete in ~5 iterations (view, view_range, edit, pytest, task_done)
        assert call_count["n"] <= 10, \
            f"Expected ≤10 LLM calls, got {call_count['n']}"

        # Generate patch from Docker container
        docker_io.run_bash("git add -A")
        patch = docker_io.run_bash("git diff --cached")
        docker_io.run_bash("git reset")

        # Patch should contain the fix
        assert patch.strip(), "Patch should not be empty"
        assert "= right" in patch, "Patch should contain the fix (= right)"
        assert "= 1" in patch, "Patch should show the old line being removed"

        # Score with real SWE-bench scorer
        from midas_agent.evaluation.swebench_scorer import SWEBenchScorer
        scorer = SWEBenchScorer(timeout=1800, run_id="test_pipeline")
        s_exec = scorer.score(patch, issue)

        assert s_exec == 1.0, \
            f"Expected s_exec=1.0 (resolved), got {s_exec}"

    def test_patch_generation_from_docker(self, issue, docker_container):
        """Verify that edits made via DockerIO produce a valid git diff."""
        cid, cm = docker_container
        docker_io = DockerIO(container_id=cid, workdir="/testbed")

        # Read original file
        content = docker_io.read_file("/testbed/astropy/modeling/separable.py")
        assert "= 1" in content, "Original file should have '= 1'"

        # Apply the fix
        new_content = content.replace(
            "cright[-right.shape[0]:, -right.shape[1]:] = 1",
            "cright[-right.shape[0]:, -right.shape[1]:] = right",
        )
        docker_io.write_file("/testbed/astropy/modeling/separable.py", new_content)

        # Verify the edit persisted
        verify = docker_io.read_file("/testbed/astropy/modeling/separable.py")
        assert "= right" in verify, "Edit should persist in container"
        assert "= 1" not in verify.split("= right")[1] if "= right" in verify else True

        # Generate git diff
        docker_io.run_bash("git add -A")
        patch = docker_io.run_bash("git diff --cached")
        docker_io.run_bash("git reset")

        assert "= right" in patch
        assert patch.startswith("diff --git")

    def test_backslash_content_survives_docker_io(self, issue, docker_container):
        """Verify that backslash-heavy content is not corrupted by DockerIO."""
        cid, cm = docker_container
        docker_io = DockerIO(container_id=cid, workdir="/testbed")

        # Write a file with backslash content
        test_content = (
            'import re\n'
            'PATTERN = re.compile(r"(\\W|\\b|_)")\n'
            'PATH = "C:\\\\Users\\\\test"\n'
            'def func():\n'
            '    return "hello\\nworld"\n'
        )
        docker_io.write_file("/testbed/test_backslash.py", test_content)

        # Read it back
        read_back = docker_io.read_file("/testbed/test_backslash.py")

        assert read_back == test_content, (
            f"Content was corrupted through DockerIO!\n"
            f"Expected:\n{test_content!r}\n"
            f"Got:\n{read_back!r}"
        )

        # Clean up
        docker_io.run_bash("rm /testbed/test_backslash.py")
