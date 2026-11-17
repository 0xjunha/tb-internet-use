"""Muse Code converter tests, with made-up results shaped as in the trajectories."""

import json
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from tb_internet_use.knowledge.harness_result_format_declaration import (
    template_regex_of,
)
from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.muse_code import (
    _SAVED_OUTPUT_REMINDER,
    MuseCodeConverter,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ToolCallKey,
    UnmatchedFormat,
)

S = ExecutionStatus
CONVERTER = MuseCodeConverter()
# The reminder that Muse Code puts at the end of a truncated shell output, with a made-up path.
TRUNCATION_REMINDER_TEXT = (
    "\n<system-reminder>\nFull output saved to: /tmp/out.log\n"
    "Full output is longer than the visible window.\n"
    "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
    "</system-reminder>"
)


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: Any
) -> HarnessToolCall:
    raw_text = content if isinstance(content, str) else json.dumps(content)
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("muse-code", tool),
        "id",
        args,
        {"content": raw_text},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def test_bash_states():
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "ok",
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (S.FINISHED, 0, "ok", False)
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "failed",
                "terminal_reason": "process exited with signal: 9 (SIGKILL)",
                "output": "",
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.KILLED,
        None,
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "execution_state": "background_running",
                "session_id": 4,
                "output": "partial",
                "truncated": False,
            },
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.RUNNING
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),
    )


def test_bash_text_failure_is_not_run():
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x &"},
            "tool failed: unmanaged shell backgrounding is not allowed",
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_bash_input_cancelled_is_killed_and_polls_the_session():
    call = _converted(
        _harness_tool_call(
            "bash_input",
            {"session_id": 4, "terminate": True},
            {
                "terminal_status": "cancelled",
                "terminal_reason": "terminated by bash_input",
                "output": "",
                "truncated": False,
            },
        )
    )
    assert call.result is not None and call.result.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "4"),), None, True
    )


def test_work_stop_is_a_terminate():
    call = _converted(
        _harness_tool_call(
            "work_stop",
            {"work_id": "w1"},
            {"status": "accepted", "request_id": "r", "work_id": "w1"},
        )
    )
    assert call.result is not None and call.result.execution_status is S.KILLED
    assert call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "w1"),), None, True
    )


def test_read_file_listing_variants():
    content = "Read text file `/f` (lines 1-2 of 9)\n(0 line(s) above)\n1|a\n2|b\n(more lines below)"
    tool_call_result = _converted(
        _harness_tool_call("read_file", {"path": "/f"}, content)
    ).result
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.harness_result_format,
    ) == (
        "a\nb",
        MatchedFormat("listing_between"),
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "read_file",
            {"path": "/i"},
            "Read image file `/i.png` as model-visible image output.\nmedia_type: image/png\nsource_bytes: 10",
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.tool_output_text,
        tool_call_result.execution_status,
    ) == (
        None,
        S.FINISHED,
    )


def test_write_and_edit():
    tool_call_result = _converted(
        _harness_tool_call("write_file", {"path": "/f"}, "wrote 12 bytes to /f")
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.FINISHED
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "edit_file", {"path": "/f"}, "edited\nchanged lines: line 3\n"
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        "",
    )
    tool_call_result = _converted(
        _harness_tool_call(
            "edit_file", {"path": "/f"}, "tool failed: no exact match found"
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.execution_status is S.NOT_RUN
    )


def test_web_search_results_are_kept_as_json_text():
    tool_call_result = _converted(
        _harness_tool_call(
            "web_search", {"query": "q"}, {"query": "q", "results": [{"url": "u"}]}
        )
    ).result
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
    ) == (
        S.FINISHED,
        '[{"url": "u"}]',
    )


def test_background_shell_names_the_session_and_the_work_as_commands():
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "execution_state": "background_running",
                "session_id": 4,
                "work_id": "w1",
                "output": "",
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None
    assert [(h.kind, h.id) for h in tool_call_result.handles] == [
        (ExecutionHandleKind.COMMAND, "4"),
        (ExecutionHandleKind.COMMAND, "w1"),
    ]


def test_bash_output_loses_the_note_about_replaced_bytes():
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "[unified exec output: 3 invalid UTF-8 bytes replaced with U+FFFD]\nok\n",
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.exit_code) == (
        "ok\n",
        0,
    )
    single = "[unified exec output: 1 invalid UTF-8 byte replaced with U+FFFD]\nok"
    tool_call_result = _converted(
        _harness_tool_call(
            "bash",
            {"command": "x"},
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": single,
                "truncated": False,
            },
        )
    ).result
    assert tool_call_result is not None and tool_call_result.tool_output_text == "ok"


@pytest.mark.parametrize(
    ("tool", "args"), [("bash", {"command": "x"}), ("bash_input", {"session_id": 4})]
)
def test_truncated_shell_output_loses_the_reminder_and_names_the_saved_file(tool, args):
    tool_call_result = _converted(
        _harness_tool_call(
            tool,
            args,
            {
                "terminal_status": "completed",
                "exit_code": 0,
                "output": "first lines" + TRUNCATION_REMINDER_TEXT,
                "truncated": True,
            },
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.tool_output_text,
        tool_call_result.output_path,
        tool_call_result.is_truncated,
    ) == (
        "first lines",
        "/tmp/out.log",
        True,
    )


def test_reminder_in_the_text_of_a_tool_that_is_no_shell_stays():
    text = "x" + TRUNCATION_REMINDER_TEXT
    tool_call_result = _converted(
        _harness_tool_call("subagent_spawn", {"objective": "p"}, text)
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.output_path) == (
        text,
        None,
    )


def test_shell_result_without_text_stays_unknown():
    harness_tool_call = replace(
        _harness_tool_call("bash", {"command": "x"}, ""), result={"content": None}
    )
    tool_call_result = _converted(harness_tool_call).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (UnmatchedFormat.UNKNOWN, None)


def test_bash_output_that_is_not_a_string_is_json_and_a_later_note_stays():
    def output_of(value: Any) -> str | None:
        result = {"terminal_status": "completed", "exit_code": 0, "output": value}
        tool_call_result = _converted(
            _harness_tool_call("bash", {"command": "x"}, result)
        ).result
        return None if tool_call_result is None else tool_call_result.tool_output_text

    assert output_of([1, "a"]) == '[1, "a"]'
    note = "[unified exec output: 2 invalid UTF-8 bytes replaced with U+FFFD]"
    assert output_of("ok\n" + note) == "ok\n" + note


def test_saved_output_reminder_matches_the_texts_of_its_template():
    # The step writes the pattern as a plain regex, since templates belong to `knowledge/`.
    template = (
        "{tool_output:text}\n<system-reminder>\nFull output saved to: {output_path:line}\n"
        "Full output is longer than the visible window.\n"
        "Use bash tools like head, tail, cat, sed, or grep to inspect and search the full output.\n"
        "</system-reminder>"
    )
    reminder = template.replace("{tool_output:text}", "").replace(
        "{output_path:line}", "/tmp/out.log"
    )
    texts = [
        "first lines" + reminder,
        "a\n" + reminder + reminder,
        reminder,
        "x" + reminder.replace("window.", "window!"),
        "x" + reminder.replace("/tmp/out.log", "/a\nb"),
        "x" + reminder + "\n",
    ]
    by_template = [template_regex_of(template).fullmatch(text) for text in texts]
    by_step = [_SAVED_OUTPUT_REMINDER.fullmatch(text) for text in texts]
    assert [found is not None for found in by_template] == [True] * 3 + [False] * 3
    assert [found and found.groupdict() for found in by_step] == [
        found and found.groupdict() for found in by_template
    ]
