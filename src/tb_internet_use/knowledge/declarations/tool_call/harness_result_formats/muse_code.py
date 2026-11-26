"""Declare the result formats of Muse Code tools."""

import re
from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
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

_SHELL_VALUE_PATHS = {
    "tool_output": "output",
    "exit_code": "exit_code",
    "is_truncated": "truncated",
}
# Muse Code starts the output with this note when it replaced bytes that are not UTF-8.
_REPLACED_BYTES_NOTE = re.compile(
    r"\[unified exec output: \d+ invalid UTF-8 bytes? replaced with U\+FFFD\]\n?"
)


def _shell_output_text_of(matched_values: MatchedValues) -> str:
    """Give the output without the note Muse Code puts before it when it replaced invalid UTF-8 bytes."""
    output = json_tool_output_text_of(matched_values)
    note = _REPLACED_BYTES_NOTE.match(output)
    return output[note.end() :] if note else output


# Formats that bash and bash_input share, of a command that ended or still runs.
_SHELL_EXITED = Json(
    "exited",
    S.FINISHED,
    _SHELL_VALUE_PATHS,
    condition=JsonCondition("terminal_status", "==", "completed"),
    text_from_matched_values=_shell_output_text_of,
)
_SHELL_FAILED = Json(
    "failed",
    S.FINISHED,
    _SHELL_VALUE_PATHS,
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
            _SHELL_VALUE_PATHS,
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
        # Muse Code marks a poll that comes after the chunk that reported the end of the command, which the trajectory does not hold, e.g. a result of the chunk `exec-37-3` without `exec-37-2`.
        # Its `output` is "" though the command printed, so it has no tool output text.
        Json(
            "end_already_reported",
            S.FINISHED,
            {"exit_code": "exit_code"},
            present_paths=("exit_code",),
            condition=JsonCondition("terminal_already_reported", "==", True),
            no_tool_output_text=True,
        ),
        _SHELL_EXITED,
        _SHELL_FAILED,
        Json(
            "cancelled",
            S.KILLED,
            _SHELL_VALUE_PATHS,
            condition=JsonCondition("terminal_status", "==", "cancelled"),
            text_from_matched_values=_shell_output_text_of,
        ),
        _SHELL_BACKGROUND,
    )
)
# Any tool's call that Muse Code refused.
_REJECTED = Text(
    "rejected",
    "tool failed: {reason:text}",
    judgment_rule="treat_tool_failure_message_as_not_run",
)
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
            value_paths={"handle": "work_id"},
            judgment_rule="treat_stop_request_for_ended_work_as_finished",
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
# Muse Code writes a failed fetch as a tool failure that says how far the request got.
_WEB_FETCH_FAILED = "tool failed: web_fetch failed: "
# Muse Code ends a fetched page with what the server answered, and a page it cut with the file that holds the whole page.
_WEB_FETCH_SOURCE = (
    "\n\nSource: {url:line}\nStatus: {http_status:int} {reason:line}\n"
    "Content-Type: {content_type:line}\nFetched: {fetched_bytes:int} bytes\n"
)
_WEB_FETCH_PAGE_TAIL = (
    "Processed: {processed_chars:int} chars\nCache: {cache:line}\nTruncated: "
)
_WEB_FETCH_SAVED_PAGE = (
    "\n<system-reminder>\nFull output saved to: {output_path:line}\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n</system-reminder>"
)
_WEB_FETCH = HarnessResultFormatList[str](
    (
        Text(
            "http_error",
            _WEB_FETCH_FAILED + "HTTP {http_status:int} {reason:rest_of_line}",
            S.FINISHED,
        ),
        Text(
            "request_failed",
            _WEB_FETCH_FAILED + "request failed: {detail:text}",
            S.FINISHED,
        ),
        Text(
            "binary_saved",
            "Binary content ({detail:line_without_brackets}) saved to: {output_path:line}"
            + _WEB_FETCH_SOURCE
            + "Prompt not applied: {note:rest_of_line}",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text(
            "page_truncated",
            "{tool_output:text}\n\n[Answer truncated]"
            + _WEB_FETCH_SOURCE
            + _WEB_FETCH_PAGE_TAIL
            + "true"
            + _WEB_FETCH_SAVED_PAGE,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "page",
            "{tool_output:text}" + _WEB_FETCH_SOURCE + _WEB_FETCH_PAGE_TAIL + "false",
            S.FINISHED,
            is_truncated=False,
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
# What Muse Code writes at the end of a listed line that it cut, e.g. a line of more than 8192 bytes.
_CUT_LINE_MARKER = "[line truncated: original_bytes={original_bytes:int}, visible_bytes={visible_bytes:int}]"
_READ_FILE = HarnessResultFormatList[str](
    (
        Text(
            "listing",
            _READ_HEAD + "{tool_output:numbered_pipe}",
            S.FINISHED,
            truncation_marker=_CUT_LINE_MARKER,
        ),
        Text(
            "listing_after",
            _READ_HEAD + _ABOVE + "\n{tool_output:numbered_pipe}",
            S.FINISHED,
            truncation_marker=_CUT_LINE_MARKER,
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
            "wrote {bytes:int} bytes to {path:line}; note: {note:text}",
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
    "web_fetch": HarnessToolResultDeclaration(text_formats=_WEB_FETCH),
    "monitor": HarnessToolResultDeclaration(json_formats=_MONITOR),
    "read_file": HarnessToolResultDeclaration(text_formats=_READ_FILE),
    "write_file": HarnessToolResultDeclaration(text_formats=_WRITE_FILE),
    "edit_file": HarnessToolResultDeclaration(text_formats=_EDIT_FILE),
}
