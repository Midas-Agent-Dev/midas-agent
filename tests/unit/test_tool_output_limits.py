"""Unit tests for tool output size limits.

These tests verify that search_code, read_file, and find_files
produce bounded output suitable for LLM context windows.

Key requirements (modeled after Claude Code / SWE-agent patterns):
- search_code: default returns files_with_matches only, limits results count,
  uses relative paths
- read_file: default limit on lines returned, prompts user to paginate
- find_files: limits result count
"""
import os

import pytest

from midas_agent.stdlib.actions.search import SearchCodeAction, FindFilesAction
from midas_agent.stdlib.actions.file_ops import ReadFileAction


# ===========================================================================
# SearchCodeAction output limits
# ===========================================================================


@pytest.mark.unit
class TestSearchCodeOutputLimits:
    """SearchCodeAction must produce bounded, context-efficient output."""

    def _make_repo(self, tmp_path, n_files=50, lines_per_file=100):
        """Create a repo with many files, each containing 'target_pattern'."""
        for i in range(n_files):
            f = tmp_path / f"module_{i}.py"
            lines = []
            for j in range(lines_per_file):
                if j == 50:
                    lines.append(f"def target_pattern_{i}():  # match here\n")
                else:
                    lines.append(f"    line_{j} = {i * 100 + j}\n")
            f.write_text("".join(lines))
        return tmp_path

    def test_search_returns_relative_paths(self, tmp_path):
        """Search results must use relative paths, not absolute paths.

        Absolute paths like /var/folders/c9/.../ws-0/astropy/modeling/core.py
        waste ~30 tokens per line. Relative paths save context."""
        (tmp_path / "src" / "module.py").parent.mkdir(parents=True)
        (tmp_path / "src" / "module.py").write_text("def hello():\n    pass\n")

        action = SearchCodeAction(cwd=str(tmp_path))
        result = action.execute(pattern="def hello")

        assert str(tmp_path) not in result, (
            f"Search result should use relative paths, not absolute. Got: {result}"
        )
        assert "src/module.py" in result or "module.py" in result

    def test_search_limits_result_count(self, tmp_path):
        """Search with many matches must cap the number of results.

        In a large repo, a broad pattern can match hundreds of files.
        Unbounded results bloat the context."""
        self._make_repo(tmp_path, n_files=100)

        action = SearchCodeAction(cwd=str(tmp_path))
        result = action.execute(pattern="target_pattern")

        # Should have a reasonable limit (e.g., 30-50 results, not 100)
        result_lines = [l for l in result.strip().split("\n") if l.strip()]
        assert len(result_lines) <= 50, (
            f"Search returned {len(result_lines)} lines, should cap at ~30-50"
        )

    def test_search_indicates_truncation(self, tmp_path):
        """When results are truncated, output must indicate more exist."""
        self._make_repo(tmp_path, n_files=100)

        action = SearchCodeAction(cwd=str(tmp_path))
        result = action.execute(pattern="target_pattern")

        # If results were capped, there should be an indication
        result_lines = [l for l in result.strip().split("\n") if l.strip()]
        if len(result_lines) < 100:
            # Result was capped — should mention more results exist
            assert "more" in result.lower() or "truncated" in result.lower() or "..." in result, (
                f"Truncated results should indicate more exist. Got:\n{result[-200:]}"
            )

    def test_search_default_mode_files_only(self, tmp_path):
        """Default search mode should return file paths with line numbers,
        not full line content. This matches Claude Code's default
        files_with_matches mode.

        Returning full line content for every match wastes context when
        the agent just needs to know WHICH files to read."""
        (tmp_path / "a.py").write_text(
            "def foo():\n    x = very_long_variable_name_that_wastes_tokens * 42\n"
        )

        action = SearchCodeAction(cwd=str(tmp_path))
        result = action.execute(pattern="very_long_variable_name")

        # Result should contain the file name
        assert "a.py" in result
        # Result should contain the line number
        assert "2" in result or ":2:" in result

    def test_search_max_results_parameter(self, tmp_path):
        """search_code should accept a max_results parameter to let the
        agent control how many results to see."""
        self._make_repo(tmp_path, n_files=50)

        action = SearchCodeAction(cwd=str(tmp_path))
        result = action.execute(pattern="target_pattern", max_results=5)

        result_lines = [l for l in result.strip().split("\n") if l.strip() and "more" not in l.lower() and "truncated" not in l.lower()]
        assert len(result_lines) <= 5, (
            f"max_results=5 but got {len(result_lines)} result lines"
        )


# ===========================================================================
# ReadFileAction output limits
# ===========================================================================


@pytest.mark.unit
class TestReadFileOutputLimits:
    """ReadFileAction must produce bounded output by default."""

    def _make_big_file(self, tmp_path, n_lines=500):
        """Create a file with many lines."""
        f = tmp_path / "big_module.py"
        lines = [f"line_{i} = {i}  # content for line {i}\n" for i in range(n_lines)]
        f.write_text("".join(lines))
        return f

    def test_read_without_limit_caps_at_default(self, tmp_path):
        """Reading a large file without specifying limit should return
        at most a default number of lines (e.g., 200), not the full file.

        A 500-line file read fully adds ~2000 tokens to context. With
        a 200-line default, it's ~800 tokens — much more manageable."""
        self._make_big_file(tmp_path, n_lines=500)

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="big_module.py")

        result_lines = result.strip().split("\n")
        assert len(result_lines) <= 250, (
            f"read_file without limit returned {len(result_lines)} lines, "
            f"should default-cap at ~200 lines"
        )

    def test_read_indicates_more_content(self, tmp_path):
        """When output is capped, must indicate that more lines exist
        and how to read them (offset/limit)."""
        self._make_big_file(tmp_path, n_lines=500)

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="big_module.py")

        # Should mention total lines and how to see more
        assert "500" in result or "more" in result.lower() or "offset" in result.lower(), (
            f"Capped output should indicate total lines / how to read more. "
            f"Last 200 chars: {result[-200:]}"
        )

    def test_read_with_explicit_limit_respected(self, tmp_path):
        """Explicit limit parameter overrides the default cap."""
        self._make_big_file(tmp_path, n_lines=500)

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="big_module.py", limit=50)

        result_lines = result.strip().split("\n")
        assert len(result_lines) <= 55, (
            f"limit=50 but got {len(result_lines)} lines"
        )

    def test_read_small_file_returns_all(self, tmp_path):
        """A small file (under default limit) is returned in full."""
        (tmp_path / "small.py").write_text("x = 1\ny = 2\nz = 3\n")

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="small.py")

        assert "x = 1" in result
        assert "y = 2" in result
        assert "z = 3" in result

    def test_read_includes_line_numbers(self, tmp_path):
        """Output should include line numbers for use with edit_file."""
        (tmp_path / "code.py").write_text("aaa\nbbb\nccc\n")

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="code.py")

        # Should have line numbers (1-indexed)
        assert "1" in result
        assert "aaa" in result

    def test_read_offset_works_with_default_limit(self, tmp_path):
        """offset + default limit reads a window from the middle."""
        self._make_big_file(tmp_path, n_lines=500)

        action = ReadFileAction(cwd=str(tmp_path))
        result = action.execute(path="big_module.py", offset=300)

        # Should start from line 300, not line 0
        assert "line_300" in result or "line_301" in result
        # Should be capped, not return all 200 remaining lines if default is lower
        result_lines = result.strip().split("\n")
        assert len(result_lines) <= 250


# ===========================================================================
# FindFilesAction output limits
# ===========================================================================


@pytest.mark.unit
class TestFindFilesOutputLimits:
    """FindFilesAction must produce bounded output."""

    def _make_many_files(self, tmp_path, n_files=200):
        """Create a repo with many Python files."""
        for i in range(n_files):
            sub = tmp_path / f"pkg_{i // 20}"
            sub.mkdir(exist_ok=True)
            (sub / f"module_{i}.py").write_text(f"# module {i}\n")

    def test_find_limits_result_count(self, tmp_path):
        """Finding files in a large repo must cap the number of results."""
        self._make_many_files(tmp_path, n_files=200)

        action = FindFilesAction(cwd=str(tmp_path))
        result = action.execute(pattern="**/*.py")

        result_lines = [l for l in result.strip().split("\n") if l.strip()]
        assert len(result_lines) <= 50, (
            f"find_files returned {len(result_lines)} results, "
            f"should cap at ~50"
        )

    def test_find_indicates_truncation(self, tmp_path):
        """When results are capped, output indicates more files exist."""
        self._make_many_files(tmp_path, n_files=200)

        action = FindFilesAction(cwd=str(tmp_path))
        result = action.execute(pattern="**/*.py")

        result_lines = [l for l in result.strip().split("\n") if l.strip()]
        if len(result_lines) < 200:
            assert "more" in result.lower() or "truncated" in result.lower() or "..." in result, (
                f"Truncated find results should indicate more exist"
            )

    def test_find_returns_relative_paths(self, tmp_path):
        """Found file paths must be relative, not absolute."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("")

        action = FindFilesAction(cwd=str(tmp_path))
        result = action.execute(pattern="**/*.py")

        assert str(tmp_path) not in result, (
            f"find_files should return relative paths. Got: {result}"
        )
        assert "src/app.py" in result or "app.py" in result

    def test_find_small_result_returns_all(self, tmp_path):
        """A small number of matches returns all results."""
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")

        action = FindFilesAction(cwd=str(tmp_path))
        result = action.execute(pattern="*.py")

        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_find_max_results_parameter(self, tmp_path):
        """find_files should accept a max_results parameter."""
        self._make_many_files(tmp_path, n_files=100)

        action = FindFilesAction(cwd=str(tmp_path))
        result = action.execute(pattern="**/*.py", max_results=10)

        result_lines = [l for l in result.strip().split("\n") if l.strip() and "more" not in l.lower()]
        assert len(result_lines) <= 10
