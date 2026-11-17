"""Declare the result formats of Muse Code tools."""

import re
from collections.abc import Mapping

from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    JsonCondition,
    JsonObject,
    MatchedValues,
    json_tool_output_text_of,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Json = HarnessJsonResultFormat
Text = HarnessTextResultFormat

_SHELL_FIELDS = {
    "tool_output": "output",
    "exit_code": "exit_code",
    "is_truncated": "truncated",
}
# Muse starts the output with this note when it replaced bytes that are not UTF-8.
_REPLACED_BYTES_NOTE = re.compile(
    r"\[unified exec output: \d+ invalid UTF-8 bytes? replaced with U\+FFFD\]\n?"
)


def _shell_output_text_of(values: MatchedValues) -> str:
    """The output, without the note Muse puts before it when it replaced invalid UTF-8 bytes."""
    output = json_tool_output_text_of(values)
    note = _REPLACED_BYTES_NOTE.match(output)
    return output[note.end() :] if note else output


# Formats that bash and bash_input share, of a command that ended or still runs.
_SHELL_EXITED = Json(
    "exited",
    S.FINISHED,
    _SHELL_FIELDS,
    condition=JsonCondition("terminal_status", "==", "completed"),
    text_from_matched_values=_shell_output_text_of,
)
_SHELL_FAILED = Json(
    "failed",
    S.FINISHED,
    _SHELL_FIELDS,
    present_paths=("exit_code",),
    condition=JsonCondition("terminal_status", "==", "failed"),
    text_from_matched_values=_shell_output_text_of,
)
_SHELL_BACKGROUND = Json(
    "background",
    S.RUNNING,
    {
        "tool_output": "output",
        "handles": ("session_id", "work_id"),
        "is_truncated": "truncated",
    },
    condition=JsonCondition("execution_state", "==", "background_running"),
    text_from_matched_values=_shell_output_text_of,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_BASH = HarnessResultFormatList[JsonObject](
    (
        _SHELL_EXITED,
        _SHELL_FAILED,
        Json(
            "signaled",
            S.KILLED,
            _SHELL_FIELDS,
            absent_paths=("exit_code",),
            condition=JsonCondition(
                "terminal_reason", "startswith", "process exited with signal"
            ),
            text_from_matched_values=_shell_output_text_of,
        ),
        _SHELL_BACKGROUND,
    )
)
_BASH_INPUT = HarnessResultFormatList[JsonObject](
    (
        _SHELL_EXITED,
        _SHELL_FAILED,
        Json(
            "cancelled",
            S.KILLED,
            _SHELL_FIELDS,
            condition=JsonCondition("terminal_status", "==", "cancelled"),
            text_from_matched_values=_shell_output_text_of,
        ),
        _SHELL_BACKGROUND,
    )
)
# Any tool's call that Muse refused.
_REJECTED = Text("rejected", "tool failed: {reason:text}", S.NOT_RUN)
_SHELL_TEXT = HarnessResultFormatList[str]((_REJECTED,))

_WORK_STOP = HarnessResultFormatList[JsonObject](
    (
        Json(
            "accepted",
            value_paths={"handle": "work_id"},
            judgment_rule="treat_accepted_stop_request_as_killed",
            condition=JsonCondition("status", "==", "accepted"),
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Json(
            "already_ended",
            S.FINISHED,
            {"handle": "work_id"},
            condition=JsonCondition("status", "==", "already_terminal"),
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
    )
)
_WEB_SEARCH = HarnessResultFormatList[JsonObject](
    (
        Json(
            "results",
            S.FINISHED,
            {"tool_output": "results"},
            present_paths=("results",),
        ),
    )
)
_MONITOR = HarnessResultFormatList[JsonObject](
    (
        Json(
            "started",
            S.RUNNING,
            {"handle": "work_id"},
            present_paths=("work_id",),
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
    )
)

_READ_HEAD = "Read text file `{path:line}`{detail:rest_of_line}\n"
_ABOVE = "({above:int} line(s) above)"
_READ_FILE = HarnessResultFormatList[str](
    (
        Text("listing", _READ_HEAD + "{tool_output:numbered_pipe}", S.FINISHED),
        Text(
            "listing_after",
            _READ_HEAD + _ABOVE + "\n{tool_output:numbered_pipe}",
            S.FINISHED,
        ),
        Text(
            "listing_before",
            _READ_HEAD + "{tool_output:numbered_pipe}\n(more lines below)",
            S.FINISHED,
        ),
        Text(
            "listing_between",
            _READ_HEAD + _ABOVE + "\n{tool_output:numbered_pipe}\n(more lines below)",
            S.FINISHED,
        ),
        Text("listing_nothing_below", _READ_HEAD + _ABOVE, S.FINISHED),
        Text(
            "header_only",
            "Read text file `{path:line}`{detail:rest_of_line}",
            S.FINISHED,
        ),
        Text(
            "image",
            "Read image file `{path:line}` as model-visible image output.\nmedia_type: {media:rest_of_line}\nsource_bytes: {bytes:int}",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        _REJECTED,
    )
)
_WRITE_FILE = HarnessResultFormatList[str](
    (
        Text(
            "written_note",
            "wrote {bytes:int} bytes to {path:line} note: {note:text}",
            S.FINISHED,
        ),
        Text("written", "wrote {bytes:int} bytes to {path:rest_of_line}", S.FINISHED),
    )
)
_EDIT_FILE = HarnessResultFormatList[str](
    (
        Text("edited", "edited\n{detail:text}", S.FINISHED),
        _REJECTED,
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "bash": HarnessToolResultDeclaration(text_formats=_SHELL_TEXT, json_formats=_BASH),
    "bash_input": HarnessToolResultDeclaration(
        text_formats=_SHELL_TEXT, json_formats=_BASH_INPUT
    ),
    "work_stop": HarnessToolResultDeclaration(json_formats=_WORK_STOP),
    "web_search": HarnessToolResultDeclaration(json_formats=_WEB_SEARCH),
    "monitor": HarnessToolResultDeclaration(json_formats=_MONITOR),
    "read_file": HarnessToolResultDeclaration(text_formats=_READ_FILE),
    "write_file": HarnessToolResultDeclaration(text_formats=_WRITE_FILE),
    "edit_file": HarnessToolResultDeclaration(text_formats=_EDIT_FILE),
}
