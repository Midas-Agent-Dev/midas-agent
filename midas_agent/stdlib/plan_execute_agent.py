"""PlanExecuteAgent — Plan then Execute two-phase agent."""
from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

from midas_agent.llm.types import LLMRequest, LLMResponse
from midas_agent.stdlib.action import Action
from midas_agent.stdlib.react_agent import ActionRecord, AgentResult, ReactAgent


class PlanExecuteAgent(ReactAgent):
    def __init__(
        self,
        system_prompt: str,
        actions: list[Action],
        call_llm: Callable[[LLMRequest], LLMResponse],
        max_iterations: int | None = None,
        market_info_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(system_prompt, actions, call_llm, max_iterations)
        self.market_info_provider = market_info_provider

    def run(self, context: str | None = None) -> AgentResult:
        from midas_agent.scheduler.resource_meter import BudgetExhaustedError

        iterations = 0
        action_history: list[ActionRecord] = []
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]

        # Build planning prompt with market info and context
        planning_parts: list[str] = []
        planning_parts.append("Create a plan for the following task.")

        if self.market_info_provider is not None:
            market_info = self.market_info_provider()
            planning_parts.append(f"Market info: {market_info}")

        if context is not None:
            planning_parts.append(f"Task context: {context}")

        messages.append({"role": "user", "content": "\n".join(planning_parts)})

        # Planning phase: call LLM once to get a plan (no tools)
        try:
            plan_request = LLMRequest(messages=messages, model="default")
            plan_response = self.call_llm(plan_request)
        except BudgetExhaustedError:
            logger.info("  Budget exhausted during planning phase")
            return AgentResult(
                output="",
                iterations=iterations,
                termination_reason="budget_exhausted",
                action_history=action_history,
            )

        iterations += 1
        plan_text = plan_response.content or ""
        plan_tokens = plan_response.usage.input_tokens + plan_response.usage.output_tokens
        logger.info("  [Plan] (%d tokens) %s", plan_tokens, plan_text[:2000])

        # Add plan to conversation as assistant response
        messages.append({"role": "assistant", "content": plan_text})

        # Add execution instruction
        messages.append({
            "role": "user",
            "content": "Now execute the plan step by step.",
        })

        # Execution phase: standard ReAct loop
        while True:
            if self.max_iterations is not None and iterations >= self.max_iterations:
                logger.info("  Hit max_iterations (%d). Stopping.", self.max_iterations)
                return AgentResult(
                    output="",
                    iterations=iterations,
                    termination_reason="max_iterations",
                    action_history=action_history,
                )

            try:
                request = LLMRequest(messages=messages, model="default", tools=self._build_tools())
                response = self.call_llm(request)
            except BudgetExhaustedError:
                logger.info("  Budget exhausted at iter %d", iterations + 1)
                return AgentResult(
                    output="",
                    iterations=iterations,
                    termination_reason="budget_exhausted",
                    action_history=action_history,
                )

            iterations += 1
            resp_tokens = response.usage.input_tokens + response.usage.output_tokens

            if response.tool_calls:
                import json as _json
                assistant_msg: dict = {"role": "assistant"}
                if response.content:
                    assistant_msg["content"] = response.content
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments if isinstance(tc.arguments, str) else _json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages.append(assistant_msg)

                for tool_call in response.tool_calls:
                    action = self._actions_by_name[tool_call.name]
                    logger.info(
                        "  [iter %d] %s(%s) (%d tokens)",
                        iterations,
                        tool_call.name,
                        ", ".join(f"{k}={repr(v)[:80]}" for k, v in tool_call.arguments.items()),
                        resp_tokens,
                    )
                    result = action.execute(**tool_call.arguments)
                    logger.info("    → %s", result[:300] if result else "(empty)")

                    record = ActionRecord(
                        action_name=tool_call.name,
                        arguments=tool_call.arguments,
                        result=result,
                        timestamp=time.time(),
                    )
                    action_history.append(record)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

                    if tool_call.name == "task_done":
                        logger.info("  Task done at iter %d", iterations)
                        return AgentResult(
                            output=result,
                            iterations=iterations,
                            termination_reason="done",
                            action_history=action_history,
                        )
            elif response.content:
                logger.info(
                    "  [iter %d] Text response (no tool call, %d tokens): %s",
                    iterations, resp_tokens, response.content[:300],
                )
                return AgentResult(
                    output=response.content,
                    iterations=iterations,
                    termination_reason="done",
                    action_history=action_history,
                )
            else:
                logger.info("  [iter %d] Empty response (no content, no tool calls)", iterations)
                return AgentResult(
                    output="",
                    iterations=iterations,
                    termination_reason="no_action",
                    action_history=action_history,
                )
