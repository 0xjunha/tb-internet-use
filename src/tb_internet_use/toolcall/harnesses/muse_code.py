"""Muse Code tool call converter."""

import re
from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    RawToolCall,
    ToolCallOutput,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
    JsonObject,
    MatchedValues,
    json_tool_output_text,
    template_regex,
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
# Muse ends a truncated shell output with this reminder, which names the full output's file.
_SAVED_OUTPUT_REMINDER = template_regex(
    "{tool_output:text}\n<system-reminder>\nFull output saved to: {output_path:line}\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
    "</system-reminder>"
)


def _shell_output_text(values: MatchedValues) -> str:
    """The output, without the note Muse puts before it when it replaced invalid UTF-8 bytes."""
    output = json_tool_output_text(values)
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
# Any tool's call that Muse refused.
_REJECTED = Text("rejected", "tool failed: {reason:text}", S.NOT_RUN)
_SHELL_TEXT = HarnessResultFormatList[str]((_REJECTED,))

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
        _REJECTED,
    )
)
_EDIT_FILE = HarnessResultFormatList[str](
    (
        Text("edited", "edited\n{detail:text}", S.FINISHED),
        _REJECTED,
    )
)


_SHELL_TOOLS = ("bash", "bash_input")


class MuseCodeConverter(HarnessToolCallConverter):
    stop_tools: ClassVar = frozenset({"work_stop"})
    # a background bash session
    argument_handle_kinds: ClassVar = {"bash_input": ExecutionHandleKind.COMMAND}
    json_formats: ClassVar = {
        **dict.fromkeys(_SHELL_TOOLS, _SHELL),
        "work_stop": _WORK_STOP,
        "web_search": _WEB_SEARCH,
        "monitor": _MONITOR,
    }
    text_formats: ClassVar = {
        **dict.fromkeys(_SHELL_TOOLS, _SHELL_TEXT),
        "read_file": _READ_FILE,
        "write_file": _WRITE_FILE,
        "edit_file": _EDIT_FILE,
    }

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        output = super().parse_output(raw, result)
        text = output.tool_output_text
        if raw.tool.name not in _SHELL_TOOLS or not text:
            return output
        found = _SAVED_OUTPUT_REMINDER.fullmatch(text)
        if found is None:
            return output
        return replace(
            output,
            tool_output_text=found["tool_output"],
            output_path=found["output_path"],
        )
