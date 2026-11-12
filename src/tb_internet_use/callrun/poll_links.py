"""Link each poll in a trial to the call that started what it polls, and read the status that the polls report.

A command run in the background ends in a later call, e.g. Claude Code `TaskOutput` or Codex `write_stdin`, so its exit code is in that poll's result.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tb_internet_use.callrun.model import CommandTextStatus
from tb_internet_use.toolcall.model import (
    ExecutionStatus,
    PollAction,
    RunCommandAction,
    ToolCall,
    ToolCallKey,
    action_steps_with_index,
)

# Characters that typed input holds when it only presses keys, e.g. Enter or Ctrl-C.
_KEY_PRESS_CHARACTERS = " \n\x03\x04"
# Statuses of a poll that saw the polled command end.
_ENDED_STATUSES = frozenset(
    {ExecutionStatus.FINISHED, ExecutionStatus.TIMED_OUT, ExecutionStatus.KILLED}
)


@dataclass(frozen=True, slots=True)
class PollLinks:
    """Links between the polls of a trial and the calls that started what they poll, used to fill `CallRun.polls` and `PollInputText.started_by`."""

    # Later polls of what each call started. For a call that typed input, the later polls of the same handle.
    polls_of_call: Mapping[ToolCallKey, tuple[ToolCallKey, ...]]
    # The call that started what a poll polls, by the polling call and the poll's 0-based step index, None for a poll that is the call's action.
    starting_call_of_poll_step: Mapping[tuple[ToolCallKey, int | None], ToolCallKey]


def link_polls(calls: Sequence[ToolCall]) -> PollLinks:
    """Link each poll to the latest earlier call of its trajectory that started the handle it names.

    Handles are matched by id alone, since no id is used for two kinds in the trajectories.
    A call starts the handles its result names, except those it polls itself, e.g. a Codex script that polls a running session.
    """
    # The latest call that started each handle, by trajectory id and handle id.
    latest_starting_call_of_handle: dict[tuple[str, str], ToolCallKey] = {}
    # Polls that typed input into each handle since its latest start.
    typed_input_polls: defaultdict[tuple[str, str], list[ToolCallKey]] = defaultdict(
        list
    )
    polls_of_call: defaultdict[ToolCallKey, dict[ToolCallKey, None]] = defaultdict(dict)
    starting_call_of_poll_step: dict[tuple[ToolCallKey, int | None], ToolCallKey] = {}
    for call in calls:
        key = call.raw.key
        polled_handle_ids: set[str] = set()
        for step_index, step in action_steps_with_index(call.action):
            if not isinstance(step, PollAction):
                continue
            for handle_id in _polled_handle_ids(call, step):
                polled_handle_ids.add(handle_id)
                handle_key = (key.trajectory_id, handle_id)
                starting_call = latest_starting_call_of_handle.get(handle_key)
                if starting_call is None:
                    continue
                starting_call_of_poll_step.setdefault((key, step_index), starting_call)
                for earlier in (starting_call, *typed_input_polls[handle_key]):
                    if earlier != key:
                        polls_of_call[earlier][key] = None
                if typed_text(step) is not None:
                    typed_input_polls[handle_key].append(key)
        if call.output is not None and not isinstance(call.action, PollAction):
            for started in call.output.handles:
                if started.id not in polled_handle_ids:
                    handle_key = (key.trajectory_id, started.id)
                    latest_starting_call_of_handle[handle_key] = key
                    typed_input_polls.pop(handle_key, None)
    return PollLinks(
        {starting: tuple(polls) for starting, polls in polls_of_call.items()},
        starting_call_of_poll_step,
    )


def command_text_status(
    call: ToolCall, polls: Sequence[ToolCall]
) -> CommandTextStatus | None:
    """Take the status and exit code of a call's command text from the first poll that saw it end, or else from its own result.

    Polls count only while the call's own result has not ended, and only a poll whose action names one handle, so its status is that command's.
    None for a call without a command text or a result.
    """
    output = call.output
    if (
        output is None
        or not isinstance(call.action, RunCommandAction)
        or call.action.command_str is None
    ):
        return None
    if (
        output.execution_status not in _ENDED_STATUSES
        and output.execution_status != ExecutionStatus.NOT_RUN
    ):
        for poll in polls:
            poll_output = poll.output
            if (
                isinstance(poll.action, PollAction)
                and len(_polled_handle_ids(poll, poll.action)) == 1
                and poll_output is not None
                and poll_output.execution_status in _ENDED_STATUSES
            ):
                return CommandTextStatus(
                    poll_output.execution_status, poll_output.exit_code, poll.raw.key
                )
    return CommandTextStatus(output.execution_status, output.exit_code, call.raw.key)


def typed_text(poll: PollAction) -> str | None:
    """Take the text a poll types into what it polls, None when it types nothing or only presses keys such as Enter or Ctrl-C."""
    if poll.input is None or not poll.input.strip(_KEY_PRESS_CHARACTERS):
        return None
    return poll.input


def _polled_handle_ids(call: ToolCall, poll: PollAction) -> tuple[str, ...]:
    """List the ids of the handles a poll names, or those its result names when the poll is the call's action and names none."""
    if poll.handles:
        return tuple(dict.fromkeys(handle.id for handle in poll.handles))
    if poll is call.action and call.output is not None:
        return tuple(dict.fromkeys(handle.id for handle in call.output.handles))
    return ()
