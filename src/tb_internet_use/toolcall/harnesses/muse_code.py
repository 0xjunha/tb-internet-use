"""Muse Code tool call converter."""

import json
import re
from typing import ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import ExecutionStatus
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
    JsonObject,
    MatchedValues,
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
    r"\[unified exec output: \d+ invalid UTF-8 bytes replaced with U\+FFFD\]\n?"
)


def _shell_output_text(values: MatchedValues) -> str:
    """The output, without the note Muse puts before it when it replaced invalid UTF-8 bytes."""
    output = values.get("tool_output")
    if output is None:
        return ""
    if not isinstance(output, str):
        return json.dumps(output, ensure_ascii=False)
    note = _REPLACED_BYTES_NOTE.match(output)
    return output[note.end() :] if note else output


_SHELL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "exited",
            S.FINISHED,
            _SHELL_FIELDS,
            condition=JsonCondition("terminal_status", "==", "completed"),
            text_from_matched_values=_shell_output_text,
        ),
        Json(
            "failed",
            S.FINISHED,
            _SHELL_FIELDS,
            present_paths=("exit_code",),
            condition=JsonCondition("terminal_status", "==", "failed"),
            text_from_matched_values=_shell_output_text,
        ),
        Json(
            "signaled",
            S.KILLED,
            _SHELL_FIELDS,
            absent_paths=("exit_code",),
            condition=JsonCondition(
                "terminal_reason", "startswith", "process exited with signal"
            ),
            text_from_matched_values=_shell_output_text,
        ),
        Json(
            "cancelled",
            S.KILLED,
            _SHELL_FIELDS,
            condition=JsonCondition("terminal_status", "==", "cancelled"),
            text_from_matched_values=_shell_output_text,
        ),
        Json(
            "background",
            S.RUNNING,
            {
                "tool_output": "output",
                "handles": ("session_id", "work_id"),
                "is_truncated": "truncated",
            },
            condition=JsonCondition("execution_state", "==", "background_running"),
            text_from_matched_values=_shell_output_text,
        ),
    )
)
_SHELL_TEXT = HarnessResultFormatList[str](
    (Text("rejected", "tool failed: {reason:text}", S.NOT_RUN),)
)

_WORK_STOP = HarnessResultFormatList[JsonObject](
    (
        Json(
            "accepted",
            S.KILLED,
            {"handle": "work_id"},
            condition=JsonCondition("status", "==", "accepted"),
        ),
        Json(
            "already_ended",
            S.FINISHED,
            {"handle": "work_id"},
            condition=JsonCondition("status", "==", "already_terminal"),
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
    (Json("started", S.RUNNING, {"handle": "work_id"}, present_paths=("work_id",)),)
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
            tool_output_not_in_trajectory=True,
        ),
        Text("rejected", "tool failed: {reason:text}", S.NOT_RUN),
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
        Text("rejected", "tool failed: {reason:text}", S.NOT_RUN),
    )
)
_EDIT_FILE = HarnessResultFormatList[str](
    (
        Text("edited", "edited\n{detail:text}", S.FINISHED),
        Text("edited_bare", "edited", S.FINISHED),
        Text("rejected", "tool failed: {reason:text}", S.NOT_RUN),
    )
)


class MuseCodeConverter(HarnessToolCallConverter):
    stop_tools: ClassVar[frozenset[str]] = frozenset({"work_stop"})
    json_formats: ClassVar = {
        "bash": _SHELL,
        "bash_input": _SHELL,
        "work_stop": _WORK_STOP,
        "web_search": _WEB_SEARCH,
        "monitor": _MONITOR,
    }
    text_formats: ClassVar = {
        "bash": _SHELL_TEXT,
        "bash_input": _SHELL_TEXT,
        "read_file": _READ_FILE,
        "write_file": _WRITE_FILE,
        "edit_file": _EDIT_FILE,
    }
