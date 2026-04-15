"""DelegateTask action — query hireable agents (Graph Emergence only)."""
from __future__ import annotations

from typing import Callable

from midas_agent.stdlib.action import Action


class DelegateTaskAction(Action):
    def __init__(
        self,
        find_candidates: Callable,
        spawn_callback: Callable | None = None,
        balance_provider: Callable[[], int] | None = None,
        calling_agent_id: str | None = None,
    ) -> None:
        self._find_candidates = find_candidates
        self._spawn_callback = spawn_callback
        self._balance_provider = balance_provider
        self._calling_agent_id = calling_agent_id

    @property
    def name(self) -> str:
        return "use_agent"

    @property
    def description(self) -> str:
        return (
            "This tool provides access to specialist sub-agents. Sub-agents "
            "start with a clean context window — fewer input tokens, more "
            "focused on the sub-task than continuing in your own bloated context.\n\n"
            "When to use this tool:\n"
            "* When a sub-task is independent and self-contained, delegate it.\n"
            "* When your context is already long (many file reads, tool results), "
            "a fresh agent is more token-efficient.\n"
            "* When the sub-task requires different expertise (e.g., writing tests "
            "vs fixing code), spawn a specialist.\n"
            "* Do NOT use if the next step depends on the result immediately "
            "and cannot proceed in parallel.\n\n"
            "Usage:\n"
            "* Use spawn to create new specialist agents: "
            "spawn=[\"debugger\", \"test writer\"]\n"
            "* Use agent_id to hire an existing agent from the market info "
            "shown in your plan.\n"
            "* Omit both to query available candidates.\n\n"
            "Spawned agents are under your protection (cost charged to your balance). "
            "Hired agents work in isolated sessions and return results via report_result."
        )

    @property
    def parameters(self) -> dict:
        return {
            "task_description": {"type": "string", "required": True},
            "spawn": {"type": "array", "items": {"type": "string"}, "required": False},
            "agent_id": {"type": "string", "required": False},
        }

    def _is_caller_protected(self) -> bool:
        """Check if the calling agent is protected by looking it up via candidates."""
        if self._calling_agent_id is None:
            return False
        # Use find_candidates with empty query to discover all agents,
        # then check if the calling agent has protected_by set.
        try:
            candidates = self._find_candidates("")
            for c in candidates:
                agent = getattr(c, "agent", None)
                if agent is not None and getattr(agent, "agent_id", None) == self._calling_agent_id:
                    return bool(getattr(agent, "protected_by", None))
        except Exception:
            pass
        return False

    def execute(self, **kwargs) -> str:
        task_description = kwargs["task_description"]
        spawn = kwargs.get("spawn", False)

        # Backward compat: spawn=True treated as spawn=[task_description]
        if spawn is True:
            spawn = [task_description]

        # Handle spawn request (list of specialist descriptions)
        if isinstance(spawn, list) and spawn and self._spawn_callback is not None:
            # Protected agents cannot spawn new agents
            if self._is_caller_protected():
                return "Protected agent cannot spawn new agents. Not allowed."
            lines: list[str] = []
            for desc in spawn:
                agent = self._spawn_callback(desc)
                aid = getattr(agent, "agent_id", None) or "new agent"
                lines.append(f"Spawned agent {aid} for: {desc}")
            return "\n".join(lines)

        candidates = self._find_candidates(task_description)
        lines: list[str] = []
        if not candidates:
            lines.append(f"No candidates found for: {task_description}")
        else:
            lines.append(f"Candidates for: {task_description}")
            for c in candidates:
                agent_id = getattr(c, "agent_id", None) or getattr(c.agent, "agent_id", str(c))
                price = getattr(c, "price", None)
                similarity = getattr(c, "similarity", None)
                parts = [f"  - {agent_id}"]
                if price is not None:
                    parts.append(f"price={price}")
                if similarity is not None:
                    parts.append(f"match={similarity:.1f}")
                # Label agents spawned by the caller as young agents
                if self._calling_agent_id is not None:
                    agent_obj = getattr(c, "agent", None)
                    if agent_obj is not None and getattr(agent_obj, "protected_by", None) == self._calling_agent_id:
                        parts.append("[幼年agent]")
                lines.append(", ".join(parts))

        # Always offer spawn option when spawn_callback is available
        if self._spawn_callback is not None:
            lines.append("Option: spawn a new agent for this task.")

        # Append balance information if provider is set
        if self._balance_provider is not None:
            balance = self._balance_provider()
            lines.append(f"[你的余额: {balance}]")

        return "\n".join(lines)
