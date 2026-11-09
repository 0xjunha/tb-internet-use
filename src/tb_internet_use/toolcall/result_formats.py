"""Build a ToolCallOutput from a tool result by matching it against the result formats its harness declares.

Terms and the overall flow are in toolcall/README.md.
"""

import functools
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal, Protocol

from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
    ToolCallOutput,
    UnmatchedFormat,
    handles_from_ids,
)

# The `tool_output_text` of a result whose tool showed no output, such as one whose
# format has no tool output placeholder.
_NO_OUTPUT_TEXT = ""

# Matched values with these names fill ToolCallOutput fields. Other names fill none.
#   tool_output       tool_output_text
#   handle            handles, one id
#   handles           handles, a list of ids from JSON or one id from a template
#   handle_kind_name  the kind of the handles, through `handle_kind_by_name` (JSON only)
#   exit_code         exit_code
#   http_status       http_status
#   output_path       output_path
#   is_truncated      is_truncated, a bool (JSON only)
# What every result of a format shares, such as `status`, is a field of the format.
# What every call of a tool shares, such as `stop_tools`, is an attribute of its converter.

# values of the placeholders or JSON paths that matched
type MatchedValues = Mapping[str, Any]
# represents one JSON object
type JsonObject = Mapping[str, Any]


class HarnessResultFormat[AnnotatedOutputT](Protocol):
    """Shared protocol for different harness result formats (text, JSON)."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> ExecutionStatus: ...

    @property
    def is_truncated(self) -> bool | None: ...

    @property
    def no_tool_output_text(self) -> bool: ...

    def match(self, annotated_output: AnnotatedOutputT) -> MatchedValues | None:
        """Return the values of its placeholders or JSON paths if the annotated output has this format, else None."""
        ...

    def handle_kind_of(self, values: MatchedValues) -> ExecutionHandleKind:
        """The kind of the handles this result gives."""
        ...

    def is_truncated_of(self, values: MatchedValues) -> bool | None:
        """Whether the tool output is truncated, None when the result does not tell."""
        ...

    def tool_output_text_of(self, values: MatchedValues) -> str | None:
        """Return `ToolCallOutput.tool_output_text`, built from the matched values.

        It is the value named `tool_output`, or what `text_from_matched_values` builds.
        It is `_NO_OUTPUT_TEXT` when the tool showed no output, and None in the cases
        that `ToolCallOutput.tool_output_text` names.
        """
        ...


# Template regexes

# The regex of each placeholder type. A lazy type takes as little as it can, so it
# ends where the next fixed text of the template starts.
PLACEHOLDER_TYPE_PATTERNS = {
    # a whole number, with or without a minus sign
    "int": r"-?\d+",
    # a whole number without a sign, e.g. after a fixed minus sign
    "uint": r"\d+",
    # Letters, digits, `_` and `-`, with dots inside but not at the end, e.g. a handle.
    "id": r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*",
    # lazy, without spaces, e.g. a path
    "word": r"\S+?",
    # lazy, within one line
    "line": r"[^\n]*?",
    # the whole rest of the line
    "rest_of_line": r"[^\n]*",
    # lazy, within one line, never crossing `[` or `]`
    "line_without_brackets": r"[^\n\[\]]*?",
    # lazy, across lines
    "text": r"[\s\S]*?",
    # A file listing with a line number before every line, e.g. "12\tcode" or " 12|code".
    "numbered_tab": r"(?:[ ]*\d+\t[^\n]*\n)*(?:[ ]*\d+(?:\t[^\n]*)?)?\n?",
    "numbered_pipe": r"(?:[ ]*\d+\|[^\n]*\n)*(?:[ ]*\d+(?:\|[^\n]*)?)?\n?",
    # Lines of which some start with a line number and "→", e.g. every tenth line,
    # always with the first.
    "partly_numbered_arrow": r"[ ]*\d+→[\s\S]*?",
}
# The placeholder types that can take several lines.
MULTILINE_PLACEHOLDER_TYPES = (
    "text",
    "numbered_tab",
    "numbered_pipe",
    "partly_numbered_arrow",
)

# For the placeholder types that carry line numbers, the text after each number.
# `tool_output_text_of` removes the numbers from the tool output.
_LINE_NUMBER_SEPARATOR_BY_TYPE = {
    "numbered_tab": "\t",
    "numbered_pipe": "|",
    "partly_numbered_arrow": "→",
}

# A `{name:type}` placeholder in a template.
PLACEHOLDER_REGEX = re.compile(r"\{(\w+):(\w+)\}")


@functools.cache
def template_regex(template: str) -> re.Pattern[str]:
    """The regex of a template or a part of one, with a named group per placeholder.

    It is not anchored, so a caller picks fullmatch, match or search.
    """
    parts: list[str] = []
    pos = 0
    for placeholder in PLACEHOLDER_REGEX.finditer(template):
        parts.append(re.escape(template[pos : placeholder.start()]))
        parts.append(
            f"(?P<{placeholder[1]}>{PLACEHOLDER_TYPE_PATTERNS[placeholder[2]]})"
        )
        pos = placeholder.end()
    parts.append(re.escape(template[pos:]))
    return re.compile("".join(parts))


@functools.cache
def _placeholder_types(template: str) -> dict[str, str]:
    """The type of each placeholder of a template, by name."""
    return {p[1]: p[2] for p in PLACEHOLDER_REGEX.finditer(template)}


# Text helpers, shared with the harness converters.


def strip_line_numbers(listing: str, separator: str, *, every_line: bool = True) -> str:
    """Remove the line numbers of a numbered file listing.

    In a listing numbered on every line, a line that is only a number is an empty line
    and loses the number too. In a partly numbered listing, such a line is content.
    """
    bare_number = "|$" if every_line else ""
    return re.sub(
        rf"^[ ]*\d+(?:{re.escape(separator)}{bare_number})",
        "",
        listing,
        flags=re.MULTILINE,
    )


def join_texts(texts: Iterable[str]) -> str | None:
    """Join separate texts with a blank line, each without its edge whitespace. None when all are empty."""
    return "\n\n".join(text.strip() for text in texts if text.strip()) or None


def join_content_items(items: Any) -> str | None:
    """The text of a list of content items (`{"type": "text", "text": ...}`). Images give nothing."""
    if not isinstance(items, list):
        return None
    return join_texts(
        str(item.get("text") or "")
        for item in items
        if isinstance(item, dict) and item.get("type") == "text"
    )


def join_text_parts(parts: Iterable[str]) -> str:
    """Join pieces of one output in order, starting a new line between them when needed."""
    joined = ""
    for part in parts:
        if joined and not joined.endswith("\n") and part:
            joined += "\n"
        joined += part
    return joined


@dataclass(frozen=True, slots=True)
class HarnessTextResultFormat:
    """A text format. Its template is an annotated output as in the trajectory, with a
    placeholder in place of each part that varies.

        template    = fixed text + placeholders
        placeholder = {name:type}

    - The fixed text must appear exactly as in the trajectory.
    - The placeholder named `tool_output` takes the tool output. Every other placeholder
      takes an annotation value. The value names at the top of this module fill
      `ToolCallOutput` fields, e.g. `handle` fills `handles`. Other names, such as
      `rest`, fill none.
    - The type says which characters the placeholder may take, see
      `PLACEHOLDER_TYPE_PATTERNS`. A lazy type stops at the next fixed text.
    - The template is matched against the whole annotated output, from its first
      character to its last.

    Example: Devin `exec`, format `exited` in harnesses/devin.py, with made-up values.

        template          Output from command in shell {handle:id}:
                          {tool_output:text}
                          Exit code: {exit_code:int}

        annotated output  Output from command in shell 3:
                          hello
                          Exit code: 0

        matched values    handle="3"  tool_output="hello"  exit_code="0"

        ToolCallOutput    tool_output_text="hello"  exit_code=0  execution_status=finished
                          handles=(ExecutionHandle(COMMAND, "3"),)

    Matched values are strings. When the template has no `tool_output` placeholder,
    `tool_output_text` is "" unless `text_from_matched_values` builds it. The field
    comments below cover the rest.
    """

    name: str
    template: str
    # The execution status of every result of this format.
    status: ExecutionStatus
    _: KW_ONLY
    # Whether every result of this format has a truncated tool output. None when the
    # format does not tell.
    is_truncated: bool | None = None
    # The kind of every handle this format gives.
    fixed_handle_kind: ExecutionHandleKind = ExecutionHandleKind.COMMAND
    # Builds text from the placeholders.
    text_from_matched_values: Callable[[MatchedValues], str | None] | None = None
    # The trajectory holds no text of what the tool returned, such as an image.
    # `tool_output_text` is then None, not "".
    no_tool_output_text: bool = False
    # Harness text left inside a tool output that the harness cut, as a template
    # part. When `is_truncated` is None, a tool output holding it is truncated.
    truncation_marker: str | None = None

    def match(self, annotated_output: str) -> MatchedValues | None:
        # The fixed text must be exactly as in the trajectory,
        # and each placeholder becomes a named group.
        found = template_regex(self.template).fullmatch(annotated_output)
        # Each group gives the value of its placeholder.
        return found.groupdict() if found else None

    def handle_kind_of(self, values: MatchedValues) -> ExecutionHandleKind:
        return self.fixed_handle_kind

    def is_truncated_of(self, values: MatchedValues) -> bool | None:
        if self.is_truncated is not None or self.truncation_marker is None:
            return self.is_truncated
        marker = template_regex(self.truncation_marker)
        return True if marker.search(str(values.get("tool_output", ""))) else None

    def tool_output_text_of(self, values: MatchedValues) -> str | None:
        if self.no_tool_output_text:
            return None
        if self.text_from_matched_values is not None:
            return self.text_from_matched_values(values)
        if "tool_output" not in values:
            return _NO_OUTPUT_TEXT
        text = str(values["tool_output"])
        placeholder_type = _placeholder_types(self.template).get("tool_output", "")
        separator = _LINE_NUMBER_SEPARATOR_BY_TYPE.get(placeholder_type)
        if separator is None:
            return text
        every_line = placeholder_type != "partly_numbered_arrow"
        return strip_line_numbers(text, separator, every_line=every_line)


@dataclass(frozen=True, slots=True)
class HarnessNotice:
    """A notice and the edge of the result the harness inserts it at. Its template is
    matched like a text format's.

    It is cut only at that edge. The same text inside a tool output, such as file
    contents, must stay.

    Example: Grok Build adds this completion notice at the end of a result, in
    harnesses/grok_build.py.

        HarnessNotice(
            "notification_bare",
            "<system-reminder>{notice:text}</system-reminder>",
            at="end",
        )
    """

    name: str
    template: str
    # In the trajectories, the harness inserts this notice at this edge of the result.
    at: Literal["start", "end"]


def _notice_at_edge(notice: HarnessNotice, text: str) -> re.Match[str] | None:
    """The notice at the start of the text, or the last notice that ends exactly at its end."""
    pattern = template_regex(notice.template)
    if notice.at == "start":
        return pattern.match(text)
    last = None
    for found in pattern.finditer(text):
        if found.end() == len(text):
            last = found
    return last


def _json_value(annotated_output: JsonObject, path: str) -> tuple[bool, Any]:
    """Follow a dotted path and return (present, value)."""
    value: Any = annotated_output
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return False, None
        value = value[key]
    return True, value


def json_tool_output_text(values: MatchedValues) -> str:
    """The value named `tool_output` as text, the default of a JSON format. "" when there is none."""
    text = values.get("tool_output")
    return _NO_OUTPUT_TEXT if text is None else _json_text(text)


def _json_text(value: Any) -> str:
    """A JSON value as text. A string stays as it is, and any other value becomes JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _has_path(annotated_output: JsonObject, path: str) -> bool:
    """Whether the dotted path leads to a value."""
    return _json_value(annotated_output, path)[0]


@dataclass(frozen=True, slots=True)
class JsonCondition:
    """A test on one JSON value, e.g. `returncode < 0`."""

    path: str
    op: Literal["==", "!=", "<", ">", "startswith", "!startswith", "contains"]
    value: Any

    def holds(self, annotated_output: JsonObject) -> bool:
        present, actual = _json_value(annotated_output, self.path)
        if not present:
            return False
        match self.op:
            case "==":
                return actual == self.value
            case "!=":
                return actual != self.value
            case "<":
                return isinstance(actual, (int, float)) and actual < self.value
            case ">":
                return isinstance(actual, (int, float)) and actual > self.value
            case "startswith":
                return isinstance(actual, str) and actual.startswith(self.value)
            case "!startswith":
                return isinstance(actual, str) and not actual.startswith(self.value)
            case "contains":
                return isinstance(actual, str) and self.value in actual


@dataclass(frozen=True, slots=True)
class HarnessJsonResultFormat:
    """A JSON format. The annotated output is a JSON object and the format tells it apart
    by the JSON paths it has.

    - A JSON path is dotted, such as `success.exitCode`.
    - The object has this format when every path in `present_paths` is in it, no path in
      `absent_paths` is, and `condition` holds if there is one. Keys the format does
      not name are ignored.
    - `value_paths` names each value and the JSON path it is read from. The value named
      `tool_output` is the tool output. Every other value is an annotation value, and
      the value names at the top of this module fill `ToolCallOutput` fields.

    Example: Cursor CLI `shellToolCall`, format `exited` in harnesses/cursor_cli.py, with made-up values.
    (The object in the trajectory has more keys than shown)

        format            present_paths=("success.exitCode",)
                          absent_paths=("success.shellId", "success.outputLocation")
                          value_paths={"tool_output": "success.interleavedOutput",
                                       "exit_code": "success.exitCode"}

        annotated output  {"success": {"exitCode": 0, "interleavedOutput": "hello"}}

        matched values    tool_output="hello"  exit_code=0

        ToolCallOutput    tool_output_text="hello"  exit_code=0  execution_status=finished

    Matched values keep their JSON types. A tool output that is not a string is kept as JSON text.
    """

    name: str
    # The execution status of every result of this format.
    status: ExecutionStatus
    # Each value name and the JSON path it is read from. Several paths give the
    # parts of one tool output in order, or one handle each for `handles`. Missing
    # and null parts are left out.
    value_paths: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    _: KW_ONLY
    # JSON paths that every result of this format has.
    present_paths: tuple[str, ...] = ()
    # JSON paths that no result of this format has.
    absent_paths: tuple[str, ...] = ()
    # A test on one JSON value that every result of this format passes.
    condition: JsonCondition | None = None
    # Whether every result of this format has a truncated tool output. None takes it
    # from the value named `is_truncated`, if there is one.
    is_truncated: bool | None = None
    # The kind of every handle this format gives, unless `handle_kind_by_name` is set.
    fixed_handle_kind: ExecutionHandleKind = ExecutionHandleKind.COMMAND
    # The handle kind for each kind name read as `handle_kind_name`, when the result
    # names the kind.
    handle_kind_by_name: Mapping[str, ExecutionHandleKind] = field(default_factory=dict)
    # Builds text from the matched values.
    text_from_matched_values: Callable[[MatchedValues], str | None] | None = None
    # As for a text format, e.g. for a file kept only as a blob id.
    no_tool_output_text: bool = False

    def match(self, annotated_output: JsonObject) -> MatchedValues | None:
        # The paths and the condition decide whether the result has this format.
        if not all(_has_path(annotated_output, path) for path in self.present_paths):
            return None
        if any(_has_path(annotated_output, path) for path in self.absent_paths):
            return None
        if self.condition is not None and not self.condition.holds(annotated_output):
            return None
        # Read each value from its JSON paths.
        values: dict[str, Any] = {}
        for name, paths in self.value_paths.items():
            if isinstance(paths, str):
                present, value = _json_value(annotated_output, paths)
                if present:
                    values[name] = value
            else:  # the parts of one tool output in order, or one handle each
                found = (_json_value(annotated_output, path) for path in paths)
                parts = [value for _, value in found if value is not None]
                values[name] = (
                    join_text_parts(map(_json_text, parts))
                    if name == "tool_output"
                    else parts
                )
        return values

    def handle_kind_of(self, values: MatchedValues) -> ExecutionHandleKind:
        if not self.handle_kind_by_name:
            return self.fixed_handle_kind
        return self.handle_kind_by_name.get(
            str(values.get("handle_kind_name")), ExecutionHandleKind.UNKNOWN
        )

    def is_truncated_of(self, values: MatchedValues) -> bool | None:
        if self.is_truncated is not None:
            return self.is_truncated
        truncated = values.get("is_truncated")
        return truncated if isinstance(truncated, bool) else None

    def tool_output_text_of(self, values: MatchedValues) -> str | None:
        if self.no_tool_output_text:
            return None
        if self.text_from_matched_values is not None:
            return self.text_from_matched_values(values)
        return json_tool_output_text(values)


@dataclass(frozen=True, slots=True)
class HarnessResultFormatList[AnnotatedOutputT]:
    """One tool's result formats and the notices its results may carry. A converter
    declares one per tool in `text_formats` or `json_formats`.

    The first format that matches a result is the result's format, so more specific
    formats come first.
    """

    # Every result format this tool has in the trajectories, more specific ones first.
    formats: tuple[HarnessResultFormat[AnnotatedOutputT], ...]
    _: KW_ONLY
    # Every notice the harness may add to this tool's results.
    notices: tuple[HarnessNotice, ...] = ()

    def match(
        self, annotated_output: AnnotatedOutputT
    ) -> tuple[HarnessResultFormat[AnnotatedOutputT], MatchedValues] | None:
        for fmt in self.formats:
            values = fmt.match(annotated_output)
            if values is not None:
                return fmt, values
        return None

    def strip_notices(self, raw_text: str) -> tuple[str, list[str]]:
        """Cut the notices off the edges of the raw text. Returns the annotated output and the cut notices' names, in cut order."""
        text = raw_text
        cut_names: list[str] = []
        while True:
            for notice in self.notices:
                found = _notice_at_edge(notice, text)
                if found:
                    cut_names.append(notice.name)
                    text = text[: found.start()] + text[found.end() :]
                    break
            else:
                return text, cut_names


def _handles(
    kind: ExecutionHandleKind, values: MatchedValues
) -> tuple[ExecutionHandle, ...]:
    return handles_from_ids(kind, values.get("handle")) + handles_from_ids(
        kind, values.get("handles")
    )


def _int_value(values: MatchedValues, name: str) -> int | None:
    value = values.get(name)
    if value is None or isinstance(value, bool):
        return None
    return int(value) if isinstance(value, (int, str)) else None


def _build_output(
    fmt: HarnessResultFormat[Any], values: MatchedValues
) -> ToolCallOutput:
    """Turn a matched format and its matched values into common types."""
    return ToolCallOutput(
        tool_output_text=fmt.tool_output_text_of(values),
        execution_status=fmt.status,
        exit_code=_int_value(values, "exit_code"),
        http_status=_int_value(values, "http_status"),
        handles=_handles(fmt.handle_kind_of(values), values),
        output_path=str(values["output_path"]) if values.get("output_path") else None,
        is_truncated=fmt.is_truncated_of(values),
        harness_result_format=MatchedFormat(fmt.name),
    )


def _unparsed_output(
    tool_result_raw_text: str | None, harness_result_format: UnmatchedFormat
) -> ToolCallOutput:
    """A ToolCallOutput that keeps the raw text as `tool_output_text`, for a result no format parsed."""
    return ToolCallOutput(
        tool_output_text=tool_result_raw_text,
        harness_result_format=harness_result_format,
    )


def annotated_output_of(
    tool_result_raw_text: str | None,
    tool_result_json: JsonObject | None,
    selected_formats: HarnessResultFormatList[Any],
) -> tuple[str | JsonObject, list[str]] | None:
    """The annotated output and the names of the notices cut from it.

    It is the JSON object, or the raw text without its notices. None when the
    trajectory has neither.
    """
    if tool_result_json is not None:
        return tool_result_json, []
    if tool_result_raw_text is None:
        return None
    return selected_formats.strip_notices(tool_result_raw_text)


def parse_output_with_formats(
    tool_result_raw_text: str | None,
    tool_result_json: JsonObject | None,
    selected_formats: HarnessResultFormatList[Any] | None,
) -> ToolCallOutput:
    """Parse a tool result into a ToolCallOutput by matching its annotated output against the selected formats."""

    if selected_formats is None:
        return _unparsed_output(tool_result_raw_text, UnmatchedFormat.SKIPPED)

    annotated = annotated_output_of(
        tool_result_raw_text, tool_result_json, selected_formats
    )
    if annotated is None:
        # The tool has formats, but the trajectory has nothing to match.
        return _unparsed_output(tool_result_raw_text, UnmatchedFormat.UNKNOWN)

    # The first format that matches wins.
    found = selected_formats.match(annotated[0])
    if found is None:
        return _unparsed_output(tool_result_raw_text, UnmatchedFormat.UNKNOWN)

    fmt, values = found
    return _build_output(fmt, values)
