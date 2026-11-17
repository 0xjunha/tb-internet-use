"""Test the conversion of Claude Code tool calls by the Claude Code converter, with made-up results shaped as in the trajectories."""

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import (
    HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
    HARNESS_TOOL_ARGUMENTS_CSV,
    HARNESS_TOOLS_CSV,
    TOOL_CALL_CATALOGS_DIR,
    ToolCallKnowledge,
)
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.claude_code import (
    ClaudeCodeConverter,
    _join_content_items,
)
from tb_internet_use.tool_call.judgment_rules import (
    treat_bash_output_without_exit_code_line_as_exit_code_0,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    StartSubagentAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnmatchedFormat,
    WebFetchAction,
    WebSearchAction,
    WriteFileAction,
)

S = ExecutionStatus
CONVERTER = ClaudeCodeConverter()
EXIT_CODE_0_RULE = treat_bash_output_without_exit_code_line_as_exit_code_0.__name__


def _harness_tool_call(
    tool: str, args: dict[str, Any], result: dict[str, Any]
) -> HarnessToolCall:
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("claude-code", tool),
        "id",
        args,
        result,
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Claude Code without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("claude-code", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


def _result(
    block: Any,
    structured_result: dict[str, Any] | None = None,
    is_error: bool | None = None,
) -> dict[str, Any]:
    """Give a result as Harbor writes it in the trajectory, with the original block kept in the metadata and blocks appended to content."""
    metadata: dict[str, Any] = {
        "raw_tool_result": {"type": "tool_result", "content": block}
    }
    if structured_result is not None:
        metadata["tool_use_result"] = structured_result
    extra: dict[str, Any] = {"tool_result_metadata": metadata}
    if is_error is not None:
        extra["tool_result_is_error"] = is_error
    return {"content": "(harbor view)", "extra": extra}


def _bash(
    block: str,
    structured_result: dict[str, Any] | None = None,
    is_error: bool | None = None,
):
    return _converted(
        _harness_tool_call(
            "Bash", {"command": "x"}, _result(block, structured_result, is_error)
        )
    ).result


def _counted_bash_result_of(
    block: str,
    structured_result: dict[str, Any],
    *,
    knowledge: ToolCallKnowledge,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallResult:
    """Convert one `Bash` call with the given door and judgment rule counter, so that a test can read what they counted."""
    tool_call = convert_one_tool_call(
        _harness_tool_call("Bash", {"command": "x"}, _result(block, structured_result)),
        CONVERTER,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )
    assert tool_call.result is not None
    return tool_call.result


IMAGE = {"type": "image", "source": {}}
# A Bash background notice, with a made-up id and path.
BACKGROUND_NOTICE = "Command running in background with ID: b1. Output is being written to: /tmp/b1.output. You will be notified when it completes. To check interim output, use Read on that file path."


def _converted_result(
    tool: str, args: dict[str, Any], result: dict[str, Any]
) -> ToolCallResult:
    tool_call_result = _converted(_harness_tool_call(tool, args, result)).result
    assert tool_call_result is not None
    return tool_call_result


def _bash_format_and_text(result: dict[str, Any]) -> tuple[object, str | None]:
    tool_call_result = _converted_result("Bash", {"command": "x"}, result)
    return tool_call_result.harness_result_format, tool_call_result.tool_output_text


_FRESH = " (file state is current in your context — no need to Read it back)"
_TOOL_USE_ERROR = (
    "<tool_use_error>File has not been read yet. Read it first.</tool_use_error>"
)
_CLASSIFIER = (
    "the response that made this tool call was stopped by a safety classifier."
)
_PERSISTED_HEAD = "<persisted-output>\nOutput too large (3.1KB). Full output saved to: /tmp/p.txt\n\nPreview (first 2KB):\n"
_BINARY_SAVED = (
    "\n\n[Binary content (application/pdf, 1.2 MB) also saved to /tmp/page.pdf]"
)
_BACKGROUND = "Command running in background with ID: b1. Output is being written to: /tmp/b1.output."
_TIMED_OUT_BACKGROUND = "Command did not complete within its 120s timeout and was moved to the background (ID: b1). Output is being written to: /tmp/b1.output."
_NOTIFY = " You will be notified when it completes. To check interim output, use Read on that file path."
_B1 = (ExecutionHandle(ExecutionHandleKind.COMMAND, "b1"),)


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _not_run_result(format_name: str) -> ToolCallResult:
    return ToolCallResult("", S.NOT_RUN, harness_result_format=_format(format_name))


def _finished_result(format_name: str, text: str | None = "") -> ToolCallResult:
    return ToolCallResult(text, S.FINISHED, harness_result_format=_format(format_name))


def _background_result(format_name: str, text: str = "") -> ToolCallResult:
    return ToolCallResult(
        text,
        S.RUNNING,
        handles=_B1,
        output_path="/tmp/b1.output",
        harness_result_format=_format(format_name),
    )


def _task_output(status: str, task_type: str, **task: Any) -> dict[str, Any]:
    """Give a `TaskOutput` result whose structured result holds the task `t1`."""
    structured_result = {
        "retrieval_status": "success",
        "task": {"task_id": "t1", "task_type": task_type, "status": status, **task},
    }
    return _result("<retrieval_status>success</retrieval_status>", structured_result)


# One made-up result per declared result format of Claude Code, built from the format, and the `ToolCallResult` it converts to.
# A `Bash` result marked as an error is held against the formats for such results.
# (tool, result in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, dict[str, Any], ToolCallResult]] = [
    (
        "Bash",
        _result(_TOOL_USE_ERROR, is_error=True),
        _not_run_result("tool_use_error"),
    ),
    (
        "Bash",
        _result("Exit code 143\nCommand timed out after 2m\nhead", is_error=True),
        ToolCallResult("head", S.TIMED_OUT, harness_result_format=_format("timed_out")),
    ),
    (
        "Bash",
        _result("Exit code 143\nCommand timed out after 2m 0.0s", is_error=True),
        ToolCallResult(
            "", S.TIMED_OUT, harness_result_format=_format("timed_out_silent")
        ),
    ),
    (
        "Bash",
        _result("Exit code 2\nboom", is_error=True),
        ToolCallResult("boom", S.FINISHED, 2, harness_result_format=_format("exited")),
    ),
    (
        "Bash",
        _result("Exit code 1", is_error=True),
        ToolCallResult(
            "", S.FINISHED, 1, harness_result_format=_format("exited_silent")
        ),
    ),
    (
        "Bash",
        _result(
            "Permission to use Bash with command rm -rf x has been denied.",
            is_error=True,
        ),
        _not_run_result("refused_permission"),
    ),
    (
        "Bash",
        _result(
            "Dangerous rm operation detected: '/x' This is blocked.", is_error=True
        ),
        _not_run_result("refused_dangerous"),
    ),
    (
        "Bash",
        _result(
            "This Bash command contains multiple operations. Split them.", is_error=True
        ),
        _not_run_result("refused_multiple"),
    ),
    # The classifier stopped a call that was running and may have completed.
    (
        "Bash",
        _result("Interrupted: " + _CLASSIFIER, is_error=True),
        ToolCallResult(
            "", S.UNKNOWN, harness_result_format=_format("interrupted_classifier")
        ),
    ),
    (
        "Bash",
        _result(
            "The user doesn't want to proceed with this tool use. The tool use was rejected.",
            is_error=True,
        ),
        _not_run_result("refused_user"),
    ),
    ("Bash", _result("(Bash completed with no output)"), _finished_result("no_output")),
    ("Bash", _result(_BACKGROUND + _NOTIFY), _background_result("background")),
    (
        "Bash",
        _result(
            _BACKGROUND
            + " If it exits while you are still working you will be notified, but it is terminated when you give your final response."
        ),
        _background_result("background_v3"),
    ),
    (
        "Bash",
        _result("early line\n" + _BACKGROUND + _NOTIFY),
        _background_result("background_after_output", "early line"),
    ),
    (
        "Bash",
        _result(_TIMED_OUT_BACKGROUND + _NOTIFY),
        _background_result("background_timeout"),
    ),
    (
        "Bash",
        _result(
            _TIMED_OUT_BACKGROUND
            + " You will be notified when it completes. If it is still running after 10 minutes, check on it."
        ),
        _background_result("background_timeout_v2"),
    ),
    (
        "Bash",
        _result(_PERSISTED_HEAD + "head\n</persisted-output>"),
        ToolCallResult(
            "head",
            S.FINISHED,
            output_path="/tmp/p.txt",
            is_truncated=True,
            harness_result_format=_format("persisted_output"),
        ),
    ),
    (
        "Bash",
        _result(
            "<persisted-output>\nOutput exceeded the 64MB persist limit; only the first 64MB were saved to: /tmp/p.txt\n\n"
            "Preview (first 2KB):\nhead\n</persisted-output>"
        ),
        ToolCallResult(
            "head",
            S.FINISHED,
            output_path="/tmp/p.txt",
            is_truncated=True,
            harness_result_format=_format("persisted_output_partial"),
        ),
    ),
    # Without a structured result, 0 and the 1 of grep look the same, so no exit code.
    ("Bash", _result("hello"), _finished_result("bare_output", "hello")),
    ("Read", _result(_TOOL_USE_ERROR), _not_run_result("tool_use_error")),
    (
        "Read",
        _result("Interrupted: " + _CLASSIFIER),
        ToolCallResult(
            "", S.UNKNOWN, harness_result_format=_format("interrupted_classifier")
        ),
    ),
    (
        "Read",
        _result(
            "<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>"
        ),
        _finished_result("warning"),
    ),
    (
        "Read",
        _result(
            "Wasted call — file unchanged since your last Read. Refer to that earlier tool_result instead."
        ),
        _not_run_result("unchanged"),
    ),
    ("Read", _result("PDF file read: /d.pdf (102.8KB)"), _finished_result("pdf", None)),
    (
        "Read",
        _result("PDF pages extracted: 2 page(s) from /d.pdf (102.8KB)"),
        _finished_result("pdf_pages", None),
    ),
    (
        "Read",
        _result("pdftoppm is not installed. Install poppler-utils."),
        _not_run_result("pdf_tool_missing"),
    ),
    (
        "Read",
        _result(
            "This PDF has 300 pages, which is too many to read at once. Use the pages parameter."
        ),
        _not_run_result("pdf_too_many_pages"),
    ),
    (
        "Read",
        _result("PDF file exceeds maximum allowed size of 32MB."),
        _not_run_result("pdf_too_large"),
    ),
    (
        "Read",
        _result("Unable to resize image below the size limit."),
        _not_run_result("image_too_large"),
    ),
    (
        "Read",
        _result("EISDIR: illegal operation on a directory, read"),
        _not_run_result("directory"),
    ),
    (
        "Read",
        _result("File does not exist. Current working directory: /app"),
        _not_run_result("missing"),
    ),
    (
        "Read",
        _result(
            "File content (30000 tokens) exceeds maximum allowed tokens (25000). Use offset."
        ),
        _not_run_result("too_large"),
    ),
    ("Read", _result("1\ta\n2\tb"), _finished_result("listing", "a\nb")),
    (
        "Read",
        _result([{"type": "image", "source": {"type": "base64", "data": "AAAA"}}]),
        _finished_result("image", None),
    ),
    ("Write", _result(_TOOL_USE_ERROR), _not_run_result("tool_use_error")),
    (
        "Write",
        _result("Not run: " + _CLASSIFIER),
        _not_run_result("not_run_classifier"),
    ),
    (
        "Write",
        _result("File created successfully at: /f.py" + _FRESH),
        _finished_result("created_fresh"),
    ),
    (
        "Write",
        _result("File created successfully at: /f.py"),
        _finished_result("created"),
    ),
    (
        "Write",
        _result("The file /f.py has been updated successfully." + _FRESH),
        _finished_result("updated_fresh"),
    ),
    (
        "Write",
        _result("The file /f.py has been updated successfully."),
        _finished_result("updated"),
    ),
    ("Edit", _result(_TOOL_USE_ERROR), _not_run_result("tool_use_error")),
    (
        "Edit",
        _result("Refusing to write through symlink: /l Edit the target instead."),
        _not_run_result("refused_symlink"),
    ),
    (
        "Edit",
        _result("The file /f has been updated successfully." + _FRESH),
        _finished_result("updated_fresh"),
    ),
    (
        "Edit",
        _result("The file /f has been updated successfully."),
        _finished_result("updated"),
    ),
    (
        "Edit",
        _result(
            "The file /f has been updated successfully. (note: the file ends without a newline)"
        ),
        _finished_result("updated_note"),
    ),
    (
        "Edit",
        _result(
            "The file /f has been updated. All occurrences were successfully replaced."
            + _FRESH
        ),
        _finished_result("replaced_all_fresh"),
    ),
    (
        "Edit",
        _result(
            "The file /f has been updated. All occurrences were successfully replaced."
        ),
        _finished_result("replaced_all"),
    ),
    (
        "Edit",
        _result(
            "The file /f has been updated. All occurrences were successfully replaced. (note: the file ends without a newline)"
        ),
        _finished_result("replaced_all_note"),
    ),
    (
        "WebFetch",
        _result("No response from model"),
        _finished_result("no_model_response"),
    ),
    (
        "WebFetch",
        _result("No response from model" + _BINARY_SAVED),
        ToolCallResult(
            "",
            S.FINISHED,
            output_path="/tmp/page.pdf",
            harness_result_format=_format("no_model_response_binary_saved"),
        ),
    ),
    # A fetch that got an error status or no connection ended on its own.
    (
        "WebFetch",
        _result(
            "The server returned HTTP 404 Not Found\n\nThe response body was not retrieved. Try another URL."
        ),
        ToolCallResult(
            "",
            S.FINISHED,
            http_status=404,
            harness_result_format=_format("http_error_body_not_retrieved"),
        ),
    ),
    ("WebFetch", _result("API Error: 500 upstream"), _finished_result("api_error")),
    (
        "WebFetch",
        _result("connect ECONNREFUSED 1.2.3.4:443"),
        _finished_result("connection_error"),
    ),
    (
        "WebFetch",
        _result("Summary of the page." + _BINARY_SAVED),
        ToolCallResult(
            "Summary of the page.",
            S.FINISHED,
            output_path="/tmp/page.pdf",
            harness_result_format=_format("page_binary_saved"),
        ),
    ),
    (
        "WebFetch",
        _result("A page about tests."),
        _finished_result("page", "A page about tests."),
    ),
    (
        "WebSearch",
        _result(
            _PERSISTED_HEAD
            + 'Web search results for query: "q"\n\nLinks: []\n\nsummary\n</persisted-output>'
        ),
        ToolCallResult(
            "Links: []\n\nsummary",
            S.FINISHED,
            output_path="/tmp/p.txt",
            is_truncated=True,
            harness_result_format=_format("persisted_results"),
        ),
    ),
    (
        "WebSearch",
        _result("The search was cut off before any results arrived. Try again."),
        _finished_result("cut_off"),
    ),
    (
        "WebSearch",
        _result(
            'Web search results for query: "q"\n\nLinks: []\n\nsummary\n\n'
            "REMINDER: You MUST include the sources above in your response to the user using markdown hyperlinks."
        ),
        _finished_result("results", "Links: []\n\nsummary"),
    ),
    (
        "TaskOutput",
        _task_output("running", "local_bash", output="partial"),
        ToolCallResult(
            "partial",
            S.RUNNING,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),),
            harness_result_format=_format("task_running"),
        ),
    ),
    (
        "TaskOutput",
        _task_output("completed", "local_agent", output="all good", exitCode=0),
        ToolCallResult(
            "all good",
            S.FINISHED,
            0,
            handles=(ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t1"),),
            harness_result_format=_format("task_completed"),
        ),
    ),
    (
        "TaskOutput",
        _task_output("failed", "local_bash", output="err", exitCode=1),
        ToolCallResult(
            "err",
            S.FINISHED,
            1,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),),
            harness_result_format=_format("task_failed"),
        ),
    ),
    ("TaskStop", _result(_TOOL_USE_ERROR), _not_run_result("tool_use_error")),
    (
        "TaskStop",
        _result(
            _PERSISTED_HEAD
            + '{"message":"Successfully stopped task: t9 (python3 server.py)","task_id":"t9"'
        ),
        ToolCallResult(
            "",
            S.KILLED,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "t9"),),
            output_path="/tmp/p.txt",
            is_truncated=True,
            harness_result_format=_format("persisted_stopped"),
        ),
    ),
    (
        "TaskStop",
        _result("Task t2 is owned by a1; agent a2 cannot stop it."),
        _not_run_result("not_owner"),
    ),
    (
        "TaskStop",
        _result(
            '{"message":"Successfully stopped task: t1 (sleep 99)","task_id":"t1","task_type":"local_bash","command":"sleep 99"}'
        ),
        ToolCallResult(
            "",
            S.KILLED,
            handles=(ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),),
            harness_result_format=_format("stopped"),
        ),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, or whose action is a poll, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    ("Bash", {"command": "ls /app", "timeout": 5000}, RunCommandAction("ls /app")),
    (
        "Edit",
        {"file_path": "/app/a.py", "old_string": "x = 1", "new_string": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    (
        "Read",
        {"file_path": "/app/a.py", "offset": 10, "limit": 20},
        ReadFileAction("/app/a.py", 10, 20),
    ),
    (
        "Write",
        {"file_path": "/app/a.txt", "content": "hi"},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    # Some calls name the same two arguments `path` and `file_text`.
    (
        "Write",
        {"path": "/app/b.txt", "file_text": "yo"},
        WriteFileAction("/app/b.txt", "yo"),
    ),
    (
        "WebFetch",
        {"url": "https://example.org/a", "prompt": "sum it up"},
        WebFetchAction(("https://example.org/a",)),
    ),
    ("WebSearch", {"query": "pytest fixtures"}, WebSearchAction(("pytest fixtures",))),
    (
        "mcp__playwright__browser_navigate",
        {"url": "https://example.org/b"},
        WebFetchAction(("https://example.org/b",)),
    ),
    ("Agent", {"prompt": "find the bug"}, StartSubagentAction()),
    # The message text fills no field.
    (
        "SendMessage",
        {"to": "a1", "message": "go on with the build"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a1"),), terminate=False
        ),
    ),
    (
        "SendMessage",
        {"recipient": "a2"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a2"),), terminate=False
        ),
    ),
    # A row without a handle kind leaves the kind unknown until a result names it.
    (
        "TaskOutput",
        {"task_id": "b1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "b1"),), terminate=False
        ),
    ),
    (
        "TaskStop",
        {"task_id": "b1"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.UNKNOWN, "b1"),), terminate=True
        ),
    ),
]


# The text of `returnCodeInterpretation` in the structured result of a `Bash` call and the exit code it stands for, one row per row of `harness_return_code_interpretations.csv`.
RETURN_CODE_INTERPRETATION_CASES = [
    ("Bash", "No matches found", 1),
    ("Bash", "Files differ", 1),
    ("Bash", "Some directories were inaccessible", 1),
]


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "result", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, result: dict[str, Any], expected: ToolCallResult
):
    assert _converted_result(tool, {}, result) == expected


def test_bash_body_without_header_is_exit_zero_and_structured_stdout_wins():
    structured_result = {"stdout": "full stdout\n", "stderr": "", "interrupted": False}
    tool_call_result = _bash("shown", structured_result)
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.tool_output_text,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        "full stdout\n",
        0,
    )
    assert tool_call_result.harness_result_format == MatchedFormat("bare_output")


@pytest.mark.parametrize(
    ("tool", "return_code_interpretation", "exit_code"),
    RETURN_CODE_INTERPRETATION_CASES,
)
def test_bash_return_code_interpretation_gives_the_exit_code_of_its_catalog_row(
    tool: str, return_code_interpretation: str, exit_code: int
):
    knowledge = ToolCallKnowledge()
    judgment_rule_use_counts: Counter[str] = Counter()
    structured_result = {
        "stdout": "",
        "interrupted": False,
        "returnCodeInterpretation": return_code_interpretation,
    }

    tool_call_result = _counted_bash_result_of(
        "(Bash completed with no output)",
        structured_result,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    assert (tool_call_result.exit_code, tool_call_result.tool_output_text) == (
        exit_code,
        "",
    )
    row_key = (
        HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
        ("claude-code", tool, return_code_interpretation),
    )
    assert knowledge.uses.row_use_counts[row_key] == 1
    assert judgment_rule_use_counts[EXIT_CODE_0_RULE] == 0


def test_bash_return_code_interpretation_gives_the_exit_code_the_door_answers(
    tmp_path: Path,
):
    # A made-up row whose exit code is not 1, so that a converter that gives 1 without asking the door fails.
    for file_name in (HARNESS_TOOLS_CSV, HARNESS_TOOL_ARGUMENTS_CSV):
        shutil.copy(TOOL_CALL_CATALOGS_DIR / file_name, tmp_path / file_name)
    (tmp_path / HARNESS_RETURN_CODE_INTERPRETATIONS_CSV).write_text(
        "harness,tool,return_code_interpretation,exit_code,checked_against,reviewed,note\n"
        "claude-code,Bash,Made-up meaning,2,,,\n"
    )

    tool_call_result = _counted_bash_result_of(
        "(Bash completed with no output)",
        {
            "stdout": "",
            "interrupted": False,
            "returnCodeInterpretation": "Made-up meaning",
        },
        knowledge=ToolCallKnowledge(catalogs_dir=tmp_path),
        judgment_rule_use_counts=Counter(),
    )

    assert tool_call_result.exit_code == 2


@pytest.mark.parametrize(
    ("return_code_interpretation", "looked_up_text"),
    [
        ("Made-up meaning", "Made-up meaning"),
        # An empty text and a value that is no text never occur in the data, and are looked up rather than read as no interpretation.
        ("", ""),
        (0, "0"),
    ],
)
def test_bash_return_code_interpretation_without_a_row_leaves_the_exit_code_unknown(
    return_code_interpretation: object, looked_up_text: str
):
    knowledge = ToolCallKnowledge()
    judgment_rule_use_counts: Counter[str] = Counter()
    structured_result = {
        "stdout": "",
        "interrupted": False,
        "returnCodeInterpretation": return_code_interpretation,
    }

    tool_call_result = _counted_bash_result_of(
        "(Bash completed with no output)",
        structured_result,
        knowledge=knowledge,
        judgment_rule_use_counts=judgment_rule_use_counts,
    )

    # It must not fall through to the rule that gives exit code 0.
    assert (tool_call_result.execution_status, tool_call_result.exit_code) == (
        S.FINISHED,
        None,
    )
    assert judgment_rule_use_counts[EXIT_CODE_0_RULE] == 0
    assert knowledge.uses.unknown_input_counts == Counter(
        {
            (
                HARNESS_RETURN_CODE_INTERPRETATIONS_CSV,
                ("claude-code", "Bash", looked_up_text),
            ): 1
        }
    )


def test_bash_exit_code_without_header_needs_the_structured_result():
    knowledge = ToolCallKnowledge()
    judgment_rule_use_counts: Counter[str] = Counter()
    # Without a return code interpretation, or with null in its place, the judgment rule gives 0.
    for structured_result in (
        {"stdout": "shown", "interrupted": False},
        {"stdout": "shown", "interrupted": False, "returnCodeInterpretation": None},
    ):
        tool_call_result = _counted_bash_result_of(
            "shown",
            structured_result,
            knowledge=knowledge,
            judgment_rule_use_counts=judgment_rule_use_counts,
        )
        assert tool_call_result.exit_code == 0
    assert judgment_rule_use_counts[EXIT_CODE_0_RULE] == 2
    assert not any(
        source == HARNESS_RETURN_CODE_INTERPRETATIONS_CSV
        for source, _ in [
            *knowledge.uses.row_use_counts,
            *knowledge.uses.unknown_input_counts,
        ]
    )
    tool_call_result = _bash("shown")  # no structured result, so 0 and 1 look the same
    assert tool_call_result is not None and (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
    ) == (
        S.FINISHED,
        None,
    )
    tool_call_result = _bash("shown", {"stdout": "shown", "interrupted": True})
    assert tool_call_result is not None and tool_call_result.exit_code is None


def test_bash_structured_result_gives_the_task_and_the_saved_output():
    block = (
        "Command running in background with ID: b1. Output is being written to: /tmp/b1.output."
        " You will be notified when it completes. To check interim output, use Read on that file path."
    )
    tool_call_result = _bash(
        block, {"stdout": "", "backgroundTaskId": "b2", "interrupted": False}
    )
    assert tool_call_result is not None
    assert (tool_call_result.handles, tool_call_result.exit_code) == (
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "b2"),),
        None,  # still running, so no exit code
    )
    tool_call_result = _bash(
        "big",
        {"stdout": "big", "persistedOutputPath": "/tmp/p.txt", "interrupted": False},
    )
    assert tool_call_result is not None
    assert (tool_call_result.output_path, tool_call_result.is_truncated) == (
        "/tmp/p.txt",
        True,
    )


def test_bash_structured_result_does_not_touch_an_unmatched_result():
    tool_call_result = _bash(
        "something else went wrong", {"stdout": "x"}, is_error=True
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (
        UnmatchedFormat.UNKNOWN,
        "something else went wrong",
    )


def test_trailing_notices_are_cut_from_bash_and_write_results():
    for block in (
        "out\nShell cwd was reset to /app",
        "out\n[This command modified 2 files you've previously read: a, b]",
        "out\n\nSession cwd was changed to /app",
        "out\nSession cwd was changed to /app",
    ):
        tool_call_result = _bash(block)
        assert (
            tool_call_result is not None and tool_call_result.tool_output_text == "out"
        ), block
    for block in ("Shell cwd was reset to /app", "[This command modified 1 file]"):
        tool_call_result = _bash(block)
        assert (
            tool_call_result is not None and tool_call_result.tool_output_text == ""
        ), block
    tool_call_result = _converted(
        _harness_tool_call(
            "Write",
            {"file_path": "/a"},
            _result(
                "File created successfully at: /a\n\n"
                "Note: Write's parameters are named file_path and content."
            ),
        )
    ).result
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == MatchedFormat("created")


def test_bash_error_output_cut_by_claude_code_is_truncated_and_keeps_the_marker():
    text = "head\n... [120 characters truncated] ...\ntail"
    tool_call_result = _bash("Exit code 1\n" + text, is_error=True)
    assert tool_call_result is not None
    assert (tool_call_result.is_truncated, tool_call_result.tool_output_text) == (
        True,
        text,
    )
    tool_call_result = _bash("Exit code 1\nwhole", is_error=True)
    assert tool_call_result is not None and tool_call_result.is_truncated is None


def test_bash_timeout_with_cut_output_has_no_exit_code_and_is_truncated():
    tool_call_result = _bash(
        "Exit code 143\nCommand timed out after 2m\nhead\n... [9 characters truncated] ...\ntail",
        is_error=True,
    )
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.exit_code,
        tool_call_result.is_truncated,
    ) == (
        S.TIMED_OUT,
        None,
        True,
    )


def test_structured_result_that_is_not_an_object_is_ignored():
    tool_call_result = _bash("shown", "not an object")  # type: ignore[arg-type]
    assert tool_call_result is not None and tool_call_result.tool_output_text == "shown"


def test_an_error_body_that_no_format_names_is_unknown_format():
    tool_call_result = _bash("something else went wrong", is_error=True)
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        S.UNKNOWN,
        UnmatchedFormat.UNKNOWN,
    )


def test_read_structured_file_content_is_the_text():
    structured_result = {
        "type": "text",
        "file": {"filePath": "/a", "content": "a\r\nb\n", "numLines": 2},
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "Read", {"file_path": "/a"}, _result("1\ta\n2\tb\n3", structured_result)
        )
    ).result
    assert (
        tool_call_result is not None and tool_call_result.tool_output_text == "a\r\nb\n"
    )


def test_read_cut_at_the_token_cap_is_truncated():
    structured_result = {
        "type": "text",
        "file": {"filePath": "/a", "content": "a\n", "truncatedByTokenCap": True},
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "Read", {"file_path": "/a"}, _result("1\ta\n", structured_result)
        )
    ).result
    assert tool_call_result is not None and tool_call_result.is_truncated is True


@pytest.mark.parametrize(
    "first_item",
    [
        {"type": "text", "text": ""},
        IMAGE,
        {"type": "tool_reference", "tool_name": "Read"},
        {"type": "document", "source": {}},
    ],
)
def test_harbor_json_items_without_a_metadata_block_are_decoded(
    first_item: dict[str, Any],
):
    # Content of Harbor items, one per paragraph, is read as items of every type Harbor writes, and only text items give text.
    text_item = {"type": "text", "text": "File created successfully at: /f.py"}
    content = json.dumps(first_item) + "\n\n" + json.dumps(text_item)
    tool_call_result = _converted(
        _harness_tool_call("Write", {"file_path": "/f.py"}, {"content": content})
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
    ) == (
        S.FINISHED,
        MatchedFormat("created"),
    )


def test_task_output_uses_the_structured_task():
    structured_result = {
        "retrieval_status": "success",
        "task": {
            "task_id": "t1",
            "task_type": "local_agent",
            "status": "completed",
            "output": "all good",
            "exitCode": 0,
        },
    }
    tool_call = _converted(
        _harness_tool_call(
            "TaskOutput",
            {"task_id": "t1"},
            _result("<retrieval_status>success</retrieval_status>", structured_result),
        )
    )
    assert tool_call.result is not None
    assert (
        tool_call.result.execution_status,
        tool_call.result.tool_output_text,
        tool_call.result.exit_code,
    ) == (
        S.FINISHED,
        "all good",
        0,
    )
    assert tool_call.result.handles == (
        ExecutionHandle(ExecutionHandleKind.SUBAGENT, "t1"),
    )
    assert tool_call.action == PollAction(tool_call.result.handles)


def test_task_stop_is_a_terminate_whose_target_is_killed():
    tool_call = _converted(
        _harness_tool_call(
            "TaskStop",
            {"task_id": "t1"},
            _result(
                '{"message":"Successfully stopped task: t1 (sleep 99)","task_id":"t1",'
                '"task_type":"local_bash","command":"sleep 99"}'
            ),
        )
    )
    assert (
        tool_call.result is not None and tool_call.result.execution_status is S.KILLED
    )
    assert tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "t1"),), None, True
    )


def test_other_tools_have_skipped_format():
    tool_call_result = _converted(
        _harness_tool_call("Agent", {"prompt": "p"}, _result("Async agent launched"))
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.execution_status,
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (
        S.UNKNOWN,
        UnmatchedFormat.SKIPPED,
        "Async agent launched",
    )


def test_bash_background_notice_that_warns_about_the_final_response_is_running():
    block = (
        "Command running in background with ID: b1a2c3d4e. Output is being written to: /tmp/b1a2c3d4e.output."
        " If it exits while you are still working you will be notified, but it is terminated when you give"
        " your final response.\nSession cwd remains /app; directory changes do not apply."
    )
    tool_call_result = _bash(block)
    assert tool_call_result is not None
    assert tool_call_result.harness_result_format == MatchedFormat("background_v3")
    assert (
        tool_call_result.execution_status,
        tool_call_result.output_path,
        tool_call_result.tool_output_text,
    ) == (
        S.RUNNING,
        "/tmp/b1a2c3d4e.output",
        "",
    )
    assert tool_call_result.handles == (
        ExecutionHandle(ExecutionHandleKind.COMMAND, "b1a2c3d4e"),
    )


def test_web_fetch_takes_the_http_status_from_the_structured_result():
    structured_result = {
        "bytes": 10,
        "code": 200,
        "codeText": "OK",
        "result": "No response from model",
    }
    tool_call_result = _converted(
        _harness_tool_call(
            "WebFetch",
            {"url": "u"},
            _result("No response from model", structured_result),
        )
    ).result
    assert tool_call_result is not None
    assert (tool_call_result.tool_output_text, tool_call_result.http_status) == (
        "",
        200,
    )


def test_content_items_join_their_texts_with_a_blank_line():
    items = [
        {"type": "text", "text": "a\n"},
        {"type": "image", "source": {}},
        {"type": "text", "text": "b"},
    ]
    assert _join_content_items(items) == "a\n\nb"
    assert _join_content_items([{"type": "image"}]) is None
    # Only items that are objects of type text add their text, and a text item without text adds nothing.
    assert _join_content_items([{"type": "document", "text": "x"}]) is None
    assert _join_content_items(["x", {"type": "text", "text": "a"}]) == "a"
    items = [{"type": "text", "text": None}, {"type": "text", "text": "a"}]
    assert _join_content_items(items) == "a"


def test_task_output_without_a_structured_result_has_no_json_object():
    harness_tool_call = _harness_tool_call("TaskOutput", {"task_id": "t1"}, {})
    assert CONVERTER.tool_result_json_of(harness_tool_call, _result("text")) is None


def test_only_a_read_without_text_and_with_an_image_is_an_image_read():
    image_of_bash = _converted_result("Bash", {"command": "x"}, _result([IMAGE]))
    assert image_of_bash.harness_result_format == UnmatchedFormat.UNKNOWN
    read_without_items = _converted_result("Read", {"file_path": "/a"}, _result([]))
    assert read_without_items.harness_result_format == UnmatchedFormat.UNKNOWN
    # Only the one item of a result without text is matched, and only an image item is an image read.
    for items in ([IMAGE, IMAGE], [{"type": "document", "source": {}}]):
        read_without_text = _converted_result(
            "Read", {"file_path": "/a"}, _result(items)
        )
        assert read_without_text.harness_result_format == UnmatchedFormat.UNKNOWN
    text_item = {"type": "text", "text": "1\ta\n"}
    read_with_text = _converted_result(
        "Read", {"file_path": "/a"}, _result([IMAGE, text_item])
    )
    assert read_with_text.harness_result_format == MatchedFormat("listing")
    # The only item of a result is matched as JSON only when the result has no text.
    read_of_one_text_item = _converted_result(
        "Read", {"file_path": "/a"}, _result([text_item])
    )
    assert read_of_one_text_item.harness_result_format == MatchedFormat("listing")


def test_harbor_image_item_without_a_metadata_block_is_an_image_read():
    result = {"content": json.dumps(IMAGE)}
    tool_call_result = _converted_result("Read", {"file_path": "/i.png"}, result)
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (MatchedFormat("image"), S.FINISHED)


def test_a_result_without_a_text_has_no_text_and_an_unknown_format():
    # A `raw_tool_result` without content, one with blank text, and content that is no string without a metadata block.
    for result in (_result(None), _result("  "), {"content": None}):
        assert _bash_format_and_text(result) == (UnmatchedFormat.UNKNOWN, None), result


def test_raw_tool_result_text_loses_its_edge_whitespace():
    harness_tool_call = _harness_tool_call("Bash", {"command": "x"}, {})
    raw_text = CONVERTER.tool_result_raw_text_of(harness_tool_call, _result("  out\n"))
    assert raw_text == "out"
    assert _bash_format_and_text(_result("  out\n"))[1] == "out"


def test_raw_tool_result_that_is_no_object_falls_back_to_content():
    metadata = {"raw_tool_result": "text"}
    result = {"content": "shown", "extra": {"tool_result_metadata": metadata}}
    assert _bash_format_and_text(result)[1] == "shown"


def test_content_that_is_not_all_harbor_items_stays_text_as_it_is():
    # A plain paragraph after an item, a JSON object of another type and JSON that is no object.
    for content in (
        '{"type": "text", "text": "a"}\n\nplain',
        '{"type": "module"}',
        "42",
    ):
        assert _bash_format_and_text({"content": content})[1] == content


def test_text_exit_code_output_path_handle_and_truncation_stay_beside_the_structured_result():
    exited = _bash("Exit code 2\nboom", {"stdout": "boom", "interrupted": False}, True)
    assert exited is not None and exited.exit_code == 2
    background = _bash(BACKGROUND_NOTICE, {"stdout": "", "interrupted": False})
    assert background is not None
    assert background.output_path == "/tmp/b1.output"
    assert background.handles == (ExecutionHandle(ExecutionHandleKind.COMMAND, "b1"),)
    cut = "head\n... [120 characters truncated] ...\ntail"
    truncated = _bash(
        "Exit code 1\n" + cut, {"stdout": cut, "interrupted": False}, True
    )
    assert truncated is not None and truncated.is_truncated is True


def test_structured_result_without_stdout_gives_empty_text():
    tool_call_result = _bash("shown", {"interrupted": False})
    assert tool_call_result is not None and tool_call_result.tool_output_text == ""


def test_structured_file_content_that_is_no_string_is_ignored():
    structured_result = {"type": "text", "file": {"filePath": "/a", "content": ["a"]}}
    result = _result("1\ta\n2\tb", structured_result)
    tool_call_result = _converted_result("Read", {"file_path": "/a"}, result)
    assert tool_call_result.tool_output_text == "a\nb"


def test_web_fetch_code_that_is_no_whole_number_is_no_http_status():
    for code in (True, "200"):
        result = _result("No response from model", {"code": code})
        tool_call_result = _converted_result("WebFetch", {"url": "u"}, result)
        assert tool_call_result.http_status is None, code
