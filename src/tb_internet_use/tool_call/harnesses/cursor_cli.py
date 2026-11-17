"""Convert the tool calls of Cursor CLI, deciding the action of a wrapped MCP tool."""

from typing import TYPE_CHECKING

from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    HarnessToolCall,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
    WebFetchAction,
    strings_from_values,
)

if TYPE_CHECKING:
    # The door is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge


class CursorCliConverter(HarnessToolCallConverter):
    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        if (
            harness_tool_call.tool.name == "mcpToolCall"
            and harness_tool_call.args.get("toolName") == "browser_navigate"
        ):
            args = harness_tool_call.args.get("args")
            return WebFetchAction(
                strings_from_values(args.get("url") if isinstance(args, dict) else None)
            )
        # A wrapped MCP tool that this converter does not know does something it cannot tell, e.g. `browser_click`.
        return UnknownAction()
