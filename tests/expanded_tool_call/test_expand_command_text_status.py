"""Tests for expanded_tool_call/_expand_command_text_status.py."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call import _expand_command_text_status
from tb_internet_use.expanded_tool_call._expand_command_text_status import (
    expand_command_text_status,
)
from tb_internet_use.expanded_tool_call._expand_poll_links import expand_poll_links
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_first_poll_that_saw_end_as_command_text_status,
)
from tb_internet_use.expanded_tool_call.model import CommandTextStatus
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    RunToolScriptAction,
    StartSubagentAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
)

FIRST_POLL_RULE_NAME = treat_first_poll_that_saw_end_as_command_text_status.__name__
RUNNING = ExecutionStatus.RUNNING
FINISHED = ExecutionStatus.FINISHED
TIMED_OUT = ExecutionStatus.TIMED_OUT
KILLED = ExecutionStatus.KILLED
NOT_RUN = ExecutionStatus.NOT_RUN
UNKNOWN = ExecutionStatus.UNKNOWN
START = RunCommandAction("pip install x")


def _tool_call(
    step_id: int,
    action: ToolCallAction,
    *handle_ids: str,
    status: ExecutionStatus = RUNNING,
    exit_code: int | None = None,
    has_result: bool = True,
) -> ToolCall:
    """Make a call whose result has the status and the exit code and names command handles of the ids, or a call without a result."""
    key = ToolCallKey("trial", "main", step_id, 0)
    handles = tuple(
        ExecutionHandle(ExecutionHandleKind.COMMAND, handle_id)
        for handle_id in handle_ids
    )
    result = (
        ToolCallResult(execution_status=status, exit_code=exit_code, handles=handles)
        if has_result
        else None
    )
    return ToolCall(
        HarnessToolCall(key, HarnessTool("h", "t"), "", {}, None), action, result
    )


def _poll(
    *handle_ids: str, typed_input: str | None = None, terminate: bool = False
) -> PollAction:
    handles = tuple(
        ExecutionHandle(ExecutionHandleKind.COMMAND, handle_id)
        for handle_id in handle_ids
    )
    return PollAction(handles=handles, input=typed_input, terminate=terminate)


def _key(tool_call: ToolCall) -> ToolCallKey:
    return tool_call.harness_tool_call.key


def _expand(
    tool_call: ToolCall, *tool_calls_of_trial: ToolCall
) -> tuple[CommandTextStatus | None, Counter[str]]:
    """Expand the command text status of `tool_call` with the polls that `expand_poll_links` links to it in the trial, as `expand_tool_calls` does."""
    poll_links = expand_poll_links(
        tool_calls_of_trial, judgment_rule_use_counts=Counter()
    )
    tool_call_of_key = {_key(other): other for other in tool_calls_of_trial}
    poll_tool_calls = [
        tool_call_of_key[poll_tool_call_key]
        for poll_tool_call_key in poll_links.poll_tool_call_keys_of_starter.get(
            _key(tool_call), ()
        )
    ]
    judgment_rule_use_counts: Counter[str] = Counter()
    command_text_status = expand_command_text_status(
        tool_call, poll_tool_calls, judgment_rule_use_counts=judgment_rule_use_counts
    )
    return command_text_status, judgment_rule_use_counts


def test_a_command_that_ended_in_its_own_call_takes_its_own_status_and_exit_code():
    start = _tool_call(1, START, status=FINISHED, exit_code=1)
    assert _expand(start, start) == (
        CommandTextStatus(FINISHED, 1, _key(start)),
        Counter(),
    )


def test_a_background_command_takes_the_status_and_exit_code_of_the_first_poll_that_saw_it_end():
    start = _tool_call(1, START, "h1")
    still_running = _tool_call(2, _poll("h1"))
    finished = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=0)
    finished_again = _tool_call(4, _poll("h1"), status=FINISHED, exit_code=0)
    assert _expand(start, start, still_running, finished, finished_again) == (
        CommandTextStatus(FINISHED, 0, _key(finished)),
        Counter({FIRST_POLL_RULE_NAME: 1}),
    )


def test_a_later_poll_gives_the_exit_code_that_the_first_poll_that_saw_the_end_left_out():
    """An Antigravity CLI `manage_task` result `Status: DONE` states no exit code, and the `SYSTEM_MESSAGE` after it says `Command exited with code 7`."""
    start = _tool_call(1, START, "h1")
    done = _tool_call(2, _poll("h1"), status=FINISHED)
    end_message = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=7)
    assert _expand(start, start, done, end_message) == (
        CommandTextStatus(FINISHED, 7, _key(end_message)),
        Counter({FIRST_POLL_RULE_NAME: 1}),
    )


def test_polls_that_saw_the_end_with_different_exit_codes_leave_the_exit_code_unknown():
    start = _tool_call(1, START, "h1")
    done = _tool_call(2, _poll("h1"), status=FINISHED)
    finished = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=0)
    finished_again = _tool_call(4, _poll("h1"), status=FINISHED, exit_code=2)
    command_text_status, _ = _expand(start, start, done, finished, finished_again)
    assert command_text_status == CommandTextStatus(FINISHED, None, _key(done))


@pytest.mark.parametrize("ended_status", [TIMED_OUT, KILLED])
def test_a_poll_that_saw_the_command_timed_out_or_killed_gives_that_status_before_a_later_report(
    ended_status: ExecutionStatus,
):
    start = _tool_call(1, START, "h1")
    stopped = _tool_call(2, _poll("h1"), status=ended_status)
    finished_later = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=0)
    command_text_status, _ = _expand(start, start, stopped, finished_later)
    assert command_text_status == CommandTextStatus(ended_status, None, _key(stopped))


def test_a_background_command_without_a_later_poll_keeps_its_running_result():
    start = _tool_call(1, START, "h1")
    assert _expand(start, start) == (
        CommandTextStatus(RUNNING, None, _key(start)),
        Counter(),
    )


@pytest.mark.parametrize(
    ("own_status", "own_exit_code"),
    [(FINISHED, 0), (TIMED_OUT, None), (KILLED, None), (NOT_RUN, None)],
)
def test_a_call_whose_own_result_ended_or_did_not_run_keeps_it_over_a_later_poll(
    own_status: ExecutionStatus, own_exit_code: int | None
):
    start = _tool_call(1, START, "h1", status=own_status, exit_code=own_exit_code)
    later_poll = _tool_call(2, _poll("h1"), status=KILLED)
    assert _expand(start, start, later_poll) == (
        CommandTextStatus(own_status, own_exit_code, _key(start)),
        Counter(),
    )


def test_a_call_whose_own_result_is_unknown_takes_a_poll_that_saw_the_end():
    start = _tool_call(1, START, "h1", status=UNKNOWN)
    finished = _tool_call(2, _poll("h1"), status=FINISHED, exit_code=3)
    command_text_status, _ = _expand(start, start, finished)
    assert command_text_status == CommandTextStatus(FINISHED, 3, _key(finished))


@pytest.mark.parametrize(
    "poll_tool_call",
    [
        _tool_call(2, _poll("h1"), status=NOT_RUN),
        _tool_call(2, _poll("h1"), status=UNKNOWN),
        _tool_call(2, _poll("h1"), has_result=False),
        _tool_call(2, _poll("h1", "h2"), status=FINISHED, exit_code=0),
        _tool_call(
            2,
            RunToolScriptAction("wait(h1)", (_poll("h1"),)),
            status=FINISHED,
            exit_code=0,
        ),
    ],
    ids=[
        "poll_that_did_nothing",
        "poll_of_unknown_state",
        "poll_without_result",
        "poll_of_two_handles",
        "poll_step_of_tool_script",
    ],
)
def test_a_poll_that_does_not_show_one_handle_ending_is_skipped_for_a_later_one(
    poll_tool_call: ToolCall,
):
    start = _tool_call(1, START, "h1", "h2")
    finished = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=0)
    command_text_status, _ = _expand(start, start, poll_tool_call, finished)
    assert command_text_status == CommandTextStatus(FINISHED, 0, _key(finished))


def test_a_poll_step_of_a_tool_script_linked_to_the_command_does_not_give_the_end_state():
    start = _tool_call(1, START, "h1")
    script = _tool_call(
        2, RunToolScriptAction("wait(h1)", (_poll("h1"),)), status=FINISHED, exit_code=0
    )
    assert _expand(start, start, script) == (
        CommandTextStatus(RUNNING, None, _key(start)),
        Counter(),
    )


def test_a_poll_naming_no_handle_reads_the_one_its_result_names():
    start = _tool_call(1, START, "h1")
    wait = _tool_call(2, PollAction(), "h1", status=FINISHED, exit_code=0)
    command_text_status, _ = _expand(start, start, wait)
    assert command_text_status == CommandTextStatus(FINISHED, 0, _key(wait))


def test_a_poll_naming_one_handle_twice_reads_one_handle():
    start = _tool_call(1, START, "h1")
    finished = _tool_call(2, _poll("h1", "h1"), status=FINISHED, exit_code=0)
    command_text_status, _ = _expand(start, start, finished)
    assert command_text_status == CommandTextStatus(FINISHED, 0, _key(finished))


def test_a_call_without_a_result_has_an_unknown_status_reported_by_itself():
    start = _tool_call(1, START, has_result=False)
    assert _expand(start, start) == (
        CommandTextStatus(UNKNOWN, None, _key(start)),
        Counter(),
    )


@pytest.mark.parametrize(
    "action",
    [
        _poll("h1"),
        ReadFileAction("notes.md"),
        StartSubagentAction(),
        RunCommandAction(None),
        RunToolScriptAction("exec('ls')", (RunCommandAction("ls"),)),
    ],
    ids=["poll", "read_tool", "subagent", "run_command_without_text", "tool_script"],
)
def test_a_call_without_a_command_text_of_its_own_has_no_status(
    action: ToolCallAction,
):
    tool_call = _tool_call(1, action, status=FINISHED, exit_code=0)
    assert _expand(tool_call, tool_call) == (None, Counter())


def test_the_other_choice_of_the_first_poll_rule_keeps_the_running_result_and_is_asked_once_per_call(
    monkeypatch: pytest.MonkeyPatch,
):
    rule_use_count = 0

    def answer_false(*, use_counts: Counter[str]) -> bool:
        nonlocal rule_use_count
        rule_use_count += 1
        return False

    monkeypatch.setattr(_expand_command_text_status, FIRST_POLL_RULE_NAME, answer_false)
    start = _tool_call(1, START, "h1")
    finished = _tool_call(2, _poll("h1"), status=FINISHED, exit_code=0)
    finished_again = _tool_call(3, _poll("h1"), status=FINISHED, exit_code=2)
    command_text_status, _ = _expand(start, start, finished, finished_again)
    assert (command_text_status, rule_use_count) == (
        CommandTextStatus(RUNNING, None, _key(start)),
        1,
    )
