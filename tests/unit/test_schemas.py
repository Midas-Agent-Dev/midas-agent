"""Unit tests for production mode Pydantic schemas."""
import json

import pytest

from midas_agent.inference.schemas import GraphEmergenceArtifact
from midas_agent.workspace.graph_emergence.agent import Agent, Soul
from midas_agent.workspace.graph_emergence.skill import Skill


@pytest.mark.unit
class TestSoul:
    def test_roundtrip(self):
        soul = Soul(system_prompt="You are an expert.")
        data = soul.model_dump()
        restored = Soul.model_validate(data)
        assert restored.system_prompt == "You are an expert."


@pytest.mark.unit
class TestSkill:
    def test_roundtrip(self):
        skill = Skill(name="debug", description="Debugging", content="Steps...")
        data = skill.model_dump()
        restored = Skill.model_validate(data)
        assert restored.name == "debug"
        assert restored.description == "Debugging"
        assert restored.content == "Steps..."


@pytest.mark.unit
class TestAgent:
    def test_roundtrip_with_skill(self):
        agent = Agent(
            agent_id="fa-1",
            soul=Soul(system_prompt="prompt"),
            agent_type="free",
            skill=Skill(name="s", description="d", content="c"),
        )
        data = agent.model_dump()
        restored = Agent.model_validate(data)
        assert restored.agent_id == "fa-1"
        assert restored.agent_type == "free"
        assert restored.skill is not None

    def test_roundtrip_without_skill(self):
        agent = Agent(
            agent_id="fa-2",
            soul=Soul(system_prompt="prompt"),
            agent_type="free",
        )
        restored = Agent.model_validate(agent.model_dump())
        assert restored.skill is None


@pytest.mark.unit
class TestGraphEmergenceArtifact:
    def _make_artifact(self) -> GraphEmergenceArtifact:
        return GraphEmergenceArtifact(
            responsible_agent=Agent(
                agent_id="resp",
                soul=Soul(system_prompt="responsible"),
                agent_type="workspace_bound",
            ),
            free_agents=[
                Agent(
                    agent_id="fa-1",
                    soul=Soul(system_prompt="free-1"),
                    agent_type="free",
                    skill=Skill(name="nav", description="code nav", content="..."),
                ),
                Agent(
                    agent_id="fa-2",
                    soul=Soul(system_prompt="free-2"),
                    agent_type="free",
                ),
            ],
            agent_prices={"fa-1": 1250, "fa-2": 3400},
            agent_bankruptcy_rates={"fa-1": 0.05, "fa-2": 0.30},
            budget_hint=58000,
        )

    def test_json_roundtrip(self):
        artifact = self._make_artifact()
        json_str = artifact.model_dump_json(indent=2)
        restored = GraphEmergenceArtifact.model_validate_json(json_str)
        assert restored.budget_hint == 58000
        assert len(restored.free_agents) == 2
        assert restored.responsible_agent.soul.system_prompt == "responsible"

    def test_free_agents_preserve_order(self):
        artifact = self._make_artifact()
        restored = GraphEmergenceArtifact.model_validate(artifact.model_dump())
        assert restored.free_agents[0].agent_id == "fa-1"
        assert restored.free_agents[1].agent_id == "fa-2"

    def test_empty_free_agents(self):
        artifact = GraphEmergenceArtifact(
            responsible_agent=Agent(
                agent_id="resp",
                soul=Soul(system_prompt="solo"),
                agent_type="workspace_bound",
            ),
            budget_hint=10000,
        )
        assert len(artifact.free_agents) == 0
        restored = GraphEmergenceArtifact.model_validate_json(artifact.model_dump_json())
        assert len(restored.free_agents) == 0
