"""Convert the tool calls of Codex, reading the steps of `exec` scripts and the sessions they leave running."""

import ast
import json
import re
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call._convert_tool_call_action import action_from_label
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_exit_code_130_after_ctrl_c_as_killed,
)
from tb_internet_use.tool_call.model import (
    DEFERRED,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    HarnessToolLabel,
    PollAction,
    RunToolScriptAction,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
    UnknownHarnessToolLabel,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    handles_from_ids,
    join_text_parts,
    strings_from_values,
)
from tb_internet_use.tool_call.parse_codex_exec_script import (
    actions_from_web_run_argument,
    parse_codex_exec_script,
)
from tb_internet_use.tool_call.parse_patch import parse_patch

if TYPE_CHECKING:
    # `ToolCallKnowledge` and the declaration types are named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
        JsonObject,
    )
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

S = ExecutionStatus

# exec runs a script, and wait polls a script that was still running.
_SCRIPT_TOOLS = frozenset({"exec", "wait"})

# Tools a script cannot call. A call fails with "not a function".
_NOT_IN_SCRIPTS = frozenset({"exec", "wait", "request_user_input_async"})

_WEB_SEARCH_CALL = "web_search_call"
# Ctrl-C sent through write_stdin stops the process.
_CTRL_C = "\x03"


# A step result a script printed as JSON, e.g. `text(JSON.stringify(await tools.exec_command(...)))`.
_STEP_RESULT_LINE = re.compile(r'^\{"chunk_id".*\}$', re.MULTILINE)


class CodexConverter(HarnessToolCallConverter):
    def tool_result_raw_text_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> str | None:
        """Read the result text, which for exec and wait is the text items of the Python list Codex writes, joined."""
        text = super().tool_result_raw_text_of(harness_tool_call, tool_result)
        items = (
            _script_items_from_content(text)
            if text and harness_tool_call.tool.name in _SCRIPT_TOOLS
            else None
        )
        if items is None:
            return text
        return join_text_parts(str(i.get("text") or "") for i in items if _is_text(i))

    def tool_result_json_of(
        self, harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
    ) -> JsonObject | None:
        """Read the JSON object of the result, which for `web_search_call` is the result entry of the trajectory itself, since Codex keeps no output of a web search and the entry is all there is to match.

        The entry stays even when it is empty, unlike a decoded raw text, since `{}` is what such a result looks like.
        """
        if harness_tool_call.tool.name == _WEB_SEARCH_CALL:
            return tool_result
        return super().tool_result_json_of(harness_tool_call, tool_result)

    def convert_result(
        self,
        harness_tool_call: HarnessToolCall,
        tool_result: dict[str, Any],
        *,
        knowledge: ToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> ToolCallResult:
        tool_call_result = super().convert_result(
            harness_tool_call,
            tool_result,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        if _has_ctrl_c_input(harness_tool_call):
            tool_call_result = treat_exit_code_130_after_ctrl_c_as_killed(
                tool_call_result, use_counts=judgment_rule_use_counts
            )
        if tool_call_result.tool_output_text == "" and _has_printed_media(
            harness_tool_call, tool_result
        ):
            tool_call_result = replace(tool_call_result, tool_output_text=None)
        if harness_tool_call.tool.name in _SCRIPT_TOOLS:
            running = _running_session_ids_from_text(tool_call_result.tool_output_text)
            sessions = handles_from_ids(ExecutionHandleKind.COMMAND, running)
            tool_call_result = replace(
                tool_call_result, handles=tool_call_result.handles + sessions
            )
        return tool_call_result

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        if harness_tool_call.tool.name == "exec":
            code = harness_tool_call.args.get("input")
            if not isinstance(code, str):
                return RunToolScriptAction()
            steps = self._steps_of_script(harness_tool_call, code, knowledge)
            return RunToolScriptAction(code, steps)
        url = harness_tool_call.args.get("url")
        match harness_tool_call.args.get("action_type"):
            case "search":
                # queries holds every query of the search, query only the first
                queries = harness_tool_call.args.get(
                    "queries"
                ) or harness_tool_call.args.get("query")
                return WebSearchAction(strings_from_values(queries))
            case "open_page":
                return WebFetchAction(strings_from_values(url))
            case "find_in_page":
                return WebFindAction(strings_from_values(url))
            case _:
                return UnknownAction()

    def _steps_of_script(
        self,
        harness_tool_call: HarnessToolCall,
        code: str,
        knowledge: ToolCallKnowledge,
    ) -> tuple[ToolCallAction, ...]:
        """List the ToolCallActions of the tool calls in an exec script, in order."""
        return tuple(
            action
            for name, argument in parse_codex_exec_script(code)
            for action in self._actions_of_script_step(
                harness_tool_call, name, argument, knowledge
            )
        )

    def _actions_of_script_step(
        self,
        harness_tool_call: HarnessToolCall,
        name: str,
        argument: Any,
        knowledge: ToolCallKnowledge,
    ) -> list[ToolCallAction]:
        """List the ToolCallActions of one tool call in a script, or UnknownAction when none can be read.

        A tool with a label gets its ToolCallAction as a top-level call of that name. This covers a tool only scripts call, such as `clock__curr_time`, which has a row in the catalog like any tool.
        """
        actions: list[ToolCallAction]
        if name == "apply_patch":
            actions = [*parse_patch(argument)] if isinstance(argument, str) else []
        elif name == "web__run":
            actions = (
                actions_from_web_run_argument(argument)
                if isinstance(argument, dict)
                else []
            )
        elif name in _NOT_IN_SCRIPTS:
            return [UnknownAction()]
        else:
            tool = HarnessTool(harness_tool_call.tool.harness, name)
            args = argument if isinstance(argument, dict) else {}
            label = knowledge.harness_tool_label(tool, args.keys())
            if (
                isinstance(label, UnknownHarnessToolLabel)
                or label.action_type == DEFERRED
            ):
                return [UnknownAction()]
            # The exec call itself, as if it were a call of the step's tool, so that refine_action treats the step like a top-level call.
            step = replace(harness_tool_call, tool=tool, args=args, result=None)
            action = action_from_label(label, args)
            actions = [self.refine_action(step, action, None, label)]
        return actions or [UnknownAction()]

    def refine_action(
        self,
        harness_tool_call: HarnessToolCall,
        action: ToolCallAction,
        tool_call_result: ToolCallResult | None,
        label: HarnessToolLabel,
    ) -> ToolCallAction:
        if harness_tool_call.tool.name == "wait" and tool_call_result is not None:
            # A wait polls its cell, not the sessions the script left running.
            cells = tuple(
                h
                for h in tool_call_result.handles
                if h.kind is ExecutionHandleKind.SCRIPT
            )
            tool_call_result = replace(tool_call_result, handles=cells)
        action = super().refine_action(
            harness_tool_call, action, tool_call_result, label
        )
        if isinstance(action, PollAction) and _has_ctrl_c_input(harness_tool_call):
            action = replace(action, terminate=True)
        return action


def _has_ctrl_c_input(harness_tool_call: HarnessToolCall) -> bool:
    return harness_tool_call.tool.name == "write_stdin" and _CTRL_C in str(
        harness_tool_call.args.get("chars", "")
    )


def _has_printed_media(
    harness_tool_call: HarnessToolCall, tool_result: dict[str, Any]
) -> bool:
    """Tell whether an exec or wait script printed images or audio.

    When it printed no text, as when convert_result asks, that is all it printed.
    """
    content = tool_result.get("content")
    if harness_tool_call.tool.name not in _SCRIPT_TOOLS or not isinstance(content, str):
        return False
    printed = (_script_items_from_content(content) or ())[1:]
    return any(not _is_text(item) for item in printed)


def _script_items_from_content(content: str) -> tuple[dict[str, Any], ...] | None:
    """Read the content items of an exec or wait result, which Codex writes as a Python list.

    The first item holds the script's state and wall time, and the rest is what the script printed. None for a result that is plain text.
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


def _running_session_ids_from_text(text: str | None) -> list[Any]:
    """List the sessions of commands still running, from step results a script printed as JSON.

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
