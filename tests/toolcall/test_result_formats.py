"""Tests for result_formats.py, with made-up annotations."""

import json

from tb_internet_use.toolcall.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    MatchedFormat,
    UnmatchedFormat,
)
from tb_internet_use.toolcall.result_formats import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
    JsonObject,
    join_content_items,
    join_text_parts,
    parse_output_with_formats,
    strip_line_numbers,
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


def _parse_json_output(fmt: HarnessJsonResultFormat, tool_result_json: JsonObject):
    """Parse a JSON tool result with a list that holds only `fmt`."""
    return parse_output_with_formats(
        json.dumps(tool_result_json),
        tool_result_json,
        HarnessResultFormatList[JsonObject]((fmt,)),
    )


def test_text_format_matches_start_to_end_and_fills_fields():
    output = parse_output_with_formats("exit 3\nhello\n", None, FORMATS)
    assert output.harness_result_format == MatchedFormat("exited")
    assert (output.execution_status, output.exit_code, output.tool_output_text) == (
        S.FINISHED,
        3,
        "hello\n",
    )


def test_text_format_does_not_match_with_extra_text_around():
    output = parse_output_with_formats("x exit 3\nhello", None, FORMATS)
    assert output.harness_result_format == UnmatchedFormat.UNKNOWN
    assert output.execution_status is S.UNKNOWN
    assert output.tool_output_text == "x exit 3\nhello"  # the raw text, unchanged


def test_id_placeholder_leaves_the_sentence_period_out():
    raw_text = "Running in background with ID: task.1. Output goes to: /tmp/task.1.out."
    output = parse_output_with_formats(raw_text, None, FORMATS)
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "task.1"),)
    assert output.output_path == "/tmp/task.1.out"
    # Nothing after the id disambiguates here, so only the type keeps the dot out.
    assert Text("id", "ID: {handle:id}", S.FINISHED).match("ID: a.b.") is None


def test_notices_are_cut_before_matching():
    raw_text = "exit 0\nout\n\n<note>\ntask done\n</note>"
    assert FORMATS.strip_notices(raw_text) == ("exit 0\nout", ["notice"])
    assert parse_output_with_formats(raw_text, None, FORMATS).tool_output_text == "out"


def test_unmatched_result_keeps_the_whole_raw_text_with_its_notices():
    raw_text = "no format\n\n<note>\nx\n</note>"
    output = parse_output_with_formats(raw_text, None, FORMATS)
    assert (output.harness_result_format, output.tool_output_text) == (
        UnmatchedFormat.UNKNOWN,
        raw_text,
    )


def test_tool_with_formats_but_no_text_is_unknown_not_skipped():
    output = parse_output_with_formats(None, None, FORMATS)
    assert (output.harness_result_format, output.execution_status) == (
        UnmatchedFormat.UNKNOWN,
        S.UNKNOWN,
    )


def test_skipped_format_keeps_the_content_with_unknown_status():
    output = parse_output_with_formats("anything", None, None)
    assert (
        output.tool_output_text,
        output.execution_status,
        output.harness_result_format,
    ) == (
        "anything",
        S.UNKNOWN,
        UnmatchedFormat.SKIPPED,
    )


def test_format_without_text_placeholder_gives_no_text():
    output = parse_output_with_formats(
        "exit 7",
        None,
        HarnessResultFormatList[str](
            (Text("silent", "exit {exit_code:int}", S.FINISHED),)
        ),
    )
    assert (output.tool_output_text, output.exit_code) == ("", 7)


def test_format_with_no_tool_output_text_gives_none_not_empty():
    image = Text("image", "[Image {index:int}]", S.FINISHED, no_tool_output_text=True)
    output = parse_output_with_formats(
        "[Image 1]", None, HarnessResultFormatList[str]((image,))
    )
    assert (output.tool_output_text, output.execution_status) == (None, S.FINISHED)
    blob = Json(
        "blob",
        S.FINISHED,
        {"tool_output": "content"},
        no_tool_output_text=True,
    )
    tool_result_json = {"content": "x"}
    output = parse_output_with_formats(
        "{}", tool_result_json, HarnessResultFormatList[JsonObject]((blob,))
    )
    assert output.tool_output_text is None


def test_numbered_listing_placeholder_strips_line_numbers_and_a_bare_final_number():
    listing = Text("listing", "{tool_output:numbered_tab}", S.FINISHED)
    raw_text = "1\tfirst\n2\t\n3\tlast\n4"
    values = listing.match(raw_text)
    assert values is not None and values["tool_output"] == raw_text
    assert listing.tool_output_text_of(values) == "first\n\nlast\n"
    assert listing.match("not numbered") is None


def test_strip_line_numbers_handles_padding_and_other_separators():
    assert strip_line_numbers("  1|a\n 10|b", "|") == "a\nb"
    assert strip_line_numbers("1→x\n2→", "→") == "x\n"


def test_partly_numbered_listing_keeps_content_lines_that_are_only_digits():
    assert strip_line_numbers("1→a\n42\n3→c", "→", every_line=False) == "a\n42\nc"
    fmt = Text("listing", "{tool_output:partly_numbered_arrow}", S.FINISHED)
    output = parse_output_with_formats(
        "1→a\n42", None, HarnessResultFormatList[str]((fmt,))
    )
    assert output.tool_output_text == "a\n42"


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
    assert parse_output_with_formats(
        "{}", {"output": "x", "code": 0, "cut": False}, JSON_FORMATS
    ).harness_result_format == MatchedFormat("exited")
    assert (
        parse_output_with_formats(
            "{}", {"output": "x", "code": -9}, JSON_FORMATS
        ).execution_status
        is S.KILLED
    )
    assert (
        parse_output_with_formats(
            "{}", {"output": "x", "error": "it timed out"}, JSON_FORMATS
        ).execution_status
        is S.TIMED_OUT
    )
    assert (
        parse_output_with_formats(
            "{}", {"other": 1}, JSON_FORMATS
        ).harness_result_format
        == UnmatchedFormat.UNKNOWN
    )
    # Only the absent path `error` keeps this from being exited.
    assert (
        parse_output_with_formats(
            "{}", {"output": "x", "code": 0, "error": "boom"}, JSON_FORMATS
        ).harness_result_format
        == UnmatchedFormat.UNKNOWN
    )


def test_a_json_null_counts_as_present():
    fmt = Json("done", S.FINISHED, present_paths=("a",), absent_paths=("b.c",))
    assert fmt.match({"a": None, "b": {}}) is not None
    assert fmt.match({"a": 1, "b": {"c": None}}) is None


def test_json_fields_follow_paths_and_join_text_parts():
    output = parse_output_with_formats(
        "{}", {"saved": {"path": "/out.txt"}, "head": "a\n", "tail": "z"}, JSON_FORMATS
    )
    assert (output.tool_output_text, output.output_path, output.is_truncated) == (
        "a\nz",
        "/out.txt",
        True,
    )
    output = parse_output_with_formats(
        "{}", {"output": "x", "code": "4", "cut": True}, JSON_FORMATS
    )
    assert (output.exit_code, output.is_truncated) == (4, True)


def test_json_condition_ops():
    assert JsonCondition("a", "startswith", "ab").holds({"a": "abc"})
    assert JsonCondition("a", "!startswith", "ab").holds({"a": "xbc"})
    assert not JsonCondition("a", "==", 1).holds({"b": 1})  # missing path never holds
    assert not JsonCondition("a", "!=", 1).holds({"b": 1})
    assert JsonCondition("a.b", ">", 1).holds({"a": {"b": 2}})
    assert not JsonCondition("a", ">", 1).holds({"a": 1})


def test_output_names_the_format_and_handles():
    fmt = Json(
        "running",
        S.RUNNING,
        {"handles": "ids"},
        fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
    )
    output = _parse_json_output(fmt, {"ids": ["a", 2]})
    assert output.harness_result_format == MatchedFormat("running")
    assert [(h.kind, h.id) for h in output.handles] == [
        (ExecutionHandleKind.SUBAGENT, "a"),
        (ExecutionHandleKind.SUBAGENT, "2"),
    ]


def test_a_text_placeholder_named_handles_gives_one_handle():
    fmt = Text("running", "IDs {handles:id}", S.RUNNING)
    output = parse_output_with_formats(
        "IDs ab", None, HarnessResultFormatList[str]((fmt,))
    )
    assert [h.id for h in output.handles] == ["ab"]


def test_json_handles_may_come_from_several_paths():
    fmt = Json(
        "running",
        S.RUNNING,
        {"handles": ("session", "work")},
        present_paths=("session",),
    )
    output = _parse_json_output(fmt, {"session": 4, "work": "w1"})
    assert [h.id for h in output.handles] == ["4", "w1"]


def test_uint_placeholder_rejects_a_negative_number():
    fmt = Text("killed", "code -{signal:uint}", S.KILLED)
    assert fmt.match("code -3") == {"signal": "3"}
    assert fmt.match("code --3") is None


def test_join_text_parts_starts_a_new_line_only_when_needed():
    assert join_text_parts(["a\n", "b"]) == "a\nb"
    assert join_text_parts(["a", "b"]) == "a\nb"
    assert join_text_parts(["", "b"]) == "b"
    assert join_text_parts(["a", ""]) == "a"


def test_empty_or_wrongly_typed_values_fill_no_field():
    fmt = Json(
        "done",
        S.FINISHED,
        {"handle": "id", "exit_code": "code", "output_path": "path"},
    )
    output = _parse_json_output(fmt, {"id": "", "code": True, "path": ""})
    assert (output.handles, output.exit_code, output.output_path) == ((), None, None)


def test_text_from_matched_values_builds_the_text_from_the_placeholders():
    fmt = Text(
        "two",
        "{a:line}|{b:line}",
        S.FINISHED,
        text_from_matched_values=lambda f: f["b"] + f["a"],
    )
    output = parse_output_with_formats(
        "x|y", None, HarnessResultFormatList[str]((fmt,))
    )
    assert output.tool_output_text == "yx"


def test_json_handle_kind_can_come_from_a_result_value():
    fmt = Json(
        "done",
        S.FINISHED,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"agent": ExecutionHandleKind.SUBAGENT},
    )
    output = _parse_json_output(fmt, {"id": "t", "kind": "agent"})
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t"),)
    output = _parse_json_output(fmt, {"id": "t", "kind": "other"})
    assert output.handles == (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "t"),)


def test_json_text_that_is_not_a_string_is_written_as_json():
    fmt = Json(
        "results", S.FINISHED, {"tool_output": "items"}, present_paths=("items",)
    )
    assert (
        fmt.tool_output_text_of(fmt.match({"items": [{"url": "u"}]}) or {})
        == '[{"url": "u"}]'
    )


def test_a_notice_shaped_block_inside_the_tool_output_is_kept():
    raw_text = "exit 0\nout\n\n<note>\nthis is file content\n</note>\nmore"
    assert FORMATS.strip_notices(raw_text) == (raw_text, [])
    assert (
        parse_output_with_formats(raw_text, None, FORMATS).tool_output_text
        == "out\n\n<note>\nthis is file content\n</note>\nmore"
    )


def test_several_notices_at_the_end_are_all_cut():
    raw_text = "exit 0\nout\n\n<note>\nfirst\n</note>\n\n<note>\nsecond\n</note>"
    assert FORMATS.strip_notices(raw_text) == ("exit 0\nout", ["notice", "notice"])


def test_json_nulls_give_no_handle_and_no_text_part():
    fmt = Json(
        "background",
        S.RUNNING,
        {"tool_output": ("head", "tail"), "handles": ("session_id", "work_id")},
    )
    result = {"head": None, "tail": {"k": 1}, "session_id": None, "work_id": "w1"}
    output = _parse_json_output(fmt, result)
    assert output.tool_output_text == '{"k": 1}'
    assert [h.id for h in output.handles] == ["w1"]


def test_content_items_join_their_texts_with_a_blank_line():
    items = [
        {"type": "text", "text": "a\n"},
        {"type": "image", "source": {}},
        {"type": "text", "text": "b"},
    ]
    assert join_content_items(items) == "a\n\nb"
    assert join_content_items([{"type": "image"}]) is None
