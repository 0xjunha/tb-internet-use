"""Tests for tool_call/_convert_tool_call_result.py, with made-up annotations matched by `HarnessToolResultDeclaration.harness_result_format_of`."""

import json
from typing import Any

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
from tb_internet_use.tool_call._convert_tool_call_result import (
    result_from_harness_result_format,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
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


def _converted(
    tool_result_raw_text: str | None,
    tool_result_json: JsonObject | None,
    format_list: HarnessResultFormatList[Any],
):
    """Match a tool result against one list, as the JSON list for a JSON object and as the text list otherwise, and build its `ToolCallResult`."""
    tool_result_formats = (
        HarnessToolResultDeclaration(text_formats=format_list)
        if tool_result_json is None
        else HarnessToolResultDeclaration(json_formats=format_list)
    )
    harness_result_format = tool_result_formats.harness_result_format_of(
        tool_result_raw_text, tool_result_json, is_marked_as_error=False
    )
    return result_from_harness_result_format(
        tool_result_raw_text, harness_result_format
    )


def _json_tool_call_result(fmt: HarnessJsonResultFormat, tool_result_json: JsonObject):
    """Parse a JSON tool result with a list that holds only `fmt`."""
    return _converted(
        json.dumps(tool_result_json),
        tool_result_json,
        HarnessResultFormatList[JsonObject]((fmt,)),
    )


def test_text_format_matches_start_to_end_and_fills_fields():
    tool_call_result = _converted("exit 3\nhello\n", None, FORMATS)
    assert tool_call_result.harness_result_format == MatchedFormat("exited")
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        3,
        "hello\n",
    )


def test_text_format_does_not_match_with_extra_text_around():
    tool_call_result = _converted("x exit 3\nhello", None, FORMATS)
    assert tool_call_result.harness_result_format == UnmatchedFormat.UNKNOWN
    assert tool_call_result.execution_status is S.UNKNOWN
    assert (
        tool_call_result.tool_output_text == "x exit 3\nhello"
    )  # the raw text, unchanged


def test_id_placeholder_leaves_the_sentence_period_out():
    raw_text = "Running in background with ID: task.1. Output goes to: /tmp/task.1.out."
    tool_call_result = _converted(raw_text, None, FORMATS)
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "task.1"),
    )
    assert tool_call_result.output_path == "/tmp/task.1.out"
    # Nothing after the id disambiguates here, so only the type keeps the dot out.
    assert (
        Text(
            "id",
            "ID: {handle:id}",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ).match("ID: a.b.")
        is None
    )


def test_notices_are_cut_before_matching():
    raw_text = "exit 0\nout\n\n<note>\ntask done\n</note>"
    assert FORMATS.strip_notices(raw_text) == ("exit 0\nout", ["notice"])
    assert _converted(raw_text, None, FORMATS).tool_output_text == "out"


def test_unmatched_result_keeps_the_whole_raw_text_with_its_notices():
    raw_text = "no format\n\n<note>\nx\n</note>"
    tool_call_result = _converted(raw_text, None, FORMATS)
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (
        UnmatchedFormat.UNKNOWN,
        raw_text,
    )


def test_tool_with_formats_but_no_text_is_unknown_not_skipped():
    tool_call_result = _converted(None, None, FORMATS)
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (
        UnmatchedFormat.UNKNOWN,
        S.UNKNOWN,
    )


def test_skipped_format_keeps_the_content_with_unknown_status():
    tool_call_result = result_from_harness_result_format(
        "anything", UnmatchedFormat.SKIPPED
    )
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        "anything",
        S.UNKNOWN,
        UnmatchedFormat.SKIPPED,
    )


def test_format_without_text_placeholder_gives_no_text():
    tool_call_result = _converted(
        "exit 7",
        None,
        HarnessResultFormatList[str](
            (Text("silent", "exit {exit_code:int}", S.FINISHED),)
        ),
    )
    assert (tool_call_result.tool_output_text, tool_call_result.exit_code) == ("", 7)


def test_format_with_no_tool_output_text_gives_none_not_empty():
    image = Text("image", "[Image {index:int}]", S.FINISHED, no_tool_output_text=True)
    tool_call_result = _converted(
        "[Image 1]", None, HarnessResultFormatList[str]((image,))
    )
    assert (tool_call_result.tool_output_text, tool_call_result.execution_status) == (
        None,
        S.FINISHED,
    )
    blob = Json(
        "blob",
        S.FINISHED,
        {"tool_output": "content"},
        no_tool_output_text=True,
    )
    tool_result_json = {"content": "x"}
    tool_call_result = _converted(
        "{}", tool_result_json, HarnessResultFormatList[JsonObject]((blob,))
    )
    assert tool_call_result.tool_output_text is None


def test_partly_numbered_listing_keeps_content_lines_that_are_only_digits():
    assert strip_line_numbers("1→a\n42\n3→c", "→", every_line=False) == "a\n42\nc"
    fmt = Text("listing", "{tool_output:partly_numbered_arrow}", S.FINISHED)
    tool_call_result = _converted("1→a\n42", None, HarnessResultFormatList[str]((fmt,)))
    assert tool_call_result.tool_output_text == "a\n42"


JSON_FORMATS = HarnessResultFormatList[dict](
    (
        Json(
            "timed_out",
            S.TIMED_OUT,
            {"tool_output": "output"},
            condition=JsonCondition("error", "contains", "timed out"),
        ),
        Json(
            "killed",
            S.KILLED,
            {"tool_output": "output", "exit_code": "code"},
            absent_paths=("error",),
            condition=JsonCondition("code", "<", 0),
        ),
        Json(
            "saved",
            S.FINISHED,
            {"tool_output": ("head", "tail"), "output_path": "saved.path"},
            present_paths=("saved",),
            is_truncated=True,
        ),
        Json(
            "exited",
            S.FINISHED,
            {"tool_output": "output", "exit_code": "code", "is_truncated": "cut"},
            present_paths=("output", "code"),
            absent_paths=("error", "saved"),
        ),
    )
)


def test_json_format_is_chosen_by_keys_and_condition():
    assert _converted(
        "{}", {"output": "x", "code": 0, "cut": False}, JSON_FORMATS
    ).harness_result_format == MatchedFormat("exited")
    assert (
        _converted("{}", {"output": "x", "code": -9}, JSON_FORMATS).execution_status
        is S.KILLED
    )
    assert (
        _converted(
            "{}", {"output": "x", "error": "it timed out"}, JSON_FORMATS
        ).execution_status
        is S.TIMED_OUT
    )
    assert (
        _converted("{}", {"other": 1}, JSON_FORMATS).harness_result_format
        == UnmatchedFormat.UNKNOWN
    )
    # Only the absent path `error` keeps this from being exited.
    assert (
        _converted(
            "{}", {"output": "x", "code": 0, "error": "boom"}, JSON_FORMATS
        ).harness_result_format
        == UnmatchedFormat.UNKNOWN
    )


def test_json_fields_follow_paths_and_join_text_parts():
    tool_call_result = _converted(
        "{}", {"saved": {"path": "/out.txt"}, "head": "a\n", "tail": "z"}, JSON_FORMATS
    )
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.output_path,
        tool_call_result.is_truncated,
    ) == (
        "a\nz",
        "/out.txt",
        True,
    )
    tool_call_result = _converted(
        "{}", {"output": "x", "code": "4", "cut": True}, JSON_FORMATS
    )
    assert (tool_call_result.exit_code, tool_call_result.is_truncated) == (4, True)


def test_output_names_the_format_and_handles():
    fmt = Json(
        "running",
        S.RUNNING,
        {"handles": "ids"},
        fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
    )
    tool_call_result = _json_tool_call_result(fmt, {"ids": ["a", 2]})
    assert tool_call_result.harness_result_format == MatchedFormat("running")
    assert [(h.kind, h.id) for h in tool_call_result.handles] == [
        (ExecutionHandleKind.SUBAGENT, "a"),
        (ExecutionHandleKind.SUBAGENT, "2"),
    ]


def test_a_text_placeholder_named_handles_gives_one_handle():
    fmt = Text(
        "running",
        "IDs {handles:id}",
        S.RUNNING,
        fixed_handle_kind=ExecutionHandleKind.COMMAND,
    )
    tool_call_result = _converted("IDs ab", None, HarnessResultFormatList[str]((fmt,)))
    assert [h.id for h in tool_call_result.handles] == ["ab"]


def test_json_handles_may_come_from_several_paths():
    fmt = Json(
        "running",
        S.RUNNING,
        {"handles": ("session", "work")},
        present_paths=("session",),
        fixed_handle_kind=ExecutionHandleKind.COMMAND,
    )
    tool_call_result = _json_tool_call_result(fmt, {"session": 4, "work": "w1"})
    assert [h.id for h in tool_call_result.handles] == ["4", "w1"]


def test_empty_or_wrongly_typed_values_fill_no_field():
    fmt = Json(
        "done",
        S.FINISHED,
        {"handle": "id", "exit_code": "code", "output_path": "path"},
        fixed_handle_kind=ExecutionHandleKind.COMMAND,
    )
    tool_call_result = _json_tool_call_result(fmt, {"id": "", "code": True, "path": ""})
    assert (
        tool_call_result.handles,
        tool_call_result.exit_code,
        tool_call_result.output_path,
    ) == ((), None, None)


def test_text_from_matched_values_builds_the_text_from_the_placeholders():
    fmt = Text(
        "two",
        "{a:line}|{b:line}",
        S.FINISHED,
        text_from_matched_values=lambda f: f["b"] + f["a"],
    )
    tool_call_result = _converted("x|y", None, HarnessResultFormatList[str]((fmt,)))
    assert tool_call_result.tool_output_text == "yx"


def test_json_handle_kind_can_come_from_a_result_value():
    fmt = Json(
        "done",
        S.FINISHED,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"agent": ExecutionHandleKind.SUBAGENT},
    )
    tool_call_result = _json_tool_call_result(fmt, {"id": "t", "kind": "agent"})
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t"),
    )
    tool_call_result = _json_tool_call_result(fmt, {"id": "t", "kind": "other"})
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.UNKNOWN, "t"),
    )


def test_a_notice_shaped_block_inside_the_tool_output_is_kept():
    raw_text = "exit 0\nout\n\n<note>\nthis is file content\n</note>\nmore"
    assert FORMATS.strip_notices(raw_text) == (raw_text, [])
    assert (
        _converted(raw_text, None, FORMATS).tool_output_text
        == "out\n\n<note>\nthis is file content\n</note>\nmore"
    )


def test_json_nulls_give_no_handle_and_no_text_part():
    fmt = Json(
        "background",
        S.RUNNING,
        {"tool_output": ("head", "tail"), "handles": ("session_id", "work_id")},
        fixed_handle_kind=ExecutionHandleKind.COMMAND,
    )
    tool_result_json = {
        "head": None,
        "tail": {"k": 1},
        "session_id": None,
        "work_id": "w1",
    }
    tool_call_result = _json_tool_call_result(fmt, tool_result_json)
    assert tool_call_result.tool_output_text == '{"k": 1}'
    assert [h.id for h in tool_call_result.handles] == ["w1"]


def test_matched_values_of_another_json_type_fill_no_exit_code_and_a_text_output_path():
    fmt = Json("done", S.FINISHED, {"exit_code": "code", "output_path": "path"})
    tool_call_result = _json_tool_call_result(fmt, {"code": [1], "path": 7})
    assert (tool_call_result.exit_code, tool_call_result.output_path) == (None, "7")
