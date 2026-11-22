"""Declare the output line patterns of web tool results, whose lines no program prints.

A web tool result is page text, so only a page that a server gave in place of the content counts, e.g. a robot check.
"""

from tb_internet_use.knowledge.declarations.network_request_result.output_line_pattern_declaration import (
    OutputLinePattern,
    OutputLinePatternTable,
)
from tb_internet_use.network_request_result.model import OutputLineKind

WEB_TOOL_RESULT_LINE_PATTERNS = OutputLinePatternTable(
    "web_tool_result",
    (
        OutputLinePattern(
            name="robot_check",
            kind=OutputLineKind.SERVER_ANSWERED,
            printing_programs=frozenset(),
            is_printed_by_other_programs_too=False,
            alternatives=(r"not a robot",),
        ),
    ),
)
