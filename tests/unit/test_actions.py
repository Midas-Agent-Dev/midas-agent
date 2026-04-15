"""Unit tests for all action implementations."""
import pytest

from midas_agent.stdlib.actions.bash import BashAction
from midas_agent.stdlib.actions.file_ops import ReadFileAction, EditFileAction, WriteFileAction
from midas_agent.stdlib.actions.search import SearchCodeAction, FindFilesAction
from midas_agent.stdlib.actions.task_done import TaskDoneAction
from midas_agent.stdlib.actions.delegate_task import DelegateTaskAction
from midas_agent.stdlib.actions.report_result import ReportResultAction


@pytest.mark.unit
class TestBashAction:
    """Tests for BashAction."""

    def test_bash_action_name(self):
        """BashAction.name returns 'bash'."""
        action = BashAction()
        assert action.name == "bash"

    def test_bash_action_execute(self):
        """BashAction.execute() returns a string result."""
        action = BashAction()
        result = action.execute(command="ls")
        assert isinstance(result, str)


@pytest.mark.unit
class TestReadFileAction:
    """Tests for ReadFileAction."""

    def test_read_file_action_name(self):
        """ReadFileAction.name returns 'read_file'."""
        action = ReadFileAction()
        assert action.name == "read_file"

    def test_read_file_action_execute(self):
        """ReadFileAction.execute() returns a string result."""
        action = ReadFileAction()
        result = action.execute(path="/tmp/test.txt")
        assert isinstance(result, str)

    def test_description_includes_cwd(self):
        """When cwd is set, tool description must include the actual working
        directory so the LLM knows where files are."""
        action = ReadFileAction(cwd="/tmp/workspace/repo")
        desc = action.description
        assert "/tmp/workspace/repo" in desc
        assert "must be an absolute path" not in desc.lower(), \
            "Description should not mandate absolute paths — this causes LLM hallucination"

    def test_description_without_cwd_no_path_leak(self):
        """When cwd is None, description must not contain a spurious working
        directory value (no empty string or None injection)."""
        action = ReadFileAction(cwd=None)
        desc = action.description
        assert "None" not in desc
        # Still should not mandate absolute paths
        assert "must be an absolute path" not in desc.lower()

    def test_file_not_found_without_cwd_no_crash(self):
        """When cwd is not set, File not found still works without crash."""
        action = ReadFileAction(cwd=None)
        result = action.execute(path="/nonexistent/path/file.py")
        assert "File not found" in result

    def test_relative_path_resolves_with_cwd(self, tmp_path):
        """Relative paths resolve against cwd and read the file successfully."""
        cwd = str(tmp_path)
        (tmp_path / "hello.py").write_text("print('hello')\n")

        action = ReadFileAction(cwd=cwd)
        result = action.execute(path="hello.py")

        assert "print('hello')" in result
        assert "File not found" not in result


@pytest.mark.unit
class TestEditFileAction:
    """Tests for EditFileAction."""

    def test_edit_file_action_name(self):
        """EditFileAction.name returns 'edit_file'."""
        action = EditFileAction()
        assert action.name == "edit_file"

    def test_edit_file_action_execute(self):
        """EditFileAction.execute() returns a string result."""
        action = EditFileAction()
        result = action.execute(
            path="/tmp/test.txt",
            command="replace",
            start_line=1,
        )
        assert isinstance(result, str)


@pytest.mark.unit
class TestWriteFileAction:
    """Tests for WriteFileAction."""

    def test_write_file_action_name(self):
        """WriteFileAction.name returns 'write_file'."""
        action = WriteFileAction()
        assert action.name == "write_file"

    def test_write_file_action_execute(self):
        """WriteFileAction.execute() returns a string result."""
        action = WriteFileAction()
        result = action.execute(path="/tmp/test.txt", content="hello")
        assert isinstance(result, str)


@pytest.mark.unit
class TestSearchCodeAction:
    """Tests for SearchCodeAction."""

    def test_search_code_action_name(self):
        """SearchCodeAction.name returns 'search_code'."""
        action = SearchCodeAction()
        assert action.name == "search_code"

    def test_search_code_action_execute(self):
        """SearchCodeAction.execute() returns a string result."""
        action = SearchCodeAction()
        result = action.execute(pattern="def test_")
        assert isinstance(result, str)


@pytest.mark.unit
class TestFindFilesAction:
    """Tests for FindFilesAction."""

    def test_find_files_action_name(self):
        """FindFilesAction.name returns 'find_files'."""
        action = FindFilesAction()
        assert action.name == "find_files"

    def test_find_files_action_execute(self):
        """FindFilesAction.execute() returns a string result."""
        action = FindFilesAction()
        result = action.execute(pattern="*.py")
        assert isinstance(result, str)


@pytest.mark.unit
class TestTaskDoneAction:
    """Tests for TaskDoneAction."""

    def test_task_done_action_name(self):
        """TaskDoneAction.name returns 'task_done'."""
        action = TaskDoneAction()
        assert action.name == "task_done"

    def test_task_done_action_execute(self):
        """TaskDoneAction.execute() returns a string result."""
        action = TaskDoneAction()
        result = action.execute(summary="Task completed successfully.")
        assert isinstance(result, str)


@pytest.mark.unit
class TestDelegateTaskAction:
    """Tests for DelegateTaskAction."""

    def test_delegate_task_construction(self):
        """DelegateTaskAction can be constructed with a find_candidates callback."""
        action = DelegateTaskAction(find_candidates=lambda desc: [])
        assert action.name == "use_agent"

    def test_description_references_planning_context(self):
        """delegate_task description should reference the planning context
        for agent/pricing info, not duplicate it in the tool description."""
        action = DelegateTaskAction(find_candidates=lambda desc: [])
        desc = action.description
        # Should reference planning phase / market info
        assert "plan" in desc.lower() or "market" in desc.lower(), \
            f"Description should reference planning context: {desc}"
        # Should NOT contain the full delegation strategy guide —
        # that belongs in market_info during planning phase
        assert "when to delegate" not in desc.lower(), \
            f"Delegation strategy should be in market_info, not tool desc: {desc}"

    def test_delegate_task_output_includes_balance(self):
        """When balance_provider is set and querying candidates (no agent_id,
        no spawn), output includes current balance."""
        action = DelegateTaskAction(
            find_candidates=lambda desc: [],
            spawn_callback=lambda desc: None,
            balance_provider=lambda: 35000,
        )
        output = action.execute(task_description="fix bug")
        assert "35000" in output

    def test_delegate_task_no_balance_without_provider(self):
        """When balance_provider is None, output does not include balance."""
        action = DelegateTaskAction(
            find_candidates=lambda desc: [],
        )
        output = action.execute(task_description="fix bug")
        assert "余额" not in output and "balance" not in output.lower()

    def test_spawn_accepts_list_of_descriptions(self):
        """spawn parameter accepts a list of specialist descriptions and
        creates one agent per description (batch spawn)."""
        from midas_agent.workspace.graph_emergence.agent import Agent, Soul

        spawned: list[Agent] = []

        def spawn_callback(task_description: str) -> Agent:
            agent = Agent(
                agent_id=f"spawned-{len(spawned)}",
                soul=Soul(system_prompt=f"Specialist: {task_description}"),
                agent_type="free",
                protected_by="lead-1",
            )
            spawned.append(agent)
            return agent

        action = DelegateTaskAction(
            find_candidates=lambda desc: [],
            spawn_callback=spawn_callback,
        )
        output = action.execute(
            task_description="fix bugs",
            spawn=["debugger specialist", "test writer"],
        )

        assert len(spawned) == 2
        assert "spawned-0" in output
        assert "spawned-1" in output

    def test_spawn_single_item_list(self):
        """spawn with a single-item list creates exactly one agent."""
        from midas_agent.workspace.graph_emergence.agent import Agent, Soul

        spawned: list[Agent] = []

        def spawn_callback(task_description: str) -> Agent:
            agent = Agent(
                agent_id=f"spawned-{len(spawned)}",
                soul=Soul(system_prompt=f"Specialist: {task_description}"),
                agent_type="free",
                protected_by="lead-1",
            )
            spawned.append(agent)
            return agent

        action = DelegateTaskAction(
            find_candidates=lambda desc: [],
            spawn_callback=spawn_callback,
        )
        output = action.execute(
            task_description="fix bug",
            spawn=["parser specialist"],
        )

        assert len(spawned) == 1
        assert "spawned-0" in output

    def test_hire_with_agent_id(self):
        """When agent_id is specified, delegate_task triggers the hire path
        (synchronous execution, returns result)."""
        action = DelegateTaskAction(
            find_candidates=lambda desc: [],
        )
        # For now, just verify the parameter is accepted without error
        # Full hire-and-wait implementation is a separate concern
        output = action.execute(
            task_description="fix parsing bug",
            agent_id="expert-1",
        )
        assert isinstance(output, str)

    def test_candidate_output_labels_young_agents(self):
        """When candidates include agents protected by the caller, they must
        be labeled as 幼年agent so the LLM understands they are its own
        spawned agents (cheap, clean context)."""
        from midas_agent.workspace.graph_emergence.agent import Agent, Soul
        from midas_agent.workspace.graph_emergence.free_agent_manager import Candidate

        young_agent = Agent(
            agent_id="spawned-1",
            soul=Soul(system_prompt="specialist"),
            agent_type="free",
            protected_by="lead-1",
        )
        independent_agent = Agent(
            agent_id="expert-2",
            soul=Soul(system_prompt="expert"),
            agent_type="free",
            protected_by=None,
        )

        candidates = [
            Candidate(agent=young_agent, similarity=1.0, price=100),
            Candidate(agent=independent_agent, similarity=0.8, price=500),
        ]

        action = DelegateTaskAction(
            find_candidates=lambda desc: candidates,
            calling_agent_id="lead-1",
        )
        output = action.execute(task_description="fix parser")

        # Young agent (protected_by == calling_agent_id) should be labeled
        assert "幼年" in output, \
            f"Protected agent should be labeled as 幼年agent: {output}"
        assert "spawned-1" in output
        assert "expert-2" in output

    def test_candidate_output_no_young_label_for_independent(self):
        """Independent agents (not protected by caller) must NOT be labeled
        as 幼年agent."""
        from midas_agent.workspace.graph_emergence.agent import Agent, Soul
        from midas_agent.workspace.graph_emergence.free_agent_manager import Candidate

        independent = Agent(
            agent_id="expert-1",
            soul=Soul(system_prompt="expert"),
            agent_type="free",
            protected_by=None,
        )

        candidates = [
            Candidate(agent=independent, similarity=1.0, price=300),
        ]

        action = DelegateTaskAction(
            find_candidates=lambda desc: candidates,
            calling_agent_id="lead-1",
        )
        output = action.execute(task_description="fix bug")

        assert "expert-1" in output
        # No young label for independent agents
        lines_with_expert = [l for l in output.split("\n") if "expert-1" in l]
        for line in lines_with_expert:
            assert "幼年" not in line


@pytest.mark.unit
class TestReportResultAction:
    """Tests for ReportResultAction."""

    def test_report_result_construction(self):
        """ReportResultAction can be constructed with a report callback."""
        action = ReportResultAction(report=lambda result: None)
        assert action.name == "report_result"
