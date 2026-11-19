"""Tests for expanded_tool_call/_expand_poll_links.py."""

from collections import Counter

import pytest

from tb_internet_use.expanded_tool_call import _expand_poll_links
from tb_internet_use.expanded_tool_call._expand_poll_links import (
    PollLinks,
    expand_poll_links,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_calls_of_other_trajectory_as_not_linked,
    treat_poll_as_reading_latest_earlier_start_of_handle,
    treat_script_poll_step_naming_no_handle_as_polling_none,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    RunCommandAction,
    RunToolScriptAction,
    StartSubagentAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
)

LATEST_START_RULE_NAME = treat_poll_as_reading_latest_earlier_start_of_handle.__name__
OTHER_TRAJECTORY_RULE_NAME = treat_calls_of_other_trajectory_as_not_linked.__name__
SCRIPT_POLL_STEP_RULE_NAME = (
    treat_script_poll_step_naming_no_handle_as_polling_none.__name__
)
COMMAND = ExecutionHandleKind.COMMAND
SCRIPT = ExecutionHandleKind.SCRIPT
SUBAGENT = ExecutionHandleKind.SUBAGENT
UNKNOWN = ExecutionHandleKind.UNKNOWN
RUNNING = ExecutionStatus.RUNNING
FINISHED = ExecutionStatus.FINISHED
START = RunCommandAction("pip install x")


def _tool_call(
    step_id: int,
    action: ToolCallAction,
    *handle_ids: str,
    status: ExecutionStatus = RUNNING,
    trajectory_id: str = "main",
    is_subagent: bool = False,
    handle_kind: ExecutionHandleKind = COMMAND,
    more_handles: tuple[ExecutionHandle, ...] = (),
    has_result: bool = True,
) -> ToolCall:
    """Make a call whose result has the status and names handles of the ids and then `more_handles`, or a call without a result."""
    key = ToolCallKey("trial", trajectory_id, step_id, 0)
    handles = (
        *(ExecutionHandle(handle_kind, i) for i in handle_ids),
        *more_handles,
    )
    result = (
        ToolCallResult(execution_status=status, handles=handles) if has_result else None
    )
    return ToolCall(
        HarnessToolCall(
            key, HarnessTool("h", "t"), "", {}, None, is_subagent=is_subagent
        ),
        action,
        result,
    )


def _poll(
    *handle_ids: str,
    kind: ExecutionHandleKind = COMMAND,
    typed_input: str | None = None,
    terminate: bool = False,
) -> PollAction:
    handles = tuple(ExecutionHandle(kind, i) for i in handle_ids)
    return PollAction(handles=handles, input=typed_input, terminate=terminate)


def _key(tool_call: ToolCall) -> ToolCallKey:
    return tool_call.harness_tool_call.key


def _expand(*tool_calls: ToolCall) -> tuple[PollLinks, Counter[str]]:
    judgment_rule_use_counts: Counter[str] = Counter()
    poll_links = expand_poll_links(
        tool_calls, judgment_rule_use_counts=judgment_rule_use_counts
    )
    return poll_links, judgment_rule_use_counts


def test_polls_of_a_background_command_are_linked_to_its_start_whether_they_read_type_or_stop():
    start = _tool_call(1, START, "h1")
    reading = _tool_call(2, _poll("h1"))
    typing = _tool_call(3, _poll("h1", typed_input="y\n"))
    stopping = _tool_call(4, _poll("h1", terminate=True), status=ExecutionStatus.KILLED)
    poll_links, judgment_rule_use_counts = _expand(start, reading, typing, stopping)
    assert poll_links == PollLinks(
        {
            (_key(reading), None): (_key(start),),
            (_key(typing), None): (_key(start),),
            (_key(stopping), None): (_key(start),),
        },
        {_key(start): (_key(reading), _key(typing), _key(stopping))},
    )
    assert judgment_rule_use_counts == Counter()


def test_a_handle_id_started_again_links_later_polls_to_the_latest_start():
    first_start, first_poll = _tool_call(1, START, "h1"), _tool_call(2, _poll("h1"))
    second_start, second_poll = _tool_call(3, START, "h1"), _tool_call(4, _poll("h1"))
    poll_links, judgment_rule_use_counts = _expand(
        first_start, first_poll, second_start, second_poll
    )
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(first_poll), None): (_key(first_start),),
        (_key(second_poll), None): (_key(second_start),),
    }
    assert poll_links.poll_tool_call_keys_of_starter == {
        _key(first_start): (_key(first_poll),),
        _key(second_start): (_key(second_poll),),
    }
    # Only the second poll comes after two starts of h1.
    assert judgment_rule_use_counts == Counter({LATEST_START_RULE_NAME: 1})


def test_a_poll_without_an_earlier_start_in_the_trial_has_no_starter():
    early_poll = _tool_call(1, _poll("h1"))
    start = _tool_call(2, START, "h1")
    poll_of_other_id = _tool_call(3, _poll("h2"))
    poll_links, judgment_rule_use_counts = _expand(early_poll, start, poll_of_other_id)
    assert poll_links == PollLinks(
        {(_key(early_poll), None): (), (_key(poll_of_other_id), None): ()}, {}
    )
    assert judgment_rule_use_counts == Counter()


def test_a_poll_of_several_handles_gets_their_starters_in_handle_order():
    start_of_h1 = _tool_call(1, START, "h1")
    start_of_h2 = _tool_call(2, START, "h2")
    poll = _tool_call(3, _poll("h2", "h3", "h1"))
    poll_links, _ = _expand(start_of_h1, start_of_h2, poll)
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(poll), None): (_key(start_of_h2), _key(start_of_h1))
    }
    assert poll_links.poll_tool_call_keys_of_starter == {
        _key(start_of_h1): (_key(poll),),
        _key(start_of_h2): (_key(poll),),
    }


def test_a_poll_naming_no_handle_takes_the_handle_its_result_names():
    start = _tool_call(1, START, "h1")
    poll = _tool_call(2, _poll(), "h1", status=FINISHED)
    poll_links, _ = _expand(start, poll)
    assert poll_links.poll_tool_call_keys_of_starter == {_key(start): (_key(poll),)}


def test_a_poll_whose_result_names_another_handle_does_not_start_it():
    script = _tool_call(
        1,
        RunToolScriptAction(steps=(START,)),
        "s1",
        handle_kind=SCRIPT,
    )
    # A Codex `wait` on a script whose result names the command session the script left running.
    wait = _tool_call(2, _poll("s1", kind=SCRIPT), "c1", status=FINISHED)
    poll_of_session = _tool_call(3, _poll("c1"))
    poll_links, _ = _expand(script, wait, poll_of_session)
    assert poll_links == PollLinks(
        {(_key(wait), None): (_key(script),), (_key(poll_of_session), None): ()},
        {_key(script): (_key(wait),)},
    )


def test_a_poll_step_of_a_tool_script_is_linked_by_its_step_index_and_does_not_start_its_handle():
    start = _tool_call(1, START, "h1")
    # A Codex `exec` script that runs a command, polls h1 and names h1 in its result because it polled it.
    script = _tool_call(
        2, RunToolScriptAction(steps=(START, _poll("h1"))), "h1", status=FINISHED
    )
    poll = _tool_call(3, _poll("h1"))
    poll_links, judgment_rule_use_counts = _expand(start, script, poll)
    assert poll_links == PollLinks(
        {(_key(script), 1): (_key(start),), (_key(poll), None): (_key(start),)},
        {_key(start): (_key(script), _key(poll))},
    )
    assert judgment_rule_use_counts == Counter()


def test_a_tool_script_starts_the_handles_its_result_names_that_it_does_not_poll():
    script = _tool_call(1, RunToolScriptAction(steps=(START,)), "h1")
    poll = _tool_call(2, _poll("h1"))
    poll_links, _ = _expand(script, poll)
    assert poll_links.poll_tool_call_keys_of_starter == {_key(script): (_key(poll),)}


def test_a_poll_that_names_handles_reads_only_those_and_not_the_others_its_result_names():
    start_of_h1 = _tool_call(1, START, "h1")
    start_of_h2 = _tool_call(2, START, "h2")
    # A Codex `wait` on h1 whose result also names h2.
    poll = _tool_call(3, _poll("h1"), "h1", "h2", status=FINISHED)
    poll_links, _ = _expand(start_of_h1, start_of_h2, poll)
    assert poll_links == PollLinks(
        {(_key(poll), None): (_key(start_of_h1),)}, {_key(start_of_h1): (_key(poll),)}
    )


def test_a_poll_of_two_handles_of_one_starter_gets_it_once_per_handle_and_the_starter_lists_the_poll_once():
    start = _tool_call(1, START, "h1", "h2")
    poll = _tool_call(2, _poll("h1", "h2"))
    poll_links, _ = _expand(start, poll)
    assert poll_links == PollLinks(
        {(_key(poll), None): (_key(start), _key(start))}, {_key(start): (_key(poll),)}
    )


def test_a_handle_named_twice_by_a_poll_or_by_a_start_counts_once():
    start = _tool_call(1, START, "h1", "h1")
    poll = _tool_call(2, PollAction(handles=(ExecutionHandle(COMMAND, "h1"),) * 2))
    poll_links, judgment_rule_use_counts = _expand(start, poll)
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(poll), None): (_key(start),)
    }
    # One start of h1, so the latest start rule is not asked.
    assert judgment_rule_use_counts == Counter()


def test_a_poll_naming_no_handle_reads_a_handle_its_result_names_twice_once():
    start = _tool_call(1, START, "h1")
    poll = _tool_call(2, _poll(), "h1", "h1", status=FINISHED)
    poll_links, _ = _expand(start, poll)
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(poll), None): (_key(start),)
    }


def test_a_call_without_a_result_starts_nothing_and_its_poll_without_handles_reads_nothing():
    start = _tool_call(1, START, has_result=False)
    poll = _tool_call(2, _poll(), has_result=False)
    poll_links, _ = _expand(start, poll)
    assert poll_links == PollLinks({(_key(poll), None): ()}, {})


def test_a_handle_is_matched_by_its_kind_as_well_as_its_id():
    command_start = _tool_call(1, START, "1")
    subagent_start = _tool_call(2, StartSubagentAction(), "1", handle_kind=SUBAGENT)
    command_poll = _tool_call(3, _poll("1"))
    script_poll = _tool_call(4, _poll("1", kind=SCRIPT))
    poll_links, judgment_rule_use_counts = _expand(
        command_start, subagent_start, command_poll, script_poll
    )
    assert poll_links == PollLinks(
        {
            (_key(command_poll), None): (_key(command_start),),
            (_key(script_poll), None): (),
        },
        {_key(command_start): (_key(command_poll),)},
    )
    assert judgment_rule_use_counts == Counter()


def test_a_subagent_start_is_linked_to_a_later_poll_of_its_subagent():
    subagent_start = _tool_call(1, StartSubagentAction(), "a1", handle_kind=SUBAGENT)
    poll = _tool_call(2, _poll("a1", kind=SUBAGENT))
    poll_links, _ = _expand(subagent_start, poll)
    assert poll_links == PollLinks(
        {(_key(poll), None): (_key(subagent_start),)},
        {_key(subagent_start): (_key(poll),)},
    )


def test_a_handle_of_unknown_kind_has_no_starter():
    start = _tool_call(1, START, "h1", handle_kind=UNKNOWN)
    poll = _tool_call(2, _poll("h1", kind=UNKNOWN))
    poll_links, _ = _expand(start, poll)
    assert poll_links == PollLinks({(_key(poll), None): ()}, {})


def test_a_tool_script_without_a_run_step_starts_only_its_own_script_handle():
    start = _tool_call(1, START, "h1")
    # A Codex `exec` script that only waits and is still running, so its result names the session and the script itself.
    waiting_script = _tool_call(
        2,
        RunToolScriptAction(steps=(_poll("h1"),)),
        "h1",
        more_handles=(ExecutionHandle(SCRIPT, "s1"),),
    )
    poll_of_session = _tool_call(3, _poll("h1"))
    poll_of_script = _tool_call(4, _poll("s1", kind=SCRIPT))
    poll_links, _ = _expand(start, waiting_script, poll_of_session, poll_of_script)
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(waiting_script), 0): (_key(start),),
        (_key(poll_of_session), None): (_key(start),),
        (_key(poll_of_script), None): (_key(waiting_script),),
    }


def test_a_script_poll_step_naming_no_handle_reads_none_of_the_handles_its_script_result_names():
    start = _tool_call(1, START, "h1")
    # A Codex `exec` script whose step `wait()` names no session and whose result names h1.
    waiting_script = _tool_call(
        2, RunToolScriptAction(steps=(_poll(),)), "h1", status=FINISHED
    )
    later_poll = _tool_call(3, _poll("h1"))
    # A script step that names no handle in a script whose result names none asks no rule.
    script_without_result_handles = _tool_call(
        4, RunToolScriptAction(steps=(_poll(),)), status=FINISHED
    )
    poll_links, judgment_rule_use_counts = _expand(
        start, waiting_script, later_poll, script_without_result_handles
    )
    assert poll_links == PollLinks(
        {
            (_key(waiting_script), 0): (),
            (_key(later_poll), None): (_key(start),),
            (_key(script_without_result_handles), 0): (),
        },
        {_key(start): (_key(later_poll),)},
    )
    assert judgment_rule_use_counts == Counter({SCRIPT_POLL_STEP_RULE_NAME: 1})


def test_a_claude_code_subagent_poll_is_not_linked_to_a_start_of_the_main_trajectory():
    start = _tool_call(1, START, "h1")
    subagent = _tool_call(2, StartSubagentAction())
    # Claude Code keeps subagent calls in the main trajectory, marked as subagent ones.
    subagent_poll = _tool_call(3, _poll("h1"), is_subagent=True)
    main_poll = _tool_call(4, _poll("h1"))
    poll_links, judgment_rule_use_counts = _expand(
        start, subagent, subagent_poll, main_poll
    )
    assert poll_links == PollLinks(
        {(_key(subagent_poll), None): (), (_key(main_poll), None): (_key(start),)},
        {_key(start): (_key(main_poll),)},
    )
    assert judgment_rule_use_counts == Counter({OTHER_TRAJECTORY_RULE_NAME: 1})


def test_a_muse_main_poll_is_not_linked_to_a_start_of_a_subagent_placed_after_it():
    # Muse puts the calls of a subagent after all calls of the main trajectory.
    main_poll = _tool_call(1, _poll("h1"))
    subagent_start = _tool_call(2, START, "h1", trajectory_id="main/sub0")
    subagent_poll = _tool_call(3, _poll("h1"), trajectory_id="main/sub0")
    poll_links, judgment_rule_use_counts = _expand(
        main_poll, subagent_start, subagent_poll
    )
    assert poll_links == PollLinks(
        {
            (_key(main_poll), None): (),
            (_key(subagent_poll), None): (_key(subagent_start),),
        },
        {_key(subagent_start): (_key(subagent_poll),)},
    )
    assert judgment_rule_use_counts == Counter({OTHER_TRAJECTORY_RULE_NAME: 1})


def test_a_poll_of_a_subagent_that_no_call_started_has_no_starter():
    # The conversion of a Claude Code `Agent` result gives no handle, so only the result of the poll names the agent id.
    subagent = _tool_call(1, StartSubagentAction(), status=FINISHED)
    poll = _tool_call(2, _poll(), "a1", status=FINISHED, handle_kind=SUBAGENT)
    poll_links, judgment_rule_use_counts = _expand(subagent, poll)
    assert poll_links == PollLinks({(_key(poll), None): ()}, {})
    assert judgment_rule_use_counts == Counter()


def test_the_other_choice_of_the_latest_start_rule_leaves_a_reused_handle_without_starter(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _expand_poll_links,
        LATEST_START_RULE_NAME,
        lambda *, use_counts: False,
    )
    first_start, second_start = _tool_call(1, START, "h1"), _tool_call(2, START, "h1")
    poll = _tool_call(3, _poll("h1"))
    poll_links, _ = _expand(first_start, second_start, poll)
    assert poll_links == PollLinks({(_key(poll), None): ()}, {})


def test_the_other_choice_of_the_other_trajectory_rule_links_to_the_latest_earlier_start_of_the_trial(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _expand_poll_links,
        OTHER_TRAJECTORY_RULE_NAME,
        lambda *, use_counts: False,
    )
    first_start, second_start = _tool_call(1, START, "h1"), _tool_call(2, START, "h1")
    subagent_poll = _tool_call(3, _poll("h1"), trajectory_id="main/sub0")
    later_start = _tool_call(4, START, "h1")
    poll_links, judgment_rule_use_counts = _expand(
        first_start, second_start, subagent_poll, later_start
    )
    assert poll_links.starter_tool_call_keys_of_poll == {
        (_key(subagent_poll), None): (_key(second_start),)
    }
    assert judgment_rule_use_counts == Counter({LATEST_START_RULE_NAME: 1})


def test_the_other_choice_of_the_script_poll_step_rule_reads_the_handles_its_script_result_names(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _expand_poll_links,
        SCRIPT_POLL_STEP_RULE_NAME,
        lambda *, use_counts: False,
    )
    start = _tool_call(1, START, "h1")
    waiting_script = _tool_call(
        2, RunToolScriptAction(steps=(_poll(),)), "h1", status=FINISHED
    )
    later_poll = _tool_call(3, _poll("h1"))
    poll_links, _ = _expand(start, waiting_script, later_poll)
    assert poll_links == PollLinks(
        {
            (_key(waiting_script), 0): (_key(start),),
            (_key(later_poll), None): (_key(start),),
        },
        {_key(start): (_key(waiting_script), _key(later_poll))},
    )
