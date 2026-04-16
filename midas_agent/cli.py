"""CLI argument parsing and action-set building for Midas Agent."""
from __future__ import annotations

import argparse

from midas_agent.stdlib.action import Action


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments with train/infer subcommands."""
    parser = argparse.ArgumentParser(prog="midas", description="Midas Agent CLI")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    # -- train subcommand --
    train_parser = subparsers.add_parser("train", help="Run training pipeline")
    train_parser.add_argument("--config", required=True, help="Path to training config YAML")
    train_parser.add_argument(
        "--output",
        default=".midas/agents/",
        help="Output directory for artifacts (default: .midas/agents/)",
    )

    # -- infer subcommand --
    infer_parser = subparsers.add_parser("infer", help="Run inference")
    infer_parser.add_argument("--artifact", default=None, help="Path to artifact file")
    infer_parser.add_argument("--model", default=None, help="LLM model name")
    infer_parser.add_argument("--budget", default=None, type=int, help="Token budget")
    infer_parser.add_argument(
        "--env",
        default="local",
        help='Execution environment: "local" or "docker" (default: local)',
    )

    return parser.parse_args(argv)


def build_action_set(cwd: str, env: str = "local") -> list[Action]:
    """Build a list of Action instances for inference mode."""
    if env == "docker":
        from midas_agent.stdlib.actions.docker_actions import (
            DockerBashAction,
            DockerEditFileAction,
            DockerFindFilesAction,
            DockerReadFileAction,
            DockerSearchCodeAction,
            DockerWriteFileAction,
        )
        from midas_agent.stdlib.actions.task_done import TaskDoneAction

        # Docker actions require a container_id; use a placeholder for now.
        # The real container_id is set at runtime before any action executes.
        container_id = ""
        return [
            DockerBashAction(container_id=container_id, cwd=cwd),
            DockerReadFileAction(container_id=container_id, cwd=cwd),
            DockerEditFileAction(container_id=container_id, cwd=cwd),
            DockerWriteFileAction(container_id=container_id, cwd=cwd),
            DockerSearchCodeAction(container_id=container_id, cwd=cwd),
            DockerFindFilesAction(container_id=container_id, cwd=cwd),
            TaskDoneAction(),
        ]

    # Default: local environment
    from midas_agent.stdlib.actions.bash import BashAction
    from midas_agent.stdlib.actions.file_ops import (
        EditFileAction,
        ReadFileAction,
        WriteFileAction,
    )
    from midas_agent.stdlib.actions.search import FindFilesAction, SearchCodeAction
    from midas_agent.stdlib.actions.task_done import TaskDoneAction

    return [
        BashAction(cwd=cwd),
        ReadFileAction(cwd=cwd),
        EditFileAction(cwd=cwd),
        WriteFileAction(cwd=cwd),
        SearchCodeAction(cwd=cwd),
        FindFilesAction(cwd=cwd),
        TaskDoneAction(),
    ]


def main(argv: list[str] | None = None) -> None:
    """Entry point for the CLI (not yet implemented)."""
    raise NotImplementedError
