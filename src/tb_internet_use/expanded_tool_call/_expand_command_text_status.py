"""Expand the end state of the command text of one call from its own result and from the later polls of the handles it started.

A command run in the background returns before it ends, e.g. Claude Code `Bash` with `run_in_background` or Codex `exec_command`, so its own result says only that it is running. Its end and its exit code show up in a later poll of its handle, e.g. Claude Code `TaskOutput` or Codex `write_stdin`.
"""

from collections import Counter
from collections.abc import Sequence

from tb_internet_use.expanded_tool_call._expand_poll_links import (
    handles_of_poll_action,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_first_poll_that_saw_end_as_command_text_status,
)
from tb_internet_use.expanded_tool_call.model import CommandTextStatus
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    PollAction,
    RunCommandAction,
    ToolCall,
    ToolCallAction,
    ToolCallResult,
)

# Statuses that say the work ended, on its own or stopped, as opposed to running, not run or not known.
_ENDED_EXECUTION_STATUSES = frozenset(
    {ExecutionStatus.FINISHED, ExecutionStatus.TIMED_OUT, ExecutionStatus.KILLED}
)


def expand_command_text_status(
    tool_call: ToolCall,
    poll_tool_calls: Sequence[ToolCall],
    *,
    judgment_rule_use_counts: Counter[str],
) -> CommandTextStatus | None:
    """Expand the end state of the command text of a call, from the first later poll that saw it end or else from the call's own result.

    `poll_tool_calls` are the later calls that poll a handle the call started, in call order, as `PollLinks.poll_tool_call_keys_of_starter` lists them.
    The value is None for a call whose action is not a `RunCommandAction` with a command text, e.g. a poll, a read tool or a tool script, whose one result covers the texts of several steps.
    A call without a result gets `UNKNOWN` with itself as the reporter, since the trajectory does not say how its text ended.
    The polls are read only while the call's own result is running or unknown, since a result that ended or did not run already gives the end state.
    `treat_first_poll_that_saw_end_as_command_text_status` is asked once for a call that has a poll that saw the end, and each use adds one to `judgment_rule_use_counts`.
    """
    if (
        not isinstance(tool_call.action, RunCommandAction)
        or tool_call.action.command_str is None
    ):
        return None
    tool_call_key = tool_call.harness_tool_call.key
    result = tool_call.result
    if result is None:
        return CommandTextStatus(ExecutionStatus.UNKNOWN, None, tool_call_key)
    own_command_text_status = CommandTextStatus(
        result.execution_status, result.exit_code, tool_call_key
    )
    if result.execution_status not in (
        ExecutionStatus.RUNNING,
        ExecutionStatus.UNKNOWN,
    ):
        return own_command_text_status
    for poll_tool_call in poll_tool_calls:
        poll_result = poll_tool_call.result
        if poll_result is None or not _has_seen_end_of_one_handle(
            poll_tool_call.action, poll_result
        ):
            continue
        if not treat_first_poll_that_saw_end_as_command_text_status(
            use_counts=judgment_rule_use_counts
        ):
            return own_command_text_status
        return CommandTextStatus(
            poll_result.execution_status,
            poll_result.exit_code,
            poll_tool_call.harness_tool_call.key,
        )
    return own_command_text_status


def _has_seen_end_of_one_handle(
    action: ToolCallAction, poll_result: ToolCallResult
) -> bool:
    """Tell whether the action of a call is a poll of exactly one handle and its result says that the handle's work ended.

    Only a poll that is the call's action counts. A poll step of a tool script shares one result with the other steps, so that result is not the state of the polled handle.
    A poll of several handles has one result for all of them, so it does not say which of them ended.
    """
    return (
        isinstance(action, PollAction)
        and poll_result.execution_status in _ENDED_EXECUTION_STATUSES
        and len(handles_of_poll_action(action, poll_result.handles)) == 1
    )

