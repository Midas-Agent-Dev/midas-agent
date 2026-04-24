"""Config reflector — proposes improved DAG configs from execution traces.

Replaces the DSPy per-step GEPA with whole-config reflection that sees
both success and failure traces with real execution outcomes.
"""
from __future__ import annotations

import logging
from typing import Callable

from midas_agent.llm.types import LLMRequest, LLMResponse
from midas_agent.workspace.config_evolution.config_schema import WorkflowConfig
from midas_agent.workspace.config_evolution.config_creator import _extract_yaml, _parse_config_yaml
from midas_agent.workspace.config_evolution.mutator import validate_config, _config_to_yaml

logger = logging.getLogger(__name__)

MAX_REFLECT_RETRIES = 2

REFLECT_PROMPT = """\
You are a prompt optimizer for a coding agent's DAG workflow.

The agent uses a multi-step DAG config to solve GitHub issues. Each step \
has a prompt that guides the agent's behavior. Your job is to improve \
the step prompts based on real execution results.

## Current DAG config

```yaml
{config_yaml}
```

## Recent execution results

{traces_section}

## Task

Analyze the failures and propose an improved DAG config. Focus on:
- What patterns caused failures? (wrong file edited, wrong fix type, etc.)
- What did successful runs do differently?
- How can the step prompts be rewritten to avoid these failure patterns?

Rules:
- Keep the SAME step IDs, tools, inputs, and goals — only change prompts
- Keep prompts concise (under 500 words per step)
- Make lessons GENERAL, not issue-specific
- If the current config is already good, return it unchanged

Output the COMPLETE YAML inside ```yaml fences.\
"""


def _format_traces_section(traces: list[dict]) -> str:
    """Format traces into a readable section for the reflection prompt."""
    lines = []
    for i, t in enumerate(traces):
        status = "PASS" if t["score"] >= 1.0 else "FAIL"
        lines.append(f"### Attempt {i+1}: {status} (score={t['score']:.1f})")
        lines.append(f"Issue: {t['issue_summary'][:200]}")
        if t.get("failure_reason"):
            lines.append(f"Failure reason: {t['failure_reason']}")
        lines.append(f"Trace: {t['trace_summary'][:500]}")
        lines.append("")
    return "\n".join(lines)


class ConfigReflector:
    """Propose improved DAG configs by reflecting on execution traces.

    Unlike the DSPy per-step GEPA, this operates on the whole config
    and uses real execution outcomes (pass/fail) as the signal.
    """

    def __init__(
        self,
        system_llm: Callable[[LLMRequest], LLMResponse],
    ) -> None:
        self._system_llm = system_llm

    def reflect(
        self,
        config: WorkflowConfig,
        traces: list[dict],
    ) -> WorkflowConfig | None:
        """Propose an improved config based on execution traces.

        Args:
            config: current DAG config
            traces: list of dicts with keys:
                - issue_summary: str
                - trace_summary: str
                - score: float (0.0 or 1.0)
                - failure_reason: str | None

        Returns:
            New config with improved prompts, or None if reflection fails.
        """
        config_yaml = _config_to_yaml(config)
        traces_section = _format_traces_section(traces)

        prompt = REFLECT_PROMPT.format(
            config_yaml=config_yaml,
            traces_section=traces_section,
        )

        messages = [{"role": "user", "content": prompt}]

        for attempt in range(1 + MAX_REFLECT_RETRIES):
            try:
                resp = self._system_llm(
                    LLMRequest(messages=messages, model="default"),
                )
            except Exception as e:
                logger.warning("Config reflection failed: %s", e)
                return None

            raw_yaml = _extract_yaml(resp.content or "")
            if not raw_yaml:
                messages.append({"role": "assistant", "content": resp.content or ""})
                messages.append({"role": "user", "content": "Output the YAML inside ```yaml fences."})
                continue

            new_config = _parse_config_yaml(raw_yaml)
            if new_config is None:
                messages.append({"role": "assistant", "content": resp.content or ""})
                messages.append({"role": "user", "content": "YAML failed to parse. Please fix."})
                continue

            # Repair structure: keep base IDs/tools/inputs, only take new prompts
            from midas_agent.workspace.config_evolution.config_schema import StepConfig
            repaired_steps = []
            for i, base_step in enumerate(config.steps):
                new_prompt = new_config.steps[i].prompt if i < len(new_config.steps) else base_step.prompt
                repaired_steps.append(StepConfig(
                    id=base_step.id,
                    prompt=new_prompt,
                    tools=base_step.tools,
                    inputs=base_step.inputs,
                    goal=base_step.goal,
                ))

            repaired = WorkflowConfig(meta=config.meta, steps=repaired_steps)

            # Check prompts actually changed
            any_changed = any(
                b.prompt != r.prompt
                for b, r in zip(config.steps, repaired.steps)
            )

            if any_changed:
                logger.info(
                    "Config reflection: %d/%d step prompts changed (attempt %d)",
                    sum(1 for b, r in zip(config.steps, repaired.steps) if b.prompt != r.prompt),
                    len(config.steps),
                    attempt + 1,
                )
                return repaired
            else:
                logger.info("Config reflection: no changes proposed (config already good)")
                return None

        logger.warning("Config reflection: exhausted retries")
        return None
