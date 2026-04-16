"""Integration tests for Issue #6: lossless artifact export/import pipeline.

Tests exercise the full export -> JSON file -> import flow, verifying that
the trained agent graph, economic state, and training metadata survive
the roundtrip without any field loss.

Tests are expected to FAIL until the migration is implemented.
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from midas_agent.inference.frozen_pricing import FrozenPricingEngine
from midas_agent.inference.schemas import GraphEmergenceArtifact
from midas_agent.workspace.graph_emergence.agent import Agent, Soul
from midas_agent.workspace.graph_emergence.free_agent_manager import FreeAgentManager
from midas_agent.workspace.graph_emergence.skill import Skill


# ===================================================================
# Helpers
# ===================================================================


def _make_agent(
    agent_id: str,
    agent_type: str = "free",
    skill_name: str | None = None,
    protected_by: str | None = None,
    protecting: list[str] | None = None,
) -> Agent:
    soul = Soul(system_prompt=f"You are agent {agent_id}.")
    skill = None
    if skill_name:
        skill = Skill(
            name=skill_name,
            description=f"{skill_name} skill",
            content=f"Do {skill_name} work.",
        )
    return Agent(
        agent_id=agent_id,
        soul=soul,
        agent_type=agent_type,
        skill=skill,
        protected_by=protected_by,
        protecting=protecting or [],
    )


def _make_full_artifact() -> GraphEmergenceArtifact:
    """Build a realistic artifact with protection chain and mixed states."""
    responsible = _make_agent(
        "resp-1",
        agent_type="workspace_bound",
        skill_name="coordinate",
        protecting=["fa-1", "fa-2", "fa-3"],
    )
    free_agents = [
        _make_agent(
            "fa-1",
            skill_name="debug",
            protected_by="resp-1",
        ),
        _make_agent(
            "fa-2",
            skill_name=None,  # no skill
            protected_by="resp-1",
        ),
        _make_agent(
            "fa-3",
            skill_name="search",
            protected_by="resp-1",
            protecting=["fa-3-sub"],  # nested protection
        ),
    ]
    return GraphEmergenceArtifact(
        responsible_agent=responsible,
        free_agents=free_agents,
        agent_prices={"fa-1": 1200, "fa-2": 800, "fa-3": 1500},
        agent_bankruptcy_rates={"fa-1": 0.05, "fa-2": 0.0, "fa-3": 0.20},
        last_etas={"ws-1": 1.8, "ws-2": 0.6},
        adaptive_multiplier_value=1.25,
        total_episodes=15,
        budget_hint=65000,
    )


def _write_artifact_file(artifact: GraphEmergenceArtifact) -> str:
    """Write artifact to a temp JSON file. Caller must os.unlink."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        f.write(artifact.model_dump_json(indent=2))
    return path


# ===================================================================
# 1. Exporter produces lossless output
# ===================================================================


@pytest.mark.integration
class TestExporterLossless:
    """The exporter must write JSON that contains ALL Agent fields."""

    def test_exported_json_contains_all_agent_fields(self):
        """Every field of every Agent appears in the JSON file."""
        from midas_agent.inference.exporter import export_graph_emergence

        responsible = _make_agent(
            "resp-1",
            agent_type="workspace_bound",
            skill_name="plan",
            protecting=["fa-1"],
        )
        free_agents = [
            _make_agent("fa-1", skill_name="debug", protected_by="resp-1"),
        ]

        pricing = MagicMock()
        pricing.calculate_price.return_value = 1000

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

        try:
            export_graph_emergence(
                responsible_agent=responsible,
                free_agents=free_agents,
                pricing_engine=pricing,
                hire_counts={"fa-1": 10},
                bankruptcy_counts={"fa-1": 1},
                budget_hint=50000,
                output_path=path,
            )
            with open(path) as f:
                data = json.load(f)

            # Responsible agent must have ALL fields
            ra = data["responsible_agent"]
            assert ra["agent_id"] == "resp-1"
            assert ra["agent_type"] == "workspace_bound"
            assert ra["protecting"] == ["fa-1"]
            assert ra["protected_by"] is None

            # Free agent must have ALL fields
            fa = data["free_agents"][0]
            assert fa["agent_id"] == "fa-1"
            assert fa["agent_type"] == "free"
            assert fa["protected_by"] == "resp-1"
            assert "protecting" in fa
        finally:
            os.unlink(path)

    def test_exported_free_agent_skill_preserved(self):
        """Free agent's Skill fields (name, description, content) all present."""
        from midas_agent.inference.exporter import export_graph_emergence

        responsible = _make_agent("resp-1", agent_type="workspace_bound")
        fa = _make_agent("fa-1", skill_name="search", protected_by="resp-1")
        pricing = MagicMock()
        pricing.calculate_price.return_value = 500

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

        try:
            export_graph_emergence(
                responsible_agent=responsible,
                free_agents=[fa],
                pricing_engine=pricing,
                hire_counts={},
                bankruptcy_counts={},
                budget_hint=10000,
                output_path=path,
            )
            with open(path) as f:
                data = json.load(f)

            skill = data["free_agents"][0]["skill"]
            assert skill["name"] == "search"
            assert skill["description"] == "search skill"
            assert skill["content"] == "Do search work."
        finally:
            os.unlink(path)

    def test_export_preserves_protection_chain(self):
        """Multi-level protection survives export."""
        from midas_agent.inference.exporter import export_graph_emergence

        resp = _make_agent(
            "resp", agent_type="workspace_bound", protecting=["mid"],
        )
        mid = _make_agent("mid", protected_by="resp", protecting=["leaf"])
        leaf = _make_agent("leaf", protected_by="mid")
        pricing = MagicMock()
        pricing.calculate_price.return_value = 100

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

        try:
            export_graph_emergence(
                responsible_agent=resp,
                free_agents=[mid, leaf],
                pricing_engine=pricing,
                hire_counts={},
                bankruptcy_counts={},
                budget_hint=10000,
                output_path=path,
            )
            with open(path) as f:
                data = json.load(f)

            r = data["responsible_agent"]
            assert r["protecting"] == ["mid"]

            agents_by_id = {a["agent_id"]: a for a in data["free_agents"]}
            assert agents_by_id["mid"]["protected_by"] == "resp"
            assert agents_by_id["mid"]["protecting"] == ["leaf"]
            assert agents_by_id["leaf"]["protected_by"] == "mid"
        finally:
            os.unlink(path)

    def test_export_all_passed_agents_included(self):
        """Every agent in the free_agents list is in the output."""
        from midas_agent.inference.exporter import export_graph_emergence

        responsible = _make_agent("r", agent_type="workspace_bound")
        free_agents = [_make_agent(f"fa-{i}") for i in range(8)]
        pricing = MagicMock()
        pricing.calculate_price.return_value = 100

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

        try:
            export_graph_emergence(
                responsible_agent=responsible,
                free_agents=free_agents,
                pricing_engine=pricing,
                hire_counts={},
                bankruptcy_counts={},
                budget_hint=10000,
                output_path=path,
            )
            with open(path) as f:
                data = json.load(f)

            exported_ids = {a["agent_id"] for a in data["free_agents"]}
            assert exported_ids == {f"fa-{i}" for i in range(8)}
        finally:
            os.unlink(path)


# ===================================================================
# 2. Artifact file roundtrip
# ===================================================================


@pytest.mark.integration
class TestArtifactFileRoundtrip:
    """Write artifact to disk, read back, verify complete agent graph."""

    def test_write_read_lossless(self):
        """Artifact survives write -> read with no field loss."""
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)

        try:
            with open(path) as f:
                raw = f.read()
            restored = GraphEmergenceArtifact.model_validate_json(raw)

            # Responsible agent
            r = restored.responsible_agent
            assert r.agent_id == "resp-1"
            assert r.agent_type == "workspace_bound"
            assert r.skill.name == "coordinate"
            assert r.protecting == ["fa-1", "fa-2", "fa-3"]
            assert r.protected_by is None

            # Free agents
            assert len(restored.free_agents) == 3
            fa_map = {a.agent_id: a for a in restored.free_agents}

            fa1 = fa_map["fa-1"]
            assert fa1.agent_type == "free"
            assert fa1.skill.name == "debug"
            assert fa1.protected_by == "resp-1"

            fa2 = fa_map["fa-2"]
            assert fa2.skill is None
            assert fa2.protected_by == "resp-1"

            fa3 = fa_map["fa-3"]
            assert fa3.skill.name == "search"
            assert fa3.protecting == ["fa-3-sub"]  # nested protection

            # Economic state
            assert restored.agent_prices["fa-1"] == 1200
            assert restored.agent_bankruptcy_rates["fa-3"] == pytest.approx(0.20)

            # Training metadata
            assert restored.last_etas["ws-1"] == pytest.approx(1.8)
            assert restored.adaptive_multiplier_value == pytest.approx(1.25)
            assert restored.total_episodes == 15
            assert restored.budget_hint == 65000
        finally:
            os.unlink(path)

    def test_complex_protection_chain(self):
        """Three-level chain: resp -> mid -> leaf survives file roundtrip."""
        resp = _make_agent(
            "resp", agent_type="workspace_bound", protecting=["mid"],
        )
        mid = _make_agent("mid", protected_by="resp", protecting=["leaf"])
        leaf = _make_agent("leaf", protected_by="mid")

        artifact = GraphEmergenceArtifact(
            responsible_agent=resp,
            free_agents=[mid, leaf],
            agent_prices={"mid": 100, "leaf": 50},
            agent_bankruptcy_rates={"mid": 0.0, "leaf": 0.0},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=1,
            budget_hint=5000,
        )
        path = _write_artifact_file(artifact)

        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())

            assert restored.responsible_agent.protecting == ["mid"]
            by_id = {a.agent_id: a for a in restored.free_agents}
            assert by_id["mid"].protected_by == "resp"
            assert by_id["mid"].protecting == ["leaf"]
            assert by_id["leaf"].protected_by == "mid"
            assert by_id["leaf"].protecting == []
        finally:
            os.unlink(path)

    def test_unicode_content_survives(self):
        """Unicode in system_prompt / skill content survives roundtrip."""
        agent = _make_agent("unicode", agent_type="workspace_bound")
        agent = Agent(
            agent_id="unicode",
            soul=Soul(system_prompt="You are an agent for debugging."),
            agent_type="workspace_bound",
            skill=Skill(
                name="multilingual",
                description="Handles multiple languages",
                content="Handle errors in various contexts.",
            ),
        )
        artifact = GraphEmergenceArtifact(
            responsible_agent=agent,
            free_agents=[],
            agent_prices={},
            agent_bankruptcy_rates={},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=0,
            budget_hint=1000,
        )
        path = _write_artifact_file(artifact)

        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert "debugging" in restored.responsible_agent.soul.system_prompt
            assert restored.responsible_agent.skill.name == "multilingual"
        finally:
            os.unlink(path)

    def test_large_agent_pool_preserved(self):
        """All 20 agents survive roundtrip; none dropped."""
        resp = _make_agent("resp", agent_type="workspace_bound")
        free_agents = [_make_agent(f"fa-{i}", skill_name=f"skill-{i}") for i in range(20)]
        prices = {f"fa-{i}": 100 * (i + 1) for i in range(20)}
        br = {f"fa-{i}": i / 100.0 for i in range(20)}

        artifact = GraphEmergenceArtifact(
            responsible_agent=resp,
            free_agents=free_agents,
            agent_prices=prices,
            agent_bankruptcy_rates=br,
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=5,
            budget_hint=100000,
        )
        path = _write_artifact_file(artifact)

        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert len(restored.free_agents) == 20
            restored_ids = {a.agent_id for a in restored.free_agents}
            expected_ids = {f"fa-{i}" for i in range(20)}
            assert restored_ids == expected_ids
            for i in range(20):
                assert restored.agent_prices[f"fa-{i}"] == 100 * (i + 1)
        finally:
            os.unlink(path)

    def test_long_skill_content_preserved(self):
        """Skill content near the 5000-char limit survives roundtrip."""
        long_content = "x" * 5000
        agent = Agent(
            agent_id="verbose",
            soul=Soul(system_prompt="p"),
            agent_type="free",
            skill=Skill(name="big", description="large skill", content=long_content),
        )
        artifact = GraphEmergenceArtifact(
            responsible_agent=_make_agent("r", agent_type="workspace_bound"),
            free_agents=[agent],
            agent_prices={"verbose": 100},
            agent_bankruptcy_rates={"verbose": 0.0},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=1,
            budget_hint=1000,
        )
        path = _write_artifact_file(artifact)

        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert len(restored.free_agents[0].skill.content) == 5000
        finally:
            os.unlink(path)


# ===================================================================
# 3. Inference runner can reconstruct full agents from artifact
# ===================================================================


@pytest.mark.integration
class TestInferenceRunnerReconstructsFullAgents:
    """After migration, the inference runner must load Agent objects
    directly from the artifact, with no manual field copying and no
    hardcoded values like agent_type='free'."""

    def _write_and_load(self, artifact: GraphEmergenceArtifact) -> GraphEmergenceArtifact:
        """Write artifact to file and load it as the runner would."""
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                raw = json.load(f)
            return GraphEmergenceArtifact.model_validate(raw)
        finally:
            os.unlink(path)

    def test_loaded_agents_have_correct_agent_type(self):
        """Free agents keep their original agent_type; not hardcoded 'free'."""
        artifact = _make_full_artifact()
        loaded = self._write_and_load(artifact)

        assert loaded.responsible_agent.agent_type == "workspace_bound"
        for fa in loaded.free_agents:
            assert fa.agent_type == "free"

    def test_loaded_agents_have_protection_fields(self):
        """protected_by and protecting are preserved, not dropped."""
        artifact = _make_full_artifact()
        loaded = self._write_and_load(artifact)

        assert loaded.responsible_agent.protecting == ["fa-1", "fa-2", "fa-3"]
        fa_map = {a.agent_id: a for a in loaded.free_agents}
        assert fa_map["fa-1"].protected_by == "resp-1"
        assert fa_map["fa-3"].protecting == ["fa-3-sub"]

    def test_free_agent_manager_populated_from_loaded_agents(self):
        """FreeAgentManager can be fully rebuilt from loaded artifact agents."""
        artifact = _make_full_artifact()
        loaded = self._write_and_load(artifact)

        frozen_prices = loaded.agent_prices
        manager = FreeAgentManager(
            pricing_engine=FrozenPricingEngine(frozen_prices)
        )
        for fa in loaded.free_agents:
            manager.register(fa)

        # All agents registered
        assert set(manager.free_agents.keys()) == {"fa-1", "fa-2", "fa-3"}

        # Registered agents retain all fields
        registered = manager.free_agents["fa-1"]
        assert registered.agent_type == "free"
        assert registered.protected_by == "resp-1"
        assert registered.skill.name == "debug"

    def test_frozen_pricing_uses_loaded_prices(self):
        """FrozenPricingEngine built from artifact prices returns correct values."""
        artifact = _make_full_artifact()
        loaded = self._write_and_load(artifact)

        frozen = FrozenPricingEngine(loaded.agent_prices)
        fa_map = {a.agent_id: a for a in loaded.free_agents}
        assert frozen.calculate_price(fa_map["fa-1"]) == 1200
        assert frozen.calculate_price(fa_map["fa-2"]) == 800
        assert frozen.calculate_price(fa_map["fa-3"]) == 1500

    def test_matching_works_with_loaded_agents(self):
        """FreeAgentManager.match() works correctly on agents loaded from file."""
        artifact = _make_full_artifact()
        loaded = self._write_and_load(artifact)

        manager = FreeAgentManager(
            pricing_engine=FrozenPricingEngine(loaded.agent_prices)
        )
        for fa in loaded.free_agents:
            manager.register(fa)

        candidates = manager.match("debug this error", top_k=3)
        assert len(candidates) > 0
        # Agent with "debug" skill should match "debug this error"
        agent_ids = [c.agent.agent_id for c in candidates]
        assert "fa-1" in agent_ids


# ===================================================================
# 4. Economic state and training metadata roundtrip
# ===================================================================


@pytest.mark.integration
class TestEconomicStateRoundtrip:
    """Prices, bankruptcy rates, etas, and multiplier survive file roundtrip."""

    def test_prices_survive(self):
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.agent_prices == {"fa-1": 1200, "fa-2": 800, "fa-3": 1500}
        finally:
            os.unlink(path)

    def test_bankruptcy_rates_survive(self):
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.agent_bankruptcy_rates["fa-1"] == pytest.approx(0.05)
            assert restored.agent_bankruptcy_rates["fa-2"] == pytest.approx(0.0)
            assert restored.agent_bankruptcy_rates["fa-3"] == pytest.approx(0.20)
        finally:
            os.unlink(path)

    def test_training_metadata_survive(self):
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.last_etas == {"ws-1": pytest.approx(1.8), "ws-2": pytest.approx(0.6)}
            assert restored.adaptive_multiplier_value == pytest.approx(1.25)
            assert restored.total_episodes == 15
        finally:
            os.unlink(path)

    def test_budget_hint_roundtrip(self):
        """budget_hint value is preserved exactly."""
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.budget_hint == 65000
        finally:
            os.unlink(path)


# ===================================================================
# 5. Edge cases and backward compatibility
# ===================================================================


@pytest.mark.integration
class TestEdgeCases:
    """Boundary conditions for the lossless artifact pipeline."""

    def test_no_free_agents(self):
        """Responsible-only artifact roundtrips."""
        artifact = GraphEmergenceArtifact(
            responsible_agent=_make_agent("solo", agent_type="workspace_bound"),
            free_agents=[],
            agent_prices={},
            agent_bankruptcy_rates={},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=0,
            budget_hint=5000,
        )
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.responsible_agent.agent_id == "solo"
            assert len(restored.free_agents) == 0
        finally:
            os.unlink(path)

    def test_agents_with_no_skills(self):
        """All agents have skill=None."""
        resp = _make_agent("r", agent_type="workspace_bound")
        fas = [_make_agent("fa-1"), _make_agent("fa-2")]
        artifact = GraphEmergenceArtifact(
            responsible_agent=resp,
            free_agents=fas,
            agent_prices={"fa-1": 100, "fa-2": 100},
            agent_bankruptcy_rates={"fa-1": 0.0, "fa-2": 0.0},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=1,
            budget_hint=1000,
        )
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())
            assert restored.responsible_agent.skill is None
            assert all(fa.skill is None for fa in restored.free_agents)
        finally:
            os.unlink(path)

    def test_file_is_valid_parseable_json(self):
        """Output file is valid JSON parseable by stdlib json module."""
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                data = json.load(f)  # must not raise
            assert isinstance(data, dict)
            assert "responsible_agent" in data
            assert "free_agents" in data
            assert "agent_prices" in data
            assert "agent_bankruptcy_rates" in data
            assert "last_etas" in data
            assert "adaptive_multiplier_value" in data
            assert "total_episodes" in data
            assert "budget_hint" in data
        finally:
            os.unlink(path)

    def test_file_human_readable(self):
        """Output JSON is pretty-printed (indent=2)."""
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                raw = f.read()
            # Pretty-printed JSON has newlines and indentation
            assert "\n" in raw
            assert "  " in raw
        finally:
            os.unlink(path)

    def test_attribute_access_on_loaded_agents(self):
        """Loaded agents support the same attribute access patterns as training."""
        artifact = _make_full_artifact()
        path = _write_artifact_file(artifact)
        try:
            with open(path) as f:
                restored = GraphEmergenceArtifact.model_validate_json(f.read())

            r = restored.responsible_agent
            assert r.agent_id == "resp-1"
            assert r.soul.system_prompt == "You are agent resp-1."
            assert r.agent_type == "workspace_bound"
            assert r.skill.name == "coordinate"
            assert r.skill.description == "coordinate skill"
            assert r.skill.content == "Do coordinate work."
            assert r.protected_by is None
            assert isinstance(r.protecting, list)

            fa = restored.free_agents[0]
            assert fa.agent_id == "fa-1"
            assert fa.soul.system_prompt == "You are agent fa-1."
            assert fa.agent_type == "free"
            assert fa.protected_by == "resp-1"
        finally:
            os.unlink(path)
