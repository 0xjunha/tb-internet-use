"""Test the conversion of Antigravity CLI tool calls by the Antigravity CLI converter, with made-up results shaped as in the trajectories."""

from collections import Counter
from typing import Any

import pytest

from tb_internet_use.knowledge.tool_call_knowledge import ToolCallKnowledge
from tb_internet_use.tool_call import convert_tool_calls
from tb_internet_use.tool_call._convert_tool_calls import convert_one_tool_call
from tb_internet_use.tool_call.harnesses.antigravity_cli import (
    AntigravityCliConverter,
)
from tb_internet_use.tool_call.model import (
    EditFileAction,
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    MatchedFormat,
    OtherAction,
    PollAction,
    ReadFileAction,
    RunCommandAction,
    StartSubagentAction,
    ToolCallAction,
    ToolCallKey,
    ToolCallResult,
    UnknownAction,
    UnmatchedFormat,
    WebSearchAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_shell_text import parse_shell_text

S = ExecutionStatus
CONVERTER = AntigravityCliConverter()
# The timestamps that start a result of a call that completed, once or twice.
TIMESTAMPS_ONCE = (
    "Created At: 2026-11-13T02:21:04Z\nCompleted At: 2026-11-13T02:21:04Z\n"
)
TIMESTAMPS = TIMESTAMPS_ONCE * 2
# The timestamp that starts a result of a command sent to the background.
CREATED = "Created At: 2026-11-13T02:21:08Z\n"
TASK_ID = "c1/task-23"
LOG_PATH = "/root/.gemini/antigravity-cli/brain/c1/.system_generated/tasks/task-23.log"
SAVED_PATH = (
    "/root/.gemini/antigravity-cli/brain/c1/.system_generated/steps/39/output.txt"
)
TRUNCATED_HEAD = (
    f"The tool's output was truncated due to being too long. You can find the full output in a file at file://{SAVED_PATH}.\n\n"
    "Here is a preview with the middle of the output truncated:\n"
)
CUT_OUTPUT = "a\r\n<truncated 10 of 90 bytes from the middle of the output>\nz\r\n"
BACKGROUND = (
    f"{CREATED}Tool is running as a background task with task id: {TASK_ID}\n"
    "Task Description: python3 run.py\n"
    f"Task logs are available at: file://{LOG_PATH}"
)
BACKGROUND_INSTRUCTION = (
    "\nYOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS: A) either proceed to other relevant work (if any) or, B) simply update the user with a short message (that you have launched the command and will wait for it to finish) and end the turn.\n"
    " DO NOTHING ELSE.\n"
    " When updating the user, always respond in the language of the user (defaulting to English). Never mix two or more languages in the same response."
)
TASK_LOG = "Log output:\n<truncated 5 lines>\nstep 9\r\n\nLast progress: 3s ago\n"
FAILED = TIMESTAMPS + "Encountered error in step execution: file does not exist"
TASKS_JSON = '[{"taskId":"c1/task-23","toolName":"run_command"}]'
# The text that wraps every message that Antigravity CLI writes to the agent as a step, here from the task of `TASK_ID`.
MESSAGE_HEAD = (
    "The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important information to pay attention to.\n\n"
    f"<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-13T02:25:00Z sender={TASK_ID} priority=MESSAGE_PRIORITY_HIGH content="
)
MESSAGE_TAIL = f"\nLog: file://{LOG_PATH}\n</SYSTEM_MESSAGE>"
TASK_FINISHED = MESSAGE_HEAD + f'Task id "{TASK_ID}" finished with result:\n'


def _format(name: str) -> MatchedFormat:
    return MatchedFormat(name)


def _task_handles() -> tuple[ExecutionHandle, ...]:
    return (ExecutionHandle(ExecutionHandleKind.COMMAND, TASK_ID),)


def _task_status(status: str) -> str:
    return f"{TIMESTAMPS}Task: {TASK_ID}\nStatus: {status}\nLog: file://{LOG_PATH}\n"


# One made-up result per declared result format of Antigravity CLI, and the `ToolCallResult` it converts to.
# (tool, result text in the trajectory, expected result)
RESULT_FORMAT_CASES: list[tuple[str, str, ToolCallResult]] = [
    (
        "run_command",
        TIMESTAMPS + "Command exited with code 1.\n\nCommand output:\nerr\r\n",
        ToolCallResult(
            "err\r\n", S.FINISHED, 1, harness_result_format=_format("exited")
        ),
    ),
    (
        "run_command",
        TIMESTAMPS + "Command exited with code 0.\n\nNo output from the command.",
        ToolCallResult(
            "", S.FINISHED, 0, harness_result_format=_format("exited_silent")
        ),
    ),
    (
        "run_command",
        TIMESTAMPS_ONCE
        + TRUNCATED_HEAD
        + "Command exited with code 0.\n\nCommand output:\n"
        + CUT_OUTPUT,
        ToolCallResult(
            CUT_OUTPUT,
            S.FINISHED,
            0,
            output_path=SAVED_PATH,
            is_truncated=True,
            harness_result_format=_format("exited_truncated"),
        ),
    ),
    (
        "run_command",
        TIMESTAMPS_ONCE
        + TRUNCATED_HEAD
        + TIMESTAMPS_ONCE
        + "Command exited with code 0.\n\nCommand output:\n"
        + CUT_OUTPUT,
        ToolCallResult(
            CUT_OUTPUT,
            S.FINISHED,
            0,
            output_path=SAVED_PATH,
            is_truncated=True,
            harness_result_format=_format("exited_truncated_timestamped"),
        ),
    ),
    (
        "run_command",
        BACKGROUND + "\nLog output:\n<truncated 3 lines>\nstep 9\r\n",
        ToolCallResult(
            "<truncated 3 lines>\nstep 9\r\n",
            S.RUNNING,
            handles=_task_handles(),
            output_path=LOG_PATH,
            is_truncated=True,
            harness_result_format=_format("background_logged"),
        ),
    ),
    (
        "run_command",
        BACKGROUND,
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_task_handles(),
            output_path=LOG_PATH,
            harness_result_format=_format("background"),
        ),
    ),
    (
        "run_command",
        TIMESTAMPS_ONCE
        + "Encountered error in step execution: run_command: CommandLine is required",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
    (
        "manage_task",
        _task_status("RUNNING") + TASK_LOG,
        ToolCallResult(
            "<truncated 5 lines>\nstep 9\r\n",
            S.RUNNING,
            handles=_task_handles(),
            output_path=LOG_PATH,
            is_truncated=True,
            harness_result_format=_format("running_logged"),
        ),
    ),
    (
        "manage_task",
        _task_status("RUNNING"),
        ToolCallResult(
            "",
            S.RUNNING,
            handles=_task_handles(),
            output_path=LOG_PATH,
            harness_result_format=_format("running"),
        ),
    ),
    (
        "manage_task",
        _task_status("DONE") + "Log output:\nok\nLast progress: 1m2s ago\n",
        ToolCallResult(
            "ok",
            S.FINISHED,
            handles=_task_handles(),
            output_path=LOG_PATH,
            harness_result_format=_format("done_logged"),
        ),
    ),
    (
        "manage_task",
        _task_status("DONE"),
        ToolCallResult(
            "",
            S.FINISHED,
            handles=_task_handles(),
            output_path=LOG_PATH,
            harness_result_format=_format("done"),
        ),
    ),
    (
        "manage_task",
        f'{TIMESTAMPS}Task "{TASK_ID}" cancelled.',
        ToolCallResult(
            None,
            S.KILLED,
            handles=_task_handles(),
            harness_result_format=_format("cancelled"),
        ),
    ),
    (
        "manage_task",
        f'{TIMESTAMPS_ONCE}Encountered error in step execution: cannot kill task "{TASK_ID}": task is not running (status: DONE)',
        ToolCallResult(
            None,
            S.FINISHED,
            handles=_task_handles(),
            harness_result_format=_format("already_done"),
        ),
    ),
    (
        "manage_task",
        f'{TIMESTAMPS_ONCE}Encountered error in step execution: cannot kill task "{TASK_ID}": task is not running (status: CANCELED)',
        ToolCallResult(
            None,
            S.KILLED,
            handles=_task_handles(),
            harness_result_format=_format("already_cancelled"),
        ),
    ),
    (
        "manage_task",
        f'{TIMESTAMPS}Input sent to task "{TASK_ID}".',
        ToolCallResult(
            None,
            S.RUNNING,
            handles=_task_handles(),
            harness_result_format=_format("input_sent"),
        ),
    ),
    (
        "manage_task",
        TIMESTAMPS + "No background tasks are currently running.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("none_running")),
    ),
    (
        "manage_task",
        TIMESTAMPS + "You have 1 background task(s) currently running:\n" + TASKS_JSON,
        ToolCallResult(
            TASKS_JSON, S.FINISHED, harness_result_format=_format("listing")
        ),
    ),
    (
        "manage_task",
        TIMESTAMPS_ONCE
        + TRUNCATED_HEAD
        + "You have 1 background task(s) currently running:\n"
        + TASKS_JSON,
        ToolCallResult(
            TASKS_JSON,
            S.FINISHED,
            output_path=SAVED_PATH,
            is_truncated=True,
            harness_result_format=_format("listing_truncated"),
        ),
    ),
    (
        "manage_task",
        TIMESTAMPS_ONCE
        + TRUNCATED_HEAD
        + TIMESTAMPS_ONCE
        + "You have 1 background task(s) currently running:\n"
        + TASKS_JSON,
        ToolCallResult(
            TASKS_JSON,
            S.FINISHED,
            output_path=SAVED_PATH,
            is_truncated=True,
            harness_result_format=_format("listing_truncated_timestamped"),
        ),
    ),
    (
        "manage_task",
        TIMESTAMPS_ONCE
        + "Error invalid tool call: invalid arguments:\n- at '/Action': value must be one of 'list', 'kill', 'status', 'send_input'",
        ToolCallResult(
            "", S.NOT_RUN, harness_result_format=_format("rejected_arguments")
        ),
    ),
    (
        "manage_task",
        TIMESTAMPS_ONCE
        + 'Encountered error in step execution: invalid task ID format: "c1"',
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
    (
        "SYSTEM_MESSAGE",
        TASK_FINISHED
        + "Command exited with code 1.\n\nCommand output:\nerr\r\n"
        + MESSAGE_TAIL,
        ToolCallResult(
            "err\r\n",
            S.FINISHED,
            1,
            handles=_task_handles(),
            harness_result_format=_format("exited"),
        ),
    ),
    (
        "SYSTEM_MESSAGE",
        TASK_FINISHED
        + "Command exited with code 0.\n\nNo output from the command."
        + MESSAGE_TAIL,
        ToolCallResult(
            "",
            S.FINISHED,
            0,
            handles=_task_handles(),
            harness_result_format=_format("exited_silent"),
        ),
    ),
    (
        "SYSTEM_MESSAGE",
        TASK_FINISHED
        + TRUNCATED_HEAD
        + "Command exited with code 0.\n\nCommand output:\n"
        + CUT_OUTPUT
        + MESSAGE_TAIL,
        ToolCallResult(
            CUT_OUTPUT,
            S.FINISHED,
            0,
            handles=_task_handles(),
            output_path=SAVED_PATH,
            is_truncated=True,
            harness_result_format=_format("exited_truncated"),
        ),
    ),
    (
        "SYSTEM_MESSAGE",
        MESSAGE_HEAD.replace("PRIORITY_HIGH", "PRIORITY_LOW")
        + f'Task id "{TASK_ID}" was canceled with result:\nTool execution was canceled'
        + MESSAGE_TAIL,
        ToolCallResult(
            None,
            S.KILLED,
            handles=_task_handles(),
            harness_result_format=_format("cancelled"),
        ),
    ),
    (
        "read_file",
        TIMESTAMPS + "Showing lines 1-2 of 2\n1: a\n2: b\n(no newline at end of file)",
        ToolCallResult(
            "a\nb",
            S.FINISHED,
            harness_result_format=_format("listing_without_final_newline"),
        ),
    ),
    (
        "read_file",
        TIMESTAMPS + "Showing lines 3-5 of 9\n3: a\n4: \n5: 6: b",
        ToolCallResult(
            "a\n\n6: b", S.FINISHED, harness_result_format=_format("listing")
        ),
    ),
    (
        "read_file",
        TIMESTAMPS
        + "Partial read (lines 1-2 of 2). Showing bytes 0-8 of 20 in this line range, truncated at the 8-byte limit. "
        + "To read the rest of this line range, call this tool again with the same StartLine and EndLine and ByteOffset=8.\n1: abcd\n2: a",
        ToolCallResult(
            "abcd\na",
            S.FINISHED,
            is_truncated=True,
            harness_result_format=_format("partial_listing_truncated"),
        ),
    ),
    (
        "read_file",
        TIMESTAMPS
        + "Partial read (lines 1-2 of 2). Showing bytes 8-20 of 20 in this line range.\nbcd\n2: efgh",
        ToolCallResult(
            "bcd\nefgh", S.FINISHED, harness_result_format=_format("partial_listing")
        ),
    ),
    (
        "read_file",
        TIMESTAMPS + "File is empty",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("empty")),
    ),
    (
        "read_file",
        TIMESTAMPS + "Showing binary file of type image/png",
        ToolCallResult(None, S.FINISHED, harness_result_format=_format("binary")),
    ),
    (
        "read_file",
        FAILED,
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
    (
        "write_file",
        TIMESTAMPS + "Created file.",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("created")),
    ),
    (
        "write_file",
        TIMESTAMPS_ONCE
        + "Encountered error in step execution: /app/a.txt already exists. To overwrite it, retry with Overwrite=true.",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
    (
        "edit_file",
        TIMESTAMPS
        + "Made 1 replacement in /app/a.py starting at line 3 (+2/-1 lines).",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("edited")),
    ),
    (
        "edit_file",
        TIMESTAMPS
        + "Made 2 replacements in /app/a.py starting at line 3 (+2/-2 lines).",
        ToolCallResult("", S.FINISHED, harness_result_format=_format("edited_several")),
    ),
    (
        "edit_file",
        TIMESTAMPS_ONCE
        + "Encountered error in step execution: target content not found in the file",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
    (
        "search_web",
        TIMESTAMPS
        + 'The search for "pytest fixtures" returned the following summary:\nFixtures are functions.\n\n'
        + "Note: Source URLs are HTTP redirects; check where they resolve if you need the direct link.",
        ToolCallResult(
            "Fixtures are functions.",
            S.FINISHED,
            harness_result_format=_format("summary"),
        ),
    ),
    (
        "search_web",
        TIMESTAMPS_ONCE
        + "Encountered error in step execution: no candidates returned by the model",
        ToolCallResult("", S.NOT_RUN, harness_result_format=_format("failed")),
    ),
]


# A made-up call of each tool with argument rows in the harness tool catalog, whose action is a poll or that is Deferred, and the `ToolCallAction` it converts to without a result.
# Every argument row has a case, and every `PollAction` states its `terminate`.
# (tool, arguments in the trajectory, expected action)
ACTION_CASES: list[tuple[str, dict[str, Any], ToolCallAction]] = [
    (
        "run_command",
        {"CommandLine": "ls /app", "WaitMsBeforeAsync": 5000, "toolSummary": "List"},
        RunCommandAction(
            "ls /app", parse_shell_text("ls /app", judgment_rule_use_counts=Counter())
        ),
    ),
    (
        "read_file",
        {"Path": "/app/a.py", "StartLine": 10, "EndLine": 20},
        ReadFileAction("/app/a.py", 10),
    ),
    (
        "edit_file",
        {"Path": "/app/a.py", "Target": "x = 1", "Replacement": "x = 2"},
        EditFileAction("/app/a.py", "x = 1", "x = 2"),
    ),
    (
        "search_web",
        {"query": "pytest fixtures", "domain": "docs.pytest.org"},
        WebSearchAction(("pytest fixtures",)),
    ),
    ("invoke_subagent", {"Prompt": "find the bug", "Role": "r"}, StartSubagentAction()),
    (
        "send_message",
        {"Recipient": "a5f5", "Message": "go on"},
        PollAction(
            (ExecutionHandle(ExecutionHandleKind.SUBAGENT, "a5f5"),), terminate=False
        ),
    ),
    (
        "write_file",
        {"Path": "/app/a.txt", "Content": "hi", "Overwrite": True},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    # An appending write does not show the text the file held before.
    (
        "write_file",
        {"Path": "/app/a.txt", "Content": "hi", "Append": True},
        EditFileAction("/app/a.txt", None, "hi"),
    ),
    (
        "write_file",
        {"Path": "/app/a.txt", "Content": "hi", "Append": False},
        WriteFileAction("/app/a.txt", "hi"),
    ),
    (
        "manage_task",
        {"Action": "status", "TaskId": TASK_ID},
        PollAction(_task_handles(), terminate=False),
    ),
    (
        "manage_task",
        {"Action": "kill", "TaskId": TASK_ID},
        PollAction(_task_handles(), terminate=True),
    ),
    (
        "manage_task",
        {"Action": "send_input", "TaskId": TASK_ID, "Input": "y\n"},
        PollAction(_task_handles(), "y\n", terminate=False),
    ),
    # Made-up arguments that are no text, which leave their fields empty as for a tool with a label.
    (
        "write_file",
        {"Path": ["/app/a.txt"], "Content": {"text": "hi"}},
        WriteFileAction(None, None),
    ),
    (
        "manage_task",
        {"Action": "send_input", "TaskId": TASK_ID, "Input": ["y"]},
        PollAction(_task_handles(), None, terminate=False),
    ),
    ("manage_task", {"Action": "list"}, OtherAction()),
    ("manage_task", {"Action": "kill_all"}, UnknownAction()),
]


def _harness_tool_call(
    tool: str, args: dict[str, Any], content: str
) -> HarnessToolCall:
    """Make a call of a tool with its result text, or for `SYSTEM_MESSAGE` a message of a step after the call, which `parse_trajectory` gives with no id, no arguments and `is_harness_message` true."""
    if tool == "SYSTEM_MESSAGE":
        return HarnessToolCall(
            ToolCallKey("t", "main", 2, 0),
            HarnessTool("antigravity-cli", tool),
            "",
            {},
            {"content": content},
            is_harness_message=True,
        )
    return HarnessToolCall(
        ToolCallKey("t", "main", 1, 0),
        HarnessTool("antigravity-cli", tool),
        "id",
        args,
        {"content": content},
    )


def _converted(harness_tool_call: HarnessToolCall):
    return convert_one_tool_call(
        harness_tool_call,
        CONVERTER,
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )


def _action_of_call_without_result(tool: str, args: dict[str, Any]) -> ToolCallAction:
    """Convert one call of Antigravity CLI without a result through `convert_tool_calls`, which picks the converter of the harness, and give its action."""
    [tool_call] = convert_tool_calls(
        [
            HarnessToolCall(
                ToolCallKey("t", "main", 1, 0),
                HarnessTool("antigravity-cli", tool),
                "id",
                args,
                None,
            )
        ],
        knowledge=ToolCallKnowledge(),
        judgment_rule_use_counts=Counter(),
    )
    return tool_call.action


@pytest.mark.parametrize(("tool", "args", "expected"), ACTION_CASES)
def test_a_call_of_each_tool_converts_to_the_action_of_its_arguments(
    tool: str, args: dict[str, Any], expected: ToolCallAction
):
    assert _action_of_call_without_result(tool, args) == expected


@pytest.mark.parametrize(("tool", "content", "expected"), RESULT_FORMAT_CASES)
def test_a_result_of_each_declared_format_converts_to_its_fields(
    tool: str, content: str, expected: ToolCallResult
):
    assert _converted(_harness_tool_call(tool, {}, content)).result == expected


def test_the_instruction_after_a_background_command_is_cut_and_the_log_ends_before_it():
    tool_call_result = _converted(
        _harness_tool_call(
            "run_command",
            {"CommandLine": "python3 run.py"},
            BACKGROUND + "\nLog output:\nstep 1\r\n" + BACKGROUND_INSTRUCTION,
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
        tool_call_result.is_truncated,
    ) == (_format("background_logged"), "step 1\r\n", None)


def test_a_multiline_command_in_the_task_description_stays_out_of_the_handle_and_path():
    content = BACKGROUND.replace("python3 run.py", "cat <<'EOF' > a.py\nprint(1)\nEOF")
    tool_call_result = _converted(_harness_tool_call("run_command", {}, content)).result
    assert tool_call_result is not None
    assert (tool_call_result.handles, tool_call_result.output_path) == (
        _task_handles(),
        LOG_PATH,
    )


def test_a_result_that_is_a_message_about_another_task_is_unknown():
    # Antigravity CLI put a message about the end of another task in place of the result of a call 7 times in the trajectories.
    content = (
        "The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important information to pay attention to.\n\n"
        '<SYSTEM_MESSAGE>\n[Message] sender=c1/task-34 content=Task id "c1/task-34" finished with result:\n'
        "Command exited with code 0.\n</SYSTEM_MESSAGE>"
    )
    tool_call_result = _converted(_harness_tool_call("run_command", {}, content)).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.execution_status,
    ) == (UnmatchedFormat.UNKNOWN, S.UNKNOWN)


def test_a_kill_of_a_task_polls_it_and_stops_it():
    tool_call = _converted(
        _harness_tool_call(
            "manage_task",
            {"Action": "kill", "TaskId": TASK_ID},
            f'{TIMESTAMPS}Task "{TASK_ID}" cancelled.',
        )
    )
    assert tool_call.action == PollAction(_task_handles(), None, True)
    assert (
        tool_call.result is not None and tool_call.result.execution_status is S.KILLED
    )


def test_a_message_of_the_end_of_a_task_polls_the_task_it_names():
    tool_call = _converted(
        _harness_tool_call(
            "SYSTEM_MESSAGE",
            {},
            TASK_FINISHED
            + "Command exited with code 0.\n\nCommand output:\nok\n"
            + MESSAGE_TAIL,
        )
    )
    assert tool_call.action == PollAction(_task_handles(), None, False)


def test_the_log_line_ends_the_output_of_a_task_whose_output_ends_without_a_newline():
    # The output ends without a newline 35 times in the trajectories, and the log line then follows its last line at once.
    tool_call_result = _converted(
        _harness_tool_call(
            "SYSTEM_MESSAGE",
            {},
            TASK_FINISHED
            + "Command exited with code 0.\n\nCommand output:\nok"
            + MESSAGE_TAIL,
        )
    ).result
    assert tool_call_result is not None
    assert (
        tool_call_result.harness_result_format,
        tool_call_result.tool_output_text,
    ) == (_format("exited"), "ok")


def test_a_timer_prompt_that_spells_the_end_of_another_task_is_no_end_of_that_task():
    # A made-up prompt of a timer that the agent set with `schedule`, whose sender is the timer's own task `c1/task-30` and whose content reads like the end of `TASK_ID`.
    tool_call = _converted(
        _harness_tool_call(
            "SYSTEM_MESSAGE",
            {},
            MESSAGE_HEAD.replace(f"sender={TASK_ID}", "sender=c1/task-30")
            + f'Task id "{TASK_ID}" finished with result:\n'
            + "Command exited with code 0.\n\nNo output from the command."
            + MESSAGE_TAIL,
        )
    )
    assert tool_call.action == UnknownAction()
    assert tool_call.result is not None
    assert tool_call.result.harness_result_format == UnmatchedFormat.UNKNOWN


def test_a_message_in_no_declared_format_is_an_unknown_action_with_an_unknown_status():
    # The prompt of a timer that the agent set with `schedule`, which Antigravity CLI sends back when the timer goes off.
    tool_call = _converted(
        _harness_tool_call(
            "SYSTEM_MESSAGE",
            {},
            MESSAGE_HEAD.replace(TASK_ID, "c1/task-30")
            + "Check task-23 completion\n</SYSTEM_MESSAGE>",
        )
    )
    assert tool_call.action == UnknownAction()
    assert tool_call.result is not None
    assert (
        tool_call.result.harness_result_format,
        tool_call.result.execution_status,
        tool_call.result.handles,
    ) == (UnmatchedFormat.UNKNOWN, S.UNKNOWN, ())
