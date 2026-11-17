"""Declare the result formats of Codex tools."""

from collections.abc import Mapping

from tb_internet_use.knowledge.harness_result_format_declaration import (
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

_HEAD = "Chunk ID: {chunk:id}\nWall time: {seconds:line_without_brackets} seconds\n"
_PROCESS_EXITED = "Process exited with code {exit_code:int}\n"
_PROCESS_RUNNING = "Process running with session ID {handle:int}\n"
_TOKENS = "Original token count: {tokens:int}\nOutput:\n"
_TRUNCATED = "Warning: truncated output (original token count: {original:int})\nTotal output lines: {lines:int}\n\n"
# The same warning without the line count, followed right away by the output.
_TRUNCATED_NO_LINE_COUNT = (
    "Warning: truncated output (original token count: {original:int})\n"
)

_V2 = "Wall time: {seconds:line_without_brackets} seconds\nOutput:\n"

_SHELL = HarnessResultFormatList[str](
    (
        Text(
            "exited_truncated",
            _HEAD + _PROCESS_EXITED + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited_truncated_no_line_count",
            _HEAD
            + _PROCESS_EXITED
            + _TOKENS
            + _TRUNCATED_NO_LINE_COUNT
            + "{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited",
            _HEAD + _PROCESS_EXITED + _TOKENS + "{tool_output:text}",
            S.FINISHED,
        ),
        Text(
            "running_truncated",
            _HEAD + _PROCESS_RUNNING + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.RUNNING,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "running",
            _HEAD + _PROCESS_RUNNING + _TOKENS + "{tool_output:text}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "v2_exited",
            _V2
            + "Exit code: {exit_code:int}\nWall time: {seconds2:line_without_brackets} seconds\nOutput:\n{tool_output:text}",
            S.FINISHED,
        ),
        Text("rejected", "exec_command failed: {reason:text}", S.NOT_RUN),
        Text(
            "rejected_command",
            "exec_command failed for `{command:text}`: {reason:text}",
            S.NOT_RUN,
        ),
        Text(
            "rejected_patch",
            "apply_patch verification failed: {reason:text}",
            S.NOT_RUN,
        ),
        Text("rejected_stdin", "write_stdin failed: {reason:text}", S.NOT_RUN),
    )
)

# exec runs a script, and wait polls a script that was still running. Both results
# start with the script's state, e.g. "Script completed", then this head.
_SCRIPT_HEAD = "\nWall time {seconds:line_without_brackets} seconds\nOutput:\n"
_SCRIPT_COMPLETED = "Script completed" + _SCRIPT_HEAD
_SCRIPT_FAILED = "Script failed" + _SCRIPT_HEAD
_SCRIPT_RUNNING = "Script running with cell ID {handle:word}" + _SCRIPT_HEAD
_COMPLETED_TRUNCATED = Text(
    "completed_truncated",
    _SCRIPT_COMPLETED + _TRUNCATED + "{tool_output:text}",
    S.FINISHED,
    is_truncated=True,
)
_COMPLETED = Text("completed", _SCRIPT_COMPLETED + "{tool_output:text}", S.FINISHED)
# A failed script ran until its error, which stays in the tool output.
_FAILED = Text("failed", _SCRIPT_FAILED + "{tool_output:text}", S.FINISHED)
_RUNNING_TRUNCATED = Text(
    "running_truncated",
    _SCRIPT_RUNNING + _TRUNCATED + "{tool_output:text}",
    S.RUNNING,
    is_truncated=True,
    fixed_handle_kind=ExecutionHandleKind.SCRIPT,
)
_RUNNING = Text(
    "running",
    _SCRIPT_RUNNING + "{tool_output:text}",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.SCRIPT,
)
_EXEC = HarnessResultFormatList[str](
    (
        _COMPLETED_TRUNCATED,
        Text(
            "completed_truncated_bytes",
            _SCRIPT_COMPLETED
            + _TRUNCATED_NO_LINE_COUNT
            + "... {omitted:int} bytes omitted ...\n\n{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        _COMPLETED,
        # A script that does not parse runs nothing.
        Text(
            "failed_syntax",
            _SCRIPT_FAILED + "Script error:\nSyntaxError: {error:rest_of_line}",
            S.NOT_RUN,
        ),
        _FAILED,
        _RUNNING_TRUNCATED,
        _RUNNING,
        Text(
            "host_killed",
            "code-mode host exited with status signal: {signal:int} ({signal_name:id})",
            S.KILLED,
        ),
        Text(
            "host_exited",
            "code-mode host exited with status exit status: {host_status:int}",
            S.UNKNOWN,
        ),
    )
)
_WAIT = HarnessResultFormatList[str](
    (
        _COMPLETED_TRUNCATED,
        _COMPLETED,
        Text(
            "cell_not_found",
            _SCRIPT_FAILED + "Script error:\nexec cell {cell:word} not found",
            S.NOT_RUN,
        ),
        _FAILED,
        _RUNNING_TRUNCATED,
        _RUNNING,
        Text(
            "terminated",
            "Script terminated" + _SCRIPT_HEAD + "{tool_output:text}",
            S.KILLED,
        ),
        Text(
            "rejected_arguments",
            "failed to parse function arguments: {reason:text}",
            S.NOT_RUN,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "exec_command": HarnessToolResultDeclaration(text_formats=_SHELL),
    "write_stdin": HarnessToolResultDeclaration(text_formats=_SHELL),
    "exec": HarnessToolResultDeclaration(text_formats=_EXEC),
    "wait": HarnessToolResultDeclaration(text_formats=_WAIT),
}
