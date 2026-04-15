"""Search actions — code search and file find."""
import os
import subprocess
from pathlib import Path

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
        include = kwargs.get("include")
        path = kwargs.get("path")

        search_dir = self.cwd or os.getcwd()
        if path:
            search_dir = os.path.join(search_dir, path)

        cmd: list[str]
        try:
            # Try ripgrep first
            cmd = ["rg", "-n", pattern]
            if include:
                cmd.extend(["--glob", include])
            cmd.append(search_dir)
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            if result.returncode == 1:
                # rg returns 1 when no matches
                return "No matches found"
            if result.returncode == 2:
                # rg error (e.g. bad regex) -- still return something useful
                return f"Search error: {result.stderr.strip()}"
            # returncode 0 but empty output
            return "No matches found"
        except FileNotFoundError:
            # rg not installed, fall back to grep
            cmd = ["grep", "-rnE", pattern]
            if include:
                cmd.extend(["--include", include])
            cmd.append(search_dir)
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
                return "No matches found"
            except Exception as e:
                return f"Search error: {e}"
        except Exception as e:
            return f"Search error: {e}"


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
        path = kwargs.get("path")

        base_dir = Path(self.cwd) if self.cwd else Path.cwd()
        if path:
            base_dir = base_dir / path

        matches = sorted(base_dir.glob(pattern))

        if not matches:
            return f"No files found matching: {pattern}"

        # Return paths relative to cwd (or base_dir if no cwd)
        cwd_path = Path(self.cwd) if self.cwd else Path.cwd()
        rel_paths: list[str] = []
        for m in matches:
            if m.is_file():
                try:
                    rel_paths.append(str(m.relative_to(cwd_path)))
                except ValueError:
                    rel_paths.append(str(m))

        if not rel_paths:
            return f"No files found matching: {pattern}"

        return "\n".join(rel_paths)
