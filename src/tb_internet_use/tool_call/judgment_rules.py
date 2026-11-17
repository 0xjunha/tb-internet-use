"""Decide the statuses of tool call results that the trajectory does not settle, one named rule per situation.

Each rule is a judgment, not a reading of the trajectory, so it lives here where it can be found and changed, and the harness converters call it.
For example, Devin writes `Exit code: -1` for a command it stopped, and only a rule says that this means the command was killed.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a `ToolCallResult`.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import replace

from tb_internet_use.tool_call.model import ExecutionStatus, ToolCallResult

# The exit code of a process stopped by SIGINT, 128 plus the signal number 2.
_SIGINT_EXIT_CODE = 130


def treat_negative_exit_code_as_killed(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a negative exit code as a killed command and drop the code, whatever the format of the result.

    It rests on Devin, which writes -1 and never another negative code for a command it stopped, e.g. one that killed its own shell.
    That -1 is no real exit code or signal number.
    A use is a result with a negative exit code.

    Provisional. It keeps the choice of the earlier code.
    """
    if tool_call_result.exit_code is not None and tool_call_result.exit_code < 0:
        use_counts[treat_negative_exit_code_as_killed.__name__] += 1
        return replace(
            tool_call_result, execution_status=ExecutionStatus.KILLED, exit_code=None
        )
    return tool_call_result


def treat_exit_code_130_after_ctrl_c_as_killed(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read exit code 130 of a call that sent Ctrl-C as a killed process and drop the code.

    It rests on Codex `write_stdin`, whose Ctrl-C stops the process, which then exits with 130 as a process stopped by SIGINT does.
    The caller decides whether the call sent Ctrl-C.
    A use is a result with exit code 130 of a call that sent Ctrl-C.

    Provisional. It keeps the choice of the earlier code.
    """
    if tool_call_result.exit_code == _SIGINT_EXIT_CODE:
        use_counts[treat_exit_code_130_after_ctrl_c_as_killed.__name__] += 1
        return replace(
            tool_call_result, execution_status=ExecutionStatus.KILLED, exit_code=None
        )
    return tool_call_result


def treat_wait_on_several_tasks_as_their_shared_status(
    task_states: Collection[str],
    status_by_task_state: Mapping[str, ExecutionStatus],
    *,
    use_counts: Counter[str],
) -> ExecutionStatus:
    """Give a wait on several tasks the status of the state that every task shares, and unknown when the states differ, are missing or have no status.

    It rests on Grok Build `get_command_or_subagent_output`, whose result lists each task with its own state while a `ToolCallResult` holds one status.
    The states are compared as the harness names them, so `completed` and `failed` differ although both are finished.
    Every call is a use, since every wait on several tasks gets its status from this rule.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_wait_on_several_tasks_as_their_shared_status.__name__] += 1
    states = set(task_states)
    if len(states) != 1:
        return ExecutionStatus.UNKNOWN
    return status_by_task_state.get(states.pop(), ExecutionStatus.UNKNOWN)
