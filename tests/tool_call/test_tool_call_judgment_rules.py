"""Tests for tool_call/judgment_rules.py, with made-up results."""

from collections import Counter
from collections.abc import Callable

import pytest

from tb_internet_use.tool_call.judgment_rules import (
    treat_accepted_stop_request_as_killed,
    treat_bash_output_without_exit_code_line_as_exit_code_0,
    treat_bash_output_without_exit_code_line_as_finished,
    treat_exit_code_130_after_ctrl_c_as_killed,
    treat_failed_file_tool_call_as_not_run,
    treat_failed_task_without_exit_code_as_killed,
    treat_get_output_without_exit_code_as_running,
    treat_negative_exit_code_as_killed,
    treat_script_syntax_error_as_not_run,
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

# (rule that sets one status whatever the result, the status it sets)
STATUS_RULE_CASES: list[tuple[JudgmentRule, ExecutionStatus]] = [
    (treat_bash_output_without_exit_code_line_as_finished, S.FINISHED),
    (treat_script_syntax_error_as_not_run, S.NOT_RUN),
    (treat_web_search_call_without_content_as_finished, S.FINISHED),
    (treat_failed_file_tool_call_as_not_run, S.NOT_RUN),
    (treat_get_output_without_exit_code_as_running, S.RUNNING),
    (treat_web_fetch_text_as_finished, S.FINISHED),
    (treat_written_input_as_running_target, S.RUNNING),
    (treat_accepted_stop_request_as_killed, S.KILLED),
    (treat_failed_task_without_exit_code_as_killed, S.KILLED),
]


def _exited(exit_code: int | None) -> ToolCallResult:
    return ToolCallResult("out", S.FINISHED, exit_code)


@pytest.mark.parametrize("exit_code", [-1, -9])
def test_a_negative_exit_code_is_killed_without_a_code_and_counted(exit_code: int):
    use_counts: Counter[str] = Counter()
    killed = treat_negative_exit_code_as_killed(
        _exited(exit_code), use_counts=use_counts
    )
    assert (killed.execution_status, killed.exit_code) == (S.KILLED, None)
    assert use_counts == Counter({"treat_negative_exit_code_as_killed": 1})


@pytest.mark.parametrize("exit_code", [0, 1, 130, None])
def test_a_real_exit_code_stays_and_counts_nothing(exit_code: int | None):
    use_counts: Counter[str] = Counter()
    tool_call_result = _exited(exit_code)
    assert (
        treat_negative_exit_code_as_killed(tool_call_result, use_counts=use_counts)
        == tool_call_result
    )
    assert use_counts == Counter()


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


@pytest.mark.parametrize(("judgment_rule", "status"), STATUS_RULE_CASES)
def test_a_status_rule_sets_its_status_keeps_every_other_field_and_counts_once(
    judgment_rule: JudgmentRule, status: ExecutionStatus
):
    use_counts: Counter[str] = Counter()
    decided = judgment_rule(UNDECIDED, use_counts=use_counts)
    assert decided == ToolCallResult(
        "out", status, harness_result_format=MatchedFormat("f")
    )
    assert use_counts == Counter({judgment_rule.__name__: 1})


def test_a_finished_bash_output_without_exit_code_line_gets_exit_code_0_and_counts_once():
    use_counts: Counter[str] = Counter()
    assert treat_bash_output_without_exit_code_line_as_exit_code_0(
        _exited(None), use_counts=use_counts
    ) == _exited(0)
    assert use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_exit_code_0": 1}
    )
