"""Unit tests for artifact and LLM config resolution.

Tests define the target behavior of the resolver module:
- resolve_artifact_path: find the right artifact (explicit > project > package default)
- resolve_llm_config: find LLM settings (CLI > env > project config > error with guidance)

Tests are expected to FAIL until the resolver module is implemented.
"""
from __future__ import annotations

import json
import os

import pytest

from midas_agent.resolver import (
    ConfigurationError,
    LLMConfig,
    resolve_artifact_path,
    resolve_llm_config,
)


# ===================================================================
# Artifact path resolution
# ===================================================================


@pytest.mark.unit
class TestResolveArtifactPath:
    """resolve_artifact_path priority: explicit > project .midas/agents/ > package default."""

    def test_explicit_path_takes_priority(self, tmp_path):
        """--artifact flag overrides everything."""
        # Create project-level artifact
        project_dir = tmp_path / ".midas" / "agents"
        project_dir.mkdir(parents=True)
        project_artifact = project_dir / "graph_emergence_artifact.json"
        project_artifact.write_text("{}")

        # Create explicit artifact
        explicit = tmp_path / "my_artifact.json"
        explicit.write_text("{}")

        result = resolve_artifact_path(explicit=str(explicit), cwd=str(tmp_path))
        assert result == str(explicit)

    def test_explicit_path_not_found_raises(self, tmp_path):
        """--artifact pointing to non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            resolve_artifact_path(explicit="/nonexistent/artifact.json", cwd=str(tmp_path))

    def test_project_level_found(self, tmp_path):
        """Artifact in cwd/.midas/agents/ is found."""
        project_dir = tmp_path / ".midas" / "agents"
        project_dir.mkdir(parents=True)
        artifact = project_dir / "graph_emergence_artifact.json"
        artifact.write_text("{}")

        result = resolve_artifact_path(cwd=str(tmp_path))
        assert result == str(artifact)

    def test_project_level_over_package_default(self, tmp_path):
        """Project-level artifact takes priority over package default."""
        project_dir = tmp_path / ".midas" / "agents"
        project_dir.mkdir(parents=True)
        artifact = project_dir / "graph_emergence_artifact.json"
        artifact.write_text('{"custom": true}')

        result = resolve_artifact_path(cwd=str(tmp_path))
        # Must be the project-level one, not the package default
        assert result == str(artifact)

    def test_package_default_used_as_fallback(self, tmp_path):
        """No explicit, no project-level -> returns package default."""
        # tmp_path has no .midas/agents/
        result = resolve_artifact_path(cwd=str(tmp_path))
        assert "midas_agent" in result
        assert "defaults" in result
        assert result.endswith(".json")

    def test_package_default_file_exists(self):
        """The package default artifact file actually exists on disk."""
        result = resolve_artifact_path(cwd="/nonexistent_dir_12345")
        assert os.path.isfile(result)

    def test_priority_explicit_gt_project_gt_default(self, tmp_path):
        """All three exist; explicit wins."""
        project_dir = tmp_path / ".midas" / "agents"
        project_dir.mkdir(parents=True)
        (project_dir / "graph_emergence_artifact.json").write_text("{}")

        explicit = tmp_path / "explicit.json"
        explicit.write_text("{}")

        result = resolve_artifact_path(explicit=str(explicit), cwd=str(tmp_path))
        assert result == str(explicit)

    def test_cwd_defaults_to_os_getcwd(self):
        """When cwd is None, uses os.getcwd()."""
        # Should not raise — always falls through to package default at worst
        result = resolve_artifact_path()
        assert result is not None
        assert result.endswith(".json")


# ===================================================================
# LLM config resolution
# ===================================================================


@pytest.mark.unit
class TestResolveLLMConfig:
    """resolve_llm_config priority: CLI > env > project config > error with guidance."""

    def test_cli_model_overrides_all(self, monkeypatch, tmp_path):
        """--model flag takes highest priority."""
        monkeypatch.setenv("MIDAS_MODEL", "env-model")
        config = resolve_llm_config(
            cli_model="cli-model", cli_api_key="sk-test", cwd=str(tmp_path),
        )
        assert config.model == "cli-model"

    def test_cli_api_key_overrides_env(self, monkeypatch, tmp_path):
        """--api-key flag overrides environment variables."""
        monkeypatch.setenv("MIDAS_API_KEY", "env-key")
        config = resolve_llm_config(
            cli_model="m", cli_api_key="cli-key", cwd=str(tmp_path),
        )
        assert config.api_key == "cli-key"

    def test_env_var_midas_model(self, monkeypatch, tmp_path):
        """MIDAS_MODEL env var used when no CLI flag."""
        monkeypatch.setenv("MIDAS_MODEL", "env-model")
        monkeypatch.setenv("MIDAS_API_KEY", "sk-test")
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.model == "env-model"

    def test_env_var_midas_api_key(self, monkeypatch, tmp_path):
        """MIDAS_API_KEY env var used for api_key."""
        monkeypatch.setenv("MIDAS_MODEL", "m")
        monkeypatch.setenv("MIDAS_API_KEY", "sk-midas")
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.api_key == "sk-midas"

    def test_env_var_openai_api_key_fallback(self, monkeypatch, tmp_path):
        """OPENAI_API_KEY used when MIDAS_API_KEY not set."""
        monkeypatch.setenv("MIDAS_MODEL", "m")
        monkeypatch.delenv("MIDAS_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.api_key == "sk-openai"

    def test_project_config_yaml(self, monkeypatch, tmp_path):
        """Model and api_key from .midas/config.yaml."""
        monkeypatch.delenv("MIDAS_MODEL", raising=False)
        monkeypatch.delenv("MIDAS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        config_dir = tmp_path / ".midas"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "model: yaml-model\napi_key: sk-yaml\n"
        )
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.model == "yaml-model"
        assert config.api_key == "sk-yaml"

    def test_project_config_api_base(self, monkeypatch, tmp_path):
        """api_base from .midas/config.yaml is picked up."""
        monkeypatch.delenv("MIDAS_MODEL", raising=False)
        monkeypatch.delenv("MIDAS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        config_dir = tmp_path / ".midas"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "model: m\napi_key: k\napi_base: http://localhost:8000\n"
        )
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.api_base == "http://localhost:8000"

    def test_priority_cli_gt_env_gt_project(self, monkeypatch, tmp_path):
        """CLI > env > project config for model."""
        monkeypatch.setenv("MIDAS_MODEL", "env-model")
        monkeypatch.setenv("MIDAS_API_KEY", "sk-env")

        config_dir = tmp_path / ".midas"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("model: yaml-model\napi_key: sk-yaml\n")

        config = resolve_llm_config(
            cli_model="cli-model", cli_api_key="sk-cli", cwd=str(tmp_path),
        )
        assert config.model == "cli-model"
        assert config.api_key == "sk-cli"

    def test_no_config_raises_guidance(self, monkeypatch, tmp_path):
        """Nothing configured -> ConfigurationError with user guidance."""
        monkeypatch.delenv("MIDAS_MODEL", raising=False)
        monkeypatch.delenv("MIDAS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ConfigurationError) as exc_info:
            resolve_llm_config(cwd=str(tmp_path))

        msg = str(exc_info.value)
        # Guidance must tell user HOW to configure
        assert "MIDAS_MODEL" in msg or "midas/config.yaml" in msg or "--model" in msg

    def test_model_found_but_no_api_key_raises_guidance(self, monkeypatch, tmp_path):
        """Model set but no API key -> ConfigurationError with guidance."""
        monkeypatch.setenv("MIDAS_MODEL", "gpt-4o")
        monkeypatch.delenv("MIDAS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ConfigurationError) as exc_info:
            resolve_llm_config(cwd=str(tmp_path))

        msg = str(exc_info.value)
        assert "API" in msg.upper() or "api_key" in msg or "MIDAS_API_KEY" in msg

    def test_returns_llm_config_dataclass(self, monkeypatch, tmp_path):
        """Return type is LLMConfig with model, api_key, api_base fields."""
        monkeypatch.setenv("MIDAS_MODEL", "m")
        monkeypatch.setenv("MIDAS_API_KEY", "k")
        config = resolve_llm_config(cwd=str(tmp_path))
        assert isinstance(config, LLMConfig)
        assert hasattr(config, "model")
        assert hasattr(config, "api_key")
        assert hasattr(config, "api_base")

    def test_api_base_defaults_to_none(self, monkeypatch, tmp_path):
        """api_base is None when not specified anywhere."""
        monkeypatch.setenv("MIDAS_MODEL", "m")
        monkeypatch.setenv("MIDAS_API_KEY", "k")
        monkeypatch.delenv("MIDAS_API_BASE", raising=False)
        config = resolve_llm_config(cwd=str(tmp_path))
        assert config.api_base is None
