"""Convert the tool calls of Cursor CLI, deciding the action of an edit and of a wrapped MCP tool and marking a web search whose references point to saved pages as truncated."""

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from tb_internet_use.tool_call._convert_tool_call_action import (
    field_value_from_argument,
)
from tb_internet_use.tool_call.harnesses.harness_tool_call_converter import (
    HarnessToolCallConverter,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    HarnessToolCall,
    MatchedFormat,
    ToolCallAction,
    ToolCallResult,
    UnknownAction,
    WebFetchAction,
    WriteFileAction,
    strings_from_values,
)

if TYPE_CHECKING:
    # `ToolCallKnowledge` is passed in and named in annotations only, so that `convert_tool_calls` never loads `knowledge/` itself.
    from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
        JsonObject,
    )
    from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge

# The format of a web search with its references, named `results` in `knowledge/` for `webSearchToolCall`.
_WEB_SEARCH_RESULTS_FORMAT = MatchedFormat("results")
# Cursor CLI writes this in place of the text of a page that it saved to a file, in the `chunk` of a reference of a web search.
_SAVED_PAGE_CHUNK_START = "Full page text written to file: "


class CursorCliConverter(HarnessToolCallConverter):
    def convert_result(
        self,
        harness_tool_call: HarnessToolCall,
        tool_result: dict[str, Any],
        *,
        knowledge: ToolCallKnowledge,
        judgment_rule_use_counts: Counter[str],
    ) -> ToolCallResult:
        """Mark a web search as truncated when a reference holds only the file of a saved page, whose text the result then lacks."""
        tool_call_result = super().convert_result(
            harness_tool_call,
            tool_result,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        if (
            harness_tool_call.tool.name == "webSearchToolCall"
            and tool_call_result.harness_result_format == _WEB_SEARCH_RESULTS_FORMAT
            and _has_reference_of_saved_page(
                self.tool_result_json_of(harness_tool_call, tool_result)
            )
        ):
            return replace(tool_call_result, is_truncated=True)
        return tool_call_result

    def action_of_deferred_tool(
        self,
        harness_tool_call: HarnessToolCall,
        tool_call_result: ToolCallResult | None,
        *,
        knowledge: ToolCallKnowledge,
    ) -> ToolCallAction:
        """Decide the action of an `editToolCall`, which writes a new file or replaces text in a file, and of an `mcpToolCall`, which wraps any MCP tool."""
        if harness_tool_call.tool.name == "editToolCall":
            return _action_of_edit_tool_call(
                harness_tool_call.args,
                None
                if harness_tool_call.result is None
                else self.tool_result_json_of(
                    harness_tool_call, harness_tool_call.result
                ),
            )
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


def _action_of_edit_tool_call(
    args: dict[str, Any], tool_result_json: JsonObject | None
) -> WriteFileAction | EditFileAction:
    """Build the action of an `editToolCall`, a `WriteFileAction` of the whole file when the edit created the file, and else an `EditFileAction` of its new text without the text it replaced.

    The diff of the result tells that the edit created the file, and `streamContent` then holds the whole file, equal to `afterFullFileContent` in each of the 524 such results of the Cursor CLI trajectories of Terminal-Bench 3.0 and 4.0.
    """
    path = field_value_from_argument("path", args.get("path"))
    stream_content = field_value_from_argument("content", args.get("streamContent"))
    if _has_diff_from_dev_null(tool_result_json):
        return WriteFileAction(path, stream_content)
    return EditFileAction(path, new=stream_content)


def _has_diff_from_dev_null(tool_result_json: JsonObject | None) -> bool:
    """Tell whether the diff of an edit result starts from `/dev/null`, which Cursor CLI writes for a file that the edit created, e.g. `--- /dev/null` and then `+++ b//app/a.py`."""
    success = (tool_result_json or {}).get("success")
    diff = success.get("diffString") if isinstance(success, dict) else None
    return isinstance(diff, str) and diff.startswith("--- /dev/null\n")


def _has_reference_of_saved_page(tool_result_json: JsonObject | None) -> bool:
    """Tell whether a reference of a web search result holds, in place of the page text, only the file that Cursor CLI saved the page to, e.g. `Full page text written to file: /root/p.md`."""
    success = (tool_result_json or {}).get("success")
    references = success.get("references") if isinstance(success, dict) else None
    if not isinstance(references, list):
        return False
    chunks = [
        reference.get("chunk")
        for reference in references
        if isinstance(reference, dict)
    ]
    return any(
        isinstance(chunk, str) and chunk.startswith(_SAVED_PAGE_CHUNK_START)
        for chunk in chunks
    )
