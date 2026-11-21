"""Convert the tool calls of Muse Code, cutting the reminder that names the file of a truncated shell output."""

import re
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import HarnessToolCall, ToolCallResult

if TYPE_CHECKING:
    # `ToolCallKnowledge` is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

# Muse Code ends a truncated shell output with this reminder, which names the full output's file.
_SAVED_OUTPUT_REMINDER = re.compile(
    r"(?P<tool_output>[\s\S]*?)\n<system-reminder>\nFull output saved to: (?P<output_path>[^\n]*?)\n"
    r"Full output is longer than the visible window\.\n"
    r"Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output\.\n"
    r"</system-reminder>"
)

_SHELL_TOOLS = ("bash", "bash_input")


class MuseCodeConverter(HarnessToolCallConverter):
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
        text = tool_call_result.tool_output_text
        if harness_tool_call.tool.name not in _SHELL_TOOLS or not text:
            return tool_call_result
        found = _SAVED_OUTPUT_REMINDER.fullmatch(text)
        if found is None:
            return tool_call_result
        return replace(
            tool_call_result,
            tool_output_text=found["tool_output"],
            output_path=found["output_path"],
        )
