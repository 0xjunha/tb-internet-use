"""Tests for tool_call/judgment_rules.py, with made-up results."""

from collections import Counter
from collections.abc import Callable
from dataclasses import replace

import pytest

from tb_internet_use.tool_call.judgment_rules import (
    treat_accepted_stop_request_as_killed,
    treat_bash_output_without_exit_code_line_as_exit_code_0,
    treat_bash_output_without_exit_code_line_as_finished,
    treat_cut_off_web_search_as_finished,
    treat_exit_code_130_after_ctrl_c_as_killed,
    treat_failed_file_tool_call_as_not_run,
    treat_failed_task_without_exit_code_as_killed,
    treat_get_output_without_exit_code_as_running,
    treat_idle_subagent_as_unknown_status,
    treat_lines_joined_after_three_repairs_as_left_joined,
    treat_negative_exit_code_as_killed,
    treat_script_syntax_error_as_not_run,
    treat_shell_id_with_exit_code_as_running,
    treat_stop_request_for_ended_work_as_finished,
    treat_tool_failure_message_as_not_run,
    treat_wait_on_several_tasks_as_their_shared_status,
    treat_web_fetch_text_as_finished,
    treat_web_search_call_without_content_as_finished,
    treat_written_input_as_running_target,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    MatchedFormat,
    ToolCallResult,
)

S = ExecutionStatus
STATUS_BY_TASK_STATE = {
    "completed": S.FINISHED,
    "failed": S.FINISHED,
    "running": S.RUNNING,
}

# (state of each task, status of the wait)
WAIT_CASES = [
    (["running", "running"], S.RUNNING),
    (["completed", "running"], S.UNKNOWN),
    # The states differ as the harness names them, although both are finished.
    (["completed", "failed"], S.UNKNOWN),
    (["cancelled", "cancelled"], S.UNKNOWN),
    ([], S.UNKNOWN),
]


type JudgmentRule = Callable[..., ToolCallResult]

# A result as a format that names the rule builds it, with the status the rule replaces still unknown.
UNDECIDED = ToolCallResult("out", harness_result_format=MatchedFormat("f"))

# The rules that set one status whatever the result. `JUDGMENT_RULE_CASES` of the tests of `convert_tool_calls` checks which status each sets.
RULES_THAT_SET_ONE_STATUS: list[JudgmentRule] = [
    treat_bash_output_without_exit_code_line_as_finished,
    treat_script_syntax_error_as_not_run,
    treat_web_search_call_without_content_as_finished,
    treat_failed_file_tool_call_as_not_run,
    treat_get_output_without_exit_code_as_running,
    treat_web_fetch_text_as_finished,
    treat_written_input_as_running_target,
    treat_accepted_stop_request_as_killed,
    treat_failed_task_without_exit_code_as_killed,
    treat_tool_failure_message_as_not_run,
    treat_shell_id_with_exit_code_as_running,
    treat_stop_request_for_ended_work_as_finished,
    treat_cut_off_web_search_as_finished,
]


def _exited(exit_code: int | None) -> ToolCallResult:
    return ToolCallResult("out", S.FINISHED, exit_code)


def test_a_negative_exit_code_is_killed_without_a_code_and_counted():
    use_counts: Counter[str] = Counter()
    killed = treat_negative_exit_code_as_killed(_exited(-1), use_counts=use_counts)
    assert (killed.execution_status, killed.exit_code) == (S.KILLED, None)
    assert use_counts == Counter({"treat_negative_exit_code_as_killed": 1})


def test_exit_code_130_after_ctrl_c_is_killed_and_counted_and_other_codes_stay():
    use_counts: Counter[str] = Counter()
    killed = treat_exit_code_130_after_ctrl_c_as_killed(
        _exited(130), use_counts=use_counts
    )
    assert (killed.execution_status, killed.exit_code) == (S.KILLED, None)
    assert treat_exit_code_130_after_ctrl_c_as_killed(
        _exited(1), use_counts=use_counts
    ) == _exited(1)
    assert use_counts == Counter({"treat_exit_code_130_after_ctrl_c_as_killed": 1})


@pytest.mark.parametrize(("task_states", "status"), WAIT_CASES)
def test_a_wait_on_several_tasks_has_the_status_of_the_state_they_share_and_counts_once(
    task_states: list[str], status: ExecutionStatus
):
    use_counts: Counter[str] = Counter()
    assert (
        treat_wait_on_several_tasks_as_their_shared_status(
            task_states, STATUS_BY_TASK_STATE, use_counts=use_counts
        )
        is status
    )
    assert use_counts == Counter(
        {"treat_wait_on_several_tasks_as_their_shared_status": 1}
    )


@pytest.mark.parametrize("judgment_rule", RULES_THAT_SET_ONE_STATUS)
def test_a_status_rule_keeps_every_other_field_and_counts_once(
    judgment_rule: JudgmentRule,
):
    use_counts: Counter[str] = Counter()
    decided = judgment_rule(UNDECIDED, use_counts=use_counts)
    assert decided.execution_status is not S.UNKNOWN
    assert replace(decided, execution_status=S.UNKNOWN) == UNDECIDED
    assert use_counts == Counter({judgment_rule.__name__: 1})


def test_an_idle_subagent_has_an_unknown_status_whatever_its_format_stated_and_counts_once():
    use_counts: Counter[str] = Counter()
    assert treat_idle_subagent_as_unknown_status(
        replace(UNDECIDED, execution_status=S.FINISHED), use_counts=use_counts
    ) == replace(UNDECIDED, execution_status=S.UNKNOWN)
    assert use_counts == Counter({"treat_idle_subagent_as_unknown_status": 1})


def test_a_finished_bash_output_without_exit_code_line_gets_exit_code_0_and_counts_once():
    use_counts: Counter[str] = Counter()
    assert treat_bash_output_without_exit_code_line_as_exit_code_0(
        _exited(None), use_counts=use_counts
    ) == _exited(0)
    assert use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_exit_code_0": 1}
    )


def test_lines_joined_after_three_repairs_are_left_joined_and_counted():
    use_counts: Counter[str] = Counter()
    assert treat_lines_joined_after_three_repairs_as_left_joined(
        3, use_counts=use_counts
    )
    assert use_counts == Counter(
        {"treat_lines_joined_after_three_repairs_as_left_joined": 1}
    )
