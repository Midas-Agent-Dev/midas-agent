"""Agent and Soul for Graph Emergence."""

from pydantic import BaseModel, Field

from midas_agent.workspace.graph_emergence.skill import Skill


class Soul(BaseModel):
    system_prompt: str


class Agent(BaseModel):
    agent_id: str
    soul: Soul
    agent_type: str  # "workspace_bound" | "free"
    skill: Skill | None = None
    protected_by: str | None = None
    protecting: list[str] = Field(default_factory=list)
