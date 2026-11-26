"""Decide what the trajectory does not settle about tool calls, one named rule per situation, i.e. the statuses and exit codes that a result text does not state and how far a misread shell text is repaired.

Each rule is a judgment, not a reading of the trajectory, so it lives here where it can be found and changed.
A declared result format names the rule that decides its status, and `convert_tool_calls` calls it for every result of that format.
A harness converter calls a rule itself when the situation is more than one format, e.g. a Codex `write_stdin` call that sent Ctrl-C, and so does `parse_shell_text`.
For example, Devin writes `Exit code: -1` for a command it stopped, and only a rule says that this means the command was killed.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a `ToolCallResult` or a `ParsedShellText`.

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
    """Read a negative exit code as a killed command and drop the code.

    It rests on Devin, which writes -1 and never another negative code for a command it stopped, e.g. one that killed its own shell.
    That -1 is no real exit code or signal number.
    A use is a result of the Devin formats that end in a negative `Exit code` line, `killed` of `exec` and `killed_silent_twice` of `get_output`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_negative_exit_code_as_killed.__name__] += 1
    return replace(
        tool_call_result, execution_status=ExecutionStatus.KILLED, exit_code=None
    )


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
    The same holds for a result that only says the output was too large and names the file it was saved to.
    A command that Claude Code moved to the background, also after a timeout, has a result of its own, which the formats `background` and `background_timeout` read as running, unless it printed before its timeout ended. Then the text shows the output before the notice, and the Claude Code converter reads the result as running after this rule, since its structured result names the background task in `backgroundTaskId`. Such a result is a use too.
    Only a finished status gets exit code 0 by `treat_bash_output_without_exit_code_line_as_exit_code_0`, so the two rules together make a later use of a saved file sure evidence.
    A use is a result of the format `bare_output`, `persisted_output_cut_preview`, `persisted_output` or `persisted_output_partial`.

    Decided. The user decided on 2026-11-24 that such a result is a finished command, as a fact of Claude Code, since a command that did not end in the call has a result of another format, and reading it as unknown would drop the evidence of 754,787 results in 8,881 of the 21,450 Terminal-Bench 4.1 trials.
    """
    use_counts[treat_bash_output_without_exit_code_line_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_bash_output_without_exit_code_line_as_exit_code_0(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Give exit code 0 to a finished command whose result has no `Exit code` line.

    It rests on Claude Code `Bash`, which writes no `Exit code` line for a command it did not judge an error, whose code is 0 or the 1 of grep, find, diff and the like.
    The caller decides that the result is such a command, that its structured result does not say that it was interrupted, also when it has no key `interrupted`, and that it has no `returnCodeInterpretation`, whose exit code `ToolCallKnowledge` gives.
    The 0 is not written in the trajectory, so a received lower bound that a sure use of a saved file gives rests on this convention of Claude Code.
    A use is a result that gets exit code 0 this way, also one of the format `no_output`, whose status is finished without a rule.

    Decided. The user decided on 2026-11-24 to take the convention as a fact of Claude Code, which marks a command that exited with another code as an error or names its code in `returnCodeInterpretation`, after the review of that day found no result in the Terminal-Bench 4.1 trajectories against it.
    """
    use_counts[treat_bash_output_without_exit_code_line_as_exit_code_0.__name__] += 1
    return replace(tool_call_result, exit_code=0)


def treat_bash_exit_code_144_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a command result that starts with `Exit code 144` as a finished command.

    It rests on Claude Code `Bash`, whose result shows this code for commands that hold `kill`, `pkill` or `killall` in 410 of the 413 such results of 2,000 random Terminal-Bench 4.1 trials, e.g. `pkill -f server.py; curl -s https://a.org/x`.
    Such a command can stop the shell that runs it when its pattern matches the command line of that shell, and then the commands after it never run. The text looks the same for a command that exited with 144 itself, so it does not say whether the command finished or was stopped.
    The formats leave 144 out of `exit_code`, which holds only a code that the command gave itself, as for the `Exit code 143` of a command that timed out.
    A use is a result of the format `exit_code_144` or `exit_code_144_silent`.

    Provisional. It keeps the status of the earlier code, which also kept 144 as the exit code.
    """
    use_counts[treat_bash_exit_code_144_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_script_syntax_error_as_not_run(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a tool script that failed with a `SyntaxError` as a script that ran nothing.

    It rests on Codex `exec`, whose result shows `Script error` and then `SyntaxError` for a script that does not parse, without saying whether any step ran.
    The format takes a result whose output is only `Script error:` and one `SyntaxError` line, so a `SyntaxError` that the code throws while it runs, e.g. from `JSON.parse`, gives the same text when the script printed nothing else.
    A use is a result of the format `failed_syntax`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_script_syntax_error_as_not_run.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.NOT_RUN)


def treat_action_not_executed_result_as_unknown_status(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a result that says the action was not executed as one whose status is unknown.

    It rests on mini-swe-agent `bash`, which stops the actions of a step after the one whose output starts with the line `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` and that exited 0, the sign that the agent submits, and fills the result of that action and of every later one of the step with `action was not executed`, as a review of 2026-11-24 read in the source of mini-swe-agent 2.4.6. So the action that submitted did run.
    Each of the 321 such results in 2,000 random Terminal-Bench 4.1 trials is the only one of its step and holds the sign in its command, e.g. `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`, so each comes from an action that ran, and none from a later action of the step.
    The format gives no tool output text, since the empty `output` of such a result is not what the command printed.
    A use is a result of the format `not_executed`.

    Decided. The user decided on 2026-11-25 that the status is unknown, since the command ran but the result holds neither its output nor its exit code. The earlier code read such a result as `NOT_RUN`, which made every request of the command a failure.
    """
    use_counts[treat_action_not_executed_result_as_unknown_status.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.UNKNOWN)


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

    It rests on the file tools that read or change a file, i.e. Claude Code `Read`, Grok Build `read_file` and `search_replace`, Cursor CLI `readToolCall` and `editToolCall` and Copilot CLI `view`, `create` and `edit`, whose results give a reason such as `File does not exist.` without saying whether the tool touched anything.
    The format `unchanged` of Claude Code `Read` names it too, though it is no failure but a read that Claude Code skipped since the file did not change, which also returns no content.
    A use is a result of one of their failure formats or of `unchanged`, e.g. `missing`, `too_large` or `not_unique`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_failed_file_tool_call_as_not_run.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.NOT_RUN)


def treat_get_output_without_exit_code_as_running(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a poll result that shows output without an `Exit code` line as a command still running.

    It rests on Devin `get_output`, whose result ends in an `Exit code` line once the command has exited, so any other text, whole or as a diff since the last read, is taken as output of a command that has not.
    A use is a result of the format `running` or `running_incremental`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_get_output_without_exit_code_as_running.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.RUNNING)


def treat_web_fetch_text_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a web fetch result that is only page text as a finished fetch.

    It rests on Claude Code `WebFetch`, whose result is any text when no other format of the tool fits, e.g. the page as the model summed it up, with no line of the harness that says how the fetch went.
    A use is a result of the format `page` or `page_truncated`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_web_fetch_text_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_written_input_as_running_target(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a result that only reports input written to a process as a process still running.

    It rests on Devin `write_to_process`, whose result `Written N bytes to shell ...` says the input arrived but not what the process did next, and on Antigravity CLI `manage_task` with the `Action` `send_input`, whose result `Input sent to task ...` says the same.
    A use is a result of the format `written` or `input_sent`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_written_input_as_running_target.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.RUNNING)


def treat_idle_subagent_as_unknown_status(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a result that reports a subagent as idle as one whose status is unknown.

    It rests on Copilot CLI `read_agent`, whose result `Agent is idle (waiting for messages)` says that the subagent ended its turn and waits for a message, which can set it to work again. The text says neither that the subagent's work ended nor that it goes on.
    A use is a result of the format `idle`.

    Provisional. No earlier code read Copilot CLI, so it takes the status that claims least.
    """
    use_counts[treat_idle_subagent_as_unknown_status.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.UNKNOWN)


def treat_accepted_stop_request_as_killed(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read an accepted request to stop background work as work that was killed.

    It rests on Muse Code `work_stop`, whose result has the `status` `accepted` and does not say whether the work then stopped, and on Devin `kill_shell`, whose result `Shell sh1 terminated successfully` does not say whether the command of the shell still ran.
    Devin writes that sentence also for a shell whose command had already exited, e.g. after a `get_output` of the same shell that showed its exit code.
    A use is a result of the format `accepted` of Muse Code `work_stop` or `killed` of Devin `kill_shell`.

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


def treat_tool_failure_message_as_not_run(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a result whose text says only that the tool call failed as a call that did no work.

    It rests on the messages in which a harness reports a failed call without saying whether the tool started, i.e. Claude Code `<tool_use_error>`, Muse Code `tool failed`, Codex `exec_command failed` and `write_stdin failed`, Grok Build ``Tool `...` failed``, Devin `Failed to configure output monitoring.` of `get_output` and Antigravity CLI `Encountered error in step execution`.
    A message that the arguments of a call could not be parsed or validated says that the tool did not start, so its format declares `NOT_RUN` without this rule, e.g. Codex `failed to parse function arguments`, Devin `Tool 'exec' validation failed` or Copilot CLI `Invalid input`.
    A use is a result of one of their formats, i.e. `tool_use_error`, `rejected`, `rejected_command`, `rejected_stdin`, `failed_monitoring` or `failed`.

    Provisional. It keeps the choice of the earlier code. The user has not yet confirmed that the formats of rejected arguments declare `NOT_RUN` without it, which a review of 2026-11-24 recommended.
    """
    use_counts[treat_tool_failure_message_as_not_run.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.NOT_RUN)


def treat_completed_await_without_exit_code_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a wait whose result says that the command is complete but gives no exit code as a finished command.

    It rests on Cursor CLI `awaitToolCall`, whose result holds `success.complete` with an `exitCode` when the awaited command exited.
    Each of the 8 such results without an `exitCode` in the Cursor CLI trials of Terminal-Bench 3.0 and 4.0 comes within three calls after a `kill`, `pkill` or `killall`, so the command may have been stopped by a signal, and the result does not say whether it ended on its own.
    A use is a result of the format `complete_without_exit_code`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_completed_await_without_exit_code_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_shell_id_with_exit_code_as_running(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a shell result that names a shell id beside an exit code as a command still running in the background.

    It rests on Cursor CLI `shellToolCall`, whose result for a command sent to the background holds a `shellId` and also an `exitCode`, which is 0 in every such result of the trajectories, while later waits on the same shell can still report it running.
    So the code may belong to starting the command rather than to the command, and the result does not say which, so its formats do not read the code.
    A use is a result of the format `background` or `background_requested`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_shell_id_with_exit_code_as_running.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.RUNNING)


def treat_stop_request_for_ended_work_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a request to stop background work that had already ended as work that finished.

    It rests on Muse Code `work_stop` and Grok Build `kill_command_or_subagent`, whose results say that the work had ended before the request but not for sure how.
    Muse Code writes the `status` `already_terminal` and a `terminal`, which is `completed` in both such results of the Terminal-Bench 4.1 trajectories. Its `bash` results give `completed` to a command that exited, and it is not known whether Muse Code writes it also for work that its time limit stopped, e.g. a `monitor` whose timeout ran out.
    Grok Build writes `already_exited: Task had already completed`, and it says `completed` also for a task that a signal stopped, e.g. in a `system-reminder` of the format `terminated`.
    A use is a result of the format `already_ended` of Muse Code `work_stop` or `already_exited` of Grok Build `kill_command_or_subagent`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_stop_request_for_ended_work_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_cut_off_web_search_as_finished(
    tool_call_result: ToolCallResult, *, use_counts: Counter[str]
) -> ToolCallResult:
    """Read a web search cut off before any result arrived as a finished search.

    It rests on Claude Code `WebSearch`, whose result says that the search was cut off before any results arrived, without saying whether the search reached the provider or what stopped it.
    A use is a result of the format `cut_off`.

    Provisional. It keeps the choice of the earlier code.
    """
    use_counts[treat_cut_off_web_search_as_finished.__name__] += 1
    return replace(tool_call_result, execution_status=ExecutionStatus.FINISHED)


def treat_lines_joined_after_three_repairs_as_left_joined(
    repair_count: int, *, use_counts: Counter[str]
) -> bool:
    """Leave the lines of a shell text that tree-sitter-bash still joins after three repairs as they are, instead of repairing on.

    It rests on tree-sitter-bash 0.25.1, which reads the line after a pipeline of three or more stages as more words of its last stage, e.g. `d` after `a | b | c` as `c d`.
    `parse_shell_text` repairs that by putting `;` at the end of each joined line and parsing again, and the new parse can join other lines.
    It asks this rule once it has repaired a text `repair_count` times, which is three, and lines are still joined.
    On `True` it marks every command of the text with `structure_may_be_wrong`, and on `False` it repairs on until no line is joined or a repair no longer lowers the number of joined lines.
    `extract_network_requests` reads the mark, so every request of a known fetching program in such a command is uncertain with the reason `STRUCTURE_MAY_BE_WRONG`, e.g. a request for `https://b.org` when the next line `echo https://b.org` is read as more words of `curl -s http://localhost:8000/x`. `decide_network_request_results` reads it too and takes no exit code and no sure file use of such a command.
    A use is such a text.

    Provisional. It keeps the choice of the earlier code, which repaired a text at most three times. That `extract_network_requests` makes the requests of such a command uncertain is what the review of 2026-11-24 recommended, and the user has not yet confirmed it.
    """
    use_counts[treat_lines_joined_after_three_repairs_as_left_joined.__name__] += 1
    return True
