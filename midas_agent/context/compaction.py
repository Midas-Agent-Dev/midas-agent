"""Conversation compaction — build prompts and histories for LLM-based compression."""
from __future__ import annotations

from midas_agent.context.truncation import truncate_output

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPACTION_PROMPT = """\
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff \
summary for another LLM that will resume the task.

You MUST include ALL of the following sections:

## Files identified
List every file path that was found relevant, with a one-line reason.

## Actions attempted and results
List every significant action (edits, test runs, reproductions) with \
its outcome. This is CRITICAL — the next LLM must know what was \
already tried so it does NOT repeat the same actions.

## Current status
Where in the workflow are we? What step? What is working, what is not?

## Remaining work
Concrete next steps. What should the next LLM do first?

## Key findings
Root cause analysis, error messages observed, important code snippets.

Here are two examples of good compaction summaries:

<example_1>
## Files identified
- /testbed/astropy/timeseries/core.py — contains _check_required_columns validation
- /testbed/astropy/timeseries/sampled.py — TimeSeries subclass
- /testbed/astropy/timeseries/tests/test_sampled.py — relevant tests

## Actions attempted and results
1. Reproduced bug with reproduce_issue.py → confirmed misleading error message
2. Edited core.py line 73: changed elif to check missing columns separately → ERROR: test_required_columns failed
3. Reverted with git checkout, tried approach 2: added len() check before comparison → ERROR: still shows wrong message
4. Reverted again

## Current status
In the "fix" step. Two fix attempts failed. The root cause is in _check_required_columns but the correct fix approach is not yet clear.

## Remaining work
- Try approach 3: split the elif into two checks — one for missing columns, one for wrong order
- Run test_sampled.py to verify
- Do NOT modify test files

## Key findings
- The error message formats required_columns[:len(colnames)] which truncates the expected list, making it match the actual list when columns are missing
- The fix must distinguish "columns missing" from "columns in wrong order"
</example_1>

<example_2>
## Files identified
- /testbed/django/db/models/sql/compiler.py — SQL compilation, COUNT/DISTINCT handling
- /testbed/django/db/models/aggregates.py — Aggregate class, Count class
- /testbed/tests/aggregation/tests.py — aggregation test suite

## Actions attempted and results
1. Searched for "COUNT.*DISTINCT" in codebase → found compiler.py and aggregates.py
2. Read compiler.py lines 100-150 → found as_sql method
3. Ran reproduction script → confirmed wrong SQL generated for Count with filter
4. Edited compiler.py line 130 → ERROR: broke other tests (test_count_star failed)
5. Reverted edit

## Current status
In the "investigate" step. Found the two relevant files but the first fix attempt was wrong — the issue is in aggregates.py not compiler.py.

## Remaining work
- Read aggregates.py Count.as_sql() method
- The CASE WHEN wrapping likely needs to happen inside Count, not in the compiler
- Do NOT search for more files — the relevant code is already identified

## Key findings
- The bug is that Count(distinct=True, filter=Q(...)) generates wrong SQL
- compiler.py handles generic SQL compilation — changing it breaks other aggregates
- aggregates.py Count class is where the DISTINCT + CASE WHEN logic should be fixed
</example_2>

Now produce the compaction summary for the conversation above."""

SUMMARY_PREFIX = """\
Another language model started working on this problem. Below is its \
progress summary. IMPORTANT: Read the "Actions attempted and results" \
section carefully — do NOT repeat actions that were already tried. \
Build on what was already done and continue from where it left off:"""

# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def should_compact(total_tokens: int, context_window: int, ratio: float = 0.9) -> bool:
    """Return ``True`` when *total_tokens* reaches *ratio* of the context window."""
    if context_window <= 0:
        return False
    return total_tokens >= int(context_window * ratio)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_compaction_prompt(messages: list[dict]) -> list[dict]:
    """Return a message list suitable for asking an LLM to produce a compaction summary.

    The returned list contains all original *messages* followed by a final user
    message with the ``COMPACTION_PROMPT``.
    """
    return list(messages) + [{"role": "user", "content": COMPACTION_PROMPT}]


# ---------------------------------------------------------------------------
# Post-compaction history
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token per 4 characters."""
    return len(text) // 4


def build_compacted_history(
    old_messages: list[dict],
    summary: str,
    max_user_message_tokens: int = 20000,
) -> list[dict]:
    """Build a new, smaller conversation history after compaction.

    Algorithm:
    1. Extract only ``role="user"`` messages from *old_messages*.
    2. Reserve the first user message (the issue description) — it is always
       kept in full and placed first in the result.
    3. Walk the remaining user messages from newest to oldest, accumulating
       until *max_user_message_tokens* is exhausted.  If a message does not
       fully fit, it is truncated (middle-elision) to fill the remaining
       budget, then iteration stops.
    4. Reverse the collected messages back to chronological order.
    5. Build result: ``[first_user_message] + [recent messages] + [summary]``.
    """
    user_messages = [m for m in old_messages if m.get("role") == "user"]

    # --- Reserve the first user message (the issue) -----------------------
    first_user_msg: dict | None = None
    remaining_user_messages: list[dict] = user_messages
    if user_messages:
        first_user_msg = user_messages[0]
        remaining_user_messages = user_messages[1:]

    budget_chars = max_user_message_tokens * 4  # inverse of token estimate
    collected: list[dict] = []
    used_chars = 0

    # Iterate newest-first over remaining (non-issue) user messages
    for msg in reversed(remaining_user_messages):
        content = msg["content"]
        msg_chars = len(content)

        remaining = budget_chars - used_chars
        if remaining <= 0:
            break

        if msg_chars <= remaining:
            collected.append({"role": "user", "content": content})
            used_chars += msg_chars
        else:
            # Truncate this message to fit and stop
            truncated = truncate_output(content, max_chars=remaining)
            collected.append({"role": "user", "content": truncated})
            break

    # Reverse to chronological order
    collected.reverse()

    # Build result: issue first, then recent messages, then summary
    result: list[dict] = []
    if first_user_msg is not None:
        result.append({"role": "user", "content": first_user_msg["content"]})
    result.extend(collected)

    # Append compaction summary
    result.append({"role": "user", "content": SUMMARY_PREFIX + "\n" + summary})

    return result
