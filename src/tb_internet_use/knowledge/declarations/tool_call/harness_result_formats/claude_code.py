"""Declare the result formats of Claude Code tools and the notices Claude Code adds to their results."""

from collections.abc import Mapping

from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    JsonCondition,
    JsonObject,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Text = HarnessTextResultFormat
Json = HarnessJsonResultFormat

_FRESH = " (file state is current in your context — no need to Read it back)"

_NOTICES = (
    HarnessNotice("cwd_reset", "\nShell cwd was reset to {cwd:rest_of_line}", at="end"),
    HarnessNotice(
        "cwd_reset_bare", "Shell cwd was reset to {cwd:rest_of_line}", at="end"
    ),
    HarnessNotice(
        "modified_files", "\n[This command modified {what:rest_of_line}", at="end"
    ),
    HarnessNotice(
        "modified_files_bare", "[This command modified {what:rest_of_line}", at="end"
    ),
    HarnessNotice("session_cwd", "\n\nSession cwd {what:rest_of_line}", at="end"),
    HarnessNotice("session_cwd_bare", "\nSession cwd {what:rest_of_line}", at="end"),
)

# Formats several tools share, e.g. a rejected call, a safety-classifier stop, a
# refused symlink and a result saved to a file.
_TOOL_USE_ERROR = Text(
    "tool_use_error", "<tool_use_error>{reason:text}</tool_use_error>", S.NOT_RUN
)
# The interrupted call was already running and "may have partially or fully completed".
_INTERRUPTED_CLASSIFIER = Text(
    "interrupted_classifier",
    "Interrupted: the response that made this tool call was stopped by a safety classifier{reason:text}",
    S.UNKNOWN,
)
_NOT_RUN_CLASSIFIER = Text(
    "not_run_classifier",
    "Not run: the response that made this tool call was stopped by a safety classifier{reason:text}",
    S.NOT_RUN,
)
_REFUSED_SYMLINK = Text(
    "refused_symlink",
    "Refusing to write through symlink: {path:word} {hint:text}",
    S.NOT_RUN,
)

_PERSISTED_HEAD = (
    "<persisted-output>\nOutput too large ({size:line_without_brackets}). Full output saved to: {output_path:word}\n\n"
    "Preview (first {preview:line_without_brackets}):\n"
)
_PERSISTED_PARTIAL_HEAD = (
    "<persisted-output>\nOutput exceeded the {limit:line_without_brackets} persist limit; only the first {kept:line_without_brackets} were saved to: "
    "{output_path:word}\n\nPreview (first {preview:line_without_brackets}):\n"
)
_PERSISTED = Text(
    "persisted_output",
    _PERSISTED_HEAD + "{tool_output:text}\n</persisted-output>",
    S.FINISHED,
    is_truncated=True,
)
_PERSISTED_PARTIAL = Text(
    "persisted_output_partial",
    _PERSISTED_PARTIAL_HEAD + "{tool_output:text}\n</persisted-output>",
    S.FINISHED,
    is_truncated=True,
)

_NOTIFY = " You will be notified when it completes. To check interim output, use Read on that file path."
_NOTIFY_V2 = " You will be notified when it completes. If it is still running after {rest:rest_of_line}"
_NOTIFY_V3 = (
    " If it exits while you are still working you will be notified, {rest:rest_of_line}"
)
_BACKGROUND = "Command running in background with ID: {handle:id}. Output is being written to: {output_path:word}."
_BACKGROUND_TIMEOUT = (
    "Command did not complete within its {seconds:int}s timeout and was moved to the background "
    "(ID: {handle:id}). Output is being written to: {output_path:word}."
)

_BASH_OK = HarnessResultFormatList[str](
    (
        Text("no_output", "(Bash completed with no output)", S.FINISHED),
        Text(
            "background",
            _BACKGROUND + _NOTIFY,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_v3",
            _BACKGROUND + _NOTIFY_V3,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_after_output",
            "{tool_output:text}\n" + _BACKGROUND + _NOTIFY,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_timeout",
            _BACKGROUND_TIMEOUT + _NOTIFY,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_timeout_v2",
            _BACKGROUND_TIMEOUT + _NOTIFY_V2,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _PERSISTED,
        _PERSISTED_PARTIAL,
        # Not judged an error, so no header. The exit code is 0, or 1 for grep, find, diff and the like.
        Text("bare_output", "{tool_output:text}", S.FINISHED),
    ),
    notices=_NOTICES,
)
# Claude Code cuts the middle of a long error output and leaves this in its place.
_CUT_MARKER = "... [{count:int} characters truncated] ..."
_BASH_ERROR = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        # The code is always 143 from the kill, so it fills no exit_code.
        Text(
            "timed_out",
            "Exit code {code:int}\nCommand timed out after {after:rest_of_line}\n{tool_output:text}",
            S.TIMED_OUT,
            truncation_marker=_CUT_MARKER,
        ),
        Text(
            "timed_out_silent",
            "Exit code {code:int}\nCommand timed out after {after:rest_of_line}",
            S.TIMED_OUT,
        ),
        Text(
            "exited",
            "Exit code {exit_code:int}\n{tool_output:text}",
            S.FINISHED,
            truncation_marker=_CUT_MARKER,
        ),
        Text("exited_silent", "Exit code {exit_code:int}", S.FINISHED),
        Text("refused_permission", "Permission to use Bash {reason:text}", S.NOT_RUN),
        Text(
            "refused_dangerous",
            "Dangerous {operation:line_without_brackets} operation detected{reason:text}",
            S.NOT_RUN,
        ),
        Text(
            "refused_multiple",
            "This Bash command contains multiple operations{reason:text}",
            S.NOT_RUN,
        ),
        _INTERRUPTED_CLASSIFIER,
        Text(
            "refused_user",
            "The user doesn't want to proceed with this tool use{reason:text}",
            S.NOT_RUN,
        ),
    ),
    notices=_NOTICES,
)

_READ = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        Text(
            "warning",
            "<system-reminder>Warning: {warning:text}</system-reminder>",
            S.FINISHED,
        ),
        # Claude Code skipped the read, since the file is unchanged since the last one.
        Text(
            "unchanged",
            "Wasted call — file unchanged since your last Read. Refer to that earlier tool_result instead.",
            S.NOT_RUN,
        ),
        Text(
            "pdf",
            "PDF file read: {path:line} ({size:line_without_brackets})",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text(
            "pdf_pages",
            "PDF pages extracted: {pages:int} page(s) from {path:line} ({size:line_without_brackets})",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text("pdf_tool_missing", "pdftoppm is not installed. {hint:text}", S.NOT_RUN),
        Text(
            "pdf_too_many_pages",
            "This PDF has {pages:int} pages, which is too many to read at once. {hint:text}",
            S.NOT_RUN,
        ),
        Text(
            "pdf_too_large",
            "PDF file exceeds maximum allowed size of {limit:rest_of_line}",
            S.NOT_RUN,
        ),
        Text("image_too_large", "Unable to resize image {detail:text}", S.NOT_RUN),
        Text(
            "directory",
            "EISDIR: illegal operation on a directory, {detail:text}",
            S.NOT_RUN,
        ),
        Text("missing", "File does not exist. {note:text}", S.NOT_RUN),
        Text(
            "too_large",
            "File content ({size:line_without_brackets}) exceeds maximum allowed {limit:text}",
            S.NOT_RUN,
        ),
        _PERSISTED,
        _PERSISTED_PARTIAL,
        Text("listing", "{tool_output:numbered_tab}", S.FINISHED),
    )
)

# What Write and Edit return after they changed a file.
_UPDATED = (
    Text(
        "updated_fresh",
        "The file {path:line} has been updated successfully." + _FRESH,
        S.FINISHED,
    ),
    Text("updated", "The file {path:line} has been updated successfully.", S.FINISHED),
)
# A notice Write adds to its result.
_PARAMETER_NOTICE = HarnessNotice(
    "parameter_notice",
    "\n\nNote: Write's parameters are named {rest:rest_of_line}",
    at="end",
)
_WRITE = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        _NOT_RUN_CLASSIFIER,
        _REFUSED_SYMLINK,
        Text(
            "created_fresh",
            "File created successfully at: {path:word}" + _FRESH,
            S.FINISHED,
        ),
        Text(
            "created", "File created successfully at: {path:rest_of_line}", S.FINISHED
        ),
        *_UPDATED,
    ),
    notices=(_PARAMETER_NOTICE,),
)

_EDIT = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        _NOT_RUN_CLASSIFIER,
        _REFUSED_SYMLINK,
        *_UPDATED,
        Text(
            "updated_note",
            "The file {path:line} has been updated successfully. (note: {note:text}",
            S.FINISHED,
        ),
        Text(
            "replaced_all_fresh",
            "The file {path:line} has been updated. All occurrences were successfully replaced."
            + _FRESH,
            S.FINISHED,
        ),
        Text(
            "replaced_all",
            "The file {path:line} has been updated. All occurrences were successfully replaced.",
            S.FINISHED,
        ),
        Text(
            "replaced_all_note",
            "The file {path:line} has been updated. All occurrences were successfully replaced. (note: {note:text}",
            S.FINISHED,
        ),
    )
)

_WEB_FETCH = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        _PERSISTED,
        _PERSISTED_PARTIAL,
        Text("no_model_response", "No response from model", S.FINISHED),
        Text(
            "no_model_response_binary_saved",
            "No response from model\n\n[Binary content ({detail:line_without_brackets}) also saved to {output_path:line_without_brackets}]",
            S.FINISHED,
        ),
        Text(
            "http_error_body_not_retrieved",
            "The server returned HTTP {http_status:int} {reason:rest_of_line}\n\nThe response body was not retrieved. {detail:text}",
            S.FINISHED,
        ),
        Text("api_error", "API Error: {detail:text}", S.FINISHED),
        Text("connection_error", "connect {error:rest_of_line}", S.FINISHED),
        Text(
            "page_binary_saved",
            "{tool_output:text}\n\n[Binary content ({detail:line_without_brackets}) also saved to {output_path:line_without_brackets}]",
            S.FINISHED,
        ),
        Text("page", "{tool_output:text}", S.FINISHED),
    )
)

_SEARCH_HEAD = 'Web search results for query: "{query:line}"\n\n'
_SEARCH_FOOT = "\n\nREMINDER: You MUST include the sources above in your response to the user using markdown hyperlinks."
_WEB_SEARCH = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        Text(
            "persisted_results",
            _PERSISTED_HEAD + _SEARCH_HEAD + "{tool_output:text}\n</persisted-output>",
            S.FINISHED,
            is_truncated=True,
        ),
        _PERSISTED,
        _PERSISTED_PARTIAL,
        Text(
            "cut_off",
            "The search was cut off before any results arrived. Try again.",
            S.FINISHED,
        ),
        Text("results", _SEARCH_HEAD + "{tool_output:text}" + _SEARCH_FOOT, S.FINISHED),
    )
)

_TASK_KINDS = {
    "local_bash": ExecutionHandleKind.COMMAND,
    "local_agent": ExecutionHandleKind.SUBAGENT,
}
_TASK_STOP = HarnessResultFormatList[JsonObject](
    (
        Json(
            "stopped",
            S.KILLED,
            {"handle": "task_id", "handle_kind_name": "task_type"},
            present_paths=("task_id", "message"),
            handle_kind_by_name=_TASK_KINDS,
        ),
    )
)
_TASK_STOP_TEXT = HarnessResultFormatList[str](
    (
        _TOOL_USE_ERROR,
        _INTERRUPTED_CLASSIFIER,
        Text(
            "persisted_stopped",
            _PERSISTED_HEAD
            + '{"message":"Successfully stopped task: {handle:id} {rest:text}',
            S.KILLED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _PERSISTED,
        _PERSISTED_PARTIAL,
        Text(
            "not_owner",
            "Task {task:id} is owned by {owner:id}; agent {agent:id} cannot stop it.",
            S.NOT_RUN,
        ),
    )
)

_TASK_FIELDS = {
    "tool_output": "task.output",
    "exit_code": "task.exitCode",
    "handle": "task.task_id",
    "handle_kind_name": "task.task_type",
}
_TASK_OUTPUT = HarnessResultFormatList[JsonObject](
    tuple(
        Json(
            f"task_{state}",
            status,
            _TASK_FIELDS,
            condition=JsonCondition("task.status", "==", state),
            handle_kind_by_name=_TASK_KINDS,
        )
        for state, status in (
            ("running", S.RUNNING),
            ("completed", S.FINISHED),
            ("failed", S.FINISHED),
        )
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "Bash": HarnessToolResultDeclaration(
        text_formats=_BASH_OK, text_formats_when_marked_as_error=_BASH_ERROR
    ),
    "Read": HarnessToolResultDeclaration(text_formats=_READ),
    "Write": HarnessToolResultDeclaration(text_formats=_WRITE),
    "Edit": HarnessToolResultDeclaration(text_formats=_EDIT),
    "WebFetch": HarnessToolResultDeclaration(text_formats=_WEB_FETCH),
    "WebSearch": HarnessToolResultDeclaration(text_formats=_WEB_SEARCH),
    "TaskOutput": HarnessToolResultDeclaration(json_formats=_TASK_OUTPUT),
    "TaskStop": HarnessToolResultDeclaration(
        text_formats=_TASK_STOP_TEXT, json_formats=_TASK_STOP
    ),
}
