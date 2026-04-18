"""Integration tests for the test gate in agent loops."""
import pytest

from midas_agent.evaluation.test_runner import TestResult, TEST_GATE_CONTINUE
from midas_agent.llm.types import LLMRequest, LLMResponse, TokenUsage, ToolCall
from midas_agent.stdlib.actions.bash import BashAction
from midas_agent.stdlib.actions.task_done import TaskDoneAction
from midas_agent.stdlib.plan_execute_agent import PlanExecuteAgent
from midas_agent.stdlib.react_agent import AgentResult, ReactAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_scripted_llm(responses: list[LLMResponse]):
    """Create a scripted LLM callback."""
    idx = {"i": 0}

    def call_llm(req: LLMRequest) -> LLMResponse:
        i = idx["i"]
        idx["i"] += 1
        return responses[i] if i < len(responses) else responses[-1]

    return call_llm


# ---------------------------------------------------------------------------
# ReactAgent integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTaskDoneGateReactAgent:
    """Integration tests for test gate with ReactAgent."""

    def test_one_hit_pass(self):
        """Agent calls task_done, tests pass, agent terminates."""
        runner = _MockTestRunner([
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        task_done = TaskDoneAction(test_runner=runner)

        llm = _make_scripted_llm([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = ReactAgent(
            system_prompt="test",
            actions=[task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert "All tests passed" in result.output
        assert runner.call_count == 1

    def test_fail_then_fix_then_pass(self):
        """Agent calls task_done, tests fail, agent fixes, calls task_done again, tests pass."""
        runner = _MockTestRunner([
            TestResult(all_passed=False, passed=3, total=5, failure_output="FAILED test_x"),
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        task_done = TaskDoneAction(test_runner=runner)

        llm = _make_scripted_llm([
            # 1st: call task_done (tests fail)
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
            # 2nd: agent "fixes" something (simulated as bash)
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c2", name="bash", arguments={"command": "echo fix"})],
                usage=TokenUsage(10, 5),
            ),
            # 3rd: call task_done again (tests pass)
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c3", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = ReactAgent(
            system_prompt="test",
            actions=[BashAction(), task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert "All tests passed" in result.output
        assert runner.call_count == 2

        # Verify task_done was called twice in action history
        task_done_calls = [
            r for r in result.action_history if r.action_name == "task_done"
        ]
        assert len(task_done_calls) == 2

    def test_max_retries_terminates(self):
        """After max_review_rounds failures, agent terminates."""
        fail_result = TestResult(
            all_passed=False, passed=0, total=5, failure_output="err",
        )
        runner = _MockTestRunner([fail_result] * 5)
        task_done = TaskDoneAction(test_runner=runner, max_review_rounds=2)

        llm = _make_scripted_llm([
            # 1st task_done — fail
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
            # 2nd task_done — fail again, max reached
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c2", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = ReactAgent(
            system_prompt="test",
            actions=[task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert "Max review rounds" in result.output

    def test_budget_exhaustion_terminates(self):
        """If budget exhausts after test failure, agent terminates with budget_exhausted."""
        from midas_agent.scheduler.resource_meter import BudgetExhaustedError

        runner = _MockTestRunner([
            TestResult(all_passed=False, passed=3, total=5, failure_output="err"),
        ])
        task_done = TaskDoneAction(test_runner=runner)

        call_count = 0

        def llm_exhaust(req: LLMRequest) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                    usage=TokenUsage(10, 5),
                )
            # Budget exhausted on second call
            raise BudgetExhaustedError("No budget")

        agent = ReactAgent(
            system_prompt="test",
            actions=[task_done],
            call_llm=llm_exhaust,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "budget_exhausted"

    def test_production_mode_no_runner(self):
        """Without a test_runner (production mode), task_done terminates immediately."""
        task_done = TaskDoneAction()

        llm = _make_scripted_llm([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={"summary": "All fixed"})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = ReactAgent(
            system_prompt="test",
            actions=[task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert result.iterations == 1


# ---------------------------------------------------------------------------
# PlanExecuteAgent integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTaskDoneGatePlanExecuteAgent:
    """Integration tests for test gate with PlanExecuteAgent."""

    def test_plan_execute_one_hit_pass(self):
        """PlanExecuteAgent: plan -> task_done with passing tests -> terminate."""
        runner = _MockTestRunner([
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        task_done = TaskDoneAction(test_runner=runner)

        llm = _make_scripted_llm([
            # Plan response
            LLMResponse(
                content="Plan: fix the bug.",
                tool_calls=None,
                usage=TokenUsage(10, 5),
            ),
            # Execute: call task_done
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = PlanExecuteAgent(
            system_prompt="test",
            actions=[task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert "All tests passed" in result.output

    def test_plan_execute_fail_then_pass(self):
        """PlanExecuteAgent: plan -> task_done (fail) -> fix -> task_done (pass)."""
        runner = _MockTestRunner([
            TestResult(all_passed=False, passed=3, total=5, failure_output="FAILED"),
            TestResult(all_passed=True, passed=5, total=5, failure_output=""),
        ])
        task_done = TaskDoneAction(test_runner=runner)

        llm = _make_scripted_llm([
            # Plan
            LLMResponse(
                content="Plan: fix the bug.",
                tool_calls=None,
                usage=TokenUsage(10, 5),
            ),
            # First task_done — fails
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
            # Fix step
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c2", name="bash", arguments={"command": "echo fix"})],
                usage=TokenUsage(10, 5),
            ),
            # Second task_done — passes
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c3", name="task_done", arguments={})],
                usage=TokenUsage(10, 5),
            ),
        ])

        agent = PlanExecuteAgent(
            system_prompt="test",
            actions=[BashAction(), task_done],
            call_llm=llm,
            max_iterations=10,
        )
        result = agent.run()
        assert result.termination_reason == "done"
        assert "All tests passed" in result.output
        assert runner.call_count == 2
