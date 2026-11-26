"""Tests for scripts/harness_result_format_audit.py, i.e. the audit checks of result formats and the labels of their table, with made-up result formats and rows of the table of the declared result formats."""

import importlib.util
import sys
from pathlib import Path

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessJsonResultFormat,
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    JsonCondition,
)
from tb_internet_use.tool_call.model import ExecutionHandleKind, ExecutionStatus

_SPEC = importlib.util.spec_from_file_location(
    "harness_result_format_audit",
    Path(__file__).parents[2] / "scripts/harness_result_format_audit.py",
)
assert _SPEC is not None and _SPEC.loader is not None
harness_result_format_audit = importlib.util.module_from_spec(_SPEC)
# Registered as an import would do, so that the audit scripts loaded by other tests share it.
sys.modules[_SPEC.name] = harness_result_format_audit
_SPEC.loader.exec_module(harness_result_format_audit)

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

# Rows of the table of declared result formats, which together fill every column and in which no two filled columns of a row hold the same value.
# (harness, tool, format, the row)
TABLE_ROW_CASES = [
    (
        "devin",
        "get_output",
        "running",
        {
            "harness": "devin",
            "tool": "get_output",
            "format": "running",
            "kind": "text",
            "template": "{tool_output:text}",
            "status": "by treat_get_output_without_exit_code_as_running",
            "is_truncated": "when … ({count:int} chars truncated)",
            "no_tool_output_text": "",
            "handle_kind": "",
        },
    ),
    (
        "claude-code",
        "TaskStop",
        "stopped",
        {
            "harness": "claude-code",
            "tool": "TaskStop",
            "format": "stopped",
            "kind": "json",
            "template": "present=task_id,message",
            "status": "killed",
            "is_truncated": "",
            "no_tool_output_text": "True",
            "handle_kind": "by task_type",
        },
    ),
    (
        "codex",
        "web_search_call",
        "no_content",
        {
            "harness": "codex",
            "tool": "web_search_call",
            "format": "no_content",
            "kind": "json",
            "template": "absent=content",
            "status": "by treat_web_search_call_without_content_as_finished",
            "is_truncated": "",
            "no_tool_output_text": "True",
            "handle_kind": "",
        },
    ),
    (
        "grok-build",
        "get_command_or_subagent_output",
        "done_truncated",
        {
            "harness": "grok-build",
            "tool": "get_command_or_subagent_output",
            "format": "done_truncated",
            "kind": "text",
            "template": "=== Task {handle:id} ===\nCommand: {command:text}\nStatus: completed\nDuration: {duration:line}\nExit Code: {exit_code:int}\nOutput File: {output_path:line}\n\n=== Output ===\n{tool_output:text}\n[truncated - use read_file on output_file for full content]",
            "status": "finished",
            "is_truncated": "True",
            "no_tool_output_text": "",
            "handle_kind": "command",
        },
    ),
]


def test_table_rows_hold_each_label_in_its_own_column():
    rows = {
        (row["harness"], row["tool"], row["format"]): row
        for row in harness_result_format_audit.table_rows_from_declarations()
    }
    for harness, tool, format_name, row in TABLE_ROW_CASES:
        assert rows[harness, tool, format_name] == row
        assert (
            list(rows[harness, tool, format_name])
            == harness_result_format_audit.DECLARED_RESULT_FORMAT_TABLE_COLUMNS
        )


def test_render_text_format_puts_the_values_back():
    raw_text = "exit 0\nsome\noutput"
    matched_values = EXITED.match(raw_text)
    assert matched_values is not None
    assert (
        harness_result_format_audit.render_text_format(EXITED, matched_values)
        == raw_text
    )


def test_all_matches_lists_every_format_that_matches_with_its_values():
    ambiguous = HarnessResultFormatList[str](
        (EXITED, Text("any", "{tool_output:text}", S.UNKNOWN))
    )
    matches = harness_result_format_audit.all_matches_of(ambiguous, "exit 1\nx")
    assert [
        (harness_result_format.name, matched_values["tool_output"])
        for harness_result_format, matched_values in matches
    ] == [
        ("exited", "x"),
        ("any", "exit 1\nx"),
    ]


def test_harness_text_patterns_cut_templates_at_the_tool_output_and_multiline_placeholders():
    patterns = dict(harness_result_format_audit.harness_text_patterns_of(FORMATS))
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
    format_list = HarnessResultFormatList[str](
        (
            Text("x", "{code:int}:\n{tool_output:text}", S.FINISHED),
            Text("y", "{tool_output:text}{note:line} saved", S.FINISHED),
            Text("z", "{tool_output:text}done {rest:line}", S.FINISHED),
        )
    )
    # `{code:int}:\n` has no letter, and lazy placeholders at either edge are dropped.
    assert [
        part
        for part, _ in harness_result_format_audit.harness_text_patterns_of(format_list)
    ] == [
        " saved",
        "done ",
    ]


def test_template_label_of_gives_the_template_or_the_json_rules():
    assert (
        harness_result_format_audit.template_label_of(EXITED)
        == "exit {exit_code:int}\n{tool_output:text}"
    )
    crlf = Text("crlf", 'C:\\ "{query:line}"\r\n{tool_output:text}', S.FINISHED)
    assert (
        harness_result_format_audit.template_label_of(crlf)
        == 'C:\\\\ "{query:line}"\\r\n{tool_output:text}'
    )
    harness_result_format = Json(
        "failed",
        S.FINISHED,
        present_paths=("exit_code",),
        absent_paths=("signal",),
        condition=JsonCondition("status", "==", "failed"),
    )
    assert (
        harness_result_format_audit.template_label_of(harness_result_format)
        == "present=exit_code absent=signal status == 'failed'"
    )


def test_handle_kind_label_names_the_path_when_the_result_names_the_kind():
    assert harness_result_format_audit.handle_kind_label_of(BACKGROUND) == "command"
    # It reads no handle.
    assert harness_result_format_audit.handle_kind_label_of(EXITED) == ""
    by_name = Json(
        "task",
        S.RUNNING,
        {"handle": "id", "handle_kind_name": "kind"},
        handle_kind_by_name={"shell": ExecutionHandleKind.COMMAND},
    )
    assert harness_result_format_audit.handle_kind_label_of(by_name) == "by kind"
