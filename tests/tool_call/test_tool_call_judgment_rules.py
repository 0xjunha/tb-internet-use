"""Tests for tool_call/judgment_rules.py, with made-up results."""

from collections import Counter

import pytest

from tb_internet_use.tool_call.judgment_rules import (
    treat_exit_code_130_after_ctrl_c_as_killed,
    treat_negative_exit_code_as_killed,
    treat_wait_on_several_tasks_as_their_shared_status,
)
from tb_internet_use.tool_call.model import ExecutionStatus, ToolCallResult

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
