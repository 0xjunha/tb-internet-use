"""Declare the result formats of Grok Build tools and the notices Grok Build adds to their results."""

from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

_NOTICES = (
    HarnessNotice(
        "notification", "\n\n<system-reminder>{notice:text}</system-reminder>", at="end"
    ),
    HarnessNotice(
        "notification_after_line",
        "\n<system-reminder>{notice:text}</system-reminder>",
        at="end",
    ),
    HarnessNotice(
        "notification_bare",
        "<system-reminder>{notice:text}</system-reminder>",
        at="end",
    ),
)

_TRUNCATED_HEAD = " [truncated: showing {shown:line_without_brackets} - full output at: {output_path:line_without_brackets}]"
_BACKGROUND = (
    "<task-id>{handle:id}</task-id>\n<task-type>bash</task-type>\n"
    "<output-file>{output_path:line}</output-file>\n<status>running</status>\n"
    "<summary>{summary:text}</summary>\n"
)
_USE_OUTPUT = 'Use get_command_or_subagent_output with task_ids=["{handle2:id}"] when you need the output.'
_USE_OUTPUT_V2 = 'Use get_command_or_subagent_output tool with task_ids=["{handle2:id}"] to retrieve the output.'

_RUN_TERMINAL_COMMAND = HarnessResultFormatList[str](
    (
        Text(
            "exited_truncated",
            "exit: {exit_code:int}" + _TRUNCATED_HEAD + "\n{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text("exited", "exit: {exit_code:int}\n{tool_output:text}", S.FINISHED),
        Text(
            "killed_truncated",
            "exit: killed (signal {signal:int})"
            + _TRUNCATED_HEAD
            + "\n{tool_output:text}",
            S.KILLED,
            is_truncated=True,
        ),
        Text(
            "killed", "exit: killed (signal {signal:int})\n{tool_output:text}", S.KILLED
        ),
        Text(
            "background",
            _BACKGROUND + _USE_OUTPUT,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_v2",
            _BACKGROUND + _USE_OUTPUT_V2,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "rejected",
            "Tool `run_terminal_command` failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        Text(
            "rejected_arguments",
            "Failed to parse arguments for tool `run_terminal_command`: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    ),
    notices=_NOTICES,
)

_TASK = "=== Task {handle:id} ===\nCommand: {command:text}\n"
_OUTPUT = "Output File: {output_path:line}\n\n=== Output ===\n"
_TRUNCATED_TAIL = "\n[truncated - use read_file on output_file for full content]"
# A line some truncated results have before `_TRUNCATED_TAIL`.
_TRUNCATED_BYTES = "\n[Output truncated - {bytes:int} bytes total. Use read_file on {saved_to:line_without_brackets} for full content]"
_MISSING = Text(
    "missing",
    "Error: {path:line} does not exist.",
    judgment_rule="treat_failed_file_tool_call_as_not_run",
)
# What Grok Build writes in place of an empty task output.
_EMPTY = "(no output)"


def _task_head_template_for(status: str, *, with_exit_code: bool = False) -> str:
    """Build the template of a task's poll result up to its output."""
    exit_line = "Exit Code: {exit_code:int}\n" if with_exit_code else ""
    return (
        _TASK
        + f"Status: {status}\n"
        + "Duration: {duration:line}\n"
        + exit_line
        + _OUTPUT
    )


_DONE = _task_head_template_for("completed", with_exit_code=True)
_FAILED = _task_head_template_for("failed", with_exit_code=True)
_FAILED_SIGNALED = _task_head_template_for("failed")
_RUNNING = _task_head_template_for("running")
_CANCELLED = _task_head_template_for("cancelled")
_TIMED_OUT = _task_head_template_for("timed_out")
_WAIT_ON_SEVERAL_TASKS = Text(
    "multi_wait",
    "=== Multi-wait ({mode:line_without_brackets}) ===\n{tool_output:text}",
    S.UNKNOWN,
)

_GET_OUTPUT = HarnessResultFormatList[str](
    (
        Text(
            "done_empty",
            _DONE + _EMPTY,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "done_empty_truncated",
            _DONE + _EMPTY + _TRUNCATED_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "done_truncated_bytes",
            _DONE + "{tool_output:text}" + _TRUNCATED_BYTES + _TRUNCATED_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "done_truncated",
            _DONE + "{tool_output:text}" + _TRUNCATED_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "done",
            _DONE + "{tool_output:text}",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "failed_empty_truncated",
            _FAILED + _EMPTY + _TRUNCATED_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "failed_truncated",
            _FAILED + "{tool_output:text}" + _TRUNCATED_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "failed",
            _FAILED + "{tool_output:text}",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "failed_signaled_empty",
            _FAILED_SIGNALED + _EMPTY,
            judgment_rule="treat_failed_task_without_exit_code_as_killed",
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "failed_signaled",
            _FAILED_SIGNALED + "{tool_output:text}",
            judgment_rule="treat_failed_task_without_exit_code_as_killed",
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "running_truncated",
            _RUNNING + "{tool_output:text}\n\n{note:rest_of_line}" + _TRUNCATED_TAIL,
            S.RUNNING,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "running",
            _RUNNING + "{tool_output:text}\n\n{note:rest_of_line}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "cancelled_empty",
            _CANCELLED + _EMPTY,
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "timed_out",
            _TIMED_OUT + "{tool_output:text}",
            S.TIMED_OUT,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _WAIT_ON_SEVERAL_TASKS,
        Text(
            "rejected",
            "Tool `get_command_or_subagent_output` failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        Text(
            "unknown_task",
            "Task {handle:id} not found. Known task IDs: {known:rest_of_line}",
            S.NOT_RUN,
            fixed_handle_kind=ExecutionHandleKind.UNKNOWN,  # nothing confirms the id
        ),
    ),
    notices=_NOTICES,
)

_KILL = HarnessResultFormatList[str](
    (
        Text("killed", "killed: Task was terminated successfully", S.KILLED),
        Text(
            "already_exited", "already_exited: Task had already completed", S.FINISHED
        ),
        Text(
            "unknown_task",
            "Task or subagent {handle:id} not found. {reason:text}",
            S.NOT_RUN,
            fixed_handle_kind=ExecutionHandleKind.UNKNOWN,
        ),
    ),
    notices=_NOTICES,
)

_MONITOR = HarnessResultFormatList[str](
    (
        Text(
            "started",
            "Monitor started (task {handle:id}, timeout {timeout:line_without_brackets}).\n{note:text}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
    ),
    notices=_NOTICES,
)

_READ_FILE = HarnessResultFormatList[str](
    (
        Text(
            "image",
            "Read image file: {path:rest_of_line}",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text(
            "pdf",
            "Read PDF file: {path:line} ({pages:line_without_brackets} pages rendered, {total:int} total)",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text("empty", "File is empty.", S.FINISHED),
        Text(
            "past_end",
            "(no lines returned: the requested window is past the end of the file; the file has {total:int} lines)",
            S.FINISHED,
        ),
        _MISSING,
        Text(
            "directory",
            "Error: {path:line} is a directory, not a file.",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "binary",
            "Cannot read binary file: {path:rest_of_line}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "too_large",
            "File content ({size:line_without_brackets}) exceeds maximum allowed tokens ({limit:line_without_brackets}).{rest:text}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "range_too_large",
            "The requested line range ({range:line_without_brackets}) contains {rest:text}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text("listing", "{tool_output:partly_numbered_arrow}", S.FINISHED),
    ),
    notices=_NOTICES,
)

_WRITE = HarnessResultFormatList[str](
    (
        Text("written", "Wrote file successfully to {path:rest_of_line}", S.FINISHED),
        Text("created", "The file {path:line} has been created.", S.FINISHED),
    ),
    notices=_NOTICES,
)

_SEARCH_REPLACE = HarnessResultFormatList[str](
    (
        Text(
            "updated", "The file {path:line} has been updated successfully.", S.FINISHED
        ),
        Text(
            "created", "The file {path:line} has been created successfully.", S.FINISHED
        ),
        Text(
            "replaced_all",
            "The file {path:line} has been updated. All occurrences were successfully replaced.",
            S.FINISHED,
        ),
        Text(
            "not_found",
            "The string to replace was not found in the file, {hint:text}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "not_unique",
            "The string to replace was found multiple times in the file. {hint:text}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "same_strings",
            "Old string and new string are the same",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        _MISSING,
        Text(
            "rejected_arguments",
            "Failed to parse arguments for tool `search_replace`: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    ),
    notices=_NOTICES,
)


# Grok Build writes the end of a task that a `run_terminal_command` in the background or a `monitor` started as a block of this tag in a step of its own, with the command or its description but not its output.
# Its tool output text is therefore None, since "" would say that the command printed nothing.
_TASK_END_TAIL = (
    "\n{command_or_description:text} | Duration: {duration:line}\n"
    + 'Use get_command_or_subagent_output("{handle2:id}") '
)
# Grok Build adds a note when a signal stopped a task much sooner than expected, e.g. after 0.1s, which may have stopped it before its command ran.
_TASK_SHORT_NOTE_TAIL = (
    "\n{command_or_description:text} | Duration: {duration:line}\n"
    + "Note: this is much shorter than expected for a backgrounded command.{note:text}\n"
    + 'Use get_command_or_subagent_output("{handle2:id}") '
)
_SYSTEM_REMINDER = HarnessResultFormatList[str](
    (
        Text(
            "exited",
            '<system-reminder>\nBackground task "{handle:id}" completed (exit code: {exit_code:int}).'
            + _TASK_END_TAIL
            + "to see the full output.\n</system-reminder>",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
        # Grok Build writes `timeout` in place of the signal when the time limit of the task stopped it, as its polls say `Status: timed_out`.
        Text(
            "timed_out",
            '<system-reminder>\nBackground task "{handle:id}" completed (terminated by signal timeout).'
            + _TASK_END_TAIL
            + "to see the full output.\n</system-reminder>",
            S.TIMED_OUT,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
        # The signal is a number, e.g. `signal 15`, or the word `killed`.
        Text(
            "terminated",
            '<system-reminder>\nBackground task "{handle:id}" completed (terminated by signal {signal:line_without_brackets}).'
            + _TASK_END_TAIL
            + "to see the full output.\n</system-reminder>",
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
        Text(
            "terminated_short",
            '<system-reminder>\nBackground task "{handle:id}" completed (terminated by signal {signal:line_without_brackets}).'
            + _TASK_SHORT_NOTE_TAIL
            + "to see the full output.\n</system-reminder>",
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
        Text(
            "monitor_exited",
            '<system-reminder>\nMonitor "{handle:id}" ended: [monitor ended: exited (code {exit_code:int})].'
            + _TASK_END_TAIL
            + "for full output.\n\n</system-reminder>",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "run_terminal_command": HarnessToolResultDeclaration(
        text_formats=_RUN_TERMINAL_COMMAND
    ),
    "get_command_or_subagent_output": HarnessToolResultDeclaration(
        text_formats=_GET_OUTPUT
    ),
    "kill_command_or_subagent": HarnessToolResultDeclaration(text_formats=_KILL),
    "monitor": HarnessToolResultDeclaration(text_formats=_MONITOR),
    "read_file": HarnessToolResultDeclaration(text_formats=_READ_FILE),
    "write": HarnessToolResultDeclaration(text_formats=_WRITE),
    "search_replace": HarnessToolResultDeclaration(text_formats=_SEARCH_REPLACE),
    # Not a tool but a block that Grok Build writes to the agent in a step of its own, which `parse_trajectory` reads as a call.
    "system-reminder": HarnessToolResultDeclaration(text_formats=_SYSTEM_REMINDER),
}
