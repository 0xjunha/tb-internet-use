"""Codex tool call converter."""

import ast
import json
import re
from dataclasses import replace
from typing import Any, ClassVar

from tb_internet_use.parse.toolcall.catalog_loader import (
    DEFERRED,
    action_from_label,
    tool_catalog,
)
from tb_internet_use.parse.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.parse.toolcall.harnesses.codex_exec import (
    patch_actions,
    script_tool_calls,
    web_run_actions,
)
from tb_internet_use.parse.toolcall.model import (
    Action,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    MatchedFormat,
    OtherAction,
    PollAction,
    RawToolCall,
    RunToolScriptAction,
    ToolCallOutput,
    UnknownAction,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    handles_from_ids,
    string_tuple,
)
from tb_internet_use.parse.toolcall.result_formats import (
    HarnessResultFormatList,
    HarnessTextResultFormat,
    join_text_parts,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

_HEAD = "Chunk ID: {chunk:id}\nWall time: {seconds:line_without_brackets} seconds\n"
_PROCESS_EXITED = "Process exited with code {exit_code:int}\n"
_PROCESS_RUNNING = "Process running with session ID {handle:int}\n"
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
            _HEAD + _PROCESS_EXITED + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited_truncated_no_line_count",
            _HEAD
            + _PROCESS_EXITED
            + _TOKENS
            + _TRUNCATED_NO_LINE_COUNT
            + "{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "exited",
            _HEAD + _PROCESS_EXITED + _TOKENS + "{tool_output:text}",
            S.FINISHED,
        ),
        Text(
            "running_truncated",
            _HEAD + _PROCESS_RUNNING + _TOKENS + _TRUNCATED + "{tool_output:text}",
            S.RUNNING,
            is_truncated=True,
        ),
        Text(
            "running",
            _HEAD + _PROCESS_RUNNING + _TOKENS + "{tool_output:text}",
            S.RUNNING,
        ),
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

# exec runs a script, and wait polls a script that was still running. Both results
# start with the script's state, e.g. "Script completed", then this head.
_SCRIPT_TOOLS = frozenset({"exec", "wait"})
_SCRIPT_HEAD = "\nWall time {seconds:line_without_brackets} seconds\nOutput:\n"
_SCRIPT_COMPLETED = "Script completed" + _SCRIPT_HEAD
_SCRIPT_FAILED = "Script failed" + _SCRIPT_HEAD
_SCRIPT_RUNNING = "Script running with cell ID {handle:word}" + _SCRIPT_HEAD
_COMPLETED_TRUNCATED = Text(
    "completed_truncated",
    _SCRIPT_COMPLETED + _TRUNCATED + "{tool_output:text}",
    S.FINISHED,
    is_truncated=True,
)
_COMPLETED = Text("completed", _SCRIPT_COMPLETED + "{tool_output:text}", S.FINISHED)
# A failed script ran until its error, which stays in the tool output.
_FAILED = Text("failed", _SCRIPT_FAILED + "{tool_output:text}", S.FINISHED)
_RUNNING_TRUNCATED = Text(
    "running_truncated",
    _SCRIPT_RUNNING + _TRUNCATED + "{tool_output:text}",
    S.RUNNING,
    is_truncated=True,
    fixed_handle_kind=ExecutionHandleKind.SCRIPT,
)
_RUNNING = Text(
    "running",
    _SCRIPT_RUNNING + "{tool_output:text}",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.SCRIPT,
)
_EXEC = HarnessResultFormatList[str](
    (
        _COMPLETED_TRUNCATED,
        Text(
            "completed_truncated_bytes",
            _SCRIPT_COMPLETED
            + _TRUNCATED_NO_LINE_COUNT
            + "... {omitted:int} bytes omitted ...\n\n{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
        ),
        _COMPLETED,
        # A script that does not parse runs nothing.
        Text(
            "failed_syntax",
            _SCRIPT_FAILED + "Script error:\nSyntaxError: {error:rest_of_line}",
            S.NOT_RUN,
        ),
        _FAILED,
        _RUNNING_TRUNCATED,
        _RUNNING,
        Text(
            "host_killed",
            "code-mode host exited with status signal: {signal:int} ({signal_name:id})",
            S.KILLED,
        ),
        Text(
            "host_exited",
            "code-mode host exited with status exit status: {host_status:int}",
            S.UNKNOWN,
        ),
    )
)
_WAIT = HarnessResultFormatList[str](
    (
        _COMPLETED_TRUNCATED,
        _COMPLETED,
        Text(
            "cell_not_found",
            _SCRIPT_FAILED + "Script error:\nexec cell {cell:word} not found",
            S.NOT_RUN,
        ),
        _FAILED,
        _RUNNING_TRUNCATED,
        _RUNNING,
        Text(
            "terminated",
            "Script terminated" + _SCRIPT_HEAD + "{tool_output:text}",
            S.KILLED,
        ),
        Text(
            "rejected_arguments",
            "failed to parse function arguments: {reason:text}",
            S.NOT_RUN,
        ),
    )
)

# Tools a script cannot call. A call fails with "not a function".
_NOT_IN_SCRIPTS = frozenset({"exec", "wait", "request_user_input_async"})
# Tools only scripts call, so the catalog, built from top-level calls, has no label.
_SCRIPT_ONLY_ACTIONS = {"clock__curr_time": OtherAction()}

_WEB_SEARCH_CALL = "web_search_call"
# Ctrl-C sent through write_stdin stops the process, which then exits with 130.
_CTRL_C = "\x03"
_SIGINT_EXIT_CODE = 130
_NO_CONTENT = ToolCallOutput(
    execution_status=S.FINISHED, harness_result_format=MatchedFormat("no_content")
)


# A step result a script printed as JSON, e.g. `text(JSON.stringify(await tools.exec_command(...)))`.
_STEP_RESULT_LINE = re.compile(r'^\{"chunk_id".*\}$', re.MULTILINE)


class CodexConverter(HarnessToolCallConverter):
    text_formats: ClassVar = {
        "exec_command": _SHELL,
        "write_stdin": _SHELL,
        "exec": _EXEC,
        "wait": _WAIT,
    }
    argument_handle_kinds: ClassVar = {
        "write_stdin": ExecutionHandleKind.COMMAND,  # an exec_command session
        "wait": ExecutionHandleKind.SCRIPT,  # an exec cell
    }

    def extract_tool_result_raw_text(
        self, raw: RawToolCall, result: dict[str, Any]
    ) -> str | None:
        """For exec and wait, the text items of the Python list Codex writes, joined."""
        text = super().extract_tool_result_raw_text(raw, result)
        items = _script_items(text) if text and raw.tool.name in _SCRIPT_TOOLS else None
        if items is None:
            return text
        return join_text_parts(str(i.get("text") or "") for i in items if _is_text(i))

    def parse_output(self, raw: RawToolCall, result: dict[str, Any]) -> ToolCallOutput:
        if raw.tool.name == _WEB_SEARCH_CALL and result.get("content") is None:
            return _NO_CONTENT
        output = super().parse_output(raw, result)
        if _sends_ctrl_c(raw) and output.exit_code == _SIGINT_EXIT_CODE:
            output = replace(output, execution_status=S.KILLED, exit_code=None)
        if output.tool_output_text == "" and _printed_only_media(raw, result):
            output = replace(output, tool_output_text=None)
        if raw.tool.name in _SCRIPT_TOOLS:
            running = _running_session_ids(output.tool_output_text)
            sessions = handles_from_ids(ExecutionHandleKind.COMMAND, running)
            output = replace(output, handles=output.handles + sessions)
        return output

    def deferred_action(
        self, raw: RawToolCall, output: ToolCallOutput | None
    ) -> Action:
        if raw.tool.name == "exec":
            code = raw.args.get("input")
            if not isinstance(code, str):
                return RunToolScriptAction()
            return RunToolScriptAction(code, self._script_steps(raw, code))
        url = raw.args.get("url")
        match raw.args.get("action_type"):
            case "search":
                # queries holds every query of the search, query only the first
                queries = raw.args.get("queries") or raw.args.get("query")
                return WebSearchAction(string_tuple(queries))
            case "open_page":
                return WebFetchAction(string_tuple(url))
            case "find_in_page":
                return WebFindAction(string_tuple(url))
            case _:
                return UnknownAction()

    def _script_steps(self, raw: RawToolCall, code: str) -> tuple[Action, ...]:
        """The Actions of the tool calls in an exec script, in order."""
        return tuple(
            action
            for name, argument in script_tool_calls(code)
            for action in self._step_actions(raw, name, argument)
        )

    def _step_actions(self, raw: RawToolCall, name: str, argument: Any) -> list[Action]:
        """The Actions of one tool call in a script, UnknownAction when none can be read.

        A tool the catalog labels gets its Action as a top-level call of that name.
        """
        actions: list[Action]
        if name == "apply_patch":
            actions = patch_actions(argument) if isinstance(argument, str) else []
        elif name == "web__run":
            actions = web_run_actions(argument) if isinstance(argument, dict) else []
        elif name in _SCRIPT_ONLY_ACTIONS:
            actions = [_SCRIPT_ONLY_ACTIONS[name]]
        else:
            tool = HarnessTool(raw.tool.harness, name)
            label = tool_catalog().get(tool)
            if (
                label is None
                or label.action_type == DEFERRED
                or name in _NOT_IN_SCRIPTS
            ):
                return [UnknownAction()]
            args = argument if isinstance(argument, dict) else {}
            # The exec call itself, as if it were a call of the step's tool, so that
            # refine_action treats the step like a top-level call.
            step = replace(raw, tool=tool, args=args, result=None)
            actions = [self.refine_action(step, action_from_label(label, args), None)]
        return actions or [UnknownAction()]

    def refine_action(
        self, raw: RawToolCall, action: Action, output: ToolCallOutput | None
    ) -> Action:
        if raw.tool.name == "wait" and output is not None:
            # A wait polls its cell, not the sessions the script left running.
            cells = tuple(
                h for h in output.handles if h.kind is ExecutionHandleKind.SCRIPT
            )
            output = replace(output, handles=cells)
        action = super().refine_action(raw, action, output)
        if isinstance(action, PollAction) and _sends_ctrl_c(raw):
            action = replace(action, terminate=True)
        return action


def _sends_ctrl_c(raw: RawToolCall) -> bool:
    return raw.tool.name == "write_stdin" and _CTRL_C in str(raw.args.get("chars", ""))


def _printed_only_media(raw: RawToolCall, result: dict[str, Any]) -> bool:
    """Whether an exec or wait script printed images or audio. When it printed no text,
    as when parse_output asks, that is all it printed."""
    content = result.get("content")
    if raw.tool.name not in _SCRIPT_TOOLS or not isinstance(content, str):
        return False
    printed = (_script_items(content) or ())[1:]
    return any(not _is_text(item) for item in printed)


def _script_items(content: str) -> tuple[dict[str, Any], ...] | None:
    """The content items of an exec or wait result, which Codex writes as a Python list.

    The first item holds the script's state and wall time, and the rest is what the
    script printed. None for a result that is plain text.
    """
    if not content.startswith("[{"):
        return None
    try:
        items = ast.literal_eval(content)
    except ValueError, SyntaxError:
        return None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        return None
    return tuple(items)


def _is_text(item: dict[str, Any]) -> bool:
    return item.get("type") == "input_text"


def _running_session_ids(text: str | None) -> list[Any]:
    """The sessions of commands still running, from step results a script printed as JSON.

    A step result with a session_id and no exit_code is a command the script left running.
    """
    ids = []
    for line in _STEP_RESULT_LINE.findall(text or ""):
        try:
            step = json.loads(line)
        except ValueError:
            continue
        if isinstance(step, dict) and "session_id" in step and "exit_code" not in step:
            ids.append(step["session_id"])
    return ids
