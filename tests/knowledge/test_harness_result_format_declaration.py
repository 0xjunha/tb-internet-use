"""Tests for knowledge/harness_result_format_declaration.py, with made-up result formats."""

import pytest

from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    JsonCondition,
    JsonObject,
    strip_line_numbers,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
    UnmatchedFormat,
)

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

TEXT_LIST = HarnessResultFormatList[str]((EXITED,))
ERROR_LIST = HarnessResultFormatList[str](
    (Text("failed", "{tool_output:text}", S.FINISHED),)
)
JSON_LIST = HarnessResultFormatList[JsonObject]((Json("done", S.FINISHED),))
TEXT_AND_ERROR = HarnessToolResultDeclaration(
    text_formats=TEXT_LIST, text_formats_when_marked_as_error=ERROR_LIST
)

# (formats of the tool, JSON object of the result, whether the harness marked it as an error, what is picked)
PICKING_CASES = [
    (
        HarnessToolResultDeclaration(text_formats=TEXT_LIST, json_formats=JSON_LIST),
        {"a": 1},
        False,
        JSON_LIST,
    ),
    (TEXT_AND_ERROR, None, True, ERROR_LIST),
    (TEXT_AND_ERROR, None, False, TEXT_LIST),
    # A tool without a list for results marked as errors reads them with its text list.
    (HarnessToolResultDeclaration(text_formats=TEXT_LIST), None, True, TEXT_LIST),
    (HarnessToolResultDeclaration(), None, False, UnmatchedFormat.SKIPPED),
    # A tool with JSON formats only can match nothing in a text result.
    (
        HarnessToolResultDeclaration(json_formats=JSON_LIST),
        None,
        False,
        UnmatchedFormat.UNKNOWN,
    ),
    # A JSON object is never held against a text list.
    (
        HarnessToolResultDeclaration(text_formats=TEXT_LIST),
        {"a": 1},
        False,
        UnmatchedFormat.SKIPPED,
    ),
]


@pytest.mark.parametrize(
    ("tool_result_formats", "tool_result_json", "is_marked_as_error", "picked"),
    PICKING_CASES,
)
def test_format_list_for_result_picks_the_list_by_the_kind_of_result(
    tool_result_formats, tool_result_json, is_marked_as_error, picked
):
    assert (
        tool_result_formats.format_list_for_result(
            tool_result_json, is_marked_as_error=is_marked_as_error
        )
        is picked
    )


def test_numbered_listing_placeholder_strips_line_numbers_and_a_bare_final_number():
    listing = Text("listing", "{tool_output:numbered_tab}", S.FINISHED)
    raw_text = "1\tfirst\n2\t\n3\tlast\n4"
    matched_values = listing.match(raw_text)
    assert matched_values is not None and matched_values["tool_output"] == raw_text
    assert listing.tool_output_text_of(matched_values) == "first\n\nlast\n"
    assert listing.match("not numbered") is None


def test_strip_line_numbers_handles_padding_and_other_separators():
    assert strip_line_numbers("  1|a\n 10|b", "|") == "a\nb"
    assert strip_line_numbers("1→x\n2→", "→") == "x\n"


def test_a_json_null_counts_as_present():
    harness_result_format = Json(
        "done", S.FINISHED, present_paths=("a",), absent_paths=("b.c",)
    )
    assert harness_result_format.match({"a": None, "b": {}}) is not None
    assert harness_result_format.match({"a": 1, "b": {"c": None}}) is None


def test_json_condition_ops():
    assert JsonCondition("a", "startswith", "ab").is_met_by({"a": "abc"})
    assert JsonCondition("a", "!startswith", "ab").is_met_by({"a": "xbc"})
    assert not JsonCondition("a", "==", 1).is_met_by(
        {"b": 1}
    )  # missing path never holds
    assert not JsonCondition("a", "!=", 1).is_met_by({"b": 1})
    assert JsonCondition("a.b", ">", 1).is_met_by({"a": {"b": 2}})
    assert not JsonCondition("a", ">", 1).is_met_by({"a": 1})


def test_uint_placeholder_rejects_a_negative_number():
    harness_result_format = Text("killed", "code -{signal:uint}", S.KILLED)
    assert harness_result_format.match("code -3") == {"signal": "3"}
    assert harness_result_format.match("code --3") is None


def test_json_text_that_is_not_a_string_is_written_as_json():
    harness_result_format = Json(
        "results", S.FINISHED, {"tool_output": "items"}, present_paths=("items",)
    )
    assert (
        harness_result_format.tool_output_text_of(
            harness_result_format.match({"items": [{"url": "u", "title": "café"}]})
            or {}
        )
        # A letter that is not ASCII stays as it is, as the trajectory shows it.
        == '[{"url": "u", "title": "café"}]'
    )


def test_several_notices_at_the_end_are_all_cut():
    raw_text = "exit 0\nout\n\n<note>\nfirst\n</note>\n\n<note>\nsecond\n</note>"
    assert FORMATS.strip_notices(raw_text) == ("exit 0\nout", ["notice", "notice"])


@pytest.mark.parametrize(
    "build_format",
    [
        # A format that gives handles and states no kind.
        lambda: Text("background", "ID {handle:id}", S.RUNNING),
        lambda: Json("background", S.RUNNING, {"handles": "ids"}),
        # A format that gives no handle and states a kind.
        lambda: Text(
            "exited",
            "exit {exit_code:int}",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        lambda: Json(
            "done",
            S.FINISHED,
            handle_kind_by_name={"shell": ExecutionHandleKind.COMMAND},
        ),
        # A JSON format that states the kind in both ways.
        lambda: Json(
            "background",
            S.RUNNING,
            {"handle": "id", "handle_kind_name": "kind"},
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            handle_kind_by_name={"shell": ExecutionHandleKind.COMMAND},
        ),
    ],
)
def test_a_format_that_misstates_its_handle_kind_cannot_be_built(build_format):
    with pytest.raises(ValueError, match="handle kind"):
        build_format()


@pytest.mark.parametrize(
    "build_format",
    [
        # Both a status and a judgment rule.
        lambda: Text("page", "{tool_output:text}", S.FINISHED, judgment_rule="r"),
        lambda: Json("accepted", S.KILLED, judgment_rule="r"),
        # Neither.
        lambda: Text("page", "{tool_output:text}"),
        lambda: Json("accepted"),
    ],
)
def test_a_format_must_state_either_a_status_or_a_judgment_rule(build_format):
    with pytest.raises(ValueError, match="either a `status` or a `judgment_rule`"):
        build_format()


def test_a_format_that_gives_handles_builds_with_one_stated_kind():
    text = Text(
        "background",
        "ID {handle:id}",
        S.RUNNING,
        fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
    )
    json_by_name = Json(
        "background",
        S.RUNNING,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"agent": ExecutionHandleKind.SUBAGENT},
    )
    assert text.handle_kind_of({"handle": "a"}) == ExecutionHandleKind.SUBAGENT
    assert (
        json_by_name.handle_kind_of({"handle": "a", "handle_kind_name": "agent"})
        == ExecutionHandleKind.SUBAGENT
    )
