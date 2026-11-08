"""Codex tool call converter."""

from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionStatus,
    MatchedFormat,
    RawToolCall,
    ToolCallOutput,
    UnknownAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessResultFormatList,
    HarnessTextResultFormat,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

_HEAD = "Chunk ID: {chunk:id}\nWall time: {seconds:line_without_brackets} seconds\n"
_EXITED = "Process exited with code {exit_code:int}\n"
_RUNNING = "Process running with session ID {handle:int}\n"
_TOKENS = "Original token count: {tokens:int}\nOutput:\n"
_TRUNCATED = "Warning: truncated output (original token count: {original:int})\nTotal output lines: {lines:int}\n\n"
# The same warning without the line count, followed right away by the output.
_TRUNCATED_NO_LINE_COUNT = (
    "Warning: truncated output (original token count: {original:int})\n"
)
_V2 = "Wall time: {seconds:line_without_brackets} seconds\nOutput:\n"

_SHELL = HarnessResultFormatList[str](
    (
        Text(
            "exited_truncated",
            _HEAD + _EXITED + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.FINISHED,
            True,
        ),
        Text(
            "exited_truncated_no_line_count",
            _HEAD + _EXITED + _TOKENS + _TRUNCATED_NO_LINE_COUNT + "{tool_output:text}",
            S.FINISHED,
            True,
        ),
        Text("exited", _HEAD + _EXITED + _TOKENS + "{tool_output:text}", S.FINISHED),
        Text(
            "running_truncated",
            _HEAD + _RUNNING + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.RUNNING,
            True,
        ),
        Text("running", _HEAD + _RUNNING + _TOKENS + "{tool_output:text}", S.RUNNING),
        Text(
            "v2_exited",
            _V2
            + "Exit code: {exit_code:int}\nWall time: {seconds2:line_without_brackets} seconds\nOutput:\n{tool_output:text}",
            S.FINISHED,
        ),
        Text(
            "v2_running",
            _V2
            + "Process running with session ID {handle:int}\nWall time: {seconds2:line_without_brackets} seconds\nOutput:\n{tool_output:text}",
            S.RUNNING,
        ),
        Text("rejected", "exec_command failed: {reason:text}", S.NOT_RUN),
        Text(
            "rejected_command",
            "exec_command failed for `{command:text}`: {reason:text}",
            S.NOT_RUN,
        ),
        Text(
            "rejected_patch",
            "apply_patch verification failed: {reason:text}",
            S.NOT_RUN,
        ),
        Text("rejected_stdin", "write_stdin failed: {reason:text}", S.NOT_RUN),
    )
)

_WEB_SEARCH_CALL = "web_search_call"
_NO_CONTENT = ToolCallOutput(
    execution_status=S.FINISHED, harness_result_format=MatchedFormat("no_content")
)


class CodexConverter(HarnessToolCallConverter):
    text_formats: ClassVar = {"exec_command": _SHELL, "write_stdin": _SHELL}

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        if raw.tool.name == _WEB_SEARCH_CALL and result.get("content") is None:
            return _NO_CONTENT
        return super().parse_output(raw, result)

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        if raw.tool.name != _WEB_SEARCH_CALL:
            return UnknownAction()
        query = raw.args.get("query")
        url = raw.args.get("url")
        match raw.args.get("action_type"):
            case "search":
                return WebSearchAction((str(query),) if query else ())
            case "open_page":
                return WebFetchAction((str(url),) if url else ())
            case "find_in_page":
                return WebFindAction((str(url),) if url else ())
            case _:
                return UnknownAction()
