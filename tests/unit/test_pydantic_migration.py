"""Unit tests for Issue #6: Pydantic BaseModel migration and lossless serialization.

These tests define the target behavior after migrating Agent, Soul, Skill,
and Relationship from @dataclass to Pydantic BaseModel, and updating
GraphEmergenceArtifact to use Agent directly instead of stripped schemas.

Tests are expected to FAIL until the migration is implemented.
"""
from __future__ import annotations

import json

import pytest

from midas_agent.workspace.graph_emergence.agent import Agent, Soul
from midas_agent.workspace.graph_emergence.skill import Skill
from midas_agent.workspace.graph_emergence.relationship import Relationship
from midas_agent.inference.schemas import GraphEmergenceArtifact


# ===================================================================
# Soul as BaseModel
# ===================================================================


@pytest.mark.unit
class TestSoulPydantic:
    """Soul must support Pydantic model_dump / model_validate."""

    def test_model_dump(self):
        soul = Soul(system_prompt="You are an expert debugger.")
        data = soul.model_dump()
        assert data == {"system_prompt": "You are an expert debugger."}

    def test_model_validate(self):
        data = {"system_prompt": "restored prompt"}
        soul = Soul.model_validate(data)
        assert soul.system_prompt == "restored prompt"

    def test_json_roundtrip(self):
        soul = Soul(system_prompt="You are helpful.")
        json_str = soul.model_dump_json()
        restored = Soul.model_validate_json(json_str)
        assert restored.system_prompt == soul.system_prompt

    def test_schema_has_system_prompt(self):
        schema = Soul.model_json_schema()
        assert "system_prompt" in schema["properties"]


# ===================================================================
# Skill as BaseModel
# ===================================================================


@pytest.mark.unit
class TestSkillPydantic:
    """Skill must support Pydantic model_dump / model_validate."""

    def test_model_dump(self):
        skill = Skill(name="debug", description="Debugging", content="Steps...")
        data = skill.model_dump()
        assert data == {
            "name": "debug",
            "description": "Debugging",
            "content": "Steps...",
        }

    def test_model_validate(self):
        data = {"name": "nav", "description": "Navigate", "content": "Use grep"}
        skill = Skill.model_validate(data)
        assert skill.name == "nav"
        assert skill.description == "Navigate"
        assert skill.content == "Use grep"

    def test_json_roundtrip(self):
        skill = Skill(name="nav", description="Navigate code", content="Use grep...")
        json_str = skill.model_dump_json()
        restored = Skill.model_validate_json(json_str)
        assert restored.name == skill.name
        assert restored.description == skill.description
        assert restored.content == skill.content

    def test_all_fields_in_dump(self):
        skill = Skill(name="n", description="d", content="c")
        data = skill.model_dump()
        assert set(data.keys()) == {"name", "description", "content"}


# ===================================================================
# Agent as BaseModel
# ===================================================================


@pytest.mark.unit
class TestAgentPydantic:
    """Agent must support Pydantic model_dump / model_validate with ALL fields."""

    def test_model_dump_minimal(self):
        """Required fields + defaults serialize correctly."""
        agent = Agent(
            agent_id="a-1",
            soul=Soul(system_prompt="prompt"),
            agent_type="free",
        )
        data = agent.model_dump()
        assert data["agent_id"] == "a-1"
        assert data["soul"] == {"system_prompt": "prompt"}
        assert data["agent_type"] == "free"
        assert data["skill"] is None
        assert data["protected_by"] is None
        assert data["protecting"] == []

    def test_model_dump_full(self):
        """All fields including skill, protected_by, protecting serialize."""
        agent = Agent(
            agent_id="a-2",
            soul=Soul(system_prompt="expert"),
            agent_type="workspace_bound",
            skill=Skill(name="debug", description="debugging", content="content"),
            protected_by="manager-1",
            protecting=["sub-1", "sub-2"],
        )
        data = agent.model_dump()
        assert data["agent_type"] == "workspace_bound"
        assert data["skill"]["name"] == "debug"
        assert data["protected_by"] == "manager-1"
        assert data["protecting"] == ["sub-1", "sub-2"]

    def test_model_validate_full(self):
        """model_validate restores Agent with all fields from dict."""
        data = {
            "agent_id": "a-3",
            "soul": {"system_prompt": "p"},
            "agent_type": "free",
            "skill": {"name": "n", "description": "d", "content": "c"},
            "protected_by": "parent-1",
            "protecting": ["child-1", "child-2"],
        }
        agent = Agent.model_validate(data)
        assert agent.agent_id == "a-3"
        assert agent.agent_type == "free"
        assert isinstance(agent.soul, Soul)
        assert agent.soul.system_prompt == "p"
        assert isinstance(agent.skill, Skill)
        assert agent.skill.name == "n"
        assert agent.protected_by == "parent-1"
        assert agent.protecting == ["child-1", "child-2"]

    def test_json_roundtrip_preserves_all_fields(self):
        """JSON roundtrip preserves fields currently LOST in export."""
        agent = Agent(
            agent_id="a-4",
            soul=Soul(system_prompt="test"),
            agent_type="free",
            skill=Skill(name="s", description="d", content="c"),
            protected_by="parent",
            protecting=["child-1"],
        )
        json_str = agent.model_dump_json()
        parsed = json.loads(json_str)

        # These fields are LOST in the current export; they must survive.
        assert parsed["agent_type"] == "free"
        assert parsed["protected_by"] == "parent"
        assert parsed["protecting"] == ["child-1"]

        restored = Agent.model_validate_json(json_str)
        assert restored.agent_type == "free"
        assert restored.protected_by == "parent"
        assert restored.protecting == ["child-1"]

    def test_all_fields_present_in_dump(self):
        """model_dump() output contains every Agent field."""
        agent = Agent(
            agent_id="a-5",
            soul=Soul(system_prompt="p"),
            agent_type="free",
        )
        expected = {
            "agent_id", "soul", "agent_type",
            "skill", "protected_by", "protecting",
        }
        assert set(agent.model_dump().keys()) == expected

    def test_nested_soul_type_preserved(self):
        """Deserialized soul is a Soul instance, not a plain dict."""
        agent = Agent(
            agent_id="a-6",
            soul=Soul(system_prompt="nested"),
            agent_type="free",
        )
        restored = Agent.model_validate(agent.model_dump())
        assert isinstance(restored.soul, Soul)
        assert restored.soul.system_prompt == "nested"

    def test_nested_skill_type_preserved(self):
        """Deserialized skill is a Skill instance, not a plain dict."""
        agent = Agent(
            agent_id="a-7",
            soul=Soul(system_prompt="p"),
            agent_type="free",
            skill=Skill(name="n", description="d", content="c"),
        )
        restored = Agent.model_validate(agent.model_dump())
        assert isinstance(restored.skill, Skill)
        assert restored.skill.name == "n"

    def test_none_skill_roundtrip(self):
        """Agent with skill=None roundtrips correctly."""
        agent = Agent(
            agent_id="a-8",
            soul=Soul(system_prompt="p"),
            agent_type="free",
        )
        restored = Agent.model_validate_json(agent.model_dump_json())
        assert restored.skill is None

    def test_empty_protecting_list_roundtrip(self):
        """Agent with protecting=[] roundtrips correctly."""
        agent = Agent(
            agent_id="a-9",
            soul=Soul(system_prompt="p"),
            agent_type="free",
        )
        restored = Agent.model_validate(agent.model_dump())
        assert restored.protecting == []
        assert isinstance(restored.protecting, list)

    def test_attribute_access_unchanged(self):
        """After migration, attribute access works the same as dataclass."""
        agent = Agent(
            agent_id="a-10",
            soul=Soul(system_prompt="p"),
            agent_type="workspace_bound",
            skill=Skill(name="n", description="d", content="c"),
            protected_by="mgr",
            protecting=["s1"],
        )
        assert agent.agent_id == "a-10"
        assert agent.soul.system_prompt == "p"
        assert agent.agent_type == "workspace_bound"
        assert agent.skill.name == "n"
        assert agent.protected_by == "mgr"
        assert agent.protecting == ["s1"]

    def test_deep_equality_after_roundtrip(self):
        """model_dump → model_validate produces an equal Agent."""
        original = Agent(
            agent_id="deep",
            soul=Soul(system_prompt="deep test"),
            agent_type="free",
            skill=Skill(name="n", description="d", content="c"),
            protected_by="p",
            protecting=["c1", "c2"],
        )
        restored = Agent.model_validate(original.model_dump())
        assert original.model_dump() == restored.model_dump()


# ===================================================================
# Relationship as BaseModel
# ===================================================================


@pytest.mark.unit
class TestRelationshipPydantic:
    """Relationship must support Pydantic model_dump / model_validate."""

    def test_model_dump_roundtrip(self):
        rel = Relationship(
            type="protection",
            from_agent_id="manager-1",
            to_agent_id="worker-1",
            workspace_id="ws-1",
            status="active",
        )
        data = rel.model_dump()
        restored = Relationship.model_validate(data)
        assert restored.type == "protection"
        assert restored.from_agent_id == "manager-1"
        assert restored.to_agent_id == "worker-1"
        assert restored.workspace_id == "ws-1"
        assert restored.status == "active"

    def test_json_roundtrip(self):
        rel = Relationship(
            type="hire",
            from_agent_id="employer",
            to_agent_id="freelancer",
            workspace_id="ws-2",
            status="completed",
        )
        json_str = rel.model_dump_json()
        restored = Relationship.model_validate_json(json_str)
        assert restored.type == "hire"
        assert restored.status == "completed"

    def test_all_fields_in_dump(self):
        rel = Relationship(
            type="hire", from_agent_id="a", to_agent_id="b",
            workspace_id="w", status="active",
        )
        expected = {"type", "from_agent_id", "to_agent_id", "workspace_id", "status"}
        assert set(rel.model_dump().keys()) == expected

    def test_mutable_after_migration(self):
        """Relationship.status must remain mutable after BaseModel migration."""
        rel = Relationship(
            type="hire", from_agent_id="a", to_agent_id="b",
            workspace_id="w", status="active",
        )
        rel.status = "completed"
        assert rel.status == "completed"
        rel.status = "terminated"
        assert rel.status == "terminated"


# ===================================================================
# Lossless GraphEmergenceArtifact
# ===================================================================


@pytest.mark.unit
class TestGraphEmergenceArtifactLossless:
    """GraphEmergenceArtifact must use Agent directly — no stripped schemas."""

    def _make_responsible(self) -> Agent:
        return Agent(
            agent_id="resp-1",
            soul=Soul(system_prompt="You are the coordinator."),
            agent_type="workspace_bound",
            skill=Skill(
                name="coordinate",
                description="Coordination",
                content="Plan and delegate.",
            ),
            protected_by=None,
            protecting=["fa-1", "fa-2"],
        )

    def _make_free_agents(self) -> list[Agent]:
        return [
            Agent(
                agent_id="fa-1",
                soul=Soul(system_prompt="You are a debugger."),
                agent_type="free",
                skill=Skill(
                    name="debug",
                    description="Debugging",
                    content="Use pdb...",
                ),
                protected_by="resp-1",
                protecting=[],
            ),
            Agent(
                agent_id="fa-2",
                soul=Soul(system_prompt="You are a navigator."),
                agent_type="free",
                skill=None,
                protected_by="resp-1",
                protecting=[],
            ),
        ]

    def _make_artifact(self) -> GraphEmergenceArtifact:
        return GraphEmergenceArtifact(
            responsible_agent=self._make_responsible(),
            free_agents=self._make_free_agents(),
            agent_prices={"fa-1": 1000, "fa-2": 2000},
            agent_bankruptcy_rates={"fa-1": 0.1, "fa-2": 0.3},
            last_etas={"ws-1": 1.5, "ws-2": 0.8},
            adaptive_multiplier_value=1.15,
            total_episodes=10,
            budget_hint=50000,
        )

    # -- Construction --

    def test_artifact_accepts_agent_objects(self):
        """Artifact should accept Agent objects directly, not stripped schemas."""
        artifact = self._make_artifact()
        assert isinstance(artifact.responsible_agent, Agent)
        assert artifact.responsible_agent.agent_id == "resp-1"
        assert len(artifact.free_agents) == 2
        assert isinstance(artifact.free_agents[0], Agent)

    # -- JSON field presence --

    def test_artifact_json_contains_agent_type(self):
        """Exported JSON must include agent_type for every agent."""
        artifact = self._make_artifact()
        parsed = json.loads(artifact.model_dump_json())
        assert parsed["responsible_agent"]["agent_type"] == "workspace_bound"
        for fa in parsed["free_agents"]:
            assert fa["agent_type"] == "free"

    def test_artifact_json_contains_protection_fields(self):
        """Exported JSON must include protected_by and protecting."""
        artifact = self._make_artifact()
        parsed = json.loads(artifact.model_dump_json())
        assert parsed["responsible_agent"]["protecting"] == ["fa-1", "fa-2"]
        assert parsed["responsible_agent"]["protected_by"] is None
        assert parsed["free_agents"][0]["protected_by"] == "resp-1"
        assert parsed["free_agents"][1]["protected_by"] == "resp-1"

    def test_artifact_json_contains_economic_state(self):
        """Exported JSON must include prices and bankruptcy rates."""
        artifact = self._make_artifact()
        parsed = json.loads(artifact.model_dump_json())
        assert parsed["agent_prices"] == {"fa-1": 1000, "fa-2": 2000}
        assert parsed["agent_bankruptcy_rates"]["fa-1"] == pytest.approx(0.1)
        assert parsed["agent_bankruptcy_rates"]["fa-2"] == pytest.approx(0.3)

    def test_artifact_json_contains_training_metadata(self):
        """Exported JSON must include etas, multiplier value, and episode count."""
        artifact = self._make_artifact()
        parsed = json.loads(artifact.model_dump_json())
        assert parsed["last_etas"] == {"ws-1": 1.5, "ws-2": 0.8}
        assert parsed["adaptive_multiplier_value"] == pytest.approx(1.15)
        assert parsed["total_episodes"] == 10

    # -- Full roundtrip --

    def test_artifact_full_roundtrip(self):
        """Create -> JSON -> restore: all fields must be preserved."""
        artifact = self._make_artifact()
        json_str = artifact.model_dump_json()
        restored = GraphEmergenceArtifact.model_validate_json(json_str)

        # Responsible agent
        r = restored.responsible_agent
        assert r.agent_id == "resp-1"
        assert r.agent_type == "workspace_bound"
        assert r.soul.system_prompt == "You are the coordinator."
        assert r.skill.name == "coordinate"
        assert r.protecting == ["fa-1", "fa-2"]
        assert r.protected_by is None

        # Free agents
        assert len(restored.free_agents) == 2
        fa1 = restored.free_agents[0]
        assert fa1.agent_id == "fa-1"
        assert fa1.agent_type == "free"
        assert fa1.skill.name == "debug"
        assert fa1.protected_by == "resp-1"
        fa2 = restored.free_agents[1]
        assert fa2.agent_id == "fa-2"
        assert fa2.skill is None
        assert fa2.protected_by == "resp-1"

        # Economic state
        assert restored.agent_prices == {"fa-1": 1000, "fa-2": 2000}
        assert restored.agent_bankruptcy_rates["fa-1"] == pytest.approx(0.1)

        # Training metadata
        assert restored.last_etas["ws-1"] == pytest.approx(1.5)
        assert restored.adaptive_multiplier_value == pytest.approx(1.15)
        assert restored.total_episodes == 10
        assert restored.budget_hint == 50000

    def test_artifact_empty_free_agents(self):
        """Artifact with no free agents roundtrips correctly."""
        artifact = GraphEmergenceArtifact(
            responsible_agent=Agent(
                agent_id="solo",
                soul=Soul(system_prompt="solo agent"),
                agent_type="workspace_bound",
            ),
            free_agents=[],
            agent_prices={},
            agent_bankruptcy_rates={},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=0,
            budget_hint=10000,
        )
        restored = GraphEmergenceArtifact.model_validate_json(
            artifact.model_dump_json()
        )
        assert len(restored.free_agents) == 0
        assert restored.agent_prices == {}

    def test_artifact_preserves_agent_order(self):
        """Free agents maintain their list order through serialization."""
        artifact = self._make_artifact()
        restored = GraphEmergenceArtifact.model_validate_json(
            artifact.model_dump_json()
        )
        ids = [a.agent_id for a in restored.free_agents]
        assert ids == ["fa-1", "fa-2"]

    def test_no_redundant_schema_needed(self):
        """Agent IS the schema: no SoulSchema/SkillSchema/FreeAgentSchema needed."""
        agent = Agent(
            agent_id="direct",
            soul=Soul(system_prompt="p"),
            agent_type="free",
            skill=Skill(name="n", description="d", content="c"),
            protected_by="parent",
            protecting=[],
        )
        artifact = GraphEmergenceArtifact(
            responsible_agent=agent,
            free_agents=[agent],
            agent_prices={"direct": 500},
            agent_bankruptcy_rates={"direct": 0.0},
            last_etas={},
            adaptive_multiplier_value=1.0,
            total_episodes=1,
            budget_hint=5000,
        )
        # Must serialize/deserialize without any Schema intermediary.
        json_str = artifact.model_dump_json()
        restored = GraphEmergenceArtifact.model_validate_json(json_str)
        assert restored.free_agents[0].agent_id == "direct"
        assert restored.free_agents[0].protected_by == "parent"
