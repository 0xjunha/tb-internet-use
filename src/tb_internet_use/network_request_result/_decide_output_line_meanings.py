"""Decide the meaning of each output line in the result of one call, keeping the lines that an output line pattern fits with their place in the result."""

from typing import TYPE_CHECKING

from tb_internet_use.network_request_result.model import (
    OutputLineMeaning,
    OutputLineWithMeaning,
)
from tb_internet_use.network_request_result.parse_tool_output_text import (
    parse_tool_output_text,
)
from tb_internet_use.tool_call.model import ToolCall

if TYPE_CHECKING:
    # `NetworkRequestResultKnowledge` is passed in and named in annotations only, so that this module never loads `knowledge/` itself.
    from tb_internet_use.knowledge.network_request_result_knowledge import (
        NetworkRequestResultKnowledge,
    )


def decide_output_line_meanings(
    tool_call: ToolCall,
    *,
    is_web_tool_result: bool,
    knowledge: NetworkRequestResultKnowledge,
) -> tuple[OutputLineWithMeaning, ...]:
    """Decide the meaning of each line of the `tool_output_text` of a call's result, at most one per line, in the order of the lines.

    The parts of a line are asked of `NetworkRequestResultKnowledge` from the last one, and the first part that a pattern fits gives the meaning of the line.
    So `Downloading x 10%\\rSuccessfully downloaded x` means what its last part means, and `HTTP/1.1 200 OK\\rContent-Length: 9` what its first part means.
    `is_web_tool_result` says that the result is page text of a call made only of web tool actions, which `NetworkRequestResultKnowledge` reads with its own patterns.
    A line that no pattern fits gives nothing and `NetworkRequestResultKnowledge` counts nothing for it.
    A call without a result, or with a result that holds no text, gives no line.
    """
    result = tool_call.result
    if result is None or result.tool_output_text is None:
        return ()
    output_lines_with_meaning: list[OutputLineWithMeaning] = []
    for tool_output_line in parse_tool_output_text(result.tool_output_text):
        for part in tool_output_line.parts:
            output_line_meaning = knowledge.output_line_meaning(
                part, is_web_tool_result=is_web_tool_result
            )
            if isinstance(output_line_meaning, OutputLineMeaning):
                output_lines_with_meaning.append(
                    OutputLineWithMeaning(
                        showing_tool_call_key=tool_call.harness_tool_call.key,
                        line_index=tool_output_line.line_index,
                        line_index_in_json_string=tool_output_line.line_index_in_json_string,
                        output_line_meaning=output_line_meaning,
                    )
                )
                break
    return tuple(output_lines_with_meaning)
