"""Convert the tool calls of one trial to common types."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.tool_call._convert_tool_call_action import (
    convert_tool_call_action,
)
from tb_internet_use.tool_call._convert_tool_call_result import (
    convert_tool_call_result,
)
from tb_internet_use.tool_call.harnesses import converter_for
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import HarnessToolCall, ToolCall

if TYPE_CHECKING:
    # `ToolCallKnowledge` is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge


def convert_tool_calls(
    harness_tool_calls: Sequence[HarnessToolCall],
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[ToolCall, ...]:
    """Convert every tool call read from one trial's trajectory to common types, asking `knowledge` what each harness tool does.

    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    """
    return tuple(
        convert_one_tool_call(
            harness_tool_call,
            converter_for(harness_tool_call.tool.harness),
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        for harness_tool_call in harness_tool_calls
    )


def convert_one_tool_call(
    harness_tool_call: HarnessToolCall,
    converter: HarnessToolCallConverter,
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCall:
    """Convert one tool call of the trajectory to a `ToolCall`, building its result first, since the action of a poll takes the handles that the result names."""
    tool_call_result = convert_tool_call_result(
        harness_tool_call,
        converter,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    action = convert_tool_call_action(
        harness_tool_call,
        tool_call_result,
        converter,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    return ToolCall(harness_tool_call, action, tool_call_result)
