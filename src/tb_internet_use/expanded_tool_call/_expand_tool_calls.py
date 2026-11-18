"""Expand the tool calls of one trial into everything each call ran, where its output shows up and which later calls use the files it wrote."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.tool_call.model import ToolCall

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `expand_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
        ExpandedToolCallKnowledge,
    )


def expand_tool_calls(
    tool_calls: Sequence[ToolCall],
    *,
    knowledge: ExpandedToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> tuple[ExpandedToolCall, ...]:
    """Expand every tool call of one trial into an `ExpandedToolCall`, in the order of `tool_calls`, asking `knowledge` what each program does.

    Every use of a rule of `judgment_rules.py` adds one to `judgment_rule_use_counts` under the name of the rule.
    """
    raise NotImplementedError
