"""Claude Code tool call converter."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
    RawToolCall,
    ToolCallOutput,
    UnmatchedFormat,
    handles_from_ids,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
    JsonObject,
    join_content_items,
)

S = ExecutionStatus
Text = HarnessTextResultFormat
Json = HarnessJsonResultFormat

_ITEM_TYPES = (
    "text",
    "image",
    "tool_reference",
    "document",
)  # content items Harbor writes as JSON
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
        Text("background", _BACKGROUND + _NOTIFY, S.RUNNING),
        Text("background_v3", _BACKGROUND + _NOTIFY_V3, S.RUNNING),
        Text(
            "background_after_output",
            "{tool_output:text}\n" + _BACKGROUND + _NOTIFY,
            S.RUNNING,
        ),
        Text("background_timeout", _BACKGROUND_TIMEOUT + _NOTIFY, S.RUNNING),
        Text("background_timeout_v2", _BACKGROUND_TIMEOUT + _NOTIFY_V2, S.RUNNING),
        _PERSISTED,
        _PERSISTED_PARTIAL,
        # Not judged an error, so no header: exit 0, or 1 for grep, find, diff and the like.
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
        Text(  # Claude Code skipped the read: the file is unchanged since the last one
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
            "The server returned HTTP {code:int} {reason:rest_of_line}\n\nThe response body was not retrieved. {detail:text}",
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


def _extra(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return result.get("extra") or {}


def _metadata(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """What Harbor keeps of Claude Code's own result."""
    return _extra(result).get("tool_result_metadata") or {}


def structured_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Claude Code's structured result (`tool_use_result`), which most calls carry, or {} without one."""
    structured = _metadata(result).get("tool_use_result")
    return structured if isinstance(structured, dict) else {}


def _harbor_items(content: str) -> list[dict[str, Any]] | None:
    """Content items Harbor wrote as JSON, one per paragraph, or None when the content is plain text."""
    items: list[dict[str, Any]] = []
    for part in content.split("\n\n"):
        try:
            item = json.loads(part)
        except ValueError:
            return None
        if not (isinstance(item, dict) and item.get("type") in _ITEM_TYPES):
            return None
        items.append(item)
    return items


def _original_text(result: Mapping[str, Any]) -> tuple[str | None, set[str]]:
    """Claude Code's own result text and the kinds of content items it had (e.g. {"image"})."""
    block = _metadata(result).get("raw_tool_result")
    if isinstance(block, dict):
        content = block.get("content")
        if isinstance(content, list):
            kinds = {
                str(item.get("type")) for item in content if isinstance(item, dict)
            }
            return join_content_items(content), kinds
        if not isinstance(content, str):
            return None, set()
        return content.strip() or None, set()
    content = result.get("content")
    if not isinstance(content, str):
        return None, set()
    items = _harbor_items(content)
    if items:
        return join_content_items(items), {str(item.get("type")) for item in items}
    return content, set()


def _code_without_header(structured: Mapping[str, Any]) -> int | None:
    """The exit code of a finished command Claude Code did not judge an error.

    Grep, find, diff and the like exit 1 without an error; Claude Code then names
    that meaning in returnCodeInterpretation, and writes it only for code 1.
    """
    if structured.get("interrupted"):
        return None
    return 1 if structured.get("returnCodeInterpretation") else 0


def _with_structured_bash(
    output: ToolCallOutput, structured: Mapping[str, Any]
) -> ToolCallOutput:
    """Prefer the structured stdout, task id and saved-output path over what the text showed."""
    saved_to = structured.get("persistedOutputPath")
    task_id = structured.get("backgroundTaskId")
    exit_code = output.exit_code
    if exit_code is None and output.execution_status is S.FINISHED:
        exit_code = _code_without_header(structured)
    # stdout is the whole tool output, since its stderr only holds the cwd notice.
    stdout = structured.get("stdout") or ""
    return replace(
        output,
        tool_output_text=stdout,
        exit_code=exit_code,
        handles=handles_from_ids(ExecutionHandleKind.COMMAND, task_id)
        or output.handles,
        output_path=saved_to or output.output_path,
        is_truncated=True if saved_to else output.is_truncated,
    )


def _with_structured_read(
    output: ToolCallOutput, file: Mapping[str, Any]
) -> ToolCallOutput:
    """Prefer the structured file content, and mark a read Claude Code cut at its token cap."""
    content = file.get("content")
    if isinstance(content, str):
        output = replace(output, tool_output_text=content)
    if file.get("truncatedByTokenCap") is True:
        output = replace(output, is_truncated=True)
    return output


class ClaudeCodeConverter(HarnessToolCallConverter):
    stop_tools: ClassVar = frozenset({"TaskStop"})
    text_formats: ClassVar = {
        "Bash": _BASH_OK,
        "Read": _READ,
        "Write": _WRITE,
        "Edit": _EDIT,
        "WebFetch": _WEB_FETCH,
        "WebSearch": _WEB_SEARCH,
        "TaskStop": _TASK_STOP_TEXT,
    }
    json_formats: ClassVar = {"TaskOutput": _TASK_OUTPUT, "TaskStop": _TASK_STOP}

    def extract_tool_result_raw_text(
        self, raw: RawToolCall, result: dict[str, Any]
    ) -> str | None:
        """Claude Code's own result text. Harbor keeps it in
        `extra.tool_result_metadata.raw_tool_result`, and `content` is read only when
        that is missing. Text from `raw_tool_result` loses its edge whitespace, and
        content items are joined.
        """
        return _original_text(result)[0]

    def extract_tool_result_json(
        self, raw: RawToolCall, result: dict[str, Any]
    ) -> JsonObject | None:
        if raw.tool.name == "TaskOutput":
            return structured_result(result) or None  # {} has nothing to match
        return super().extract_tool_result_json(raw, result)

    def select_formats(
        self,
        raw: RawToolCall,
        result: dict[str, Any],
        tool_result_json: JsonObject | None,
    ) -> HarnessResultFormatList[Any] | None:
        if raw.tool.name == "Bash" and _extra(result).get("tool_result_is_error"):
            return _BASH_ERROR
        return super().select_formats(raw, result, tool_result_json)

    def declared_formats(self) -> list[tuple[str, HarnessResultFormatList[Any]]]:
        """Also `_BASH_ERROR`, which `select_formats` picks outside `text_formats`."""
        return [("Bash", _BASH_ERROR), *super().declared_formats()]

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        name = raw.tool.name
        if name == "Read":
            raw_text, item_kinds = _original_text(result)
            if raw_text is None and "image" in item_kinds:
                return ToolCallOutput(
                    execution_status=S.FINISHED,
                    harness_result_format=MatchedFormat("image"),
                )
        structured = structured_result(result)
        output = super().parse_output(raw, result)
        if isinstance(output.harness_result_format, UnmatchedFormat):
            return output
        if name == "Bash" and structured:
            return _with_structured_bash(output, structured)
        if name == "Read":
            return _with_structured_read(output, structured.get("file") or {})
        return output
