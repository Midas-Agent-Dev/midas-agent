"""Relationship data class for Graph Emergence."""
from pydantic import BaseModel


class Relationship(BaseModel):
    type: str  # "protection" | "hire"
    from_agent_id: str
    to_agent_id: str
    workspace_id: str
    status: str  # "active" | "completed" | "terminated"
