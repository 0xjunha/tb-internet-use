"""Tests for the audit checks and catalog labels of result formats, with made-up annotations, and for the committed catalog."""

import csv

import pytest

from tb_internet_use.knowledge.harness_result_format_audit import (
    RESULT_FORMAT_CATALOG_CSV,
    REVIEWED_LABELS,
    all_matches_of,
    catalog_rows_from_declarations,
    describe_format,
    handle_kind_label_of,
    harness_text_patterns_of,
    render_text_format,
    rows_with_kept_reviews_from,
)
from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
)
from tb_internet_use.tool_call.model import ExecutionHandleKind, ExecutionStatus

S = ExecutionStatus
Text = HarnessTextResultFormat
Json = HarnessJsonResultFormat

BACKGROUND = Text(
    "background",
    "Running in background with ID: {handle:id}. Output goes to: {output_path:word}.",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
EXITED = Text("exited", "exit {exit_code:int}\n{tool_output:text}", S.FINISHED)
FORMATS = HarnessResultFormatList[str](
    (BACKGROUND, EXITED),
    notices=(HarnessNotice("notice", "\n\n<note>\n{note:text}\n</note>", at="end"),),
)


def _without_hand_filled(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {k: v for k, v in row.items() if k not in ("reviewed", "note")} for row in rows
    ]


def test_render_text_format_puts_the_values_back():
    raw_text = "exit 0\nsome\noutput"
    values = EXITED.match(raw_text)
    assert values is not None
    assert render_text_format(EXITED, values) == raw_text


def test_all_matches_lists_every_format_that_matches_with_its_values():
    ambiguous = HarnessResultFormatList[str](
        (EXITED, Text("any", "{tool_output:text}", S.UNKNOWN))
    )
    matches = all_matches_of(ambiguous, "exit 1\nx")
    assert [(fmt.name, values["tool_output"]) for fmt, values in matches] == [
        ("exited", "x"),
        ("any", "exit 1\nx"),
    ]


def test_harness_text_patterns_cut_templates_at_the_tool_output_and_multiline_placeholders():
    patterns = dict(harness_text_patterns_of(FORMATS))
    assert list(patterns) == [
        "Running in background with ID: {handle:id}. Output goes to: {output_path:word}.",
        "exit {exit_code:int}\n",
        "\n\n<note>\n",
        "\n</note>",
    ]
    exit_line = patterns["exit {exit_code:int}\n"]
    assert exit_line.search("out\nexit 3\nmore")  # an exit line taken as tool output
    assert not exit_line.search("the exit code was zero\n")


def test_harness_text_patterns_skip_parts_without_letters_and_optional_edges():
    formats = HarnessResultFormatList[str](
        (
            Text("x", "{code:int}:\n{tool_output:text}", S.FINISHED),
            Text("y", "{tool_output:text}{note:line} saved", S.FINISHED),
            Text("z", "{tool_output:text}done {rest:line}", S.FINISHED),
        )
    )
    # `{code:int}:\n` has no letter, and lazy placeholders at either edge are dropped.
    assert [part for part, _ in harness_text_patterns_of(formats)] == [
        " saved",
        "done ",
    ]


def test_describe_format_gives_the_template_or_the_json_rules():
    assert describe_format(EXITED) == "exit {exit_code:int}\n{tool_output:text}"
    crlf = Text("crlf", 'C:\\ "{query:line}"\r\n{tool_output:text}', S.FINISHED)
    assert describe_format(crlf) == 'C:\\\\ "{query:line}"\\r\n{tool_output:text}'
    fmt = Json(
        "failed",
        S.FINISHED,
        present_paths=("exit_code",),
        absent_paths=("signal",),
        condition=JsonCondition("status", "==", "failed"),
    )
    assert describe_format(fmt) == "present=exit_code absent=signal status == 'failed'"


def test_handle_kind_label_names_the_path_when_the_result_names_the_kind():
    assert handle_kind_label_of(BACKGROUND) == "command"
    assert handle_kind_label_of(EXITED) == ""  # it reads no handle
    by_name = Json(
        "task",
        S.RUNNING,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"shell": ExecutionHandleKind.COMMAND},
    )
    assert handle_kind_label_of(by_name) == "by kind"


@pytest.mark.parametrize("label", REVIEWED_LABELS)
def test_a_review_stays_only_while_the_row_labels_stay(label: str):
    row = {
        "harness": "h",
        "tool": "t",
        "format": "f",
        "template": "x",
        "status": "finished",
        "is_truncated": "",
        "no_tool_output_text": "",
        "handle_kind": "command",
        "reviewed": "",
    }
    reviewed = {**row, "reviewed": "ok", "note": "n"}
    assert rows_with_kept_reviews_from([row], [reviewed])[0]["reviewed"] == "ok"
    changed = {**row, label: "changed"}
    assert rows_with_kept_reviews_from([changed], [reviewed])[0]["reviewed"] == ""
    assert (
        rows_with_kept_reviews_from([changed], [reviewed])[0]["note"] == "n"
    )  # a note stays
    assert rows_with_kept_reviews_from([row], [])[0]["reviewed"] == ""


def test_committed_catalog_matches_the_declared_formats():
    with RESULT_FORMAT_CATALOG_CSV.open(newline="") as f:
        committed = list(csv.DictReader(f))
    assert _without_hand_filled(committed) == _without_hand_filled(
        catalog_rows_from_declarations()
    ), "rebuild it with scripts/build_harness_result_format_catalog.py"
