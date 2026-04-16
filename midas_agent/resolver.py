"""Artifact and LLM config resolution.

Priority chains:
- Artifact: explicit path > project .midas/agents/ > package default
- LLM config: CLI args > env vars > project .midas/config.yaml > error
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""
    pass


@dataclass
class LLMConfig:
    """Resolved LLM configuration."""
    model: str
    api_key: str
    api_base: str | None = None


def resolve_artifact_path(explicit: str | None = None, cwd: str | None = None) -> str:
    """Resolve the path to the graph emergence artifact JSON file.

    Priority:
    1. explicit path (--artifact flag)
    2. cwd/.midas/agents/graph_emergence_artifact.json
    3. Package default at midas_agent/defaults/graph_emergence_artifact.json
    """
    # 1. Explicit path
    if explicit is not None:
        if not os.path.isfile(explicit):
            raise FileNotFoundError(
                f"Artifact file not found: {explicit}"
            )
        return explicit

    # 2. Project-level artifact
    if cwd is None:
        cwd = os.getcwd()
    project_path = os.path.join(cwd, ".midas", "agents", "graph_emergence_artifact.json")
    if os.path.isfile(project_path):
        return project_path

    # 3. Package default
    import midas_agent
    pkg_dir = os.path.dirname(midas_agent.__file__)
    return os.path.join(pkg_dir, "defaults", "graph_emergence_artifact.json")


def resolve_llm_config(
    cli_model: str | None = None,
    cli_api_key: str | None = None,
    cli_api_base: str | None = None,
    cwd: str | None = None,
) -> LLMConfig:
    """Resolve LLM configuration from CLI args, env vars, and project config.

    Priority for each field: CLI arg > env var > project config.yaml
    """
    if cwd is None:
        cwd = os.getcwd()

    # Load project config if it exists
    project_config: dict = {}
    config_path = os.path.join(cwd, ".midas", "config.yaml")
    if os.path.isfile(config_path):
        with open(config_path) as f:
            project_config = yaml.safe_load(f) or {}

    # Resolve model: CLI > env > project config
    model = cli_model
    if model is None:
        model = os.environ.get("MIDAS_MODEL")
    if model is None:
        model = project_config.get("model")
    if model is None:
        raise ConfigurationError(
            "No model configured. Set one of: "
            "MIDAS_MODEL environment variable, "
            "'model' in .midas/config.yaml, "
            "or pass --model on the command line."
        )

    # Resolve api_key: CLI > MIDAS_API_KEY > OPENAI_API_KEY > project config
    api_key = cli_api_key
    if api_key is None:
        api_key = os.environ.get("MIDAS_API_KEY")
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY")
    if api_key is None:
        api_key = project_config.get("api_key")
    if api_key is None:
        raise ConfigurationError(
            "No API key configured. Set one of: "
            "MIDAS_API_KEY or OPENAI_API_KEY environment variable, "
            "'api_key' in .midas/config.yaml, "
            "or pass --api-key on the command line."
        )

    # Resolve api_base: CLI > env > project config (defaults to None)
    api_base = cli_api_base
    if api_base is None:
        api_base = os.environ.get("MIDAS_API_BASE")
    if api_base is None:
        api_base = project_config.get("api_base")

    return LLMConfig(model=model, api_key=api_key, api_base=api_base)
