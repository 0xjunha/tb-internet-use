"""Convert the tool calls of Antigravity CLI, deciding the action of a write that may append, of a task tool whose `Action` argument picks what it does and of a message step that reports the end of a task."""

from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call._convert_tool_call_action import (
    field_value_from_argument,
)
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
    action_from_harness_message_result,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandleKind,
    HarnessToolCall,
    OtherAction,
    PollAction,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
    WriteFileAction,
    handles_from_ids,
)

if TYPE_CHECKING:
    # `ToolCallKnowledge` is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge


class AntigravityCliConverter(HarnessToolCallConverter):
    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        args = harness_tool_call.args
        if harness_tool_call.tool.name == "write_file":
            return _write_action_from_arguments(args)
        if harness_tool_call.is_harness_message:
            return action_from_harness_message_result(tool_call_result)
        return _manage_task_action_from_arguments(args)


def _write_action_from_arguments(args: dict[str, Any]) -> ToolCallAction:
    """Build the action of a `write_file` call, an edit that keeps the old text when `Append` is true and a write of the whole file otherwise.

    An appending write adds `Content` after what the file holds, which the call does not show, so it is an `EditFileAction` without the text it replaces.
    A `Path` or `Content` that is no text leaves its field empty, as for a tool with a label.
    """
    path = field_value_from_argument("path", args.get("Path"))
    content = field_value_from_argument("content", args.get("Content"))
    if args.get("Append") is True:
        return EditFileAction(path, None, content)
    return WriteFileAction(path, content)


def _manage_task_action_from_arguments(args: dict[str, Any]) -> ToolCallAction:
    """Build the action of a `manage_task` call from its `Action` argument, a poll of the task `TaskId` names for `status`, `kill` and `send_input`.

    A `list` reads only the harness's list of its tasks, and any other `Action` is one the harness refused, e.g. `kill_all`.
    The task ids of `run_command` and `schedule` are one sequence per conversation, e.g. `<conversation id>/task-23`, so a command handle never names the task of another call.
    """
    handles = handles_from_ids(ExecutionHandleKind.COMMAND, args.get("TaskId"))
    match args.get("Action"):
        case "status":
            return PollAction(handles)
        case "kill":
            return PollAction(handles, terminate=True)
        case "send_input":
            return PollAction(
                handles, field_value_from_argument("input", args.get("Input"))
            )
        case "list":
            return OtherAction()
        case _:
            return UnknownAction()
