"""Devin tool call converter."""

from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandle,
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
_EXIT = "\nExit code: {exit_code:uint}"
_SIGNALED = "\nExit code: -{signal:uint}"

_LIVE_HEAD = (
    "Output from command in shell {handle:id}. The full terminal output is being written live to "
    "{output_path:word}; read or grep it for anything omitted below. Preview:\n"
)
_FILE_VIEW = '<file-view path="{path%s:line}" start_line="{start%s:int}" end_line="{end%s:int}" total_lines="{total%s:int}">\n'
_OMITTED = "… {omitted:int} lines omitted …\n"
_LIVE_HEAD_VIEW = (
    _LIVE_HEAD
    + _FILE_VIEW % ("", "", "", "")
    + "{head:numbered_pipe}\n</file-view>\n"
    + _OMITTED
)
_LIVE_TAIL_VIEW = (
    _FILE_VIEW % ("2", "2", "2", "2") + "{tail:numbered_pipe}\n</file-view>\n"
)


def _preview_text(values: MatchedValues) -> str:
    listings = (str(values.get(name, "")) for name in ("head", "tail"))
    return join_text_parts(strip_line_numbers(listing, "|") for listing in listings)


_EXEC = HarnessResultFormatList[str](
    (
        Text(
            "exited_truncated_after_warning",
            _OUTPUT_HEAD
            + _WARNING
            + "{tool_output:text}"
            + _EXIT
            + "\n\n{note:line}\n"
            + _TRUNCATED,
            S.FINISHED,
            True,
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
            True,
        ),
        Text("exited", _OUTPUT_HEAD + "{tool_output:text}" + _EXIT, S.FINISHED),
        Text("killed", _OUTPUT_HEAD + "{tool_output:text}" + _SIGNALED, S.KILLED),
        Text(
            "exited_live_file",
            _LIVE_HEAD_VIEW + _LIVE_TAIL_VIEW + _EXIT,
            S.FINISHED,
            True,
            text_from_matched_values=_preview_text,
        ),
        Text(
            "exited_live_file_head",
            _LIVE_HEAD_VIEW + _EXIT,
            S.FINISHED,
            True,
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
            True,
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
            "exited_silent_twice",
            "Exited with code {code:int} and no output\n" + _EXIT,
            S.FINISHED,
        ),
        Text(
            "killed_silent_twice",
            "Exited with code {code:int} and no output\n" + _SIGNALED,
            S.KILLED,
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
        Text("exited", "{tool_output:text}" + _EXIT, S.FINISHED),
        Text("exited_bare", "Exit code: {exit_code:uint}", S.FINISHED),
        Text("killed", "{tool_output:text}" + _SIGNALED, S.KILLED),
        Text("killed_bare", "Exit code: -{signal:uint}", S.KILLED),
        Text(
            "exited_silent",
            "Exited with code {exit_code:uint} and no output",
            S.FINISHED,
        ),
        Text(
            "exited_no_more",
            "No more output to read. Shell {handle:id} exited with code {exit_code:uint}.",
            S.FINISHED,
        ),
        Text("running_silent", "No output yet (still running)", S.RUNNING),
        Text(
            "rejected", "Tool 'get_output' validation failed: {reason:text}", S.NOT_RUN
        ),
        Text("running", "{tool_output:text}", S.RUNNING),
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
            _FILE_VIEW % ("", "", "", "") + "{tool_output:numbered_pipe}\n</file-view>",
            S.FINISHED,
        ),
        Text(
            "image",
            "[Image {index:int}]",
            S.FINISHED,
            tool_output_not_in_trajectory=True,
        ),
        Text("rejected", "Tool 'read' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_UPDATED = (
    "The file {path:line} has been updated. Here's the result of running `cat -n` on a snippet of the edited file:\n"
    "{snippet:numbered_pipe}"
)
_CUT_LINES = "\n… ({cut:int} lines truncated)\n"
_UPDATED_TRUNCATED = _UPDATED + "\n" + _TRUNCATED
_UPDATED_TRUNCATED_NOTE = _UPDATED + _CUT_LINES + _TRUNCATED
_UPDATED_TRUNCATED_CUT_LINE = _UPDATED + "\n{cut_line:line}" + _CUT_LINES + _TRUNCATED

_WRITE = HarnessResultFormatList[str](
    (
        Text(
            "created", "File created successfully at: {path:rest_of_line}", S.FINISHED
        ),
        Text("updated_truncated_note", _UPDATED_TRUNCATED_NOTE, S.FINISHED, True),
        Text(
            "updated_truncated_cut_line", _UPDATED_TRUNCATED_CUT_LINE, S.FINISHED, True
        ),
        Text("updated_truncated", _UPDATED_TRUNCATED, S.FINISHED, True),
        Text("updated", _UPDATED, S.FINISHED),
        Text("rejected", "Tool 'write' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_EDIT = HarnessResultFormatList[str](
    (
        Text("updated_truncated_note", _UPDATED_TRUNCATED_NOTE, S.FINISHED, True),
        Text(
            "updated_truncated_cut_line", _UPDATED_TRUNCATED_CUT_LINE, S.FINISHED, True
        ),
        Text("updated_truncated", _UPDATED_TRUNCATED, S.FINISHED, True),
        Text("updated", _UPDATED, S.FINISHED),
        Text("rejected", "Tool 'edit' validation failed: {reason:text}", S.NOT_RUN),
    )
)

_WEBFETCH = HarnessResultFormatList[str](
    (
        Text(
            "page_truncated",
            "# Web Content from {url:rest_of_line}\n{tool_output:text}\n" + _TRUNCATED,
            S.FINISHED,
            True,
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
            True,
        ),
        Text(
            "results_crlf_truncated",
            _SEARCH_HEAD + "\r\n{tool_output:text}\n" + _TRUNCATED,
            S.FINISHED,
            True,
        ),
        Text("results", _SEARCH_HEAD + "\n{tool_output:text}", S.FINISHED),
        Text("results_crlf", _SEARCH_HEAD + "\r\n{tool_output:text}", S.FINISHED),
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

_SHELL_TOOLS = frozenset({"get_output", "kill_shell", "write_to_process"})
_RAN = frozenset({S.FINISHED, S.RUNNING, S.KILLED, S.TIMED_OUT})


class DevinConverter(HarnessToolCallConverter):
    stop_tools: ClassVar[frozenset[str]] = frozenset({"kill_shell"})
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
        # A shell poll's result rarely names the shell; the argument does.
        shell_id = raw.args.get("shell_id")
        if (
            raw.tool.name in _SHELL_TOOLS
            and not output.handles
            and shell_id
            and output.execution_status in _RAN
        ):
            handles = (ExecutionHandle(ExecutionHandleKind.COMMAND, str(shell_id)),)
            output = replace(output, handles=handles)
        return output
