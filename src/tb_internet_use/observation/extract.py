"""Extract the observations in each call's result, i.e. the HTTP status field and the output lines that show how far a request got."""

import json
import re
from collections.abc import Iterator

from tb_internet_use.network.hosts import host_from_name
from tb_internet_use.network.package_names import normalized_package_names
from tb_internet_use.observation.line_patterns import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
    WEB_TOOL_RESULT_LINE_PATTERNS,
    LinePatternTable,
)
from tb_internet_use.observation.model import (
    HttpStatusField,
    Observation,
    ObservationKind,
    OutputLine,
)
from tb_internet_use.shell.programs import normalized_program_name
from tb_internet_use.toolcall.model import (
    ToolCall,
    ToolCallKey,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    action_steps_with_index,
)

# The trailing number of a named group, which `line_patterns` adds to keep names unique, e.g. 0 in host0.
_GROUP_NUMBER = re.compile(r"\d+$")
# An ANSI control sequence of the CSI form, i.e. ESC and `[`, then parameter and intermediate bytes and a final byte, e.g. the color code `\x1b[32m`.
_ANSI_CSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def extract_observations(call: ToolCall) -> tuple[Observation, ...]:
    """Extract the observations in one call's HTTP status field and tool output lines, at most one per line.

    The result of a call made of one or more web tool actions and nothing else is page text, so its lines are read with the web tool result table.
    """
    output = call.output
    if output is None:
        return ()
    key = call.raw.key
    observations: list[Observation] = []
    if output.http_status is not None:
        observations.append(_http_status_observation(key, output.http_status))
    if output.tool_output_text:
        steps = [step for _, step in action_steps_with_index(call.action)]
        is_web_tool_result = bool(steps) and all(
            isinstance(step, (WebSearchAction, WebFetchAction, WebFindAction))
            for step in steps
        )
        table = (
            WEB_TOOL_RESULT_LINE_PATTERNS
            if is_web_tool_result
            else PROGRAM_OUTPUT_LINE_PATTERNS
        )
        for place, parts in _scanned_lines(output.tool_output_text):
            for part in parts:
                if table.any_row_regex.search(part) and (
                    observation := _line_observation(key, place, part, table)
                ):
                    observations.append(observation)
                    break
    return tuple(observations)


def _http_status_observation(call_key: ToolCallKey, http_status: int) -> Observation:
    """Make the observation of the HTTP status that a web fetch reports in its result."""
    return Observation(
        call=call_key,
        place=HttpStatusField(),
        kind=ObservationKind.HTTP_STATUS,
        printing_programs=frozenset(),
        is_printed_by_other_programs_too=False,
        host=None,
        package_names=frozenset(),
        missing_program=None,
        status_code=http_status,
    )


def _scanned_lines(tool_output_text: str) -> Iterator[tuple[OutputLine, list[str]]]:
    """List the lines of a tool output with their place, each split into its parts, a JSON object's `output` string read as the lines it holds.

    Codex scripts often print a step's result as one JSON line, e.g. `{"output": "Downloading x\\n...", "exit_code": 0}`.
    """
    for line_index, line in enumerate(tool_output_text.split("\n")):
        output_string = _json_output_string(line)
        if output_string is None:
            yield OutputLine(line_index, None), _line_parts(line)
            continue
        for index_in_string, inner_line in enumerate(output_string.split("\n")):
            yield (
                OutputLine(line_index, index_in_string),
                _line_parts(inner_line),
            )


def _json_output_string(line: str) -> str | None:
    """Take the `output` string of a line that is a JSON object, or None for any other line."""
    if not line.startswith("{") or '"output"' not in line:
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    output = value.get("output") if isinstance(value, dict) else None
    return output if isinstance(output, str) else None


def _line_parts(line: str) -> list[str]:
    """Split an output line at each `\\r` into parts without ANSI control sequences, the last part first.

    A `\\r` either lets progress output draw over the line, e.g. `Downloading x 10%\\rSuccessfully installed x-1.0`, where the last part is what a terminal shows,
    or ends a line in text joined without line breaks, e.g. `HTTP/1.1 200 OK\\rContent-Length: 9`, where every part is a line.
    Trying the parts from the last one serves both. Removing color codes, e.g. `\\x1b[32m`, lets rows that match at the start of a line match.
    The `\\r` at the end of a CRLF line ends no part.
    """
    return _ANSI_CSI_SEQUENCE.sub("", line.rstrip("\r")).split("\r")[::-1]


def _line_observation(
    call_key: ToolCallKey,
    place: OutputLine,
    line: str,
    table: LinePatternTable,
) -> Observation | None:
    """Make the observation of a line from the first table row that matches it, or None when no row does."""
    for pattern in table.rows:
        match = pattern.regex.search(line)
        if match is None:
            continue
        found = {
            _GROUP_NUMBER.sub("", name): value
            for name, value in match.groupdict().items()
            if value
        }
        return Observation(
            call=call_key,
            place=place,
            kind=pattern.kind,
            printing_programs=pattern.printing_programs,
            is_printed_by_other_programs_too=pattern.is_printed_by_other_programs_too,
            host=host_from_name(found["host"]) if "host" in found else None,
            package_names=normalized_package_names(found.get("packages", "")),
            missing_program=normalized_program_name(found["program"])
            if "program" in found
            else None,
            status_code=int(found["status_code"]) if "status_code" in found else None,
        )
    return None
