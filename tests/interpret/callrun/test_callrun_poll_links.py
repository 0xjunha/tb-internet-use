"""Tests for interpret/callrun/_poll_links.py."""

from tb_internet_use.interpret.callrun._poll_links import (
    command_text_status,
    link_polls,
    typed_text,
)
from tb_internet_use.interpret.callrun.model import CommandTextStatus
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
)

RUNNING = ExecutionStatus.RUNNING
FINISHED = ExecutionStatus.FINISHED


def _call(
    step_id: int,
    action: ToolCallAction,
    status: ExecutionStatus = FINISHED,
    *handle_ids: str,
    exit_code: int | None = None,
    trajectory_id: str = "main",
) -> ToolCall:
    """A call whose result has the status, the exit code and handles of the ids."""
    key = ToolCallKey("trial", trajectory_id, step_id, 0)
    handles = tuple(ExecutionHandle(ExecutionHandleKind.COMMAND, i) for i in handle_ids)
    output = ToolCallResult(
        execution_status=status, exit_code=exit_code, handles=handles
    )
    return ToolCall(
        HarnessToolCall(key, HarnessTool("h", "t"), "", {}, None), action, output
    )


def _poll(*handle_ids: str, typed: str | None = None) -> PollAction:
    handles = tuple(ExecutionHandle(ExecutionHandleKind.UNKNOWN, i) for i in handle_ids)
    return PollAction(handles=handles, input=typed)


START = RunCommandAction("pip install x")


def test_a_poll_reads_the_latest_earlier_start_of_its_id():
    first, poll_first = _call(1, START, RUNNING, "1"), _call(2, _poll("1"))
    second, poll_second = _call(3, START, RUNNING, "1"), _call(4, _poll("1"))
    links = link_polls([first, poll_first, second, poll_second])
    assert links.polls_of_call == {
        first.harness_tool_call.key: (poll_first.harness_tool_call.key,),
        second.harness_tool_call.key: (poll_second.harness_tool_call.key,),
    }


def test_polls_without_an_earlier_start_in_their_trajectory_stay_unlinked():
    early_poll = _call(1, _poll("1"))
    start = _call(2, START, RUNNING, "1")
    poll_in_subagent = _call(3, _poll("1"), trajectory_id="main/sub0")
    assert link_polls([early_poll, start, poll_in_subagent]).polls_of_call == {}


def test_a_poll_naming_no_handle_uses_the_handle_its_result_names():
    start, poll = _call(1, START, RUNNING, "1"), _call(2, _poll(), FINISHED, "1")
    assert link_polls([start, poll]).polls_of_call == {
        start.harness_tool_call.key: (poll.harness_tool_call.key,)
    }


def test_a_script_step_poll_is_linked_by_its_step_index():
    start = _call(1, START, RUNNING, "1")
    script = _call(2, RunToolScriptAction(steps=(START, _poll("1"))), FINISHED, "1")
    poll = _call(3, _poll("1"))
    links = link_polls([start, script, poll])
    assert links.starting_call_of_poll_step == {
        (script.harness_tool_call.key, 1): start.harness_tool_call.key,
        (poll.harness_tool_call.key, None): start.harness_tool_call.key,
    }
    # The script names session 1 in its result because it polled it, so it did not start it.
    assert links.polls_of_call == {
        start.harness_tool_call.key: (
            script.harness_tool_call.key,
            poll.harness_tool_call.key,
        )
    }


def test_typed_input_is_shown_by_later_polls_of_the_same_handle():
    start = _call(1, START, RUNNING, "1")
    typing = _call(2, _poll("1", typed="ls\n"))
    poll = _call(3, _poll("1"))
    links = link_polls([start, typing, poll])
    assert links.polls_of_call == {
        start.harness_tool_call.key: (
            typing.harness_tool_call.key,
            poll.harness_tool_call.key,
        ),
        typing.harness_tool_call.key: (poll.harness_tool_call.key,),
    }


def test_key_presses_type_no_text():
    assert typed_text(_poll("1", typed="\x03")) is None
    assert typed_text(_poll("1", typed=" \n")) is None
    assert typed_text(_poll("1", typed="y\n")) == "y\n"


def test_command_text_status_comes_from_the_first_poll_that_saw_the_command_end():
    start = _call(1, START, RUNNING, "1")
    still_running = _call(2, _poll("1"), RUNNING)
    timed_out = _call(3, _poll("1"), ExecutionStatus.TIMED_OUT)
    ended_again = _call(4, _poll("1"), FINISHED, exit_code=0)
    assert command_text_status(
        start, [still_running, timed_out, ended_again]
    ) == CommandTextStatus(
        ExecutionStatus.TIMED_OUT, None, timed_out.harness_tool_call.key
    )


def test_command_text_status_ignores_polls_of_several_handles_and_ended_own_results():
    start = _call(1, START, RUNNING, "1")
    poll_of_two = _call(2, _poll("1", "2"), FINISHED, exit_code=0)
    assert command_text_status(start, [poll_of_two]) == CommandTextStatus(
        RUNNING, None, start.harness_tool_call.key
    )
    ended = _call(3, START, FINISHED, exit_code=0)
    later_poll = _call(4, _poll("1"), ExecutionStatus.KILLED)
    assert command_text_status(ended, [later_poll]) == CommandTextStatus(
        FINISHED, 0, ended.harness_tool_call.key
    )


def test_command_text_status_is_none_without_a_command_text():
    assert command_text_status(_call(1, _poll("1")), []) is None
    assert command_text_status(_call(2, RunCommandAction(None)), []) is None
