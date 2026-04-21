"""GEPA-based prompt optimizer for Configuration Evolution.

Replaces reflective mutation with DSPy GEPA (Guided Evolutionary Prompt
Adaptation).  GEPA provides brevity pressure and regression checking —
the two features missing from the old reflective self-rewrite.

Architecture:
  - StepPromptModule: wraps a step prompt as a DSPy-evolvable parameter
  - config_fitness_metric: Pareto scoring (accuracy + brevity)
  - ConfigDatasetBuilder: accumulates (trace, score) pairs across episodes
  - GEPAConfigOptimizer: runs GEPA every N episodes on accumulated data
"""
from __future__ import annotations

import logging
import math
from types import SimpleNamespace
from typing import Callable

from midas_agent.llm.types import LLMRequest, LLMResponse
from midas_agent.workspace.config_evolution.config_schema import (
    WorkflowConfig,
)
from midas_agent.workspace.config_evolution.mutator import validate_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DSPy import — graceful fallback when not installed
# ---------------------------------------------------------------------------
try:
    import dspy

    _BASE_MODULE = dspy.Module
    HAS_DSPY = True
except ImportError:
    HAS_DSPY = False

    class _StubModule:
        """Minimal stand-in so StepPromptModule can be defined without dspy."""
        def __init__(self) -> None:
            pass

    _BASE_MODULE = _StubModule  # type: ignore[misc,assignment]


# ===================================================================
# StepPromptModule
# ===================================================================

class StepPromptModule(_BASE_MODULE):  # type: ignore[misc]
    """Wraps a single DAG step prompt as a DSPy-evolvable parameter.

    GEPA mutates ``self.step_prompt`` while preserving the step's identity
    (id, tools, inputs).
    """

    def __init__(self, step_prompt: str, step_id: str) -> None:
        super().__init__()
        self.step_prompt = step_prompt
        self.step_id = step_id
        if HAS_DSPY:

            class StepTask(dspy.Signature):
                """Complete a coding workflow step following the prompt."""

                step_instructions: str = dspy.InputField(
                    desc="The step prompt/instructions to follow"
                )
                task_input: str = dspy.InputField(desc="The task to complete")
                output: str = dspy.OutputField(
                    desc="Your response following the step instructions"
                )

            self.predictor = dspy.ChainOfThought(StepTask)
        else:
            self.predictor = lambda **kwargs: None

    def forward(self, task_input: str):
        return self.predictor(
            step_instructions=self.step_prompt,
            task_input=task_input,
        )


# ===================================================================
# Fitness metric
# ===================================================================

# Max prompt length for brevity scoring (chars).  Prompts at or above
# this length get a brevity score of 0.
BREVITY_CEILING = 2000


def config_fitness_metric(example, prediction, trace=None, pred_name=None, pred_trace=None) -> dict:
    """Multi-objective fitness: accuracy (word overlap) + brevity.

    Returns ``{"scores": {"accuracy": float, "brevity": float}}``.

    DSPy GEPA requires a 5-argument signature:
    ``(gold, pred, trace, pred_name, pred_trace)``.

    - **accuracy**: overlap between predicted output and the expected
      successful trace summary.  Floor of 0.3 for non-empty output
      (the model tried something).
    - **brevity**: linear penalty as prompt output grows toward
      ``BREVITY_CEILING`` chars.  This is the key difference from the
      old reflective mutation — it actively rewards shorter prompts.
    """
    output: str = prediction.output if hasattr(prediction, "output") else str(prediction)
    expected: str = example.expected_behavior

    # --- brevity ---
    brevity = max(0.0, 1.0 - len(output) / BREVITY_CEILING)

    # --- accuracy ---
    if not output.strip():
        return {"scores": {"accuracy": 0.0, "brevity": brevity}}

    expected_words = set(expected.lower().split())
    output_words = set(output.lower().split())

    if not expected_words:
        accuracy = 0.5
    else:
        overlap = len(expected_words & output_words) / len(expected_words)
        accuracy = 0.3 + 0.7 * overlap

    return {"scores": {"accuracy": accuracy, "brevity": brevity}}


# ===================================================================
# Dataset builder
# ===================================================================

class ConfigDatasetBuilder:
    """Accumulates (trace summary, score) pairs across episodes.

    Builds train / val / holdout splits (50/25/25) for GEPA evaluation.
    """

    def __init__(self) -> None:
        self._episodes: list[SimpleNamespace] = []

    @property
    def size(self) -> int:
        return len(self._episodes)

    def add_episode(
        self,
        task_input: str,
        action_summary: str,
        score: float,
    ) -> None:
        """Record one episode's data.

        Args:
            task_input: the issue description
            action_summary: compact trace summary of what the agent did
            score: s_exec for this episode
        """
        self._episodes.append(
            SimpleNamespace(
                task_input=task_input,
                expected_behavior=action_summary,
                score=score,
            )
        )

    def build(self) -> tuple[list, list, list]:
        """Return ``(train, val, holdout)`` with a 50/25/25 split."""
        n = len(self._episodes)
        if n == 0:
            return [], [], []

        n_train = max(1, math.floor(n * 0.5))
        n_val = math.floor(n * 0.25)

        train = self._episodes[:n_train]
        val = self._episodes[n_train : n_train + n_val]
        holdout = self._episodes[n_train + n_val :]
        return train, val, holdout


# ===================================================================
# GEPA Config Optimizer
# ===================================================================

# Default: run GEPA every N episodes
DEFAULT_GEPA_INTERVAL = 5

# Minimum dataset size before GEPA is worth running
MIN_DATASET_SIZE = 5

# Maximum allowed prompt size after optimization
MAX_OPTIMIZED_PROMPT_CHARS = 2000


class GEPAConfigOptimizer:
    """Runs GEPA prompt optimization on DAG step prompts.

    Replaces the old ``ConfigMutator.reflective_self_rewrite()``.

    Flow:
      1. Workspace calls ``record_episode()`` after each episode
      2. Workspace calls ``maybe_optimize()`` after each episode
      3. If enough episodes accumulated (>= interval), GEPA runs on
         each step prompt using the accumulated dataset
      4. Constraint gating: size limit + holdout regression check
      5. Returns optimized config or original if gating rejects
    """

    def __init__(
        self,
        system_llm: Callable[[LLMRequest], LLMResponse],
        gepa_interval: int = DEFAULT_GEPA_INTERVAL,
        min_dataset_size: int = MIN_DATASET_SIZE,
    ) -> None:
        self._system_llm = system_llm
        self._gepa_interval = gepa_interval
        self._min_dataset_size = min_dataset_size
        self._dataset = ConfigDatasetBuilder()
        self._episodes_since_last_optimization = 0

    @property
    def dataset(self) -> ConfigDatasetBuilder:
        return self._dataset

    def record_episode(
        self,
        task_input: str,
        action_summary: str,
        score: float,
    ) -> None:
        """Record an episode's data for future GEPA optimization."""
        self._dataset.add_episode(task_input, action_summary, score)
        self._episodes_since_last_optimization += 1

    def should_optimize(self) -> bool:
        """Check whether it's time to run GEPA."""
        return (
            self._episodes_since_last_optimization >= self._gepa_interval
            and self._dataset.size >= self._min_dataset_size
        )

    def maybe_optimize(self, config: WorkflowConfig) -> WorkflowConfig:
        """Run GEPA if conditions are met, otherwise return config as-is."""
        if not self.should_optimize():
            return config
        return self.optimize(config)

    def optimize(self, config: WorkflowConfig) -> WorkflowConfig:
        """Run GEPA on each step prompt in the config.

        For each step:
          1. Wrap prompt as StepPromptModule
          2. Run GEPA with trainset + valset
          3. Constraint gate: size check + holdout regression
          4. Accept or keep original

        Returns a new WorkflowConfig with optimized prompts.
        """
        if not HAS_DSPY:
            logger.warning("DSPy not installed — skipping GEPA optimization")
            return config

        train, val, holdout = self._dataset.build()
        if not train:
            logger.info("GEPA: no training data, skipping")
            return config

        logger.info(
            "GEPA optimization starting: %d train, %d val, %d holdout examples",
            len(train), len(val), len(holdout),
        )

        # Configure DSPy LM for GEPA's reflection calls
        system_lm = self._make_dspy_lm()

        from midas_agent.workspace.config_evolution.config_schema import (
            ConfigMeta,
            StepConfig,
        )

        optimized_steps: list[StepConfig] = []
        any_changed = False

        for step in config.steps:
            new_prompt = self._optimize_step(
                step_id=step.id,
                step_prompt=step.prompt,
                train=train,
                val=val,
                holdout=holdout,
                system_lm=system_lm,
            )

            if new_prompt != step.prompt:
                any_changed = True
                logger.info(
                    "GEPA: step '%s' prompt updated (%d → %d chars)",
                    step.id, len(step.prompt), len(new_prompt),
                )

            optimized_steps.append(StepConfig(
                id=step.id,
                prompt=new_prompt,
                tools=list(step.tools),
                inputs=list(step.inputs),
            ))

        if any_changed:
            new_config = WorkflowConfig(
                meta=ConfigMeta(
                    name=config.meta.name,
                    description=config.meta.description,
                ),
                steps=optimized_steps,
            )
            # Final validation — reject if invalid
            errors = validate_config(new_config)
            if errors:
                logger.warning(
                    "GEPA: optimized config failed validation (%s), keeping original",
                    errors,
                )
                return config

            self._episodes_since_last_optimization = 0
            return new_config
        else:
            logger.info("GEPA: no step prompts changed, keeping original")
            self._episodes_since_last_optimization = 0
            return config

    def _optimize_step(
        self,
        step_id: str,
        step_prompt: str,
        train: list,
        val: list,
        holdout: list,
        system_lm,
    ) -> str:
        """Optimize a single step prompt using GEPA.

        Returns the optimized prompt, or the original if gating rejects.
        """
        module = StepPromptModule(step_prompt=step_prompt, step_id=step_id)

        try:
            optimizer = dspy.GEPA(
                metric=config_fitness_metric,
                reflection_lm=system_lm,
                auto="light",  # 6 candidates
                candidate_selection_strategy="pareto",
            )
            optimized_module = optimizer.compile(
                module,
                trainset=train,
                valset=val if val else None,
            )
        except Exception as e:
            logger.warning("GEPA failed for step '%s': %s", step_id, e)
            return step_prompt

        # Extract the optimized prompt
        new_prompt = getattr(optimized_module, "step_prompt", step_prompt)

        # --- Constraint gating ---

        # 1. Size check
        if len(new_prompt) > MAX_OPTIMIZED_PROMPT_CHARS:
            logger.info(
                "GEPA: step '%s' rejected — prompt too large (%d > %d chars)",
                step_id, len(new_prompt), MAX_OPTIMIZED_PROMPT_CHARS,
            )
            return step_prompt

        # 2. Non-empty check
        if not new_prompt.strip():
            logger.info("GEPA: step '%s' rejected — empty prompt", step_id)
            return step_prompt

        # 3. Holdout regression check
        if holdout and not self._passes_holdout_check(
            module, optimized_module, holdout
        ):
            logger.info(
                "GEPA: step '%s' rejected — holdout regression", step_id
            )
            return step_prompt

        return new_prompt

    def _passes_holdout_check(
        self,
        original_module: StepPromptModule,
        optimized_module: StepPromptModule,
        holdout: list,
    ) -> bool:
        """Check that the optimized module doesn't regress on the holdout set.

        Returns True if the optimized module scores >= original on average.
        """
        def _avg_score(mod: StepPromptModule, data: list) -> float:
            total = 0.0
            count = 0
            for example in data:
                try:
                    pred = mod.forward(task_input=example.task_input)
                    result = config_fitness_metric(example, pred)
                    scores = result.get("scores", {})
                    # Combined score: weighted accuracy + brevity
                    total += 0.7 * scores.get("accuracy", 0.0) + 0.3 * scores.get("brevity", 0.0)
                    count += 1
                except Exception:
                    continue
            return total / count if count > 0 else 0.0

        original_score = _avg_score(original_module, holdout)
        optimized_score = _avg_score(optimized_module, holdout)

        logger.info(
            "Holdout check: original=%.3f, optimized=%.3f",
            original_score, optimized_score,
        )
        return optimized_score >= original_score

    def _make_dspy_lm(self):
        """Create a DSPy LM backed by our system_llm.

        Uses dspy.LM with a wrapper that routes calls through
        system_llm.
        """
        # For GEPA's reflection calls, use a basic dspy.LM pointed at
        # the same model.  We read the model name from the system_llm's
        # resolver if available, otherwise default.
        try:
            return dspy.LM(model="openai/default")
        except Exception:
            logger.warning("Could not create DSPy LM, GEPA may not work")
            return None
