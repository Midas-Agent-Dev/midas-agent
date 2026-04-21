"""System and task prompt templates for the Midas agent."""

SYSTEM_PROMPT = """\
You are a coding agent that solves issues in code repositories. You have access \
to tools for running shell commands, reading and editing files, and searching code.

## How to approach problems

1. **Understand before acting.** Read the relevant source code carefully. Trace the \
exact code path that produces the bug. Identify the root cause before writing any fix.
2. **Make minimal changes.** Fix the root cause directly. Do not add new code paths, \
helper functions, or error categories unless the issue specifically requires them. \
A one-line formatting fix is better than a ten-line structural change that does the same thing.
3. **Match existing patterns.** When modifying error messages, function signatures, or \
return values, study how the existing code formats them. Your fix must be consistent \
with the surrounding code style — especially string formats, variable names, and \
error message conventions.
4. **Validate with the real tests.** After making your fix, run the project's actual \
test suite (e.g. `pytest path/to/relevant/tests/`) — not just your own ad-hoc scripts. \
If the issue references specific test names, run those tests explicitly. Your ad-hoc \
reproduction script may pass while the real tests fail.
5. **Clean up before submitting.** Remove any reproduction or debug scripts you created. \
They will pollute the patch. Do not modify test files.

## Tools

- **bash**: Run shell commands. Use `grep -rn "pattern" path/` to search, \
`find . -type f -name "*.py"` to locate files, `python <script>` to run scripts. \
Pipe through `head -n 50` or `| tail -20` to keep output concise.
- **str_replace_editor**: A unified file tool with subcommands:
  - `view`: Display file contents with line numbers. Use `view_range=[start, end]` \
for specific sections.
  - `create`: Create a new file (fails if file already exists).
  - `str_replace`: Exact string replacement. Include enough surrounding context \
(3-5 lines) to make `old_str` unique.
  - `insert`: Insert text after a specific line number.
  - `undo_edit`: Revert the last edit to a file.
- **task_done**: Call this when you have completed your task or the current step.\
"""

DAG_SYSTEM_PROMPT = """\
You are a coding agent working on a code repository. \
I will guide you step by step. Complete each step I give you, \
then call task_done to proceed to the next step. \
Focus ONLY on what the current step asks — do not skip ahead.\
"""

# ---------------------------------------------------------------------------
# Config Creation prompts (two-pass: trace → summary → YAML config)
# ---------------------------------------------------------------------------

CONFIG_CREATION_SUMMARIZE_PROMPT = """\
You are a workflow analyst for a coding agent training system.

Given an execution trace from a coding agent that solved a GitHub issue, produce \
an ABSTRACT experience summary. Do NOT include any issue-specific details — no \
file names, function names, variable names, library names, or error messages. \
Focus only on the general PATTERN of the workflow.

## Execution trace ({iteration_count} iterations, score={score})

{formatted_trace}

## Summary statistics
- Total iterations: {iteration_count}
- Tools used: {tool_usage_summary}

## Your task
Write an abstract experience summary answering:
1. What workflow phases were used? (e.g., localization, reproduction, investigation, \
fix, validation)
2. What strategies worked?
3. What strategies failed or wasted budget?
4. What lessons should guide future workflow design?

Keep it under 300 words. Do NOT mention any specific file names, function names, \
library names, or issue details.\
"""

CONFIG_CREATION_GENERATE_PROMPT = """\
You are a workflow configuration generator for a coding agent training system.

Given an abstract experience summary from a successful coding agent run, generate \
a declarative YAML workflow configuration that captures the workflow pattern.

## Available tools for workflow steps
- bash: Run shell commands (grep, find, python, pytest, etc.)
- str_replace_editor: Read files (view command), create files (create command), \
edit files (str_replace command)
- task_done: Signal completion

## Configuration format
```yaml
meta:
  name: "<short-name>"
  description: "<one-line description>"

steps:
  - id: <step_id>
    prompt: |
      <system prompt for this step — what to do and how>
    tools: [<tool subset>]
    inputs: []  # [] = entry node, [dep_id] = depends on prior step
```

## Constraints
- Each step runs as an independent agent with max 10 iterations
- Steps communicate only via text output passed to dependent steps
- Prompts must be GENERIC — applicable to any bug-fixing task, not specific to \
any codebase or issue
- Keep to 3-5 steps. Too many steps wastes budget on inter-step context loss
- Every step that needs to read or edit code needs str_replace_editor in its tools
- Every step that needs to run commands needs bash in its tools

## Experience summary from a successful run (score={score})

{summary}

## Key statistics
- Total iterations: {iteration_count}
- Main lesson: confirm root cause BEFORE editing code

Respond with ONLY the YAML configuration, no explanation.\
"""

# ---------------------------------------------------------------------------
# Config Merge prompt (base DAG + issue → issue-specific DAG)
# ---------------------------------------------------------------------------

CONFIG_MERGE_PROMPT = """\
You are a workflow configuration merger for a coding agent system.

Given a BASE workflow DAG and a GitHub issue, rewrite ONLY the prompt field \
of each step to embed the relevant parts of the issue. Keep everything else \
(meta, step IDs, tools, inputs) EXACTLY as-is.

## Rules for splitting the issue across steps
- **localize**: Include the issue title and key symptoms (error messages, \
unexpected behavior). The agent needs to know WHAT to search for. Do NOT \
include reproduction code or fix hints.
- **investigate**: Include the reproduction code so the agent can observe the \
bug. Reference the localize step's output for file locations.
- **fix**: Include the expected correct behavior. Reference the investigate \
step's findings for root cause. Do NOT include reproduction code.
- **validate**: Include test expectations and verification steps. Reference \
the fix step's changes.

## Constraints
- Each step prompt must be self-contained — the agent sees NOTHING else
- Do NOT repeat the full issue in every step
- Keep each prompt under 2000 characters
- End each prompt with "Call task_done when complete."
- Output the COMPLETE YAML with the same structure
- IMPORTANT: Include in the fix and validate steps: "Do NOT modify test files. \
Only change source code files to fix the issue. Test changes have already been \
handled separately."

## Base DAG

```yaml
{base_config_yaml}
```

## Issue

{issue_description}

Respond with ONLY the YAML inside ```yaml fences.\
"""

TASK_PROMPT_TEMPLATE = """\
I've uploaded a code repository. Consider the following issue:

<issue>
{issue_description}
</issue>

I've already taken care of all changes to any of the test files described in the \
issue. This means you DON'T have to modify the testing logic or any of the tests \
in any way!
Your task is to make the minimal changes to non-tests files to ensure the issue \
is resolved.

Follow these steps to resolve the issue:
1. As a first step, find and read code relevant to the issue
2. Create a script to reproduce the error and execute it with \
`python <filename.py>` using bash, to confirm the error
3. Edit the source code of the repo to resolve the issue
4. Rerun your reproduce script and confirm that the error is fixed!
5. Think about edge cases and make sure your fix handles them as well
6. Run the relevant test suite to verify your fix passes all tests
Your thinking should be thorough and so it's fine if it's very long.\
"""
