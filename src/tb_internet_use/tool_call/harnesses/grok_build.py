"""Convert the tool calls of Grok Build, reading the tasks of a wait on several tasks and the system reminders that report the end of a background task."""

import re
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
    action_from_harness_message_result,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_wait_on_several_tasks_as_their_shared_status,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessToolCall,
    MatchedFormat,
    ToolCallAction,
    ToolCallResult,
    handles_from_ids,
    join_text_parts,
)

if TYPE_CHECKING:
    # `ToolCallKnowledge` is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

S = ExecutionStatus

# The format of a wait on several tasks, named `multi_wait` in `knowledge/` for `get_command_or_subagent_output`.
_WAIT_ON_SEVERAL_TASKS_FORMAT = MatchedFormat("multi_wait")
# The line that starts the part of one task in the result, with the task id and its state.
_WAITED_TASK_LINE = re.compile(r"^--- Task (\S+) \[(\w+)\] ---$", re.MULTILINE)
# The rest of the part of one task after its task line, i.e. the command, which can take several lines, the duration, the exit code of a task that ended, the output, the note that Grok Build writes after the output of a task that still runs, and in the last part the line that counts the tasks that ended, e.g. `1/2 tasks completed (wait_all)`.
_WAITED_TASK_PART = re.compile(
    r"\nCommand: [\s\S]*?\nDuration: [\d.]+s\n(?:Exit Code: -?\d+\n)?"
    r"(?P<task_output>[\s\S]*?)"
    r"(?:\n\n(?:Waited the requested |Use timeout_ms to wait for completion\.)[^\n]*)?"
    r"\n*(?:\d+/\d+ tasks completed \(\w+\))?"
)
_STATUS_BY_WAITED_TASK_STATE = {
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
            _result_from_wait_on_several_tasks(
                tool_call_result, judgment_rule_use_counts=judgment_rule_use_counts
            )
            if tool_call_result.harness_result_format == _WAIT_ON_SEVERAL_TASKS_FORMAT
            else tool_call_result
        )

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        """Build the action of a `system-reminder` block, the only Deferred tool of Grok Build, a poll of the task whose end it reports."""
        return action_from_harness_message_result(tool_call_result)


def _result_from_wait_on_several_tasks(
    tool_call_result: ToolCallResult, *, judgment_rule_use_counts: Counter[str]
) -> ToolCallResult:
    """Fill the status, handles and tool output text of a wait on several tasks from the tasks it lists, the status by its judgment rule."""
    text = tool_call_result.tool_output_text or ""
    task_lines = list(_WAITED_TASK_LINE.finditer(text))
    status = treat_wait_on_several_tasks_as_their_shared_status(
        [task_line[2] for task_line in task_lines],
        _STATUS_BY_WAITED_TASK_STATE,
        use_counts=judgment_rule_use_counts,
    )
    handles = handles_from_ids(
        ExecutionHandleKind.COMMAND, [task_line[1] for task_line in task_lines]
    )
    return replace(
        tool_call_result,
        tool_output_text=_task_output_text_of(text, task_lines),
        execution_status=status,
        handles=handles,
    )


def _task_output_text_of(text: str, task_lines: list[re.Match[str]]) -> str:
    """Join the outputs of the waited tasks without what Grok Build writes around each, or give the text as it is when it has a part that is not laid out that way.

    The command of a task is no output of it, though it can hold what an output line holds, e.g. `HTTP/1.1 200` in `Command: curl -s http://localhost:5000/api/v1 | grep "HTTP/1.1 200"`.
    """
    if not task_lines or task_lines[0].start() != 0:
        return text
    part_ends = [task_line.start() for task_line in task_lines[1:]] + [len(text)]
    task_outputs: list[str] = []
    for task_line, part_end in zip(task_lines, part_ends, strict=True):
        task_part = _WAITED_TASK_PART.fullmatch(text, task_line.end(), part_end)
        if task_part is None:
            return text
        # The newlines that end an output separate it from the next part too.
        task_outputs.append(task_part["task_output"].rstrip("\n"))
    return join_text_parts(task_outputs)
