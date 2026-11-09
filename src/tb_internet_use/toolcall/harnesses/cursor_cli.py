"""Cursor CLI tool call converter."""

from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import (
    HarnessToolCallConverter,
    join_content_items,
    string_tuple,
)
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandleKind,
    ExecutionStatus,
    OtherAction,
    RawToolCall,
    ToolCallOutput,
    WebFetchAction,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessResultFormatList,
    JsonCondition,
    JsonObject,
    MatchedValues,
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
            condition=JsonCondition(
                "error.error", "startswith", "Cannot fetch from localhost"
            ),
        ),
        Json(
            "error",
            S.FINISHED,
            present_paths=("error.error",),
            condition=JsonCondition(
                "error.error", "!startswith", "Cannot fetch from localhost"
            ),
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
    flat: list[dict[str, Any]] = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else None
        if isinstance(text, dict):
            text = text.get("text")
        if isinstance(text, str):
            flat.append({"type": "text", "text": text})
    return join_content_items(flat)


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
        args = raw.args.get("args")
        url = args.get("url") if isinstance(args, dict) else None
        if (
            raw.tool.name == "mcpToolCall"
            and raw.args.get("toolName") == "browser_navigate"
        ):
            return WebFetchAction(string_tuple(url))
        return OtherAction()
