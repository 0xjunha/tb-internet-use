"""Convert the tool calls of Devin, reading a negative exit code by a judgment rule."""

from collections import Counter
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_negative_exit_code_as_killed,
)
from tb_internet_use.tool_call.model import HarnessToolCall, ToolCallResult

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge


class DevinConverter(HarnessToolCallConverter):
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
        return treat_negative_exit_code_as_killed(
            tool_call_result, use_counts=judgment_rule_use_counts
        )
