"""Convert tool calls in trajectories to common types."""

from pathlib import Path

from tb_internet_use.parse.toolcall.atif_reader import read_trial_tool_calls
from tb_internet_use.parse.toolcall.catalog_loader import (
    DEFERRED,
    action_from_label,
    tool_catalog,
)
from tb_internet_use.parse.toolcall.harnesses import converter_for
from tb_internet_use.parse.toolcall.harnesses.base import HarnessToolCallConverter
from tb_internet_use.parse.toolcall.model import RawToolCall, ToolCall, UnknownAction


def convert_trial(trial_dir: Path) -> list[ToolCall]:
    """Convert every tool call of one trial. Empty when its trajectory cannot be read."""
    trial = read_trial_tool_calls(trial_dir)
    return [convert_call(raw, converter_for(raw.tool.harness)) for raw in trial.calls]


def convert_call(raw: RawToolCall, converter: HarnessToolCallConverter) -> ToolCall:
    """Convert one tool call in the trajectory to common ToolCall type."""

    # Convert tool call output
    output = None if raw.result is None else converter.parse_output(raw, raw.result)

    # Convert tool call action
    label = tool_catalog().get(raw.tool)
    if label is None:
        action = UnknownAction()
    elif label.action_type == DEFERRED:
        action = converter.deferred_action(raw, output)
    else:
        action = action_from_label(label, raw.args)
        action = converter.refine_action(raw, action, output)
    return ToolCall(raw, action, output)
