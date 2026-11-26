"""Declare the result formats of Devin tools and the notices Devin adds to their results."""

from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    MatchedValues,
    strip_line_numbers,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    join_text_parts,
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
# Devin writes -1 here, never another negative code, for a command it stopped, e.g. one that killed its own shell.
# It is no real exit code or signal number, so the formats that end in it name the judgment rule `treat_negative_exit_code_as_killed`, which reads it as killed.
_SIGNALED = "\nExit code: {exit_code:negative_int}"
# Devin cuts a long line and ends it with this.
_CUT_LINE_MARKER = "… ({count:int} chars truncated)"

_LIVE_HEAD = (
    "Output from command in shell {handle:id}. The full terminal output is being written live to "
    "{output_path:word}; read or grep it for anything omitted below. Preview:\n"
)


_OMITTED = "… {omitted:int} lines omitted …\n"


def _file_view_template_for(suffix: str = "") -> str:
    """Build the template of a file view's opening tag. A second view in one template takes a suffix, since placeholder names must differ."""
    return (
        f'<file-view path="{{path{suffix}:line}}" start_line="{{start{suffix}:int}}" '
        f'end_line="{{end{suffix}:int}}" total_lines="{{total{suffix}:int}}">\n'
    )


_LIVE_HEAD_VIEW = (
    _LIVE_HEAD
    + _file_view_template_for()
    + "{head:numbered_pipe}\n</file-view>\n"
    + _OMITTED
)
_LIVE_TAIL_VIEW = _file_view_template_for("2") + "{tail:numbered_pipe}\n</file-view>\n"


def _preview_text_of(matched_values: MatchedValues) -> str:
    listings = (str(matched_values.get(name, "")) for name in ("head", "tail"))
    return join_text_parts(strip_line_numbers(listing, "|") for listing in listings)


_EXEC = HarnessResultFormatList[str](
    (
        # Before the exited formats, whose exit code would take the "-" too.
        Text(
            "killed",
            _OUTPUT_HEAD + "{tool_output:text}" + _SIGNALED,
            judgment_rule="treat_negative_exit_code_as_killed",
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
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
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited_after_warning",
            _OUTPUT_HEAD + _WARNING + "{tool_output:text}" + _EXIT,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
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
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited",
            _OUTPUT_HEAD + "{tool_output:text}" + _EXIT,
            S.FINISHED,
            truncation_marker=_CUT_LINE_MARKER,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited_live_file",
            _LIVE_HEAD_VIEW + _LIVE_TAIL_VIEW + _EXIT,
            S.FINISHED,
            is_truncated=True,
            text_from_matched_values=_preview_text_of,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited_live_file_head",
            _LIVE_HEAD_VIEW + _EXIT,
            S.FINISHED,
            is_truncated=True,
            text_from_matched_values=_preview_text_of,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_silent",
            "No output produced after {seconds:line_without_brackets} seconds. "
            + _BACKGROUND,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_after_output_truncated",
            _STOPPED + "\n" + _TRUNCATED,
            S.RUNNING,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_after_output",
            _STOPPED,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_requested",
            "Command running in background with ID: {handle:id}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "rejected",
            "Tool 'exec' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        Text(
            "rejected_env",
            "`env` can only be set when starting a new shell; {reason:text}",
            S.NOT_RUN,
        ),
        # The refused call starts no command, so the shell it names is no handle of the call.
        Text(
            "rejected_busy",
            "Shell {shell:id} still has a running command. {reason:text}",
            S.NOT_RUN,
        ),
    ),
    notices=_NOTICES,
)

_DIFF_HEAD = (
    "[Changes since your last read, shown as a unified diff: '+' lines are new, '-' lines were "
    "replaced/removed in place, ' ' lines are unchanged context; '@@' line numbers index into the full output.]\n"
)


def _tool_output_text_from_diff(matched_values: MatchedValues) -> str:
    kept: list[str] = []
    for line in str(matched_values["diff"]).split("\n"):
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
            judgment_rule="treat_negative_exit_code_as_killed",
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
            text_from_matched_values=_tool_output_text_from_diff,
        ),
        Text(
            "running_incremental",
            _DIFF_HEAD + "{diff:text}",
            judgment_rule="treat_get_output_without_exit_code_as_running",
            text_from_matched_values=_tool_output_text_from_diff,
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
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text("running_silent", "No output yet (still running)", S.RUNNING),
        Text(
            "rejected",
            "Tool 'get_output' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        # Devin writes this alone when it could not watch the shell, so the poll shows no output.
        Text(
            "failed_monitoring",
            "Failed to configure output monitoring. Please try again.",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        Text(
            "running",
            "{tool_output:text}",
            judgment_rule="treat_get_output_without_exit_code_as_running",
            truncation_marker=_CUT_LINE_MARKER,
        ),
    ),
    notices=_NOTICES,
)

_KILL_SHELL = HarnessResultFormatList[str](
    (
        Text(
            "killed",
            "Shell {handle:id} terminated successfully",
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
        Text(
            "rejected",
            "Tool 'kill_shell' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    )
)

_WRITE_TO_PROCESS = HarnessResultFormatList[str](
    (
        Text(
            "written",
            "Written {bytes:int} bytes to shell {handle:id}",
            judgment_rule="treat_written_input_as_running_target",
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
    )
)

_READ = HarnessResultFormatList[str](
    (
        Text(
            "listing",
            _file_view_template_for() + "{tool_output:numbered_pipe}\n</file-view>",
            S.FINISHED,
        ),
        Text(
            "image",
            "[Image {index:int}]",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text(
            "rejected",
            "Tool 'read' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    )
)

_UPDATED_WITH_SNIPPET = (
    "The file {path:line} has been updated. Here's the result of running `cat -n` on a snippet of the edited file:\n"
    "{snippet:numbered_pipe}"
)
_CUT_LINES = "\n… ({cut:int} lines truncated)\n"
# Formats that write and edit share, of a file they changed.
_UPDATED_TRUNCATED_NOTE = Text(
    "updated_truncated_note",
    _UPDATED_WITH_SNIPPET + _CUT_LINES + _TRUNCATED,
    S.FINISHED,
    is_truncated=True,
)
_UPDATED = Text("updated", _UPDATED_WITH_SNIPPET, S.FINISHED)

_WRITE = HarnessResultFormatList[str](
    (
        Text(
            "created", "File created successfully at: {path:rest_of_line}", S.FINISHED
        ),
        _UPDATED_TRUNCATED_NOTE,
        Text(
            "updated_truncated_cut_line",
            _UPDATED_WITH_SNIPPET + "\n{cut_line:line}" + _CUT_LINES + _TRUNCATED,
            S.FINISHED,
            is_truncated=True,
        ),
        _UPDATED,
        Text(
            "rejected",
            "Tool 'write' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    )
)

_EDIT = HarnessResultFormatList[str](
    (
        _UPDATED_TRUNCATED_NOTE,
        _UPDATED,
        Text(
            "rejected",
            "Tool 'edit' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
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
        Text(
            "http_error",
            "HTTP request failed with status: {http_status:int}",
            S.FINISHED,
        ),
        Text(
            "rejected",
            "Tool 'webfetch' validation failed: {reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
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


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "exec": HarnessToolResultDeclaration(text_formats=_EXEC),
    "get_output": HarnessToolResultDeclaration(text_formats=_GET_OUTPUT),
    "kill_shell": HarnessToolResultDeclaration(text_formats=_KILL_SHELL),
    "write_to_process": HarnessToolResultDeclaration(text_formats=_WRITE_TO_PROCESS),
    "read": HarnessToolResultDeclaration(text_formats=_READ),
    "write": HarnessToolResultDeclaration(text_formats=_WRITE),
    "edit": HarnessToolResultDeclaration(text_formats=_EDIT),
    "webfetch": HarnessToolResultDeclaration(text_formats=_WEBFETCH),
    "web_search": HarnessToolResultDeclaration(text_formats=_WEB_SEARCH),
    "browser_preview": HarnessToolResultDeclaration(text_formats=_BROWSER_PREVIEW),
}
