"""Helper functions for scripts/audit_results.py and scripts/build_harness_result_format_catalog.py, not used in conversion."""

import functools
import re
from collections.abc import Iterator
from typing import Any

from tb_internet_use.toolcall.catalog_loader import CATALOGS_DIR
from tb_internet_use.toolcall.harnesses import CONVERTERS
from tb_internet_use.toolcall.result_formats import (
    MULTILINE_PLACEHOLDER_TYPES,
    PLACEHOLDER_REGEX,
    PLACEHOLDER_TYPE_PATTERNS,
    HarnessJsonResultFormat,
    HarnessResultFormat,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    MatchedValues,
    template_regex,
)

# Where a template is cut into harness text, at the tool output and at every
# multiline placeholder. What these take is not harness text, so a harness text
# pattern never spans one of them.
_HARNESS_TEXT_CUT = re.compile(
    rf"\{{tool_output:\w+\}}|\{{\w+:(?:{'|'.join(MULTILINE_PLACEHOLDER_TYPES)})\}}"
)


RESULT_FORMAT_CATALOG_CSV = CATALOGS_DIR / "harness_result_format_catalog.csv"
# The columns of the result format catalog. Only `reviewed` and `note` are filled by hand.
CATALOG_COLUMNS = [
    "harness",
    "tool",
    "format",
    "kind",
    "template",
    "status",
    "is_truncated",
    "no_tool_output_text",
    "handle_kind",
    "reviewed",
    "note",
]
# A hand review stays only while these columns of its row stay the same.
REVIEWED_LABELS = (
    "template",
    "status",
    "is_truncated",
    "no_tool_output_text",
    "handle_kind",
)


def iter_declared_formats() -> Iterator[tuple[str, str, HarnessResultFormat[Any]]]:
    """Every declared format with its harness and tool, in the order the formats are tried."""
    for harness, converter in CONVERTERS.items():
        for tool, formats in converter.declared_formats():
            for fmt in formats.formats:
                yield harness, tool, fmt


def catalog_rows() -> list[dict[str, str]]:
    """One catalog row per declared format, in the order the formats are tried, with `reviewed` and `note` empty."""
    return [
        {
            "harness": harness,
            "tool": tool,
            "format": fmt.name,
            "kind": format_kind(fmt),
            "template": describe_format(fmt),
            "status": fmt.status.value,
            "is_truncated": is_truncated_label(fmt),
            "no_tool_output_text": "True" if fmt.no_tool_output_text else "",
            "handle_kind": handle_kind_label(fmt),
            "reviewed": "",
            "note": "",
        }
        for harness, tool, fmt in iter_declared_formats()
    ]


def with_kept_reviews(
    rows: list[dict[str, str]], previous_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    """The rows with the hand-filled values of the previous catalog.

    A review covers the declaration it saw, so `reviewed` stays only while the row's labels
    are unchanged. A `note` always stays, until it is removed by hand.
    """
    previous = {(r["harness"], r["tool"], r["format"]): r for r in previous_rows}
    kept: list[dict[str, str]] = []
    for row in rows:
        old = previous.get((row["harness"], row["tool"], row["format"]))
        unchanged = old is not None and all(
            old.get(column, "") == row[column] for column in REVIEWED_LABELS
        )
        review = old.get("reviewed", "") if old and unchanged else ""
        note = old.get("note", "") if old else ""
        kept.append({**row, "reviewed": review, "note": note})
    return kept


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


def is_truncated_label(fmt: HarnessResultFormat[Any]) -> str:
    """`True`, `False`, empty when the format does not tell, or what in the result tells, for the catalog."""
    if fmt.is_truncated is not None:
        return str(fmt.is_truncated)
    if isinstance(fmt, HarnessTextResultFormat) and fmt.truncation_marker:
        return f"when {fmt.truncation_marker}"
    if isinstance(fmt, HarnessJsonResultFormat) and "is_truncated" in fmt.value_paths:
        return f"by {fmt.value_paths['is_truncated']}"
    return ""


def handle_kind_label(fmt: HarnessResultFormat[Any]) -> str:
    """The handle kind a format gives, or the JSON path whose value names it, for the catalog."""
    if isinstance(fmt, HarnessJsonResultFormat) and fmt.handle_kind_by_name:
        return f"by {fmt.value_paths['handle_kind_name']}"
    if not isinstance(fmt, HarnessTextResultFormat | HarnessJsonResultFormat):
        raise TypeError(f"unknown result format kind {type(fmt).__name__}")
    return fmt.fixed_handle_kind.value


def all_matches(
    formats: HarnessResultFormatList[Any], annotated_output: Any
) -> list[tuple[HarnessResultFormat[Any], MatchedValues]]:
    """Every format of the list that matches, in order, with its values. The first is the
    result's format, and more than one means the list is ambiguous."""
    matches = ((fmt, fmt.match(annotated_output)) for fmt in formats.formats)
    return [(fmt, values) for fmt, values in matches if values is not None]


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
