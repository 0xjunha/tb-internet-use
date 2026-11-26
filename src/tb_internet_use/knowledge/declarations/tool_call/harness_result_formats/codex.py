"""Declare the result formats of Codex tools."""

from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    JsonObject,
    MatchedValues,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Text = HarnessTextResultFormat
Json = HarnessJsonResultFormat

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

# Codex writes this when the arguments of a call are not of the types the tool takes, e.g. an `exec_command` whose `cmd` is a list of words.
# It reads the arguments before it starts or polls anything, so the call ran nothing.
_REJECTED_ARGUMENTS = Text(
    "rejected_arguments",
    "failed to parse function arguments: {reason:text}",
    S.NOT_RUN,
)
# Formats that exec_command and write_stdin share, of a command that exited or still runs.
_SHELL_EXITED_TRUNCATED = Text(
    "exited_truncated",
    _HEAD + _PROCESS_EXITED + _TOKENS + _TRUNCATED + "{tool_output:text}",
    S.FINISHED,
    is_truncated=True,
)
_SHELL_EXITED_TRUNCATED_NO_LINE_COUNT = Text(
    "exited_truncated_no_line_count",
    _HEAD + _PROCESS_EXITED + _TOKENS + _TRUNCATED_NO_LINE_COUNT + "{tool_output:text}",
    S.FINISHED,
    is_truncated=True,
)
_SHELL_EXITED = Text(
    "exited",
    _HEAD + _PROCESS_EXITED + _TOKENS + "{tool_output:text}",
    S.FINISHED,
)
_SHELL_RUNNING_TRUNCATED = Text(
    "running_truncated",
    _HEAD + _PROCESS_RUNNING + _TOKENS + _TRUNCATED + "{tool_output:text}",
    S.RUNNING,
    is_truncated=True,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_SHELL_RUNNING_TRUNCATED_NO_LINE_COUNT = Text(
    "running_truncated_no_line_count",
    _HEAD
    + _PROCESS_RUNNING
    + _TOKENS
    + _TRUNCATED_NO_LINE_COUNT
    + "{tool_output:text}",
    S.RUNNING,
    is_truncated=True,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_SHELL_RUNNING = Text(
    "running",
    _HEAD + _PROCESS_RUNNING + _TOKENS + "{tool_output:text}",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_EXEC_COMMAND = HarnessResultFormatList[str](
    (
        _SHELL_EXITED_TRUNCATED,
        _SHELL_EXITED_TRUNCATED_NO_LINE_COUNT,
        _SHELL_EXITED,
        _SHELL_RUNNING_TRUNCATED,
        _SHELL_RUNNING_TRUNCATED_NO_LINE_COUNT,
        _SHELL_RUNNING,
        Text(
            "v2_exited",
            _V2
            + "Exit code: {exit_code:int}\nWall time: {seconds2:line_without_brackets} seconds\nOutput:\n{tool_output:text}",
            S.FINISHED,
        ),
        Text(
            "rejected",
            "exec_command failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        Text(
            "rejected_command",
            "exec_command failed for `{command:text}`: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        _REJECTED_ARGUMENTS,
        Text(
            "rejected_patch",
            "apply_patch verification failed: {reason:text}",
            S.NOT_RUN,
        ),
    )
)
_WRITE_STDIN = HarnessResultFormatList[str](
    (
        _SHELL_EXITED_TRUNCATED,
        _SHELL_EXITED_TRUNCATED_NO_LINE_COUNT,
        _SHELL_EXITED,
        _SHELL_RUNNING_TRUNCATED,
        _SHELL_RUNNING_TRUNCATED_NO_LINE_COUNT,
        _SHELL_RUNNING,
        Text(
            "rejected_stdin",
            "write_stdin failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    )
)

# exec runs a script, and wait polls a script that was still running.
# A result that tells the state of the script starts with it, e.g. "Script completed", then this head.
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
# Codex adds the error of a failed script as its last item, under a line `Script error:` of its own.
_SCRIPT_ERROR_HEAD = "Script error:\n"


def _failed_script_output_text_of(matched_values: MatchedValues) -> str:
    """Give what a failed script printed and its error, without the line `Script error:` that Codex writes before the error."""
    text = str(matched_values.get("tool_output", ""))
    index = text.rfind(_SCRIPT_ERROR_HEAD)
    if index == -1 or (index > 0 and text[index - 1] != "\n"):
        return text
    return text[:index] + text[index + len(_SCRIPT_ERROR_HEAD) :]


# A failed script ran until its error, which stays in the tool output.
_FAILED = Text(
    "failed",
    _SCRIPT_FAILED + "{tool_output:text}",
    S.FINISHED,
    text_from_matched_values=_failed_script_output_text_of,
)
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
        # The result does not say whether a script that does not parse ran any step, so a judgment rule decides the status.
        Text(
            "failed_syntax",
            _SCRIPT_FAILED + "Script error:\nSyntaxError: {error:rest_of_line}",
            judgment_rule="treat_script_syntax_error_as_not_run",
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
        _REJECTED_ARGUMENTS,
    )
)

# The result entry of a web search in the trajectory, which the Codex converter holds as a JSON object.
_WEB_SEARCH_CALL = HarnessResultFormatList[JsonObject](
    (
        # Codex keeps no output of a web search, so the entry has no `content`.
        Json(
            "no_content",
            judgment_rule="treat_web_search_call_without_content_as_finished",
            absent_paths=("content",),
            no_tool_output_text=True,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "exec_command": HarnessToolResultDeclaration(text_formats=_EXEC_COMMAND),
    "write_stdin": HarnessToolResultDeclaration(text_formats=_WRITE_STDIN),
    "exec": HarnessToolResultDeclaration(text_formats=_EXEC),
    "wait": HarnessToolResultDeclaration(text_formats=_WAIT),
    "web_search_call": HarnessToolResultDeclaration(json_formats=_WEB_SEARCH_CALL),
}
