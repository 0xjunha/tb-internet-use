"""Build the `ToolCallAction` of one tool call from the label of its tool and its arguments."""

from collections import Counter
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call._convert_parsed_shell_texts import (
    convert_parsed_shell_texts,
)
from tb_internet_use.tool_call.model import (
    DEFERRED,
    TOOL_CALL_ACTION_CLASSES,
    ExecutionHandleKind,
    HarnessToolCall,
    HarnessToolLabel,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
    UnknownHarnessToolLabel,
    handles_from_ids,
    strings_from_values,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

    # `harnesses/codex.py` imports this module, so importing the converters here when the module runs would be a cycle.
    from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
        HarnessToolCallConverter,
    )


def convert_tool_call_action(
    harness_tool_call: HarnessToolCall,
    tool_call_result: ToolCallResult | None,
    converter: HarnessToolCallConverter,
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallAction:
    """Build the `ToolCallAction` of one call from the label of its tool, its arguments and its converted result.

    A tool without a label gives `UnknownAction`.
    A tool labeled `DEFERRED` gets its action from the converter of its harness.
    Any other tool gets it from the label and the arguments, and the converter then fills what the label cannot express.
    Each command string of the action, e.g. of a Claude Code `Bash` call or of a step of a Codex `exec` script, is then split into commands.
    """
    label = knowledge.harness_tool_label(
        harness_tool_call.tool, harness_tool_call.args.keys()
    )
    action: ToolCallAction
    if isinstance(label, UnknownHarnessToolLabel):
        action = UnknownAction()
    elif label.action_type == DEFERRED:
        action = converter.action_of_deferred_tool(
            harness_tool_call, tool_call_result, knowledge=knowledge
        )
    else:
        action = converter.refine_action(
            harness_tool_call,
            action_from_label(label, harness_tool_call.args),
            tool_call_result,
            label,
        )
    return convert_parsed_shell_texts(
        action, judgment_rule_use_counts=judgment_rule_use_counts
    )


def action_from_label(label: HarnessToolLabel, args: dict[str, Any]) -> ToolCallAction:
    """Build a tool's `ToolCallAction` from the arguments that its label maps to action fields.

    A label can map two arguments to one field, e.g. `to` and `recipient` of Claude Code `SendMessage`, which both name the subagent.
    When a call has both, a field of several values takes the values of both, in the order of the arguments and without repeated ones.
    Any other field holds one value, so two arguments that give it different values make the call an `UnknownAction` and neither value is dropped unseen.
    """
    field_values: dict[str, Any] = {}
    for argument_name, argument_value in args.items():
        field_name = label.action_field_by_argument_name.get(argument_name)
        if field_name is None:
            continue
        value = _field_value_from_argument(field_name, argument_value)
        if field_name not in field_values:
            field_values[field_name] = value
        # `_field_value_from_argument` gives a tuple for a field of several values and never for another field.
        elif isinstance(value, tuple):
            both = (*field_values[field_name], *value)
            field_values[field_name] = tuple(dict.fromkeys(both))
        elif value != field_values[field_name]:
            return UnknownAction()
    return TOOL_CALL_ACTION_CLASSES[label.action_type](**field_values)


def _field_value_from_argument(field_name: str, value: Any) -> Any:
    """Turn an argument in the trajectory into the type of its `ToolCallAction` field.

    An argument of another type than its field leaves the field empty, since the harness may not have read it as the text or number the field holds.
    E.g. Codex rejects an `exec_command` whose `cmd` is a list of words with `failed to parse function arguments`, so the call ran no command line.
    """
    match field_name:
        case "queries" | "urls" | "paths":
            return strings_from_values(value)
        case "handles":
            return handles_from_ids(ExecutionHandleKind.UNKNOWN, value)
        case "input":
            return value if isinstance(value, str) and value else None
        case "offset" | "limit":
            return value if isinstance(value, int) else None
        case "command_str" | "path" | "content" | "old" | "new":
            return value if isinstance(value, str) else None
        case _:
            return value
