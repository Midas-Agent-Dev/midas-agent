"""Bash action — shell command execution."""
import subprocess

from midas_agent.stdlib.action import Action


class BashAction(Action):
    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        cwd_note = f"The current working directory is: {self.cwd}\n" if self.cwd else ""
        return (
            "Executes a bash command and returns its output.\n\n"
            f"{cwd_note}"
            "The working directory persists between calls, but shell state "
            "(environment variables, shell functions, aliases) does not — each "
            "invocation starts a fresh shell. Use `&&` to chain sequential "
            "commands or `;` when you don't care if earlier commands fail. "
            "Do NOT use newlines to separate commands.\n\n"
            "IMPORTANT: Do NOT use this tool to run `cat`, `head`, `tail`, "
            "`sed`, `awk`, `grep`, or `find` commands. Use the appropriate "
            "dedicated tool instead, as it will be faster and more reliable:\n"
            " - Read files: use `read_file` (NOT cat/head/tail)\n"
            " - Search code: use `search_code` (NOT grep/rg)\n"
            " - Find files: use `find_files` (NOT find/ls)\n"
            " - Edit files: use `edit_file` (NOT sed/awk)\n\n"
            "Reserve `bash` exclusively for system commands, running tests, "
            "executing scripts, installing packages, and git operations that "
            "require actual shell execution.\n\n"
            "# Instructions\n"
            " - Always set the `description` parameter with a 5-10 word summary "
            "of what the command does.\n"
            " - Always quote file paths containing spaces with double quotes.\n"
            " - Interactive commands (python REPL, vim, nano, etc.) are NOT "
            "supported. To run a Python script, use `python script.py`.\n"
            " - If a command might take a long time, set an appropriate "
            "`timeout` (default 120 seconds, max 600).\n"
            " - If a command fails, read the error output carefully before "
            "retrying. Diagnose the root cause — do not blindly retry the "
            "same command."
        )

    @property
    def parameters(self) -> dict:
        return {
            "command": {"type": "string", "required": True},
            "timeout": {"type": "integer", "required": False, "default": 120},
            "description": {"type": "string", "required": False},
        }

    def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        timeout = kwargs.get("timeout", 120)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.cwd or None,
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += result.stderr
            return output
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout} seconds."
        except Exception as e:
            return f"Error executing command: {e}"
