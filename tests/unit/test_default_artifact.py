"""Unit tests for the package-shipped default artifact.

The default artifact at midas_agent/defaults/graph_emergence_artifact.json
is the out-of-box agent used when no training has been done.

Tests are expected to FAIL until the default artifact file is created.
"""
from __future__ import annotations

import json
import os

import pytest

from midas_agent.inference.schemas import GraphEmergenceArtifact
from midas_agent.workspace.graph_emergence.agent import Agent, Soul


# ===================================================================
# Default artifact existence and validity
# ===================================================================


def _get_default_path() -> str:
    """Return the expected path of the default artifact."""
    import midas_agent
    pkg_dir = os.path.dirname(midas_agent.__file__)
    return os.path.join(pkg_dir, "defaults", "graph_emergence_artifact.json")


@pytest.mark.unit
class TestDefaultArtifact:
    """The package default artifact must be valid and usable out of the box."""

    def test_file_exists(self):
        """Default artifact file exists in the package."""
        path = _get_default_path()
        assert os.path.isfile(path), f"Default artifact not found at {path}"

    def test_valid_json(self):
        """File is valid JSON."""
        with open(_get_default_path()) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_parseable_as_artifact(self):
        """File parses into a GraphEmergenceArtifact."""
        with open(_get_default_path()) as f:
            raw = f.read()
        artifact = GraphEmergenceArtifact.model_validate_json(raw)
        assert artifact is not None

    def test_has_responsible_agent(self):
        """Default artifact has a responsible agent."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert artifact.responsible_agent is not None
        assert isinstance(artifact.responsible_agent, Agent)

    def test_responsible_agent_is_workspace_bound(self):
        """Responsible agent has agent_type='workspace_bound'."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert artifact.responsible_agent.agent_type == "workspace_bound"

    def test_responsible_agent_has_system_prompt(self):
        """Responsible agent has a non-empty system prompt."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert artifact.responsible_agent.soul.system_prompt
        assert len(artifact.responsible_agent.soul.system_prompt) > 50

    def test_no_free_agents(self):
        """Default artifact has no free agents (single-agent mode)."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert len(artifact.free_agents) == 0

    def test_has_positive_budget_hint(self):
        """budget_hint is a positive integer."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert artifact.budget_hint > 0

    def test_empty_economic_state(self):
        """Default artifact has empty prices/rates (no training history)."""
        with open(_get_default_path()) as f:
            artifact = GraphEmergenceArtifact.model_validate_json(f.read())
        assert artifact.agent_prices == {}
        assert artifact.agent_bankruptcy_rates == {}
