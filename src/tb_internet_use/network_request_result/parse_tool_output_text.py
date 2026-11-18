"""Split the `tool_output_text` of a call's result into its lines, each split again into the parts that a terminal draws over one another.

A Codex `exec` script often prints the result of a step as one JSON line, e.g. `{"chunk_id": "a1", "output": "Collecting x\\nDownloading x-1.0.whl", "exit_code": 0}`, so the lines of its `output` string are read in place of that line.
The `exit_code` of such a line is not read. Most `exec` scripts print no such line for a command step, or print the output of a step in another form, so a line cannot be tied to the step whose exit code it holds.
"""

import json
import re

from tb_internet_use.network_request_result.model import ToolOutputLine

# An ANSI control sequence of the CSI form, i.e. ESC and `[`, then parameter and intermediate bytes and a final byte, e.g. the color code `\x1b[32m` (ECMA-48 section 5.4).
_ANSI_CSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse_tool_output_text(tool_output_text: str) -> tuple[ToolOutputLine, ...]:
    """Split a tool output text at each `\\n` into lines, reading a JSON object line with an `output` string as the lines of that string.

    Any text can be split, so there is no text that this function cannot read.
    A line that only looks like JSON, e.g. `{not json`, stays one line of the text.
    """
    tool_output_lines: list[ToolOutputLine] = []
    for line_index, line in enumerate(tool_output_text.split("\n")):
        output_string = _output_string_of(line)
        if output_string is None:
            tool_output_lines.append(ToolOutputLine(line_index, None, _parts_of(line)))
            continue
        tool_output_lines.extend(
            ToolOutputLine(line_index, line_index_in_json_string, _parts_of(inner_line))
            for line_index_in_json_string, inner_line in enumerate(
                output_string.split("\n")
            )
        )
    return tuple(tool_output_lines)


def _output_string_of(line: str) -> str | None:
    """Take the `output` string of a line that is a JSON object, or None for any other line."""
    try:
        json_value = json.loads(line)
    except ValueError:
        return None
    output = json_value.get("output") if isinstance(json_value, dict) else None
    return output if isinstance(output, str) else None


def _parts_of(line: str) -> tuple[str, ...]:
    """Split a line at each `\\r` into parts without ANSI control sequences, the last part first.

    A `\\r` either lets progress output draw over the line, e.g. `Downloading x 10%\\rSuccessfully installed x-1.0`, where the last part is what a terminal shows, or ends a line in text joined without line breaks, e.g. `HTTP/1.1 200 OK\\rContent-Length: 9`, where every part is a line.
    Giving the parts from the last one serves both.
    Removing color codes, e.g. `\\x1b[32m`, lets a pattern that matches at the start of a line match.
    The `\\r` at the end of a CRLF line ends no part, also when a color code follows it, e.g. `Done\\r\\x1b[0m`.
    """
    return tuple(_ANSI_CSI_SEQUENCE.sub("", line).rstrip("\r").split("\r")[::-1])
