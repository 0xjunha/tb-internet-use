"""Cursor CLI tool call converter."""

from typing import ClassVar

from tb_internet_use.parse.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.parse.toolcall.model import (
    Action,
    ExecutionHandleKind,
    ExecutionStatus,
    OtherAction,
    RawToolCall,
    ToolCallOutput,
    WebFetchAction,
    string_tuple,
)
from tb_internet_use.parse.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    JsonCondition,
    JsonObject,
    MatchedValues,
    join_texts,
)

S = ExecutionStatus
Json = HarnessJsonResultFormat

_SHELL_DONE = {
    "tool_output": "success.interleavedOutput",
    "exit_code": "success.exitCode",
}
_SHELL_FAILED = {
    "tool_output": "failure.interleavedOutput",
    "exit_code": "failure.exitCode",
}
_SHELL_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json("not_spawned", S.NOT_RUN, present_paths=("spawnError",)),
        Json(
            "background",
            S.RUNNING,
            {"tool_output": "success.interleavedOutput", "handle": "success.shellId"},
            present_paths=("success.shellId", "success.interleavedOutput"),
        ),
        Json(
            "background_requested",
            S.RUNNING,
            {"tool_output": "success.stdout", "handle": "success.shellId"},
            present_paths=("success.shellId",),
            absent_paths=("success.interleavedOutput",),
        ),
        Json(
            "exited_saved",
            S.FINISHED,
            {**_SHELL_DONE, "output_path": "success.outputLocation.filePath"},
            present_paths=("success.exitCode", "success.outputLocation"),
            is_truncated=True,
        ),
        Json(
            "exited",
            S.FINISHED,
            _SHELL_DONE,
            present_paths=("success.exitCode",),
            absent_paths=("success.shellId", "success.outputLocation"),
        ),
        Json(
            "failed_saved",
            S.FINISHED,
            {**_SHELL_FAILED, "output_path": "failure.outputLocation.filePath"},
            present_paths=("failure.exitCode", "failure.outputLocation"),
            is_truncated=True,
        ),
        Json(
            "failed",
            S.FINISHED,
            _SHELL_FAILED,
            present_paths=("failure.exitCode",),
            absent_paths=("failure.outputLocation",),
        ),
    )
)

_AWAIT_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "no_task",
            S.UNKNOWN,
            present_paths=("success.complete",),
            condition=JsonCondition("success.complete.taskId", "==", ""),
        ),
        Json(
            "complete",
            S.FINISHED,
            {
                "tool_output": "success.complete.regexMatch",
                "exit_code": "success.complete.exitCode",
                "handle": "success.complete.taskId",
                "output_path": "success.complete.outputFilePath",
            },
            present_paths=("success.complete",),
            condition=JsonCondition("success.complete.taskId", "!=", ""),
        ),
        Json(
            "still_running",
            S.RUNNING,
            {
                "tool_output": "success.stillRunning.regexMatch",
                "handle": "success.stillRunning.taskId",
                "output_path": "success.stillRunning.outputFilePath",
            },
            present_paths=("success.stillRunning",),
        ),
        Json("error", S.NOT_RUN, present_paths=("error",)),
    )
)

_READ_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "content",
            S.FINISHED,
            {"tool_output": "success.content"},
            present_paths=("success.content",),
            condition=JsonCondition("success.exceededLimit", "!=", True),
        ),
        # The file is over the size limit, so the tool read nothing.
        Json(
            "too_large",
            S.NOT_RUN,
            present_paths=("success.content",),
            condition=JsonCondition("success.exceededLimit", "==", True),
        ),
        # The file was read, but the trajectory keeps only its contentBlobId, not the content.
        Json(
            "blob",
            S.FINISHED,
            present_paths=("success",),
            absent_paths=("success.content",),
            no_tool_output_text=True,
        ),
        Json("error", S.NOT_RUN, present_paths=("error",)),
    )
)

_EDIT_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json("edited", S.FINISHED, present_paths=("success",)),
        Json("error", S.NOT_RUN, present_paths=("error",)),
    )
)

_LOCALHOST_REFUSAL = "Cannot fetch from localhost"
_WEB_FETCH_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "page_saved",
            S.FINISHED,
            {
                "tool_output": "success.markdown",
                "output_path": "success.outputLocation.filePath",
            },
            present_paths=("success.markdown", "success.outputLocation"),
            is_truncated=True,
        ),
        Json(
            "page",
            S.FINISHED,
            {"tool_output": "success.markdown"},
            present_paths=("success.markdown",),
            absent_paths=("success.outputLocation",),
        ),
        Json(
            "refused_localhost",
            S.NOT_RUN,
            present_paths=("error.error",),
            condition=JsonCondition("error.error", "startswith", _LOCALHOST_REFUSAL),
        ),
        Json(
            "error",
            S.FINISHED,
            present_paths=("error.error",),
            condition=JsonCondition("error.error", "!startswith", _LOCALHOST_REFUSAL),
        ),
    )
)

_WEB_SEARCH_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "results",
            S.FINISHED,
            {"tool_output": "success.references"},
            present_paths=("success.references",),
        ),
        Json("error", S.FINISHED, present_paths=("error",)),
    )
)


def _content_text(values: MatchedValues) -> str | None:
    items = values.get("tool_output")
    if not isinstance(items, list):
        return None
    texts: list[str] = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else None
        if isinstance(text, dict):
            text = text.get("text")
        if isinstance(text, str):
            texts.append(text)
    return join_texts(texts)


_MCP_TOOL_CALL = HarnessResultFormatList[JsonObject](
    (
        Json(
            "content",
            S.FINISHED,
            {"tool_output": "success.content"},
            present_paths=("success.content",),
            condition=JsonCondition("success.isError", "!=", True),
            text_from_matched_values=_content_text,
        ),
        Json("error", S.NOT_RUN, present_paths=("error",)),
    )
)


class CursorCliConverter(HarnessToolCallConverter):
    # a background shell
    argument_handle_kinds: ClassVar = {"awaitToolCall": ExecutionHandleKind.COMMAND}
    json_formats: ClassVar = {
        "shellToolCall": _SHELL_TOOL_CALL,
        "awaitToolCall": _AWAIT_TOOL_CALL,
        "readToolCall": _READ_TOOL_CALL,
        "editToolCall": _EDIT_TOOL_CALL,
        "webFetchToolCall": _WEB_FETCH_TOOL_CALL,
        "webSearchToolCall": _WEB_SEARCH_TOOL_CALL,
        "mcpToolCall": _MCP_TOOL_CALL,
    }

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        if (
            raw.tool.name == "mcpToolCall"
            and raw.args.get("toolName") == "browser_navigate"
        ):
            args = raw.args.get("args")
            return WebFetchAction(
                string_tuple(args.get("url") if isinstance(args, dict) else None)
            )
        # another wrapped MCP tool, labeled OtherAction like Claude Code's MCP tools
        return OtherAction()
