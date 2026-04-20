"""Config mutator — reproduction and reflective self-rewrite via SystemLLM."""
from __future__ import annotations

import json
import logging
from typing import Callable

import yaml

from midas_agent.llm.types import LLMRequest, LLMResponse
from midas_agent.stdlib.react_agent import ActionRecord
from midas_agent.workspace.config_evolution.config_schema import (
    ConfigMeta,
    StepConfig,
    WorkflowConfig,
)

logger = logging.getLogger(__name__)

# Constraint limits for evolved prompts
MAX_STEP_PROMPT_CHARS = 2000
MAX_PROMPT_GROWTH = 1.3  # 30 % increase per mutation


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _config_to_yaml(config: WorkflowConfig) -> str:
    """Serialise a WorkflowConfig to readable YAML."""
    data = {
        "meta": {
            "name": config.meta.name,
            "description": config.meta.description,
        },
        "steps": [
            {
                "id": s.id,
                "prompt": s.prompt,
                "tools": s.tools,
                "inputs": s.inputs,
            }
            for s in config.steps
        ],
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _validate_mutation(
    old_config: WorkflowConfig,
    new_config: WorkflowConfig,
) -> bool:
    """Check that a mutation only changed prompts and respects constraints."""
    if len(new_config.steps) != len(old_config.steps):
        return False

    for old_step, new_step in zip(old_config.steps, new_config.steps):
        # Structure must be preserved
        if new_step.id != old_step.id:
            return False
        if new_step.tools != old_step.tools:
            return False
        if new_step.inputs != old_step.inputs:
            return False
        # Prompt constraints
        if not new_step.prompt.strip():
            return False
        if len(new_step.prompt) > MAX_STEP_PROMPT_CHARS:
            return False
        old_len = len(old_step.prompt)
        if old_len >= 50 and len(new_step.prompt) > old_len * MAX_PROMPT_GROWTH:
            return False

    return True


# ------------------------------------------------------------------
# ConfigMutator
# ------------------------------------------------------------------

class ConfigMutator:
    def __init__(
        self,
        system_llm: Callable[[LLMRequest], LLMResponse],
    ) -> None:
        self._system_llm = system_llm

    # ------------------------------------------------------------------
    # Reflective self-rewrite (Option B)
    # ------------------------------------------------------------------

    def reflective_self_rewrite(
        self,
        config: WorkflowConfig,
        action_history: list[ActionRecord],
        score: float,
    ) -> WorkflowConfig:
        """Improve step prompts based on real execution traces.

        Two-pass approach:
          1. Trace → abstract experience summary  (reuses creation summarise prompt)
          2. Config + summary + score → improved config  (reflective mutation prompt)

        Falls back to the original config if any step fails.
        """
        from midas_agent.prompts import (
            CONFIG_CREATION_SUMMARIZE_PROMPT,
            REFLECTIVE_MUTATION_PROMPT,
        )
        from midas_agent.workspace.config_evolution.config_creator import (
            format_trace,
            _extract_yaml,
            _parse_config_yaml,
            _tool_usage_summary,
        )

        if not action_history:
            return config

        # -- Pass 1: trace → abstract summary --
        formatted = format_trace(action_history)
        tool_summary = _tool_usage_summary(action_history)

        summarize_prompt = CONFIG_CREATION_SUMMARIZE_PROMPT.format(
            iteration_count=len(action_history),
            score=score,
            formatted_trace=formatted,
            tool_usage_summary=tool_summary,
        )

        try:
            resp = self._system_llm(
                LLMRequest(messages=[{"role": "user", "content": summarize_prompt}],
                           model="default"),
            )
        except Exception as e:
            logger.warning("Reflective mutation pass 1 failed: %s", e)
            return config

        summary = (resp.content or "").strip()
        if not summary:
            logger.warning("Reflective mutation pass 1 returned empty summary")
            return config

        # -- Pass 2: config + summary + score → improved config --
        config_yaml = _config_to_yaml(config)

        mutate_prompt = REFLECTIVE_MUTATION_PROMPT.format(
            config_yaml=config_yaml,
            summary=summary,
            score=score,
        )

        try:
            resp = self._system_llm(
                LLMRequest(messages=[{"role": "user", "content": mutate_prompt}],
                           model="default"),
            )
        except Exception as e:
            logger.warning("Reflective mutation pass 2 failed: %s", e)
            return config

        raw_yaml = _extract_yaml(resp.content or "")
        if not raw_yaml:
            logger.warning("Reflective mutation pass 2 returned empty response")
            return config

        new_config = _parse_config_yaml(raw_yaml)
        if new_config is None:
            logger.warning("Reflective mutation: failed to parse YAML")
            return config

        # -- Constraint gating --
        if not _validate_mutation(config, new_config):
            logger.warning("Reflective mutation rejected by constraint gate")
            return config

        logger.info("Reflective mutation accepted for '%s'", config.meta.name)
        return new_config

    # ------------------------------------------------------------------
    # Legacy methods (kept for backward compatibility / eviction path)
    # ------------------------------------------------------------------

    def reproduce(
        self,
        base_config: WorkflowConfig,
        summaries: list[str],
    ) -> dict:
        """Create a new config variant based on the base config and episode summaries.

        Calls system_llm to generate a new configuration, then parses the
        response into a dict.  Falls back to a simple dict derived from the
        base config when parsing fails.
        """
        steps_repr = []
        for step in base_config.steps:
            steps_repr.append({
                "id": step.id,
                "prompt": step.prompt,
                "tools": step.tools,
                "inputs": step.inputs,
            })

        prompt = (
            "You are a configuration evolution engine. Given the base workflow "
            "configuration and summaries of past episodes, create a new variant "
            "configuration that improves upon the base.\n\n"
            f"Base config name: {base_config.meta.name}\n"
            f"Base config description: {base_config.meta.description}\n"
            f"Steps: {json.dumps(steps_repr)}\n\n"
            f"Episode summaries:\n"
            + "\n".join(f"- {s}" for s in summaries)
            + "\n\nRespond with a JSON object representing the new configuration."
        )

        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="default",
        )
        response = self._system_llm(request)

        # Try to parse the LLM response as JSON; fall back to a simple dict.
        try:
            result = json.loads(response.content or "{}")
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "meta": {
                "name": base_config.meta.name + "_variant",
                "description": base_config.meta.description,
            },
            "steps": steps_repr,
        }

    def self_rewrite(
        self,
        config: WorkflowConfig,
        summary: str,
    ) -> WorkflowConfig:
        """Legacy self-rewrite (plain LLM, no trace feedback).

        Kept as fallback when no action_history is available.
        """
        steps_repr = []
        for step in config.steps:
            steps_repr.append({
                "id": step.id,
                "prompt": step.prompt,
                "tools": step.tools,
                "inputs": step.inputs,
            })

        prompt = (
            "You are a configuration evolution engine. Given the current workflow "
            "configuration and an episode summary, rewrite the configuration to "
            "improve it.\n\n"
            f"Current config name: {config.meta.name}\n"
            f"Current config description: {config.meta.description}\n"
            f"Steps: {json.dumps(steps_repr)}\n\n"
            f"Episode summary: {summary}\n\n"
            "Respond with a JSON object representing the rewritten configuration."
        )

        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="default",
        )
        response = self._system_llm(request)

        try:
            data = json.loads(response.content or "{}")
            if isinstance(data, dict) and "steps" in data:
                meta_data = data.get("meta", {})
                new_meta = ConfigMeta(
                    name=meta_data.get("name", config.meta.name),
                    description=meta_data.get("description", config.meta.description),
                )
                new_steps = []
                for s in data["steps"]:
                    new_steps.append(StepConfig(
                        id=s.get("id", "step"),
                        prompt=s.get("prompt", ""),
                        tools=s.get("tools", []),
                        inputs=s.get("inputs", []),
                    ))
                return WorkflowConfig(meta=new_meta, steps=new_steps)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        # Fallback: return a copy of the config with an updated description.
        new_meta = ConfigMeta(
            name=config.meta.name,
            description=config.meta.description + " (rewritten)",
        )
        new_steps = [
            StepConfig(
                id=step.id,
                prompt=step.prompt,
                tools=list(step.tools),
                inputs=list(step.inputs),
            )
            for step in config.steps
        ]
        return WorkflowConfig(meta=new_meta, steps=new_steps)
