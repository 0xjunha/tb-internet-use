"""Convert tool calls in trajectories to common types."""

from pathlib import Path
from typing import Any

from tb_internet_use.toolcall.atif_reader import read_trial_tool_calls
from tb_internet_use.toolcall.catalog_loader import (
    ACTION_CLASSES,
    DEFERRED,
    ToolLabel,
    load_catalog,
)
from tb_internet_use.toolcall.harnesses import converter_for
from tb_internet_use.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.toolcall.model import (
    Action,
    ExecutionHandle,
    ExecutionHandleKind,
    RawToolCall,
    ToolCall,
    UnknownAction,
)

_CATALOG = load_catalog()


def _field_value(field_name: str, value: Any) -> Any:
    """Turn an argument in the trajectory into the type of its Action field."""
    match field_name:
        case "queries" | "urls":
            return (value,)
        case "handles":
            ids = value if isinstance(value, list) else [value]
            return tuple(
                ExecutionHandle(ExecutionHandleKind.UNKNOWN, str(handle_id))
                for handle_id in ids
                if handle_id != ""
            )
        case "input":
            return value or None
        case "offset" | "limit":
            return value if isinstance(value, int) else None
        case _:
            return value


def _action_from_label(label: ToolLabel, args: dict[str, Any]) -> Action:
    """Build a tool's Action from the arguments that the catalog maps."""
    fields = {
        label.arg_fields[arg_name]: _field_value(label.arg_fields[arg_name], value)
        for arg_name, value in args.items()
        if arg_name in label.arg_fields
    }
    return ACTION_CLASSES[label.action_type](**fields)


def convert_call(raw: RawToolCall, converter: HarnessToolCallConverter) -> ToolCall:
    """Convert one tool call in the trajectory to common ToolCall type."""

    # Convert tool call output
    output = None if raw.result is None else converter.parse_output(raw, raw.result)

    # Convert tool call action
    label = _CATALOG.get(raw.tool)
    if label is None:
        action = UnknownAction()
    elif label.action_type == DEFERRED:
        action = converter.deferred_action(raw, output)
    else:
        action = _action_from_label(label, raw.args)
        action = converter.refine_action(raw, action, output)
    return ToolCall(raw, action, output)


def convert_trial(trial_dir: Path) -> list[ToolCall]:
    """Convert every tool call of one trial. Empty when its trajectory cannot be read."""
    trial = read_trial_tool_calls(trial_dir)
    return [convert_call(raw, converter_for(raw.tool.harness)) for raw in trial.calls]
