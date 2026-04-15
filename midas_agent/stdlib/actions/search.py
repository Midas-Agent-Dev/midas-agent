"""Search actions — code search and file find."""
from midas_agent.stdlib.action import Action


class SearchCodeAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "search_code"

    @property
    def description(self) -> str:
        cwd_note = f"The current working directory is: {self.cwd}\n" if self.cwd else ""
        return (
            "Searches file contents using regular expressions. Powered by "
            "ripgrep for fast, reliable results across large codebases.\n\n"
            f"{cwd_note}"
            "Usage:\n"
            " - Supports full regex syntax (e.g. `log.*Error`, "
            "`def\\s+\\w+`, `class\\s+MyClass`).\n"
            " - Filter files by glob with the `include` parameter (e.g. "
            "`*.py`, `*.{js,ts}`, `tests/**/*.py`).\n"
            " - Returns file paths and matching lines. Use `read_file` to "
            "read the full context around a match.\n"
            " - You can call multiple tools in a single response. When you "
            "are not sure which file contains the code you need, issue "
            "multiple searches in parallel with different patterns rather "
            "than searching one-by-one — this is faster and costs fewer "
            "iterations.\n\n"
            "# Tips for effective searching\n"
            " - Search for function/class definitions: `def function_name`, "
            "`class ClassName`\n"
            " - Search for imports: `from module import`, `import module`\n"
            " - Search for error messages: use a distinctive substring from "
            "the error\n"
            " - If a search returns too many results, narrow it with "
            "`include` or a more specific pattern\n"
            " - If a search returns no results, broaden the pattern or try "
            "alternative names\n\n"
            "IMPORTANT: ALWAYS use this tool instead of running `grep` or "
            "`rg` via `bash`. This tool is optimized for the workspace "
            "environment."
        )

    @property
    def parameters(self) -> dict:
        return {
            "pattern": {"type": "string", "required": True},
            "path": {"type": "string", "required": False},
            "include": {"type": "string", "required": False},
        }

    def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        return f"Search results for: {pattern}"


class FindFilesAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def description(self) -> str:
        cwd_note = f"The current working directory is: {self.cwd}\n" if self.cwd else ""
        return (
            "Fast file pattern matching tool that finds files by name using "
            "glob patterns. Returns matching file paths sorted by modification "
            "time.\n\n"
            f"{cwd_note}"
            "Usage:\n"
            " - Supports glob patterns like `**/*.py`, `src/**/*.ts`, "
            "`**/test_*.py`.\n"
            " - Use this when you need to find files by name or path "
            "pattern, not by content. For searching inside files, use "
            "`search_code` instead.\n"
            " - The `path` parameter narrows the search to a subdirectory "
            "(e.g. `path='src/models'` to only search within that folder).\n"
            " - You can call multiple tools in a single response. When "
            "exploring an unfamiliar codebase, issue multiple find_files "
            "calls in parallel with different patterns to quickly map the "
            "project structure.\n\n"
            "IMPORTANT: ALWAYS use this tool instead of running `find` or "
            "`ls` via `bash`. This tool is faster and works correctly in "
            "the workspace environment."
        )

    @property
    def parameters(self) -> dict:
        return {
            "pattern": {"type": "string", "required": True},
            "path": {"type": "string", "required": False},
        }

    def execute(self, **kwargs) -> str:
        pattern = kwargs["pattern"]
        return f"Found files matching: {pattern}"
