"""Decide the statuses and exit codes of tool call results that the result text does not state, one named rule per situation.

Each rule is a judgment, not a reading of the trajectory, so it lives here where it can be found and changed.
A declared result format names the rule that decides its status, and `convert_tool_calls` calls it for every result of that format.
A harness converter calls a rule itself when the situation is more than one format, e.g. a Codex `write_stdin` call that sent Ctrl-C.
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
    The Devin formats that end in a negative `Exit code` line name this rule, and the Devin converter applies it to the result of any other format too.
    A use is a result with a negative exit code.

    Provisional. It keeps the choice of the earlier code.
    """
    if tool_call_result.exit_code is not None and tool_call_result.exit_code < 0:
        # A format that names this rule fits only a negative code, so it always gets here.
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


def treat_bash_output_without_exit_code_line_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a command result that holds only the command output, without an `Exit code` line, as a finished command.

    It rests on Claude Code `Bash`, which writes `Exit code N` before the output only in a result it marked as an error.
    A result without the line may still come from a command that was stopped, since nothing in the text says how it ended.
    A use is a result of the format `bare_output`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_bash_output_without_exit_code_line_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_bash_output_without_exit_code_line_as_exit_code_0(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Give exit code 0 to a finished command whose result has no `Exit code` line.

    It rests on Claude Code `Bash`, which writes no `Exit code` line for a command it did not judge an error, whose code is 0 or the 1 of grep, find, diff and the like.
    The caller decides that the result is such a command, that its structured result says it was not interrupted and that it names no meaning for code 1.
    A use is a result that gets exit code 0 this way.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_bash_output_without_exit_code_line_as_exit_code_0.__name__] += 1
    return replace(tool_call_result, exit_code=0)


def treat_script_syntax_error_as_not_run(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a tool script that failed with a `SyntaxError` as a script that ran nothing.

    It rests on Codex `exec`, whose result shows `Script error` and then `SyntaxError` for a script that does not parse, without saying whether any step ran.
    A use is a result of the format `failed_syntax`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_script_syntax_error_as_not_run.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.NOT_RUN)


def treat_web_search_call_without_content_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a web search whose result has no content as a finished search.

    It rests on Codex `web_search_call`, whose result in the trajectory has no `content` at all, so nothing tells how the search ended.
    A use is a result of the format `no_content`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_web_search_call_without_content_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_failed_file_tool_call_as_not_run(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a file tool call whose result gives a reason it failed as a call that did no work.

    It rests on the file tools that read or change a file, i.e. Claude Code `Read`, Grok Build `read_file` and `search_replace` and Cursor `readToolCall` and `editToolCall`, whose results give a reason such as `File does not exist.` without saying whether the tool touched anything.
    A use is a result of one of their failure formats, e.g. `missing`, `too_large` or `not_unique`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_failed_file_tool_call_as_not_run.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.NOT_RUN)


def treat_get_output_without_exit_code_as_running(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a poll result that shows output without an `Exit code` line as a command still running.

    It rests on Devin `get_output`, whose result ends in an `Exit code` line once the command has exited, so any other text is taken as output of a command that has not.
    A use is a result of the format `running`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_get_output_without_exit_code_as_running.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.RUNNING)


def treat_web_fetch_text_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a web fetch result that is only page text as a finished fetch.

    It rests on Claude Code `WebFetch`, whose result is any text when no other format of the tool fits, e.g. the page as the model summed it up.
    A use is a result of the format `page`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_web_fetch_text_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_written_input_as_running_target(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a result that only reports input written to a process as a process still running.

    It rests on Devin `write_to_process`, whose result `Written N bytes to shell ...` says the input arrived but not what the process did next.
    A use is a result of the format `written`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_written_input_as_running_target.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.RUNNING)


def treat_accepted_stop_request_as_killed(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read an accepted request to stop background work as work that was killed.

    It rests on Muse `work_stop`, whose result has the `status` `accepted` and does not say whether the work then stopped.
    A use is a result of the format `accepted`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_accepted_stop_request_as_killed.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.KILLED)


def treat_failed_task_without_exit_code_as_killed(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a failed background task whose result has no `Exit Code` line as a killed task.

    It rests on Grok Build `get_command_or_subagent_output`, whose result shows `Status: failed` with an `Exit Code` line for a command that exited, and without one otherwise, e.g. for a command stopped by a signal.
    A use is a result of the format `failed_signaled` or `failed_signaled_empty`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_failed_task_without_exit_code_as_killed.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.KILLED)
