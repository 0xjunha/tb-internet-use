"""Answer the questions of `decide_network_request_results` about output lines from the output line pattern declarations, counting every use of a pattern."""

from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
    WEB_TOOL_RESULT_LINE_PATTERNS,
)
from tb_internet_use.network_request_result.model import (
    OutputLineMeaning,
    UnknownOutputLineMeaning,
)

# The name of the folder of the output line pattern declarations, which the counts of their uses carry.
OUTPUT_LINE_PATTERNS_DECLARATIONS = "output_line_patterns"


class NetworkRequestResultKnowledge:
    """Door of `decide_network_request_results` to the outside knowledge, made for one trial and passed to `decide_network_request_results`, which asks it one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every declared pattern that answered.
    A line without a pattern is not counted, since an output line has no name, so a missing pattern cannot be told apart from a line that means nothing.
    """

    def __init__(self) -> None:
        self.uses = KnowledgeUses()

    def output_line_meaning(
        self, line: str, *, is_web_tool_result: bool
    ) -> OutputLineMeaning | UnknownOutputLineMeaning:
        """Answer what one output line means and which programs print it, from the first pattern that matches it, or `UnknownOutputLineMeaning` when no pattern does.

        `line` is one part of a line of a result, without ANSI control sequences, e.g. `Successfully installed x-1.0`.
        The result of a call made only of web tool actions is page text, so its lines are read with the web tool result patterns and no program output pattern.
        A matched line counts as a use of the row `(table, pattern)` under `OUTPUT_LINE_PATTERNS_DECLARATIONS`, e.g. `("program_output", "pip_already_satisfied")`.
        A line without a pattern gives `UnknownOutputLineMeaning` and is not counted, since an output line has no name that a missing pattern could be noticed for.
        """
        table = (
            WEB_TOOL_RESULT_LINE_PATTERNS
            if is_web_tool_result
            else PROGRAM_OUTPUT_LINE_PATTERNS
        )
        matched_output_line_pattern = table.matched_output_line_pattern_of(line)
        if matched_output_line_pattern is None:
            return UnknownOutputLineMeaning()
        row_key = (table.name, matched_output_line_pattern.output_line_pattern.name)
        self.uses.row_use_counts[OUTPUT_LINE_PATTERNS_DECLARATIONS, row_key] += 1
        return matched_output_line_pattern.output_line_meaning
