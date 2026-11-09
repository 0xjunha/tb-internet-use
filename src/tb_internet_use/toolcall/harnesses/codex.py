"""Codex tool call converter."""

from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
    PollAction,
    RawToolCall,
    ToolCallOutput,
    UnknownAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    string_tuple,
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
            is_truncated=True,
        ),
        Text(
            "exited_truncated_no_line_count",
            _HEAD + _EXITED + _TOKENS + _TRUNCATED_NO_LINE_COUNT + "{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text("exited", _HEAD + _EXITED + _TOKENS + "{tool_output:text}", S.FINISHED),
        Text(
            "running_truncated",
            _HEAD + _RUNNING + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.RUNNING,
            is_truncated=True,
        ),
        Text("running", _HEAD + _RUNNING + _TOKENS + "{tool_output:text}", S.RUNNING),
        Text(
            "v2_exited",
            _V2
            + "Exit code: {exit_code:int}\nWall time: {seconds2:line_without_brackets} seconds\nOutput:\n{tool_output:text}",
            S.FINISHED,
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
# Ctrl-C sent through write_stdin stops the process, which then exits with 130.
_CTRL_C = "\x03"
_SIGINT_EXIT_CODE = 130
_NO_CONTENT = ToolCallOutput(
    execution_status=S.FINISHED, harness_result_format=MatchedFormat("no_content")
)


def _search_queries(args: dict[str, Any]) -> tuple[str, ...]:
    """Every query of a search, in order and without repeats. `query` holds only the first."""
    queries = args.get("queries")
    if not isinstance(queries, list) or not queries:
        queries = [args.get("query")]
    return tuple(dict.fromkeys(str(query) for query in queries if query))


def _sends_ctrl_c(raw: RawToolCall) -> bool:
    return raw.tool.name == "write_stdin" and _CTRL_C in str(raw.args.get("chars", ""))


class CodexConverter(HarnessToolCallConverter):
    text_formats: ClassVar = {"exec_command": _SHELL, "write_stdin": _SHELL}
    argument_handle_kinds: ClassVar = {
        "write_stdin": ExecutionHandleKind.COMMAND,  # an exec_command session
        "wait": ExecutionHandleKind.SCRIPT,  # an exec cell
    }

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        if raw.tool.name == _WEB_SEARCH_CALL and result.get("content") is None:
            return _NO_CONTENT
        output = super().parse_output(raw, result)
        if _sends_ctrl_c(raw) and output.exit_code == _SIGINT_EXIT_CODE:
            output = replace(output, execution_status=S.KILLED, exit_code=None)
        return output

    def refine_action(
        self, raw: RawToolCall, action: Action, output: ToolCallOutput | None
    ) -> Action:
        action = super().refine_action(raw, action, output)
        if isinstance(action, PollAction) and _sends_ctrl_c(raw):
            action = replace(action, terminate=True)
        return action

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        if raw.tool.name != _WEB_SEARCH_CALL:
            return UnknownAction()  # exec, whose script steps are not converted yet
        url = raw.args.get("url")
        match raw.args.get("action_type"):
            case "search":
                return WebSearchAction(_search_queries(raw.args))
            case "open_page":
                return WebFetchAction(string_tuple(url))
            case "find_in_page":
                return WebFindAction(string_tuple(url))
            case _:
                return UnknownAction()
