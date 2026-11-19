"""Declare the result formats of Antigravity CLI tools and the notices Antigravity CLI adds to their results."""

from collections.abc import Mapping

from tb_internet_use.knowledge.harness_result_format_declaration import (
    HarnessNotice,
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
    MatchedValues,
    strip_line_numbers,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

_TIMESTAMPS = "Created At: {created_at:line}\nCompleted At: {completed_at:line}\n"
# Antigravity CLI starts every result with the time the call was created, and with the time it completed once it has, once or twice.
_NOTICES = (
    HarnessNotice("timestamps", _TIMESTAMPS, at="start"),
    HarnessNotice("creation_timestamp", "Created At: {created_at:line}\n", at="start"),
)
# Antigravity CLI ends some results of a command sent to the background with this instruction to the model.
_BACKGROUND_INSTRUCTION = HarnessNotice(
    "background_instruction",
    "\nYOU MUST TAKE ONE OF THE FOLLOWING TWO ACTIONS: A) either proceed to other relevant work (if any) or, B) simply update the user with a short message (that you have launched the command and will wait for it to finish) and end the turn.\n"
    " DO NOTHING ELSE.\n"
    " When updating the user, always respond in the language of the user (defaulting to English). Never mix two or more languages in the same response.",
    at="end",
)

# Any tool's call that Antigravity CLI reports as failed, e.g. `file does not exist`.
_FAILED = Text(
    "failed",
    "Encountered error in step execution: {reason:text}",
    judgment_rule="treat_tool_failure_message_as_not_run",
)
# Antigravity CLI writes this before a preview of a result that was too long, with the whole result in the file it names.
_TRUNCATED_HEAD = (
    "The tool's output was truncated due to being too long. You can find the full output in a file at file://{output_path:line}.\n\n"
    "Here is a preview with the middle of the output truncated:\n"
)
# The marker that a log output starts with when its first lines are left out.
_CUT_LOG_MARKER = "<truncated {line_count:int} lines>"


def _listing_text_of(matched_values: MatchedValues) -> str:
    """Give the file text of a listing without the line number and `: ` that start each line."""
    return strip_line_numbers(str(matched_values["tool_output"]), ": ")


_EXITED = (
    "Command exited with code {exit_code:int}.\n\nCommand output:\n{tool_output:text}"
)
_BACKGROUND = (
    "Tool is running as a background task with task id: {handle:word}\n"
    "Task Description: {command:text}\n"
    "Task logs are available at: file://{output_path:line}"
)
_RUN_COMMAND = HarnessResultFormatList[str](
    (
        Text("exited", _EXITED, S.FINISHED),
        Text(
            "exited_silent",
            "Command exited with code {exit_code:int}.\n\nNo output from the command.",
            S.FINISHED,
        ),
        Text(
            "exited_truncated", _TRUNCATED_HEAD + _EXITED, S.FINISHED, is_truncated=True
        ),
        Text(
            "exited_truncated_timestamped",
            _TRUNCATED_HEAD + _TIMESTAMPS + _EXITED,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "background_logged",
            _BACKGROUND + "\nLog output:\n{tool_output:text}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            truncation_marker=_CUT_LOG_MARKER,
        ),
        Text(
            "background",
            _BACKGROUND,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _FAILED,
    ),
    notices=(*_NOTICES, _BACKGROUND_INSTRUCTION),
)

_READ_FILE = HarnessResultFormatList[str](
    (
        Text(
            "listing_without_final_newline",
            "Showing lines {first_line:int}-{last_line:int} of {line_count:int}\n{tool_output:text}\n(no newline at end of file)",
            S.FINISHED,
            text_from_matched_values=_listing_text_of,
        ),
        Text(
            "listing",
            "Showing lines {first_line:int}-{last_line:int} of {line_count:int}\n{tool_output:text}",
            S.FINISHED,
            text_from_matched_values=_listing_text_of,
        ),
        Text(
            "partial_listing_truncated",
            "Partial read (lines {first_line:int}-{last_line:int} of {line_count:int}). Showing bytes {first_byte:int}-{end_byte:int} of {byte_count:int} in this line range, truncated at the {byte_limit:int}-byte limit. "
            "To read the rest of this line range, call this tool again with the same StartLine and EndLine and ByteOffset={next_byte:int}.\n{tool_output:text}",
            S.FINISHED,
            is_truncated=True,
            text_from_matched_values=_listing_text_of,
        ),
        Text(
            "partial_listing",
            "Partial read (lines {first_line:int}-{last_line:int} of {line_count:int}). Showing bytes {first_byte:int}-{end_byte:int} of {byte_count:int} in this line range.\n{tool_output:text}",
            S.FINISHED,
            text_from_matched_values=_listing_text_of,
        ),
        Text("empty", "File is empty", S.FINISHED),
        Text(
            "binary",
            "Showing binary file of type {media_type:rest_of_line}",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        _FAILED,
    ),
    notices=_NOTICES,
)

_EDIT_TAIL = " in {path:line} starting at line {first_line:int} (+{added_line_count:int}/-{removed_line_count:int} lines)."
_EDIT_FILE = HarnessResultFormatList[str](
    (
        Text("edited", "Made 1 replacement" + _EDIT_TAIL, S.FINISHED),
        Text(
            "edited_several",
            "Made {replacement_count:int} replacements" + _EDIT_TAIL,
            S.FINISHED,
        ),
        _FAILED,
    ),
    notices=_NOTICES,
)

_WRITE_FILE = HarnessResultFormatList[str](
    (Text("created", "Created file.", S.FINISHED), _FAILED),
    notices=_NOTICES,
)

_SEARCH_WEB = HarnessResultFormatList[str](
    (
        Text(
            "summary",
            'The search for "{query:line}" returned the following summary:\n{tool_output:text}'
            "\n\nNote: Source URLs are HTTP redirects; check where they resolve if you need the direct link.",
            S.FINISHED,
        ),
        _FAILED,
    ),
    notices=_NOTICES,
)


def _task_status_template_for(status: str) -> str:
    """Build the template of a `manage_task` status result of a task in one state, up to its log path."""
    return (
        "Task: {handle:word}\n"
        + f"Status: {status}\n"
        + "Log: file://{output_path:line}\n"
    )


_TASK_LOG = "Log output:\n{tool_output:text}\nLast progress: {progress:line} ago\n"
_NOT_RUNNING = 'Encountered error in step execution: cannot kill task "{handle:word}": task is not running '
_TASK_LISTING = "You have {task_count:int} background task(s) currently running:\n{tool_output:text}"
_MANAGE_TASK = HarnessResultFormatList[str](
    (
        Text(
            "running_logged",
            _task_status_template_for("RUNNING") + _TASK_LOG,
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            truncation_marker=_CUT_LOG_MARKER,
        ),
        Text(
            "running",
            _task_status_template_for("RUNNING"),
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "done_logged",
            _task_status_template_for("DONE") + _TASK_LOG,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            truncation_marker=_CUT_LOG_MARKER,
        ),
        Text(
            "done",
            _task_status_template_for("DONE"),
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "cancelled",
            'Task "{handle:word}" cancelled.',
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "already_done",
            _NOT_RUNNING + "(status: DONE)",
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "already_cancelled",
            _NOT_RUNNING + "(status: CANCELED)",
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "input_sent",
            'Input sent to task "{handle:word}".',
            judgment_rule="treat_written_input_as_running_target",
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text("none_running", "No background tasks are currently running.", S.FINISHED),
        Text("listing", _TASK_LISTING, S.FINISHED),
        Text(
            "listing_truncated",
            _TRUNCATED_HEAD + _TASK_LISTING,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "listing_truncated_timestamped",
            _TRUNCATED_HEAD + _TIMESTAMPS + _TASK_LISTING,
            S.FINISHED,
            is_truncated=True,
        ),
        Text(
            "rejected_arguments",
            "Error invalid tool call: invalid arguments:\n{reason:text}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
        _FAILED,
    ),
    notices=_NOTICES,
)

# Antigravity CLI wraps every message it writes to the agent as a step in this text, with the task id of a task's end as the sender.
# The sender must be the task id that the content names, so that the prompt of a `schedule` timer, whose sender is the timer's task and whose content the agent wrote, never passes for the end of another task.
_MESSAGE_HEAD = (
    "The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important information to pay attention to.\n\n"
    "<SYSTEM_MESSAGE>\n[Message] timestamp={timestamp:word} sender={handle:word} priority={priority:word} content="
)
# A task's end names the log of the task, which the result of the `run_command` that started it named as its output path.
_MESSAGE_TAIL = "\nLog: file://{log_path:line}\n</SYSTEM_MESSAGE>"
_TASK_FINISHED = _MESSAGE_HEAD + 'Task id "{handle:word}" finished with result:\n'
# The text after `finished with result:` is the one that `run_command` gives a command that ends before it is sent to the background.
_SYSTEM_MESSAGE = HarnessResultFormatList[str](
    (
        Text(
            "exited",
            _TASK_FINISHED + _EXITED + _MESSAGE_TAIL,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited_silent",
            _TASK_FINISHED
            + "Command exited with code {exit_code:int}.\n\nNo output from the command."
            + _MESSAGE_TAIL,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "exited_truncated",
            _TASK_FINISHED + _TRUNCATED_HEAD + _EXITED + _MESSAGE_TAIL,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        # Antigravity CLI writes this after a `manage_task` kill of the task, and a few times without one.
        # It holds none of the output of the task, so its tool output text is None, since "" would say that the command printed nothing.
        Text(
            "cancelled",
            _MESSAGE_HEAD
            + 'Task id "{handle:word}" was canceled with result:\nTool execution was canceled'
            + _MESSAGE_TAIL,
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
            no_tool_output_text=True,
        ),
    )
)


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "run_command": HarnessToolResultDeclaration(text_formats=_RUN_COMMAND),
    "manage_task": HarnessToolResultDeclaration(text_formats=_MANAGE_TASK),
    "read_file": HarnessToolResultDeclaration(text_formats=_READ_FILE),
    "write_file": HarnessToolResultDeclaration(text_formats=_WRITE_FILE),
    "edit_file": HarnessToolResultDeclaration(text_formats=_EDIT_FILE),
    "search_web": HarnessToolResultDeclaration(text_formats=_SEARCH_WEB),
    # Not a tool but a step that Antigravity CLI writes to the agent, which `parse_trajectory` reads as a call.
    "SYSTEM_MESSAGE": HarnessToolResultDeclaration(text_formats=_SYSTEM_MESSAGE),
}
