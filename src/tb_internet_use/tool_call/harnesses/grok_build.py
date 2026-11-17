"""Convert the tool calls of Grok Build, reading the tasks of a wait on several tasks."""

import re
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_wait_on_several_tasks_as_their_shared_status,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessToolCall,
    MatchedFormat,
    ToolCallResult,
    handles_from_ids,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

S = ExecutionStatus

# The format of a wait on several tasks, declared in `knowledge/` for `get_command_or_subagent_output`.
_MULTI_WAIT_FORMAT = MatchedFormat("multi_wait")
_MULTI_WAIT_TASK = re.compile(r"^--- Task (\S+) \[(\w+)\] ---$", re.MULTILINE)
_MULTI_WAIT_STATES = {
    "completed": S.FINISHED,
    "failed": S.FINISHED,
    "running": S.RUNNING,
}


class GrokBuildConverter(HarnessToolCallConverter):
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
        return (
            _result_from_multi_wait(
                tool_call_result, judgment_rule_use_counts=judgment_rule_use_counts
            )
            if tool_call_result.harness_result_format == _MULTI_WAIT_FORMAT
            else tool_call_result
        )


def _result_from_multi_wait(
    tool_call_result: ToolCallResult, *, judgment_rule_use_counts: Counter[str]
) -> ToolCallResult:
    """Fill the status and handles of a multi-wait from the tasks it lists, the status by the judgment rule for a wait on several tasks."""
    tasks = _MULTI_WAIT_TASK.findall(tool_call_result.tool_output_text or "")
    status = treat_wait_on_several_tasks_as_their_shared_status(
        [state for _, state in tasks],
        _MULTI_WAIT_STATES,
        use_counts=judgment_rule_use_counts,
    )
    handles = handles_from_ids(ExecutionHandleKind.COMMAND, [i for i, _ in tasks])
    return replace(tool_call_result, execution_status=status, handles=handles)
