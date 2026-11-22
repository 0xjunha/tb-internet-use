"""Describe the declared result formats and check how they match results, for scripts/audit_results.py and scripts/build_harness_result_format_table.py and never for conversion."""

import functools
import re
from collections.abc import Iterator
from typing import Any

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    MULTILINE_PLACEHOLDER_TYPES,
    PLACEHOLDER_REGEX,
    PLACEHOLDER_TYPE_PATTERNS,
    HarnessJsonResultFormat,
    HarnessResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    MatchedValues,
    template_regex_of,
)
from tb_internet_use.knowledge.declarations.tool_call.harness_result_formats import (
    RESULT_FORMATS_BY_HARNESS,
)

# Where a template is cut into harness text, at the tool output and at every multiline placeholder. What these take is not harness text, so a harness text pattern never spans one of them.
_HARNESS_TEXT_CUT = re.compile(
    rf"\{{tool_output:\w+\}}|\{{\w+:(?:{'|'.join(MULTILINE_PLACEHOLDER_TYPES)})\}}"
)


# The columns of the table of declared result formats.
DECLARED_RESULT_FORMAT_TABLE_COLUMNS = [
    "harness",
    "tool",
    "format",
    "kind",
    "template",
    "status",
    "is_truncated",
    "no_tool_output_text",
    "handle_kind",
]


def table_rows_from_declarations() -> list[dict[str, str]]:
    """List one table row per declared format, in the order of `iter_declared_formats`."""
    return [
        {
            "harness": harness,
            "tool": tool,
            "format": harness_result_format.name,
            "kind": format_kind_of(harness_result_format),
            "template": template_label_of(harness_result_format),
            "status": _status_label_of(harness_result_format),
            "is_truncated": _truncation_label_of(harness_result_format),
            "no_tool_output_text": "True"
            if harness_result_format.no_tool_output_text
            else "",
            "handle_kind": handle_kind_label_of(harness_result_format),
        }
        for harness, tool, harness_result_format in iter_declared_formats()
    ]


def format_kind_of(harness_result_format: HarnessResultFormat[Any]) -> str:
    """Name the kind of a format, `text` or `json`, for the `kind` column of the table."""
    return (
        "text" if isinstance(harness_result_format, HarnessTextResultFormat) else "json"
    )


def template_label_of(harness_result_format: HarnessResultFormat[Any]) -> str:
    """Label a format by its template or its JSON rules, for the `template` column of the table, with the line feeds of a template kept.

    A text format gives its template, with a carriage return written as `\\r` so that editors keep it, and a backslash as `\\\\`. A JSON format gives its present paths, absent paths and condition.
    """
    if isinstance(harness_result_format, HarnessTextResultFormat):
        return harness_result_format.template.replace("\\", "\\\\").replace("\r", "\\r")
    if not isinstance(harness_result_format, HarnessJsonResultFormat):
        raise TypeError(
            f"unknown result format kind {type(harness_result_format).__name__}"
        )
    rules: list[str] = []
    if harness_result_format.present_paths:
        rules.append(f"present={','.join(harness_result_format.present_paths)}")
    if harness_result_format.absent_paths:
        rules.append(f"absent={','.join(harness_result_format.absent_paths)}")
    if harness_result_format.condition:
        condition = harness_result_format.condition
        rules.append(f"{condition.path} {condition.op} {condition.value!r}")
    return " ".join(rules)


def _status_label_of(harness_result_format: HarnessResultFormat[Any]) -> str:
    """Label the status a format states, or `by <judgment rule>` for a format whose judgment rule decides it, for the table."""
    if harness_result_format.status is None:
        return f"by {harness_result_format.judgment_rule}"
    return harness_result_format.status.value


def _truncation_label_of(harness_result_format: HarnessResultFormat[Any]) -> str:
    """Label whether a format is truncated, `True`, `False`, empty when the format does not tell, or what in the result tells, for the table."""
    if harness_result_format.is_truncated is not None:
        return str(harness_result_format.is_truncated)
    if (
        isinstance(harness_result_format, HarnessTextResultFormat)
        and harness_result_format.truncation_marker
    ):
        return f"when {harness_result_format.truncation_marker}"
    if (
        isinstance(harness_result_format, HarnessJsonResultFormat)
        and "is_truncated" in harness_result_format.value_paths
    ):
        return f"by {harness_result_format.value_paths['is_truncated']}"
    return ""


def handle_kind_label_of(harness_result_format: HarnessResultFormat[Any]) -> str:
    """Label the handle kind a format gives, or the JSON path whose value names it, for the table.

    Empty when the format reads no handle from the result, since such a format states no handle kind.
    """
    if (
        isinstance(harness_result_format, HarnessJsonResultFormat)
        and harness_result_format.handle_kind_by_name
    ):
        return f"by {harness_result_format.value_paths['handle_kind_name']}"
    if not isinstance(
        harness_result_format, HarnessTextResultFormat | HarnessJsonResultFormat
    ):
        raise TypeError(
            f"unknown result format kind {type(harness_result_format).__name__}"
        )
    kind = harness_result_format.fixed_handle_kind
    return "" if kind is None else kind.value


def iter_declared_formats() -> Iterator[tuple[str, str, HarnessResultFormat[Any]]]:
    """List every declared format with its harness and tool, in the order the formats are tried."""
    for harness, tool, format_list in iter_declared_format_lists():
        for harness_result_format in format_list.formats:
            yield harness, tool, harness_result_format


def iter_declared_format_lists() -> Iterator[
    tuple[str, str, HarnessResultFormatList[Any]]
]:
    """List every declared format list with its harness and tool, per harness the lists for results marked as errors, then the text lists, then the JSON lists, each in the order of its tools."""
    for harness, formats_by_tool in RESULT_FORMATS_BY_HARNESS.items():
        tools = formats_by_tool.items()
        lists: list[tuple[str, HarnessResultFormatList[Any] | None]] = [
            *((tool, f.text_formats_when_marked_as_error) for tool, f in tools),
            *((tool, f.text_formats) for tool, f in tools),
            *((tool, f.json_formats) for tool, f in tools),
        ]
        for tool, format_list in lists:
            if format_list is not None:
                yield harness, tool, format_list


def all_matches_of(
    format_list: HarnessResultFormatList[Any], annotated_output: Any
) -> list[tuple[HarnessResultFormat[Any], MatchedValues]]:
    """List every format of the list that matches, in order, with its values.

    The first is the result's format, and more than one means the list is ambiguous.
    """
    matches = (
        (harness_result_format, harness_result_format.match(annotated_output))
        for harness_result_format in format_list.formats
    )
    return [
        (harness_result_format, matched_values)
        for harness_result_format, matched_values in matches
        if matched_values is not None
    ]


def render_text_format(
    harness_result_format: HarnessTextResultFormat, matched_values: MatchedValues
) -> str:
    """Put the matched values back into the template. This equals the annotated output when the split is exact."""
    return PLACEHOLDER_REGEX.sub(
        lambda placeholder: str(matched_values[placeholder[1]]),
        harness_result_format.template,
    )


def harness_text_patterns_of(
    format_list: HarnessResultFormatList[Any],
) -> list[tuple[str, re.Pattern[str]]]:
    """List the harness text of this tool's format and notice templates, as regexes, longest first.

    None of them should match inside a tool output. A match means either that the tool output really holds that text, such as a log file, or that a format took annotation or notice text as tool output. Each item is the template part as declared and its regex.
    """
    found: dict[str, re.Pattern[str]] = {}
    for harness_result_format in format_list.formats:
        if isinstance(harness_result_format, HarnessTextResultFormat):
            found.update(_harness_text_of_template(harness_result_format.template))
    for notice in format_list.notices:
        found.update(_harness_text_of_template(notice.template))
    return sorted(found.items(), key=lambda item: len(item[0]), reverse=True)


@functools.cache
def _harness_text_of_template(template: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Cut a template at the tool output and at every multiline placeholder.

    A part is kept when its fixed text has a letter, since a part such as `:\\n` is found anywhere.
    """
    parts: list[tuple[str, re.Pattern[str]]] = []
    for part in _HARNESS_TEXT_CUT.split(template):
        part = _strip_optional_edge_placeholders(part)
        if any(char.isalpha() for char in PLACEHOLDER_REGEX.sub("", part)):
            parts.append((part, template_regex_of(part)))
    return tuple(parts)


def _strip_optional_edge_placeholders(part: str) -> str:
    """Drop the placeholders at either edge that can take nothing.

    They never change whether the part is found, and a lazy one at the start makes the search slow.
    """
    placeholders = list(PLACEHOLDER_REGEX.finditer(part))
    start, end = 0, len(part)
    for placeholder in placeholders:
        if placeholder.start() != start or not _may_be_empty(placeholder[2]):
            break
        start = placeholder.end()
    for placeholder in reversed(placeholders):
        if placeholder.end() != end or placeholder.start() < start:
            break
        if not _may_be_empty(placeholder[2]):
            break
        end = placeholder.start()
    return part[start:end]


def _may_be_empty(placeholder_type: str) -> bool:
    return re.fullmatch(PLACEHOLDER_TYPE_PATTERNS[placeholder_type], "") is not None
