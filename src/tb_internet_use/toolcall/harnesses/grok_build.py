"""Grok Build tool call converter."""

import re
from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
    RawToolCall,
    ToolCallOutput,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
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
            True,
        ),
        Text("exited", "exit: {exit_code:int}\n{tool_output:text}", S.FINISHED),
        Text("exited_silent", "exit: {exit_code:int}", S.FINISHED),
        Text(
            "killed_truncated",
            "exit: killed (signal {signal:int})"
            + _TRUNCATED_HEAD
            + "\n{tool_output:text}",
            S.KILLED,
            True,
        ),
        Text(
            "killed", "exit: killed (signal {signal:int})\n{tool_output:text}", S.KILLED
        ),
        Text("background", _BACKGROUND + _USE_OUTPUT, S.RUNNING),
        Text("background_v2", _BACKGROUND + _USE_OUTPUT_V2, S.RUNNING),
        Text(
            "rejected", "Tool `run_terminal_command` failed: {reason:text}", S.NOT_RUN
        ),
        Text(
            "rejected_arguments",
            "Failed to parse arguments for tool `run_terminal_command`: {reason:text}",
            S.NOT_RUN,
        ),
    ),
    notices=_NOTICES,
)

_TASK = "=== Task {handle:id} ===\nCommand: {command:text}\n"
_OUTPUT = "Output File: {output_path:line}\n\n=== Output ===\n"
_TRUNCATED_TAIL = "\n[truncated - use read_file on output_file for full content]"
# A line some truncated results have before `_TRUNCATED_TAIL`.
_TRUNCATED_BYTES = "\n[Output truncated - {bytes:int} bytes total. Use read_file on {saved_to:line_without_brackets} for full content]"
_DONE = (
    _TASK
    + "Status: completed\nDuration: {duration:line}\nExit Code: {exit_code:int}\n"
    + _OUTPUT
)
_FAILED = (
    _TASK
    + "Status: failed\nDuration: {duration:line}\nExit Code: {exit_code:int}\n"
    + _OUTPUT
)
_RUNNING = _TASK + "Status: running\nDuration: {duration:line}\n" + _OUTPUT
_FAILED_SIGNALED = _TASK + "Status: failed\nDuration: {duration:line}\n" + _OUTPUT
_CANCELLED = _TASK + "Status: cancelled\nDuration: {duration:line}\n" + _OUTPUT
_TIMED_OUT = _TASK + "Status: timed_out\nDuration: {duration:line}\n" + _OUTPUT

_GET_OUTPUT = HarnessResultFormatList[str](
    (
        Text("done_empty", _DONE + "(no output)", S.FINISHED),
        Text(
            "done_empty_truncated",
            _DONE + "(no output)" + _TRUNCATED_TAIL,
            S.FINISHED,
            True,
        ),
        Text(
            "done_truncated_bytes",
            _DONE + "{tool_output:text}" + _TRUNCATED_BYTES + _TRUNCATED_TAIL,
            S.FINISHED,
            True,
        ),
        Text(
            "done_truncated",
            _DONE + "{tool_output:text}" + _TRUNCATED_TAIL,
            S.FINISHED,
            True,
        ),
        Text("done", _DONE + "{tool_output:text}", S.FINISHED),
        Text("failed_empty", _FAILED + "(no output)", S.FINISHED),
        Text(
            "failed_empty_truncated",
            _FAILED + "(no output)" + _TRUNCATED_TAIL,
            S.FINISHED,
            True,
        ),
        Text(
            "failed_truncated",
            _FAILED + "{tool_output:text}" + _TRUNCATED_TAIL,
            S.FINISHED,
            True,
        ),
        Text("failed", _FAILED + "{tool_output:text}", S.FINISHED),
        Text("failed_signaled_empty", _FAILED_SIGNALED + "(no output)", S.KILLED),
        Text("failed_signaled", _FAILED_SIGNALED + "{tool_output:text}", S.KILLED),
        Text(
            "running_empty", _RUNNING + "(no output)\n\n{note:rest_of_line}", S.RUNNING
        ),
        Text(
            "running_empty_truncated",
            _RUNNING + "(no output)\n\n{note:rest_of_line}" + _TRUNCATED_TAIL,
            S.RUNNING,
            True,
        ),
        Text(
            "running_truncated",
            _RUNNING + "{tool_output:text}\n\n{note:rest_of_line}" + _TRUNCATED_TAIL,
            S.RUNNING,
            True,
        ),
        Text(
            "running", _RUNNING + "{tool_output:text}\n\n{note:rest_of_line}", S.RUNNING
        ),
        Text("running_no_note", _RUNNING + "{tool_output:text}", S.RUNNING),
        Text("cancelled_empty", _CANCELLED + "(no output)", S.KILLED),
        Text("cancelled", _CANCELLED + "{tool_output:text}", S.KILLED),
        Text("timed_out_empty", _TIMED_OUT + "(no output)", S.TIMED_OUT),
        Text("timed_out", _TIMED_OUT + "{tool_output:text}", S.TIMED_OUT),
        Text(
            "multi_wait",
            "=== Multi-wait ({mode:line_without_brackets}) ===\n{tool_output:text}",
            S.UNKNOWN,
        ),
        Text(
            "rejected",
            "Tool `get_command_or_subagent_output` failed: {reason:text}",
            S.NOT_RUN,
        ),
        Text(
            "unknown_task",
            "Task {handle:id} not found. Known task IDs: {known:rest_of_line}",
            S.NOT_RUN,
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
            tool_output_not_in_trajectory=True,
        ),
        Text(
            "pdf",
            "Read PDF file: {path:line} ({pages:line_without_brackets} pages rendered, {total:int} total)",
            S.FINISHED,
            tool_output_not_in_trajectory=True,
        ),
        Text("empty", "File is empty.", S.FINISHED),
        Text(
            "past_end",
            "(no lines returned: the requested window is past the end of the file; the file has {total:int} lines)",
            S.FINISHED,
        ),
        Text("missing", "Error: {path:line} does not exist.", S.NOT_RUN),
        Text(
            "too_large",
            "File content ({size:line_without_brackets}) exceeds maximum allowed tokens ({limit:line_without_brackets}).{rest:text}",
            S.NOT_RUN,
        ),
        Text(
            "range_too_large",
            "The requested line range ({range:line_without_brackets}) contains {rest:text}",
            S.NOT_RUN,
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
            S.NOT_RUN,
        ),
        Text(
            "not_unique",
            "The string to replace was found multiple times in the file. {hint:text}",
            S.NOT_RUN,
        ),
        Text("same_strings", "Old string and new string are the same", S.NOT_RUN),
        Text("missing", "Error: {path:line} does not exist.", S.NOT_RUN),
        Text(
            "rejected_arguments",
            "Failed to parse arguments for tool `search_replace`: {reason:text}",
            S.NOT_RUN,
        ),
    ),
    notices=_NOTICES,
)

_MULTI_WAIT_TASK = re.compile(r"^--- Task (\S+) \[(\w+)\] ---$", re.MULTILINE)
_MULTI_WAIT_STATES = {
    "completed": S.FINISHED,
    "failed": S.FINISHED,
    "running": S.RUNNING,
}


def _multi_wait(output: ToolCallOutput) -> ToolCallOutput:
    """Status and handles of a multi-wait: one state shared by every task, else unknown."""
    tasks = _MULTI_WAIT_TASK.findall(output.tool_output_text or "")
    states = {state for _, state in tasks}
    status = (
        _MULTI_WAIT_STATES.get(states.pop(), S.UNKNOWN)
        if len(states) == 1
        else S.UNKNOWN
    )
    handles = tuple(
        ExecutionHandle(ExecutionHandleKind.COMMAND, task_id) for task_id, _ in tasks
    )
    return replace(output, execution_status=status, handles=handles)


class GrokBuildConverter(HarnessToolCallConverter):
    stop_tools: ClassVar[frozenset[str]] = frozenset({"kill_command_or_subagent"})
    text_formats: ClassVar = {
        "run_terminal_command": _RUN_TERMINAL_COMMAND,
        "get_command_or_subagent_output": _GET_OUTPUT,
        "kill_command_or_subagent": _KILL,
        "monitor": _MONITOR,
        "read_file": _READ_FILE,
        "write": _WRITE,
        "search_replace": _SEARCH_REPLACE,
    }

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        output = super().parse_output(raw, result)
        return (
            _multi_wait(output)
            if output.harness_result_format == MatchedFormat("multi_wait")
            else output
        )
