"""Define the types that harness result formats are declared in, and match a tool result against them.

Terms and the overall flow are in the README of `tool_call/`.
"""

import functools
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal, Protocol

from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    UnmatchedFormat,
    join_text_parts,
)

# The `tool_output_text` of a result whose tool showed no output, such as one whose format has no tool output placeholder.
_NO_OUTPUT_TEXT = ""

# Matched values with these names fill ToolCallResult fields. Other names fill none.
#   tool_output       tool_output_text
#   handle            handles, one id
#   handles           handles, a list of ids from JSON or one id from a template
#   handle_kind_name  the kind of the handles, through `handle_kind_by_name` (JSON only)
#   exit_code         exit_code
#   http_status       http_status
#   output_path       output_path
#   is_truncated      is_truncated, a bool (JSON only)
# A format that gives `handle` or `handles` states the kind of its handles, and a format that gives neither states no kind.
# What every result of a format shares, such as `status`, is a field of the format.
# A format states its `status`, or names the `judgment_rule` that decides it when the result text does not say, never both.
# What every call of a tool shares, such as `stops_execution`, is a column of the harness tool catalog.

# values of the placeholders or JSON paths that matched
type MatchedValues = Mapping[str, Any]
# represents one JSON object
type JsonObject = Mapping[str, Any]


# The regex of each placeholder type. A lazy type takes as little as it can, so it ends where the next fixed text of the template starts.
PLACEHOLDER_TYPE_PATTERNS = {
    # a whole number, with or without a minus sign
    "int": r"-?\d+",
    # a whole number without a sign, e.g. after a fixed minus sign
    "uint": r"\d+",
    # a whole number with a minus sign, e.g. an exit code that only a negative value fits
    "negative_int": r"-\d+",
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
    # Lines of which some start with a line number and "→", e.g. every tenth line, always with the first.
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

# The matched value names that fill `ToolCallResult.handles`.
_HANDLE_VALUE_NAMES = frozenset({"handle", "handles"})

# A `{name:type}` placeholder in a template.
PLACEHOLDER_REGEX = re.compile(r"\{(\w+):(\w+)\}")


@dataclass(frozen=True, slots=True)
class HarnessToolResultDeclaration:
    """Declaration of the result formats of one harness tool, written in `knowledge/declarations/` and held by `ToolCallKnowledge` against the results of the tool.

    A tool has up to three lists, since a harness writes a result as text or as a JSON object.
    A harness can also mark a text result as an error and write it in other formats, e.g. Claude Code `Bash` writes `Exit code 1` before the output of a failed command only in a result marked as an error.
    """

    _: KW_ONLY
    # For a result that is text.
    text_formats: HarnessResultFormatList[str] | None = None
    # For a result that is a JSON object.
    json_formats: HarnessResultFormatList[JsonObject] | None = None
    # For a text result that the harness marked as an error, used in place of `text_formats`.
    text_formats_when_marked_as_error: HarnessResultFormatList[str] | None = None

    def harness_result_format_of(
        self,
        tool_result_raw_text: str | None,
        tool_result_json: JsonObject | None,
        *,
        is_marked_as_error: bool,
    ) -> MatchedHarnessResultFormat | UnmatchedFormat:
        """Find the first format of the picked list that one tool result matches, or the `UnmatchedFormat` of a result that matches none or has no list to try.

        The result is held against the list that `format_list_for_result` picks, as its JSON object or as its raw text without the notices of that list.
        """
        selected_format_list = self.format_list_for_result(
            tool_result_json, is_marked_as_error=is_marked_as_error
        )
        if isinstance(selected_format_list, UnmatchedFormat):
            return selected_format_list
        annotated = annotated_output_and_notice_names_of(
            tool_result_raw_text, tool_result_json, selected_format_list
        )
        if annotated is None:
            # The tool has formats, but the trajectory has nothing to match.
            return UnmatchedFormat.UNKNOWN
        # The first format that matches wins.
        found = selected_format_list.match(annotated[0])
        if found is None:
            return UnmatchedFormat.UNKNOWN
        return MatchedHarnessResultFormat(*found)

    def format_list_for_result(
        self,
        tool_result_json: JsonObject | None,
        *,
        is_marked_as_error: bool,
    ) -> HarnessResultFormatList[Any] | UnmatchedFormat:
        """Pick the format list that one result is held against, or the `UnmatchedFormat` of a result that has no list to try.

        A JSON object gets the JSON list.
        A text result that the harness marked as an error gets the list for such results when the tool has one, e.g. Claude Code `Bash`, and any other text result gets the text list.
        A tool without the list it needs gives `UnmatchedFormat.SKIPPED`, except a tool with JSON formats only, whose text result gives `UnmatchedFormat.UNKNOWN` since none of its formats can match it.
        """
        if tool_result_json is not None:
            format_list = self.json_formats
        elif is_marked_as_error and self.text_formats_when_marked_as_error is not None:
            format_list = self.text_formats_when_marked_as_error
        else:
            format_list = self.text_formats
        if format_list is not None:
            return format_list
        if tool_result_json is None and self.json_formats is not None:
            return UnmatchedFormat.UNKNOWN
        return UnmatchedFormat.SKIPPED


def annotated_output_and_notice_names_of(
    tool_result_raw_text: str | None,
    tool_result_json: JsonObject | None,
    selected_format_list: HarnessResultFormatList[Any],
) -> tuple[str | JsonObject, list[str]] | None:
    """Derive the annotated output of a result and the names of the notices cut from it.

    It is the JSON object, or the raw text without its notices.
    None when the trajectory has neither.
    """
    if tool_result_json is not None:
        return tool_result_json, []
    if tool_result_raw_text is None:
        return None
    return selected_format_list.strip_notices(tool_result_raw_text)


@dataclass(frozen=True, slots=True)
class MatchedHarnessResultFormat:
    """Answer of `ToolCallKnowledge.harness_result_format` for a result that a declared format matched, read by `convert_tool_calls` to build the `ToolCallResult`."""

    format: HarnessResultFormat[Any]
    matched_values: MatchedValues


@dataclass(frozen=True, slots=True)
class HarnessTextResultFormat:
    """Declaration of one text result format of a harness tool, written in `knowledge/declarations/` and tried in order by its `HarnessResultFormatList`.

    Its template is an annotated output as in the trajectory, with a placeholder in place of each part that varies.

        template    = fixed text + placeholders
        placeholder = `{name:type}`

    - The fixed text must appear exactly as in the trajectory.
    - The placeholder named `tool_output` takes the tool output. Every other placeholder takes an annotation value. The value names at the top of this module fill `ToolCallResult` fields, e.g. `handle` fills `handles`. Other names, such as `rest`, fill none.
    - The type says which characters the placeholder may take, see `PLACEHOLDER_TYPE_PATTERNS`. A lazy type stops at the next fixed text.
    - The template is matched against the whole annotated output, from its first character to its last.

    For example, Devin `exec`, format `exited` in declarations/tool_call/harness_result_formats/devin.py, with made-up values.

        template          Output from command in shell {handle:id}:
                          {tool_output:text}
                          Exit code: {exit_code:int}

        annotated output  Output from command in shell 3:
                          hello
                          Exit code: 0

        matched values    handle="3"  tool_output="hello"  exit_code="0"

        ToolCallResult    tool_output_text="hello"  exit_code=0  execution_status=finished
                          handles=(ExecutionHandle(COMMAND, "3"),)

    Matched values are strings. When the template has no `tool_output` placeholder, `tool_output_text` is "" unless `text_from_matched_values` builds it. The field comments below cover the rest.
    """

    name: str
    template: str
    # The execution status of every result of this format, None when `judgment_rule` decides it.
    status: ExecutionStatus | None = None
    _: KW_ONLY
    # The function of `tool_call/judgment_rules.py` that decides the status, named as text since `knowledge/` imports no rule.
    judgment_rule: str | None = None
    # Whether every result of this format has a truncated tool output. None when the format does not tell.
    is_truncated: bool | None = None
    # The kind of every handle this format gives. None for a format without a `handle` or `handles` placeholder, and stated for any other.
    fixed_handle_kind: ExecutionHandleKind | None = None
    # Builds text from the placeholders.
    text_from_matched_values: Callable[[MatchedValues], str | None] | None = None
    # The trajectory holds no text of what the tool returned, such as an image.
    # `tool_output_text` is then None, not "".
    no_tool_output_text: bool = False
    # Harness text left inside a tool output that the harness cut, as a template part. When `is_truncated` is None, a tool output holding it is truncated.
    truncation_marker: str | None = None

    def __post_init__(self) -> None:
        _check_status_or_judgment_rule_stated(
            self.name, self.status, self.judgment_rule
        )
        _check_handle_kind_stated(
            self.name,
            gives_handles=not _HANDLE_VALUE_NAMES.isdisjoint(
                _placeholder_types_of(self.template)
            ),
            stated_handle_kind_count=int(self.fixed_handle_kind is not None),
        )

    def match(self, annotated_output: str) -> MatchedValues | None:
        # The fixed text must be exactly as in the trajectory, and each placeholder becomes a named group.
        found = template_regex_of(self.template).fullmatch(annotated_output)
        # Each group gives the value of its placeholder.
        return found.groupdict() if found else None

    def handle_kind_of(
        self, matched_values: MatchedValues
    ) -> ExecutionHandleKind | None:
        return self.fixed_handle_kind

    def is_truncated_of(self, matched_values: MatchedValues) -> bool | None:
        if self.is_truncated is not None or self.truncation_marker is None:
            return self.is_truncated
        marker = template_regex_of(self.truncation_marker)
        return (
            True if marker.search(str(matched_values.get("tool_output", ""))) else None
        )

    def tool_output_text_of(self, matched_values: MatchedValues) -> str | None:
        if self.no_tool_output_text:
            return None
        if self.text_from_matched_values is not None:
            return self.text_from_matched_values(matched_values)
        if "tool_output" not in matched_values:
            return _NO_OUTPUT_TEXT
        text = str(matched_values["tool_output"])
        placeholder_type = _placeholder_types_of(self.template).get("tool_output", "")
        separator = _LINE_NUMBER_SEPARATOR_BY_TYPE.get(placeholder_type)
        if separator is None:
            return text
        every_line = placeholder_type != "partly_numbered_arrow"
        return strip_line_numbers(text, separator, every_line=every_line)


def _check_status_or_judgment_rule_stated(
    format_name: str, status: ExecutionStatus | None, judgment_rule: str | None
) -> None:
    """Raise ValueError when a format states both a status and a judgment rule, or neither.

    A format whose result text tells the status states it, and any other format names the judgment rule that decides it, so every status has one source.
    """
    if (status is None) == (judgment_rule is None):
        raise ValueError(
            f"the format {format_name!r} must state either a `status` or a `judgment_rule`, not both and not neither"
        )


def _check_handle_kind_stated(
    format_name: str, *, gives_handles: bool, stated_handle_kind_count: int
) -> None:
    """Raise ValueError when a format that gives handles does not state exactly one way to their kind, or a format that gives none states one.

    A declaration that says nothing about the kind would otherwise look the same as one that says command, so a wrong declaration fails when its module is imported.
    """
    if gives_handles and stated_handle_kind_count != 1:
        raise ValueError(
            f"the format {format_name!r} gives handles, so it must state one handle kind, by `fixed_handle_kind` or `handle_kind_by_name`"
        )
    if not gives_handles and stated_handle_kind_count:
        raise ValueError(
            f"the format {format_name!r} gives no handle, so it must state no handle kind"
        )


@functools.cache
def _placeholder_types_of(template: str) -> dict[str, str]:
    """Map each placeholder of a template to its type, by name."""
    return {p[1]: p[2] for p in PLACEHOLDER_REGEX.finditer(template)}


# Text helpers, shared with the harness declarations.
def strip_line_numbers(listing: str, separator: str, *, every_line: bool = True) -> str:
    """Remove the line numbers of a numbered file listing.

    In a listing numbered on every line, a line that is only a number is an empty line and loses the number too. In a partly numbered listing, such a line is content.
    """
    bare_number = "|$" if every_line else ""
    return re.sub(
        rf"^[ ]*\d+(?:{re.escape(separator)}{bare_number})",
        "",
        listing,
        flags=re.MULTILINE,
    )


@dataclass(frozen=True, slots=True)
class HarnessJsonResultFormat:
    """Declaration of one JSON result format of a harness tool, written in `knowledge/declarations/` and tried in order by its `HarnessResultFormatList`.

    The annotated output is a JSON object and the format tells it apart by the JSON paths it has.

    - A JSON path is dotted, such as `success.exitCode`.
    - The object has this format when every path in `present_paths` is in it, no path in `absent_paths` is, and `condition` holds if there is one. Keys the format does not name are ignored.
    - `value_paths` names each value and the JSON path it is read from. The value named `tool_output` is the tool output. Every other value is an annotation value, and the value names at the top of this module fill `ToolCallResult` fields.

    For example, Cursor CLI `shellToolCall`, format `exited` in declarations/tool_call/harness_result_formats/cursor_cli.py, with made-up values.
    (The object in the trajectory has more keys than shown)

        format            present_paths=("success.exitCode",)
                          absent_paths=("success.shellId", "success.outputLocation")
                          value_paths={"tool_output": "success.interleavedOutput",
                                       "exit_code": "success.exitCode"}

        annotated output  {"success": {"exitCode": 0, "interleavedOutput": "hello"}}

        matched values    tool_output="hello"  exit_code=0

        ToolCallResult    tool_output_text="hello"  exit_code=0  execution_status=finished

    Matched values keep their JSON types. A tool output that is not a string is kept as JSON text.
    """

    name: str
    # The execution status of every result of this format, None when `judgment_rule` decides it.
    status: ExecutionStatus | None = None
    # Each value name and the JSON path it is read from. Several paths give the parts of one tool output in order, or one handle each for `handles`. Missing and null parts are left out.
    value_paths: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    _: KW_ONLY
    # The function of `tool_call/judgment_rules.py` that decides the status, as for a text format.
    judgment_rule: str | None = None
    # JSON paths that every result of this format has.
    present_paths: tuple[str, ...] = ()
    # JSON paths that no result of this format has.
    absent_paths: tuple[str, ...] = ()
    # A test on one JSON value that every result of this format passes.
    condition: JsonCondition | None = None
    # Whether every result of this format has a truncated tool output. None takes it from the value named `is_truncated`, if there is one.
    is_truncated: bool | None = None
    # The kind of every handle this format gives, when the result does not name it. A format with a `handle` or `handles` value path states this or `handle_kind_by_name`, and any other format states neither.
    fixed_handle_kind: ExecutionHandleKind | None = None
    # The handle kind for each kind name read as `handle_kind_name`, when the result names the kind.
    handle_kind_by_name: Mapping[str, ExecutionHandleKind] = field(default_factory=dict)
    # Builds text from the matched values.
    text_from_matched_values: Callable[[MatchedValues], str | None] | None = None
    # As for a text format, e.g. for a file kept only as a blob id.
    no_tool_output_text: bool = False

    def __post_init__(self) -> None:
        _check_status_or_judgment_rule_stated(
            self.name, self.status, self.judgment_rule
        )
        _check_handle_kind_stated(
            self.name,
            gives_handles=not _HANDLE_VALUE_NAMES.isdisjoint(self.value_paths),
            stated_handle_kind_count=int(self.fixed_handle_kind is not None)
            + int(bool(self.handle_kind_by_name)),
        )

    def match(self, annotated_output: JsonObject) -> MatchedValues | None:
        # The paths and the condition decide whether the result has this format.
        if not all(_has_path(annotated_output, path) for path in self.present_paths):
            return None
        if any(_has_path(annotated_output, path) for path in self.absent_paths):
            return None
        if self.condition is not None and not self.condition.is_met_by(
            annotated_output
        ):
            return None
        # Read each value from its JSON paths.
        matched_values: dict[str, Any] = {}
        for name, paths in self.value_paths.items():
            if isinstance(paths, str):
                present, value = _json_value_from(annotated_output, paths)
                if present:
                    matched_values[name] = value
            else:  # the parts of one tool output in order, or one handle each
                found = (_json_value_from(annotated_output, path) for path in paths)
                parts = [value for _, value in found if value is not None]
                matched_values[name] = (
                    join_text_parts(map(_json_text_of, parts))
                    if name == "tool_output"
                    else parts
                )
        return matched_values

    def handle_kind_of(
        self, matched_values: MatchedValues
    ) -> ExecutionHandleKind | None:
        if not self.handle_kind_by_name:
            return self.fixed_handle_kind
        return self.handle_kind_by_name.get(
            str(matched_values.get("handle_kind_name")), ExecutionHandleKind.UNKNOWN
        )

    def is_truncated_of(self, matched_values: MatchedValues) -> bool | None:
        if self.is_truncated is not None:
            return self.is_truncated
        truncated = matched_values.get("is_truncated")
        return truncated if isinstance(truncated, bool) else None

    def tool_output_text_of(self, matched_values: MatchedValues) -> str | None:
        if self.no_tool_output_text:
            return None
        if self.text_from_matched_values is not None:
            return self.text_from_matched_values(matched_values)
        return json_tool_output_text_of(matched_values)


@dataclass(frozen=True, slots=True)
class JsonCondition:
    """Test on one JSON value that every result of a JSON format passes, held in its `condition`, e.g. `returncode < 0`."""

    path: str
    op: Literal["==", "!=", "<", ">", "startswith", "!startswith", "contains"]
    value: Any

    def is_met_by(self, annotated_output: JsonObject) -> bool:
        present, actual = _json_value_from(annotated_output, self.path)
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


def _has_path(annotated_output: JsonObject, path: str) -> bool:
    """Tell whether the dotted path leads to a value."""
    return _json_value_from(annotated_output, path)[0]


def _json_value_from(annotated_output: JsonObject, path: str) -> tuple[bool, Any]:
    """Follow a dotted path and return (present, value)."""
    value: Any = annotated_output
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return False, None
        value = value[key]
    return True, value


def json_tool_output_text_of(matched_values: MatchedValues) -> str:
    """Give the value named `tool_output` as text, the default of a JSON format, and "" when there is none."""
    text = matched_values.get("tool_output")
    return _NO_OUTPUT_TEXT if text is None else _json_text_of(text)


def _json_text_of(value: Any) -> str:
    """Write a JSON value as text. A string stays as it is, and any other value becomes JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class HarnessResultFormatList[AnnotatedOutputT]:
    """List of the result formats of one harness tool and the notices its results may carry, declared up to three per tool in a `HarnessToolResultDeclaration` and tried by `ToolCallKnowledge`.

    The first format that matches a result is the result's format, so more specific formats come first.
    """

    # Every result format this tool has in the trajectories, more specific ones first.
    formats: tuple[HarnessResultFormat[AnnotatedOutputT], ...]
    _: KW_ONLY
    # Every notice the harness may add to this tool's results.
    notices: tuple[HarnessNotice, ...] = ()

    def match(
        self, annotated_output: AnnotatedOutputT
    ) -> tuple[HarnessResultFormat[AnnotatedOutputT], MatchedValues] | None:
        for harness_result_format in self.formats:
            matched_values = harness_result_format.match(annotated_output)
            if matched_values is not None:
                return harness_result_format, matched_values
        return None

    def strip_notices(self, raw_text: str) -> tuple[str, list[str]]:
        """Cut the notices off the edges of the raw text. Returns the annotated output and the cut notices' names, in cut order."""
        text = raw_text
        cut_names: list[str] = []
        while True:
            for notice in self.notices:
                found = _notice_at_edge_of(notice, text)
                if found:
                    cut_names.append(notice.name)
                    text = text[: found.start()] + text[found.end() :]
                    break
            else:
                return text, cut_names


def _notice_at_edge_of(notice: HarnessNotice, text: str) -> re.Match[str] | None:
    """Find the notice at the start of the text, or the last notice that ends exactly at its end."""
    pattern = template_regex_of(notice.template)
    if notice.at == "start":
        return pattern.match(text)
    last = None
    for found in pattern.finditer(text):
        if found.end() == len(text):
            last = found
    return last


@functools.cache
def template_regex_of(template: str) -> re.Pattern[str]:
    """Build the regex of a template or a part of one, with a named group per placeholder.

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


@dataclass(frozen=True, slots=True)
class HarnessNotice:
    """Declaration of a notice that a harness inserts at one edge of a tool's results, cut by `HarnessResultFormatList.strip_notices` before the formats are tried.

    Its template is matched like a text format's.

    It is cut only at that edge. The same text inside a tool output, such as file contents, must stay.

    For example, Grok Build adds this completion notice at the end of a result, in declarations/tool_call/harness_result_formats/grok_build.py.

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


class HarnessResultFormat[AnnotatedOutputT](Protocol):
    """Protocol of the text and JSON result formats, shared so that `HarnessResultFormatList`, `convert_tool_calls` and the audits read either kind the same way."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> ExecutionStatus | None: ...

    @property
    def judgment_rule(self) -> str | None: ...

    @property
    def is_truncated(self) -> bool | None: ...

    @property
    def no_tool_output_text(self) -> bool: ...

    def match(self, annotated_output: AnnotatedOutputT) -> MatchedValues | None:
        """Return the values of its placeholders or JSON paths if the annotated output has this format, else None."""
        ...

    def handle_kind_of(
        self, matched_values: MatchedValues
    ) -> ExecutionHandleKind | None:
        """Give the kind of the handles this result gives, None for a format that gives no handle."""
        ...

    def is_truncated_of(self, matched_values: MatchedValues) -> bool | None:
        """Tell whether the tool output is truncated, None when the result does not tell."""
        ...

    def tool_output_text_of(self, matched_values: MatchedValues) -> str | None:
        """Return `ToolCallResult.tool_output_text`, built from the matched values.

        It is the value named `tool_output`, or what `text_from_matched_values` builds.
        It is `_NO_OUTPUT_TEXT` when the tool showed no output, and None in the cases that `ToolCallResult.tool_output_text` names.
        """
        ...
