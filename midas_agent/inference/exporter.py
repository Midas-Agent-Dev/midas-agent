"""Export training artifacts for production use."""
from __future__ import annotations

import os

from midas_agent.inference.schemas import (
    GraphEmergenceArtifact,
)
from midas_agent.workspace.config_evolution.snapshot_store import (
    ConfigSnapshotStore,
    SnapshotFilter,
)
from midas_agent.workspace.graph_emergence.agent import Agent
from midas_agent.workspace.graph_emergence.pricing import PricingEngine


def export_config_evolution(snapshot_store: ConfigSnapshotStore, output_path: str) -> str:
    """Export the highest-eta configuration as a YAML file.

    Returns the config_yaml content that was written.
    """
    snapshots = snapshot_store.query(SnapshotFilter(top_k=1))
    if not snapshots:
        raise ValueError("No snapshots found in store")

    config_yaml = snapshots[0].config_yaml
    with open(output_path, "w") as f:
        f.write(config_yaml)
    return config_yaml


def export_graph_emergence(
    responsible_agent: Agent,
    free_agents: list[Agent],
    pricing_engine: PricingEngine,
    hire_counts: dict[str, int],
    bankruptcy_counts: dict[str, int],
    budget_hint: int,
    output_path: str,
) -> GraphEmergenceArtifact:
    """Export the agent pool as a JSON artifact.

    Args:
        responsible_agent: The highest-eta responsible agent.
        free_agents: All free agents in the pool.
        pricing_engine: Used to get the final price for each agent.
        hire_counts: Total times each agent was hired (agent_id -> count).
        bankruptcy_counts: Total times each agent went bankrupt (agent_id -> count).
        budget_hint: Default budget for production (from training's most expensive issue).
        output_path: Where to write the JSON file.

    Returns the constructed artifact.
    """
    agent_prices = {
        fa.agent_id: pricing_engine.calculate_price(fa) for fa in free_agents
    }

    def _bankruptcy_rate(agent_id: str) -> float:
        hires = hire_counts.get(agent_id, 0)
        if hires == 0:
            return 0.0
        return bankruptcy_counts.get(agent_id, 0) / hires

    agent_bankruptcy_rates = {
        fa.agent_id: _bankruptcy_rate(fa.agent_id) for fa in free_agents
    }

    artifact = GraphEmergenceArtifact(
        responsible_agent=responsible_agent,
        free_agents=free_agents,
        agent_prices=agent_prices,
        agent_bankruptcy_rates=agent_bankruptcy_rates,
        budget_hint=budget_hint,
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(artifact.model_dump_json(indent=2))

    return artifact
