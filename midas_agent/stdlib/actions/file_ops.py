"""File operation actions — read, edit, write."""
import ast
import os

from midas_agent.stdlib.action import Action


class ReadFileAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        cwd_note = f"The current working directory is: {self.cwd}\n" if self.cwd else ""
        return (
            "Reads a file from the local filesystem. You can access any file "
            "directly by using this tool.\n\n"
            f"{cwd_note}"
            "Usage:\n"
            " - Use relative paths from the working directory (e.g. "
            "`./src/module.py`), or absolute paths. Relative paths are "
            "resolved against the working directory.\n"
            " - By default, reads up to 2000 lines starting from the "
            "beginning of the file.\n"
            " - For large files, use `offset` and `limit` to read specific "
            "portions. When you already know which part of the file you need, "
            "only read that part — this saves tokens.\n"
            " - Results are returned with line numbers (1-indexed). Use these "
            "line numbers when calling `edit_file`.\n"
            " - You can call multiple tools in a single response. When multiple "
            "files might be relevant, read them all in parallel rather than "
            "sequentially — this is faster and avoids wasting iterations.\n"
            " - If the file does not exist, an error message is returned with "
            "the resolved path. Check the path and try again.\n\n"
            "IMPORTANT: You must read a file with this tool before editing it "
            "with `edit_file`. The edit tool will reference line numbers from "
            "this tool's output."
        )

    @property
    def parameters(self) -> dict:
        return {
            "path": {"type": "string", "required": True},
            "offset": {"type": "integer", "required": False},
            "limit": {"type": "integer", "required": False},
        }

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.cwd:
            return os.path.join(self.cwd, path)
        return path

    def execute(self, **kwargs) -> str:
        file_path = self._resolve(kwargs["path"])
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit")
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
            selected = lines[offset:] if limit is None else lines[offset:offset + limit]
            return "".join(selected)
        except FileNotFoundError:
            return f"File not found: {file_path}"
        except Exception as e:
            return f"Error reading file: {e}"


class EditFileAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edits an existing file using line-number-based operations.\n\n"
            "Usage:\n"
            " - You MUST use `read_file` at least once on a file before "
            "editing it. This tool references line numbers from `read_file` "
            "output. Editing without reading first will produce wrong results.\n"
            " - When editing, preserve the exact indentation (tabs/spaces) as "
            "it appears in the file. Incorrect indentation will break the code.\n"
            " - ALWAYS prefer editing existing source files in the repository. "
            "NEVER create new files when you can edit an existing one — this "
            "is how you produce a patch that fixes the issue.\n\n"
            "Three sub-commands:\n"
            " - `replace`: Replace lines from `start_line` to `end_line` "
            "(inclusive) with `new_content`. This is the most common operation "
            "for bug fixes.\n"
            " - `insert`: Insert `new_content` after `insert_line`. Use this "
            "to add new code without removing existing lines.\n"
            " - `delete`: Delete lines from `start_line` to `end_line` "
            "(inclusive). Use this to remove dead code.\n\n"
            "# Instructions\n"
            " - Line numbers are 1-indexed and reference the output of "
            "`read_file`.\n"
            " - For Python files, the edit is syntax-checked with `ast.parse` "
            "before being committed. If the syntax check fails, the edit is "
            "rejected and an error is returned — fix the syntax and retry.\n"
            " - After editing, the file's line numbers may shift. If you need "
            "to make another edit to the same file, call `read_file` again to "
            "get the updated line numbers.\n"
            " - To fix a bug, the typical workflow is:\n"
            "   1. `read_file` to understand the code\n"
            "   2. `edit_file(command='replace', ...)` to apply the fix\n"
            "   3. `bash` to run tests and verify the fix\n"
            "   4. `task_done` when satisfied"
        )

    @property
    def parameters(self) -> dict:
        return {
            "command": {"type": "string", "required": True},
            "path": {"type": "string", "required": True},
            "start_line": {"type": "integer", "required": False},
            "end_line": {"type": "integer", "required": False},
            "insert_line": {"type": "integer", "required": False},
            "new_content": {"type": "string", "required": False},
            "auto_indent": {"type": "boolean", "required": False, "default": True},
        }

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.cwd:
            return os.path.join(self.cwd, path)
        return path

    def execute(self, **kwargs) -> str:
        try:
            file_path = self._resolve(kwargs["path"])
        except KeyError:
            return "Error: missing required parameter 'path'"

        command = kwargs.get("command")
        if command is None:
            return f"Error: missing required parameter 'command' for {file_path}"

        # Read existing file
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return f"Error: file not found: {file_path}"
        except Exception as e:
            return f"Error reading file: {e}"

        # Apply the edit to produce new lines
        try:
            if command == "replace":
                start = kwargs["start_line"]
                end = kwargs["end_line"]
                new_content = kwargs.get("new_content", "")
                new_lines = new_content.splitlines(True)
                result_lines = lines[: start - 1] + new_lines + lines[end:]

            elif command == "insert":
                insert_line = kwargs["insert_line"]
                new_content = kwargs.get("new_content", "")
                new_lines = new_content.splitlines(True)
                result_lines = lines[:insert_line] + new_lines + lines[insert_line:]

            elif command == "delete":
                start = kwargs["start_line"]
                end = kwargs["end_line"]
                result_lines = lines[: start - 1] + lines[end:]

            else:
                return f"Error: unknown command '{command}'"
        except KeyError as e:
            return f"Error: missing required parameter {e} for command '{command}'"

        result_text = "".join(result_lines)

        # Syntax check for Python files
        if file_path.endswith(".py"):
            try:
                ast.parse(result_text)
            except SyntaxError as e:
                return f"Syntax error: {e}. Edit rejected; file unchanged."

        # Write back
        try:
            with open(file_path, "w") as f:
                f.write(result_text)
        except Exception as e:
            return f"Error writing file: {e}"

        return f"Edited {file_path}"


class WriteFileAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Writes a file to the local filesystem. Creates parent directories "
            "automatically if they do not exist.\n\n"
            "Usage:\n"
            " - This tool will overwrite the existing file if there is one at "
            "the provided path.\n"
            " - Prefer `edit_file` for modifying existing files — it only "
            "changes the lines you specify and preserves the rest. Only use "
            "`write_file` to create genuinely new files (e.g. test scripts, "
            "reproduction scripts).\n"
            " - NEVER use `write_file` to rewrite an entire source file when "
            "you only need to change a few lines. Use `edit_file` instead — "
            "the resulting diff will be cleaner and the patch more reviewable.\n\n"
            "IMPORTANT: New files created with `write_file` are useful for "
            "testing and reproduction, but they are NOT the fix. To fix a "
            "bug, you must edit the existing source files with `edit_file`. "
            "Your score is based on whether the repository's failing tests "
            "pass after your changes, not on new files you create."
        )

    @property
    def parameters(self) -> dict:
        return {
            "path": {"type": "string", "required": True},
            "content": {"type": "string", "required": True},
        }

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.cwd:
            return os.path.join(self.cwd, path)
        return path

    def execute(self, **kwargs) -> str:
        file_path = self._resolve(kwargs["path"])
        content = kwargs["content"]
        try:
            dir_name = os.path.dirname(file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)
            return f"Written {len(content)} bytes to {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"
