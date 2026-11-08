"""Helper functions for scripts/audit_results.py and scripts/build_harness_result_format_catalog.py, not used in conversion."""

import functools
import re
from typing import Any

from tb_internet_use.toolcall.harnesses import CONVERTERS
from tb_internet_use.toolcall.result_formats import (
    PLACEHOLDER_REGEX,
    PLACEHOLDER_TYPE_PATTERNS,
    HarnessJsonResultFormat,
    HarnessResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    MatchedValues,
    template_regex,
)

# The placeholder types that can take several lines. What they take is not harness
# text, so a harness text pattern never spans one of them.
_MULTILINE_TYPES = ("text", "numbered_tab", "numbered_pipe", "partly_numbered_arrow")

# Where a template is cut into harness text, at the tool output and at every
# placeholder of a multiline type.
_HARNESS_TEXT_CUT = re.compile(
    rf"\{{tool_output:\w+\}}|\{{\w+:(?:{'|'.join(_MULTILINE_TYPES)})\}}"
)


# The columns of the result format catalog. Only `reviewed` is filled by hand.
CATALOG_COLUMNS = [
    "harness",
    "tool",
    "format",
    "kind",
    "template",
    "status",
    "is_truncated",
    "handle_kind",
    "reviewed",
]
# A hand review stays only while these columns of its row stay the same.
REVIEWED_LABELS = ("template", "status", "is_truncated", "handle_kind")


def catalog_rows() -> list[dict[str, str]]:
    """One catalog row per declared format, in the order the formats are tried, with `reviewed` empty."""
    rows: list[dict[str, str]] = []
    for harness, converter in CONVERTERS.items():
        for tool, formats in converter.declared_formats():
            for fmt in formats.formats:
                rows.append(
                    {
                        "harness": harness,
                        "tool": tool,
                        "format": fmt.name,
                        "kind": format_kind(fmt),
                        "template": describe_format(fmt),
                        "status": fmt.status.value,
                        "is_truncated": ""
                        if fmt.is_truncated is None
                        else str(fmt.is_truncated),
                        "handle_kind": handle_kind_label(fmt),
                        "reviewed": "",
                    }
                )
    return rows


def format_kind(fmt: HarnessResultFormat[Any]) -> str:
    """`text` or `json`, for the catalog `kind` column."""
    return "text" if isinstance(fmt, HarnessTextResultFormat) else "json"


def describe_format(fmt: HarnessResultFormat[Any]) -> str:
    """The format in one line, for the catalog `template` column.

    A text format gives its template. A JSON format gives its present paths, absent
    paths and condition.
    """
    if isinstance(fmt, HarnessTextResultFormat):
        return fmt.template
    if not isinstance(fmt, HarnessJsonResultFormat):
        raise TypeError(f"unknown result format kind {type(fmt).__name__}")
    rules: list[str] = []
    if fmt.present_paths:
        rules.append(f"present={','.join(fmt.present_paths)}")
    if fmt.absent_paths:
        rules.append(f"absent={','.join(fmt.absent_paths)}")
    if fmt.condition:
        condition = fmt.condition
        rules.append(f"{condition.path} {condition.op} {condition.value!r}")
    return " ".join(rules)


def handle_kind_label(fmt: HarnessResultFormat[Any]) -> str:
    """The handle kind a format gives, or the JSON path whose value names it, for the catalog."""
    if isinstance(fmt, HarnessJsonResultFormat) and fmt.handle_kind_by_name:
        return f"by {fmt.value_paths['handle_kind_name']}"
    if not isinstance(fmt, HarnessTextResultFormat | HarnessJsonResultFormat):
        raise TypeError(f"unknown result format kind {type(fmt).__name__}")
    return fmt.fixed_handle_kind.value


def matching_format_names(
    formats: HarnessResultFormatList[Any], annotated_output: Any
) -> list[str]:
    """Every format of the list that matches, in order. More than one means the list is ambiguous."""
    return [
        fmt.name for fmt in formats.formats if fmt.match(annotated_output) is not None
    ]


def render_text_format(fmt: HarnessTextResultFormat, values: MatchedValues) -> str:
    """Put the matched values back into the template. This equals the annotated output when the split is exact."""
    return PLACEHOLDER_REGEX.sub(
        lambda placeholder: str(values[placeholder[1]]), fmt.template
    )


def harness_text_patterns(
    formats: HarnessResultFormatList[Any],
) -> list[tuple[str, re.Pattern[str]]]:
    """The harness text of this tool's format and notice templates, as regexes, longest first.

    None of them should match inside a tool output. A match means either that the
    tool output really holds that text, such as a log file, or that a format took
    annotation or notice text as tool output. Each item is the template part as
    declared and its regex.
    """
    found: dict[str, re.Pattern[str]] = {}
    for fmt in formats.formats:
        if isinstance(fmt, HarnessTextResultFormat):
            found.update(_harness_text_of_template(fmt.template))
    for notice in formats.notices:
        found.update(_harness_text_of_template(notice.template))
    return sorted(found.items(), key=lambda item: len(item[0]), reverse=True)


@functools.cache
def _harness_text_of_template(template: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Cut a template at the tool output and at every multiline placeholder.

    A part is kept when its fixed text has a letter, since a part such as `:\\n` is found anywhere.
    """
    parts: list[tuple[str, re.Pattern[str]]] = []
    for part in _HARNESS_TEXT_CUT.split(template):
        part = _without_optional_edge_placeholders(part)
        if any(char.isalpha() for char in PLACEHOLDER_REGEX.sub("", part)):
            parts.append((part, template_regex(part)))
    return tuple(parts)


def _without_optional_edge_placeholders(part: str) -> str:
    """Drop the placeholders at either edge that can take nothing.

    They never change whether the part is found, and a lazy one at the start makes the search slow.
    """
    placeholders = list(PLACEHOLDER_REGEX.finditer(part))
    start, end = 0, len(part)
    for placeholder in placeholders:
        if placeholder.start() != start or not _can_be_empty(placeholder[2]):
            break
        start = placeholder.end()
    for placeholder in reversed(placeholders):
        if placeholder.end() != end or placeholder.start() < start:
            break
        if not _can_be_empty(placeholder[2]):
            break
        end = placeholder.start()
    return part[start:end]


def _can_be_empty(placeholder_type: str) -> bool:
    return re.fullmatch(PLACEHOLDER_TYPE_PATTERNS[placeholder_type], "") is not None
