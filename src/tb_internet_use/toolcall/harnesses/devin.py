"""Devin tool call converter."""

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
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    MatchedValues,
    join_text_parts,
    strip_line_numbers,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

_WARNING = "Warning: requested timeout {asked:line_without_brackets} exceeds maximum of {max:line_without_brackets}; clamping to {clamped:line_without_brackets}.\n"
_NOTICES = (
    HarnessNotice(
        "timeout_clamped",
        _WARNING,
        at="start",
    ),
    HarnessNotice(
        "cwd_changed",
        "Shell {shell:id} changed directory to {path:rest_of_line}\n",
        at="start",
    ),
)

_BACKGROUND = "Command running in background with ID: {handle:id}. Run get_output with timeout if you need to wait."
_TRUNCATED = "<truncation_notice>\nFull output written to: {output_path:word}\n</truncation_notice>"
_STOPPED = (
    "{tool_output:text}\n\n===\nStopped waiting for output after {seconds:line_without_brackets} seconds. "
    + _BACKGROUND
)
_OUTPUT_HEAD = "Output from command in shell {handle:id}:\n"
_EXIT = "\nExit code: {exit_code:int}"
# Devin writes -1 here, never another negative code, for a command it stopped, e.g.
# one that killed its own shell. It is no real exit code or signal number, so
# `parse_output` reads any negative code as killed, whatever the format.
_SIGNALED = "\nExit code: -{sentinel:uint}"
# Devin cuts a long line and ends it with this.
_CUT_LINE_MARKER = "… ({count:int} chars truncated)"

_LIVE_HEAD = (
    "Output from command in shell {handle:id}. The full terminal output is being written live to "
    "{output_path:word}; read or grep it for anything omitted below. Preview:\n"
)


def _file_view(suffix: str = "") -> str:
    """A file view's opening tag. A second view in one template takes a suffix, since placeholder names must differ."""
    return (
        f'<file-view path="{{path{suffix}:line}}" start_line="{{start{suffix}:int}}" '
        f'end_line="{{end{suffix}:int}}" total_lines="{{total{suffix}:int}}">\n'
    )


_OMITTED = "… {omitted:int} lines omitted …\n"
_LIVE_HEAD_VIEW = (
    _LIVE_HEAD + _file_view() + "{head:numbered_pipe}\n</file-view>\n" + _OMITTED
)
_LIVE_TAIL_VIEW = _file_view("2") + "{tail:numbered_pipe}\n</file-view>\n"


def _preview_text(values: MatchedValues) -> str:
    listings = (str(values.get(name, "")) for name in ("head", "tail"))
    return join_text_parts(strip_line_numbers(listing, "|") for listing in listings)


_EXEC = HarnessResultFormatList[str](
    (
        # Before the exited formats, whose exit code would take the "-" too.
        Text("killed", _OUTPUT_HEAD + "{tool_output:text}" + _SIGNALED, S.KILLED),
        Text(
            "exited_truncated_after_warning",
            _OUTPUT_HEAD
            + _WARNING
            + "{tool_output:text}"
            + _EXIT
            + "\n\n{note:line}\n"
            + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited_after_warning",
            _OUTPUT_HEAD + _WARNING + "{tool_output:text}" + _EXIT,
            S.FINISHED,
        ),
        Text(
            "exited_truncated",
            _OUTPUT_HEAD
            + "{tool_output:text}"
            + _EXIT
            + "\n\n{note:line}\n"
            + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited",
            _OUTPUT_HEAD + "{tool_output:text}" + _EXIT,
            S.FINISHED,
            truncation_marker=_CUT_LINE_MARKER,
        ),
        Text(
            "exited_live_file",
            _LIVE_HEAD_VIEW + _LIVE_TAIL_VIEW + _EXIT,
            S.FINISHED,
            is_truncated=True,
            text_from_matched_values=_preview_text,
        ),
        Text(
            "exited_live_file_head",
            _LIVE_HEAD_VIEW + _EXIT,
            S.FINISHED,
            is_truncated=True,
            text_from_matched_values=_preview_text,
        ),
        Text(
            "background_silent",
            "No output produced after {seconds:line_without_brackets} seconds. "
            + _BACKGROUND,
            S.RUNNING,
        ),
        Text(
            "background_after_output_truncated",
            _STOPPED + "\n" + _TRUNCATED,
            S.RUNNING,
            is_truncated=True,
        ),
        Text("background_after_output", _STOPPED, S.RUNNING),
        Text(
            "background_requested",
            "Command running in background with ID: {handle:id}",
            S.RUNNING,
        ),
        Text("rejected", "Tool 'exec' validation failed: {reason:text}", S.NOT_RUN),
        Text(
            "rejected_env",
            "`env` can only be set when starting a new shell; {reason:text}",
            S.NOT_RUN,
        ),
        Text(
            "rejected_busy",
            "Shell {handle:id} still has a running command. {reason:text}",
            S.NOT_RUN,
        ),
    ),
    notices=_NOTICES,
)

_DIFF_HEAD = (
    "[Changes since your last read, shown as a unified diff: '+' lines are new, '-' lines were "
    "replaced/removed in place, ' ' lines are unchanged context; '@@' line numbers index into the full output.]\n"
)


def _diff_output(values: MatchedValues) -> str:
    kept: list[str] = []
    for line in str(values["diff"]).split("\n"):
        if line[:1] in ("+", " "):
            kept.append(line[1:])
        elif not line.startswith(("@@", "-")):
            kept.append(line)  # an unprefixed line, such as the trailing empty one
    return "\n".join(kept)


_GET_OUTPUT = HarnessResultFormatList[str](
    (
        Text(
            "killed_silent_twice",
            "Exited with code {code:int} and no output\n" + _SIGNALED,
            S.KILLED,
        ),
        Text(
            "exited_silent_twice",
            "Exited with code {code:int} and no output\n" + _EXIT,
            S.FINISHED,
        ),
        Text(
            "exited_incremental",
            _DIFF_HEAD + "{diff:text}" + _EXIT,
            S.FINISHED,
            text_from_matched_values=_diff_output,
        ),
        Text(
            "running_incremental",
            _DIFF_HEAD + "{diff:text}",
            S.RUNNING,
            text_from_matched_values=_diff_output,
        ),
        Text(
            "exited",
            "{tool_output:text}" + _EXIT,
            S.FINISHED,
            truncation_marker=_CUT_LINE_MARKER,
        ),
        Text(
            "exited_no_more",
            "No more output to read. Shell {handle:id} exited with code {exit_code:int}.",
            S.FINISHED,
        ),
        Text("running_silent", "No output yet (still running)", S.RUNNING),
        Text(
            "rejected", "Tool 'get_output' validation failed: {reason:text}", S.NOT_RUN
        ),
        Text(
            "running",
            "{tool_output:text}",
            S.RUNNING,
            truncation_marker=_CUT_LINE_MARKER,
        ),
    ),
    notices=_NOTICES,
)

_KILL_SHELL = HarnessResultFormatList[str](
    (
        Text("killed", "Shell {handle:id} terminated successfully", S.KILLED),
        Text(
            "rejected", "Tool 'kill_shell' validation failed: {reason:text}", S.NOT_RUN
        ),
    )
)

_WRITE_TO_PROCESS = HarnessResultFormatList[str](
    (Text("written", "Written {bytes:int} bytes to shell {handle:id}", S.RUNNING),)
)

_READ = HarnessResultFormatList[str](
    (
        Text(
            "listing",
            _file_view() + "{tool_output:numbered_pipe}\n</file-view>",
            S.FINISHED,
        ),
        Text(
            "image",
            "[Image {index:int}]",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text("rejected", "Tool 'read' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_UPDATED = (
    "The file {path:line} has been updated. Here's the result of running `cat -n` on a snippet of the edited file:\n"
    "{snippet:numbered_pipe}"
)
_CUT_LINES = "\n… ({cut:int} lines truncated)\n"
_UPDATED_TRUNCATED_NOTE = _UPDATED + _CUT_LINES + _TRUNCATED
_UPDATED_TRUNCATED_CUT_LINE = _UPDATED + "\n{cut_line:line}" + _CUT_LINES + _TRUNCATED
# What write and edit return after they changed a file.
_UPDATED_FORMATS = (
    Text(
        "updated_truncated_note", _UPDATED_TRUNCATED_NOTE, S.FINISHED, is_truncated=True
    ),
    Text(
        "updated_truncated_cut_line",
        _UPDATED_TRUNCATED_CUT_LINE,
        S.FINISHED,
        is_truncated=True,
    ),
    Text("updated", _UPDATED, S.FINISHED),
)

_WRITE = HarnessResultFormatList[str](
    (
        Text(
            "created", "File created successfully at: {path:rest_of_line}", S.FINISHED
        ),
        *_UPDATED_FORMATS,
        Text("rejected", "Tool 'write' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_EDIT = HarnessResultFormatList[str](
    (
        *_UPDATED_FORMATS,
        Text("rejected", "Tool 'edit' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_WEBFETCH = HarnessResultFormatList[str](
    (
        Text(
            "page_truncated",
            "# Web Content from {url:rest_of_line}\n{tool_output:text}\n" + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "page",
            "# Web Content from {url:rest_of_line}\n{tool_output:text}",
            S.FINISHED,
        ),
        Text("http_error", "HTTP request failed with status: {code:int}", S.FINISHED),
        Text("rejected", "Tool 'webfetch' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_SEARCH_HEAD = '# Web Search Results for "{query:line}"'
_WEB_SEARCH = HarnessResultFormatList[str](
    (
        Text(
            "results_truncated",
            _SEARCH_HEAD + "\n{tool_output:text}\n" + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "results_crlf_truncated",
            _SEARCH_HEAD + "\r\n{tool_output:text}\n" + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text("results", _SEARCH_HEAD + "\n{tool_output:text}", S.FINISHED),
    )
)

_BROWSER_PREVIEW = HarnessResultFormatList[str](
    (
        Text(
            "preview_running",
            "Browser preview running with ID: {handle:id}\n{detail:text}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.UNKNOWN,
        ),
    )
)


class DevinConverter(HarnessToolCallConverter):
    stop_tools: ClassVar = frozenset({"kill_shell"})
    # A shell poll's result rarely names the shell, but its argument does.
    argument_handle_kinds: ClassVar = dict.fromkeys(
        ("get_output", "kill_shell", "write_to_process"), ExecutionHandleKind.COMMAND
    )
    text_formats: ClassVar = {
        "exec": _EXEC,
        "get_output": _GET_OUTPUT,
        "kill_shell": _KILL_SHELL,
        "write_to_process": _WRITE_TO_PROCESS,
        "read": _READ,
        "write": _WRITE,
        "edit": _EDIT,
        "webfetch": _WEBFETCH,
        "web_search": _WEB_SEARCH,
        "browser_preview": _BROWSER_PREVIEW,
    }

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        output = super().parse_output(raw, result)
        if output.exit_code is not None and output.exit_code < 0:
            return replace(output, execution_status=S.KILLED, exit_code=None)
        return output
