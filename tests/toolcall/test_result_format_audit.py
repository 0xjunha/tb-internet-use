"""Tests for the audit checks and catalog labels of result formats, with made-up annotations."""

import pytest

from tb_internet_use.toolcall.model import ExecutionHandleKind, ExecutionStatus
from tb_internet_use.toolcall.result_format_audit import (
    REVIEWED_LABELS,
    all_matches,
    describe_format,
    handle_kind_label,
    harness_text_patterns,
    render_text_format,
    with_kept_reviews,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
)

S = ExecutionStatus
Text = HarnessTextResultFormat
Json = HarnessJsonResultFormat

BACKGROUND = Text(
    "background",
    "Running in background with ID: {handle:id}. Output goes to: {output_path:word}.",
    S.RUNNING,
)
EXITED = Text("exited", "exit {exit_code:int}\n{tool_output:text}", S.FINISHED)
FORMATS = HarnessResultFormatList[str](
    (BACKGROUND, EXITED),
    notices=(HarnessNotice("notice", "\n\n<note>\n{note:text}\n</note>", at="end"),),
)


def test_render_text_format_puts_the_values_back():
    raw_text = "exit 0\nsome\noutput"
    values = EXITED.match(raw_text)
    assert values is not None
    assert render_text_format(EXITED, values) == raw_text


def test_all_matches_lists_every_format_that_matches_with_its_values():
    ambiguous = HarnessResultFormatList[str](
        (EXITED, Text("any", "{tool_output:text}", S.UNKNOWN))
    )
    matches = all_matches(ambiguous, "exit 1\nx")
    assert [(fmt.name, values["tool_output"]) for fmt, values in matches] == [
        ("exited", "x"),
        ("any", "exit 1\nx"),
    ]


def test_harness_text_patterns_cut_templates_at_the_tool_output_and_multiline_placeholders():
    patterns = dict(harness_text_patterns(FORMATS))
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
    assert [part for part, _ in harness_text_patterns(formats)] == [" saved", "done "]


def test_describe_format_gives_the_template_or_the_json_rules():
    assert describe_format(EXITED) == "exit {exit_code:int}\n{tool_output:text}"
    fmt = Json(
        "failed",
        S.FINISHED,
        present_paths=("exit_code",),
        absent_paths=("signal",),
        condition=JsonCondition("status", "==", "failed"),
    )
    assert describe_format(fmt) == "present=exit_code absent=signal status == 'failed'"


def test_handle_kind_label_names_the_path_when_the_result_names_the_kind():
    assert handle_kind_label(BACKGROUND) == "command"
    by_name = Json(
        "task",
        S.RUNNING,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"shell": ExecutionHandleKind.COMMAND},
    )
    assert handle_kind_label(by_name) == "by kind"


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
    reviewed = {**row, "reviewed": "ok"}
    assert with_kept_reviews([row], [reviewed])[0]["reviewed"] == "ok"
    changed = {**row, label: "changed"}
    assert with_kept_reviews([changed], [reviewed])[0]["reviewed"] == ""
    assert with_kept_reviews([row], [])[0]["reviewed"] == ""
