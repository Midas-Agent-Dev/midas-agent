"""Pydantic schemas for production mode artifact serialization."""
from __future__ import annotations

from pydantic import BaseModel, Field

from midas_agent.workspace.graph_emergence.agent import Agent


class GraphEmergenceArtifact(BaseModel):
    """Production artifact for Graph Emergence mode."""
    responsible_agent: Agent
    free_agents: list[Agent] = Field(default_factory=list)
    agent_prices: dict[str, int] = Field(default_factory=dict)
    agent_bankruptcy_rates: dict[str, float] = Field(default_factory=dict)
    last_etas: dict[str, float] = Field(default_factory=dict)
    adaptive_multiplier_value: float = 1.0
    total_episodes: int = 0
    budget_hint: int
