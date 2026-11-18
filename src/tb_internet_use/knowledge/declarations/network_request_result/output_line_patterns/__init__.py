"""Collect the tables of output line patterns, one for program output and one for web tool results."""

from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns.program_output import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
)
from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns.web_tool_result import (
    WEB_TOOL_RESULT_LINE_PATTERNS,
)
from tb_internet_use.knowledge.output_line_pattern_declaration import (
    OutputLinePatternTable,
)

# Every table, in the order of the review record.
OUTPUT_LINE_PATTERN_TABLES: tuple[OutputLinePatternTable, ...] = (
    PROGRAM_OUTPUT_LINE_PATTERNS,
    WEB_TOOL_RESULT_LINE_PATTERNS,
)
