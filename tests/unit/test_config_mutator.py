"""Unit tests for config mutation utilities and GEPAConfigOptimizer."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from midas_agent.llm.types import LLMRequest, LLMResponse, TokenUsage
from midas_agent.workspace.config_evolution.config_schema import (
    ConfigMeta,
    StepConfig,
    WorkflowConfig,
)
from midas_agent.workspace.config_evolution.mutator import (
    _config_to_yaml,
    _validate_mutation,
    validate_config,
)
from midas_agent.workspace.config_evolution.prompt_optimizer import (
    ConfigDatasetBuilder,
    GEPAConfigOptimizer,
    StepPromptModule,
    config_fitness_metric,
)


def _make_config(*steps: StepConfig, name: str = "test") -> WorkflowConfig:
    return WorkflowConfig(
        meta=ConfigMeta(name=name, description="test"),
        steps=list(steps),
    )


def _make_system_llm():
    return MagicMock(
        return_value=LLMResponse(
            content="ok",
            tool_calls=None,
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
    )


# ===========================================================================
# validate_config
# ===========================================================================


@pytest.mark.unit
class TestValidateConfig:
    def test_valid_single_step(self):
        config = _make_config(StepConfig(id="s1", prompt="Do.", tools=["bash"]))
        assert validate_config(config) == []

    def test_empty_steps(self):
        config = _make_config()
        errors = validate_config(config)
        assert any("at least one step" in e for e in errors)

    def test_duplicate_ids(self):
        config = _make_config(
            StepConfig(id="s1", prompt="A.", tools=["bash"]),
            StepConfig(id="s1", prompt="B.", tools=["bash"]),
        )
        errors = validate_config(config)
        assert any("Duplicate" in e for e in errors)


# ===========================================================================
# _validate_mutation
# ===========================================================================


@pytest.mark.unit
class TestValidateMutation:
    def test_accepts_prompt_only_change(self):
        old = _make_config(StepConfig(id="s1", prompt="Find bug.", tools=["bash"]))
        new = _make_config(StepConfig(id="s1", prompt="Search for the bug.", tools=["bash"]))
        assert _validate_mutation(old, new)

    def test_rejects_changed_step_ids(self):
        old = _make_config(StepConfig(id="s1", prompt="A.", tools=["bash"]))
        new = _make_config(StepConfig(id="s2", prompt="A.", tools=["bash"]))
        assert not _validate_mutation(old, new)

    def test_rejects_changed_tools(self):
        old = _make_config(StepConfig(id="s1", prompt="A.", tools=["bash"]))
        new = _make_config(StepConfig(id="s1", prompt="A.", tools=["bash", "str_replace_editor"]))
        assert not _validate_mutation(old, new)

    def test_rejects_empty_prompt(self):
        old = _make_config(StepConfig(id="s1", prompt="A.", tools=["bash"]))
        new = _make_config(StepConfig(id="s1", prompt="   ", tools=["bash"]))
        assert not _validate_mutation(old, new)

    def test_rejects_excessive_growth(self):
        old = _make_config(StepConfig(id="s1", prompt="A" * 100, tools=["bash"]))
        new = _make_config(StepConfig(id="s1", prompt="B" * 200, tools=["bash"]))
        assert not _validate_mutation(old, new)

    def test_rejects_different_step_count(self):
        old = _make_config(
            StepConfig(id="s1", prompt="A.", tools=["bash"]),
            StepConfig(id="s2", prompt="B.", tools=["bash"], inputs=["s1"]),
        )
        new = _make_config(StepConfig(id="s1", prompt="A.", tools=["bash"]))
        assert not _validate_mutation(old, new)


# ===========================================================================
# StepPromptModule
# ===========================================================================


@pytest.mark.unit
class TestStepPromptModule:
    def test_construction(self):
        mod = StepPromptModule(step_prompt="Find the bug.", step_id="locate")
        assert mod.step_prompt == "Find the bug."
        assert mod.step_id == "locate"

    def test_has_predictor(self):
        mod = StepPromptModule(step_prompt="Fix it.", step_id="fix")
        assert hasattr(mod, "predictor")


# ===========================================================================
# config_fitness_metric
# ===========================================================================


@pytest.mark.unit
class TestConfigFitnessMetric:
    def test_empty_output_zero_accuracy(self):
        example = SimpleNamespace(expected_behavior="some expected output")
        prediction = SimpleNamespace(output="")
        result = config_fitness_metric(example, prediction)
        assert result["scores"]["accuracy"] == 0.0
        assert result["scores"]["brevity"] == 1.0

    def test_perfect_overlap(self):
        example = SimpleNamespace(expected_behavior="find the bug using grep")
        prediction = SimpleNamespace(output="find the bug using grep")
        result = config_fitness_metric(example, prediction)
        assert result["scores"]["accuracy"] == 1.0

    def test_partial_overlap(self):
        example = SimpleNamespace(expected_behavior="find the bug using grep")
        prediction = SimpleNamespace(output="find the bug with search")
        result = config_fitness_metric(example, prediction)
        assert 0.3 < result["scores"]["accuracy"] < 1.0

    def test_brevity_decreases_with_length(self):
        example = SimpleNamespace(expected_behavior="short")
        short_pred = SimpleNamespace(output="a" * 100)
        long_pred = SimpleNamespace(output="a" * 1500)
        short_result = config_fitness_metric(example, short_pred)
        long_result = config_fitness_metric(example, long_pred)
        assert short_result["scores"]["brevity"] > long_result["scores"]["brevity"]

    def test_brevity_zero_at_ceiling(self):
        example = SimpleNamespace(expected_behavior="short")
        prediction = SimpleNamespace(output="a" * 2000)
        result = config_fitness_metric(example, prediction)
        assert result["scores"]["brevity"] == 0.0


# ===========================================================================
# ConfigDatasetBuilder
# ===========================================================================


@pytest.mark.unit
class TestConfigDatasetBuilder:
    def test_empty_build(self):
        builder = ConfigDatasetBuilder()
        train, val, holdout = builder.build()
        assert train == [] and val == [] and holdout == []

    def test_size_tracking(self):
        builder = ConfigDatasetBuilder()
        builder.add_episode("task", "summary", 0.5)
        assert builder.size == 1

    def test_split_ratios(self):
        builder = ConfigDatasetBuilder()
        for i in range(20):
            builder.add_episode(f"task_{i}", f"summary_{i}", float(i) / 20)
        train, val, holdout = builder.build()
        assert len(train) == 10  # 50%
        assert len(val) == 5     # 25%
        assert len(holdout) == 5  # 25%

    def test_minimum_one_train(self):
        builder = ConfigDatasetBuilder()
        builder.add_episode("task", "summary", 1.0)
        train, val, holdout = builder.build()
        assert len(train) == 1


# ===========================================================================
# GEPAConfigOptimizer
# ===========================================================================


@pytest.mark.unit
class TestGEPAConfigOptimizer:
    def test_construction(self):
        opt = GEPAConfigOptimizer(system_llm=_make_system_llm())
        assert opt is not None

    def test_construction_with_data_dir(self, tmp_path):
        data_dir = str(tmp_path / "data")
        opt = GEPAConfigOptimizer(system_llm=_make_system_llm(), data_dir=data_dir)
        assert os.path.isdir(data_dir)

    def test_record_episode(self):
        opt = GEPAConfigOptimizer(system_llm=_make_system_llm())
        opt.record_episode("task", "trace text", 1.0)
        assert opt.dataset.size == 1

    def test_record_episode_persists_to_disk(self, tmp_path):
        data_dir = str(tmp_path / "data")
        opt = GEPAConfigOptimizer(system_llm=_make_system_llm(), data_dir=data_dir)
        opt.record_episode("Fix the bug", "[iter 1] bash(...)", 1.0, issue_id="astropy-123")
        files = os.listdir(data_dir)
        assert len(files) == 1
        assert "astropy-123" in files[0]
        import json
        with open(os.path.join(data_dir, files[0])) as f:
            data = json.load(f)
        assert data["issue_id"] == "astropy-123"
        assert data["trace"] == "[iter 1] bash(...)"
        assert data["score"] == 1.0

    def test_should_not_optimize_before_interval(self):
        opt = GEPAConfigOptimizer(
            system_llm=_make_system_llm(),
            gepa_interval=5,
            min_dataset_size=5,
        )
        for i in range(4):
            opt.record_episode(f"task_{i}", f"trace_{i}", 1.0)
        assert not opt.should_optimize()

    def test_should_optimize_after_interval(self):
        opt = GEPAConfigOptimizer(
            system_llm=_make_system_llm(),
            gepa_interval=5,
            min_dataset_size=5,
        )
        for i in range(5):
            opt.record_episode(f"task_{i}", f"trace_{i}", 1.0)
        assert opt.should_optimize()

    def test_maybe_optimize_returns_original_before_interval(self):
        opt = GEPAConfigOptimizer(
            system_llm=_make_system_llm(),
            gepa_interval=5,
            min_dataset_size=5,
        )
        config = _make_config(StepConfig(id="s1", prompt="Do.", tools=["bash"]))
        result = opt.maybe_optimize(config)
        assert result is config  # unchanged
