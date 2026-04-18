"""Unit tests for run_training entry point."""
from unittest.mock import patch, MagicMock

import pytest

from midas_agent.training import run_training, collect_patches, load_swe_bench
from midas_agent.config import MidasConfig
from midas_agent.types import Issue


@pytest.mark.unit
class TestRunTraining:
    """Tests for the run_training() orchestration function."""

    def _make_config(self, **kwargs) -> MidasConfig:
        """Helper to create a MidasConfig with sensible defaults."""
        defaults = dict(
            initial_budget=10000,
            workspace_count=4,
            runtime_mode="config_evolution",
        )
        defaults.update(kwargs)
        return MidasConfig(**defaults)

    def _make_issues(self, count: int = 2) -> list[Issue]:
        return [
            Issue(
                issue_id=f"test-issue-{i}",
                repo="",
                description=f"Fix bug {i}",
            )
            for i in range(count)
        ]

    def test_run_training_callable(self):
        """run_training is a callable function."""
        assert callable(run_training)

    def test_run_training_accepts_config(self):
        """run_training accepts a MidasConfig argument and completes without error."""
        config = self._make_config()
        result = run_training(config, issues=[])
        assert result is None

    def test_run_training_creates_scheduler(self):
        """run_training must internally create a Scheduler to orchestrate episodes."""
        config = self._make_config()

        with patch("midas_agent.training.Scheduler") as MockScheduler:
            mock_instance = MockScheduler.return_value
            mock_instance.get_workspaces.return_value = []
            mock_instance.create_workspaces.return_value = None
            mock_instance.allocate_budgets.return_value = None
            mock_instance.evaluate_and_select.return_value = ([], [], {})
            mock_instance.replace_evicted.return_value = None

            run_training(config, issues=self._make_issues(1))

            MockScheduler.assert_called_once()

    def test_run_training_episode_loop(self):
        """run_training runs one episode per issue."""
        config = self._make_config()
        issues = self._make_issues(2)

        with patch("midas_agent.training.Scheduler") as MockScheduler:
            mock_instance = MockScheduler.return_value
            mock_instance.get_workspaces.return_value = []
            mock_instance.create_workspaces.return_value = None
            mock_instance.allocate_budgets.return_value = None
            mock_instance.evaluate_and_select.return_value = ([], [], {})
            mock_instance.replace_evicted.return_value = None

            run_training(config, issues=issues)

            mock_instance.create_workspaces.assert_called_once()
            assert mock_instance.allocate_budgets.call_count == 2

    def test_run_training_returns_none(self):
        """run_training should return None after completing all episodes."""
        config = self._make_config()
        result = run_training(config, issues=[])
        assert result is None

    def test_run_training_empty_issues_no_episodes(self):
        """With no issues, no episodes are executed."""
        config = self._make_config()

        with patch("midas_agent.training.Scheduler") as MockScheduler:
            mock_instance = MockScheduler.return_value
            mock_instance.create_workspaces.return_value = None

            run_training(config, issues=[])

            mock_instance.create_workspaces.assert_called_once()
            mock_instance.allocate_budgets.assert_not_called()

    def test_run_training_full_episode_with_real_components(self):
        """Integration-style: run one episode with real (stub) components."""
        config = self._make_config(workspace_count=2)
        issues = self._make_issues(1)

        # Mock the SWE-bench scorer since we use fake issue IDs
        # that don't exist in the real SWE-bench dataset.
        with patch("midas_agent.evaluation.swebench_scorer.SWEBenchScorer.score", return_value=0.0):
            run_training(config, issues=issues)


@pytest.mark.unit
class TestCollectPatches:
    def test_collect_empty_patch(self):
        ws = MagicMock()
        ws.workspace_id = "ws-0"
        ws._last_patch = ""
        patches = collect_patches([ws])
        assert patches == {"ws-0": ""}

    def test_collect_existing_patch(self):
        ws = MagicMock()
        ws.workspace_id = "ws-0"
        ws._last_patch = "diff --git a/foo"
        patches = collect_patches([ws])
        assert patches["ws-0"] == "diff --git a/foo"

    def test_collect_reads_from_workspace_not_disk(self, tmp_path):
        """collect_patches reads from _last_patch, not from disk."""
        # Write a stale patch to disk to prove it is NOT read
        ws_dir = tmp_path / "ws-0"
        ws_dir.mkdir()
        (ws_dir / "stale.patch").write_text("stale content")

        ws = MagicMock()
        ws.workspace_id = "ws-0"
        ws._last_patch = "fresh content"
        patches = collect_patches([ws], str(tmp_path))
        assert patches["ws-0"] == "fresh content"
