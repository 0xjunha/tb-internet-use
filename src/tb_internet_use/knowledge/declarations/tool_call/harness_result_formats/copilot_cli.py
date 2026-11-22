"""Declare the result formats of Copilot CLI tools.

A result here is the text that Copilot CLI gave the model, without the JSON line that Harbor writes after it, which `CopilotCliConverter` cuts.
Copilot CLI marks a failed call with `success: false`, and its results then follow the lists for results marked as errors.
"""

from collections.abc import Mapping

from tb_internet_use.knowledge.declarations.tool_call.harness_result_format_declaration import (
    HarnessResultFormatList,
    HarnessTextResultFormat,
    HarnessToolResultDeclaration,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandleKind,
    ExecutionStatus,
)

S = ExecutionStatus
Text = HarnessTextResultFormat

# The last line of the result of a shell command that ended.
_EXITED = "<shellId: {handle:id} completed with exit code {exit_code:int}>"
_STILL_RUNNING = "<command with shellId: {handle:id} is still running after {seconds:int} seconds. The command is still running"
# Copilot CLI writes a long output to a file and shows only its start.
_SAVED_HEAD = (
    "Output too large to read at once ({size:line_without_brackets}). Saved to: {output_path:line}\n"
    "Consider using tools like {hint:line}\n\nPreview (first {preview:int} chars):\n"
)
# The result of a failed shell call shows its message twice with this line between, which holds the rest of the result as JSON, e.g. `Command not executed. ...`, then `{"detailedContent": ...}`, then `Command not executed. ...` again.
_RESULT_JSON_LINE = '\n{"detailedContent": {result_json:rest_of_line}\n'

_SHELL_SAVED = Text(
    "exited_saved",
    _SAVED_HEAD + "{tool_output:text}\n" + _EXITED,
    S.FINISHED,
    is_truncated=True,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_SHELL_EXITED = Text(
    "exited",
    "{tool_output:text}\n" + _EXITED,
    S.FINISHED,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_SHELL_RUNNING_SILENT = Text(
    "running_silent",
    _STILL_RUNNING + " but hasn't produced output yet. {note:line}>",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)
_SHELL_RUNNING = Text(
    "running",
    "{tool_output:text}\n" + _STILL_RUNNING + ". {note:line}>",
    S.RUNNING,
    fixed_handle_kind=ExecutionHandleKind.COMMAND,
)

_BASH = HarnessResultFormatList[str](
    (
        _SHELL_SAVED,
        Text(
            "exited_compacted",
            "Shell output was automatically compacted. Compacted output below. Original at {output_path:line}; {hint:line}\n\n"
            "{tool_output:text}\n" + _EXITED,
            S.FINISHED,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _SHELL_EXITED,
        _SHELL_RUNNING_SILENT,
        _SHELL_RUNNING,
        Text(
            "background",
            "<command started in background with shellId: {handle:id}>",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "background_detached",
            "<command started in detached background with shellId: {handle:id}>",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
    )
)
_BASH_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "not_executed",
            "Command not executed. {reason:line}"
            + _RESULT_JSON_LINE
            + "Command not executed. {reason_again:rest_of_line}",
            S.NOT_RUN,
        ),
        Text(
            "blocked",
            "Command blocked: {reason:line}"
            + _RESULT_JSON_LINE
            + "Command blocked: {reason_again:rest_of_line}",
            S.NOT_RUN,
        ),
    )
)

_DETACHED_EXITED = "<detached command with shellId: {handle:id} completed with exit code {exit_code:int}>"
_READ_BASH = HarnessResultFormatList[str](
    (
        _SHELL_SAVED,
        _SHELL_EXITED,
        Text(
            "detached_exited",
            "Output:\n{tool_output:text}\n" + _DETACHED_EXITED,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        Text(
            "detached_exited_silent",
            _DETACHED_EXITED,
            S.FINISHED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _SHELL_RUNNING_SILENT,
        Text(
            "running_saved",
            _SAVED_HEAD + "{tool_output:text}\n" + _STILL_RUNNING + ". {note:line}>",
            S.RUNNING,
            is_truncated=True,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
        _SHELL_RUNNING,
    )
)
_READ_BASH_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "invalid_delay",
            "Invalid delay: {reason:line}"
            + _RESULT_JSON_LINE
            + "Invalid delay: {reason_again:rest_of_line}",
            judgment_rule="treat_tool_failure_message_as_not_run",
        ),
    )
)

_STOP_BASH = HarnessResultFormatList[str](
    (
        Text(
            "stopped",
            "<command with id: {handle:id} stopped>",
            S.KILLED,
            fixed_handle_kind=ExecutionHandleKind.COMMAND,
        ),
    )
)
_STOP_BASH_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "unknown_shell",
            "Unknown shell ID. No command was stopped. {hint:line}"
            + _RESULT_JSON_LINE
            + "Unknown shell ID. No command was stopped. {hint_again:rest_of_line}",
            S.NOT_RUN,
        ),
    )
)

_VIEW = HarnessResultFormatList[str](
    (
        Text(
            "image",
            "Viewed image file successfully.",
            S.FINISHED,
            no_tool_output_text=True,
        ),
        Text(
            "too_large",
            "File too large to read at once ({size:line_without_brackets}). {hint:rest_of_line}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        # An empty file or folder shows no text, and Harbor writes the diff of its empty content in its place.
        Text(
            "empty_folder",
            "\ndiff --git a/{path_a:line} b/{path_b:line}\ncreate file mode 100644\nindex 0000000..0000000\n"
            "--- a/dev/null\n+++ b/{path_new:line}\n@@ -1,0 +1,0 @@\n\n",
            S.FINISHED,
        ),
        Text(
            "empty_file",
            "\ndiff --git a/{path_a:line} b/{path_b:line}\nindex 0000000..0000000 100644\n"
            "--- a/{path_old:line}\n+++ b/{path_new:line}\n@@ -1,0 +1,0 @@\n\n",
            S.FINISHED,
        ),
        Text(
            "listing_truncated",
            "{tool_output:text}\n\n[Output truncated. {note:rest_of_line}",
            S.FINISHED,
            is_truncated=True,
        ),
        Text("listing", "{tool_output:text}", S.FINISHED),
    )
)
_VIEW_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "missing",
            "Path {path:line} does not exist. Please provide a valid path.\nPath does not exist",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "invalid_range",
            "Invalid view_range: {reason:line}\n{short_reason:rest_of_line}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
    )
)

_INVALID_INPUT = Text(
    "invalid_input",
    "Invalid input: {reason:line}\n{reason_again:rest_of_line}",
    judgment_rule="treat_tool_failure_message_as_not_run",
)

_CREATE = HarnessResultFormatList[str](
    (
        Text(
            "created",
            "Created file {path:line} with {characters:int} characters",
            S.FINISHED,
        ),
    )
)
_CREATE_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "exists",
            "Path {path:line} already exists as a file. Use `view` to check contents then edit it.\nPath already exists",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        Text(
            "parent_missing",
            "Parent directory {path:line} does not exist. You need to create it before creating the file.\n"
            "Parent directory does not exist",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        _INVALID_INPUT,
        Text(
            "arguments_cut",
            "The response reached its output token limit while the arguments for the tool call '{tool:line}' were still being written, "
            "so they arrived truncated and have been cleared. This tool call was NOT executed and nothing was changed. {hint:line}\n"
            "Tool call arguments truncated by the model output token limit",
            S.NOT_RUN,
        ),
    )
)

_EDIT = HarnessResultFormatList[str](
    (
        Text("updated", "File {path:line} updated with changes.", S.FINISHED),
        Text(
            "same_strings",
            "No changes made: old_str and new_str are the same",
            S.NOT_RUN,
        ),
    )
)
_EDIT_FAILED = HarnessResultFormatList[str](
    (
        Text(
            "not_found",
            "No match found: old_str not found in {path:line}; no changes made; {hint:line}\nNo match found",
            S.NOT_RUN,
        ),
        Text(
            "failed",
            "Failed to execute `edit` on {path:line} due to error: {reason:line}\nUnhandled error: {reason_again:rest_of_line}",
            judgment_rule="treat_failed_file_tool_call_as_not_run",
        ),
        _INVALID_INPUT,
    )
)


def _patch_summary_template_for(*changes: str) -> str:
    """Build the template of a patch result, one line per kind of change, e.g. `Added 1 file(s): /app/a.py`."""
    return "\n".join(
        f"{change} {{{change.lower()}_count:int}} file(s): {{{change.lower()}_paths:rest_of_line}}"
        for change in changes
    )


_APPLY_PATCH = HarnessResultFormatList[str](
    (
        Text("added", _patch_summary_template_for("Added"), S.FINISHED),
        Text("modified", _patch_summary_template_for("Modified"), S.FINISHED),
        Text("deleted", _patch_summary_template_for("Deleted"), S.FINISHED),
        Text(
            "added_modified",
            _patch_summary_template_for("Added", "Modified"),
            S.FINISHED,
        ),
        Text(
            "added_modified_deleted",
            _patch_summary_template_for("Added", "Modified", "Deleted"),
            S.FINISHED,
        ),
    )
)

# A `task` with `mode` `background` returns at once with the id of its subagent, which `read_agent` takes as `agent_id`.
# A `task` without it returns the last message of its subagent.
_TASK = HarnessResultFormatList[str](
    (
        Text(
            "background",
            "Agent started in background with agent_id: {handle:id}. {hint:rest_of_line}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
        ),
        Text("finished", "{tool_output:text}", S.FINISHED),
    )
)

# The first line of a `read_agent` result names the subagent and its state. An idle subagent has ended its turn and waits for a message, and its last message follows.
_AGENT_LINE = "agent_id: {handle:id}, agent_type: {agent_type:line}, status: "
_READ_AGENT = HarnessResultFormatList[str](
    (
        Text(
            "idle",
            "Agent is idle (waiting for messages). "
            + _AGENT_LINE
            + "idle, description: {description:rest_of_line}\n\n[Turn {turn:int}]\n{tool_output:text}",
            judgment_rule="treat_idle_subagent_as_unknown_status",
            fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
        ),
        Text(
            "running_after_wait",
            "Agent is still running after waiting {seconds:int}s. "
            + _AGENT_LINE
            + "running, description: {description:rest_of_line}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
        ),
        Text(
            "running",
            "Agent is still running. "
            + _AGENT_LINE
            + "running, description: {description:rest_of_line}",
            S.RUNNING,
            fixed_handle_kind=ExecutionHandleKind.SUBAGENT,
        ),
    )
)
_READ_AGENT_FAILED = HarnessResultFormatList[str]((_INVALID_INPUT,))


RESULT_FORMATS_BY_TOOL: Mapping[str, HarnessToolResultDeclaration] = {
    "bash": HarnessToolResultDeclaration(
        text_formats=_BASH, text_formats_when_marked_as_error=_BASH_FAILED
    ),
    "read_bash": HarnessToolResultDeclaration(
        text_formats=_READ_BASH, text_formats_when_marked_as_error=_READ_BASH_FAILED
    ),
    "stop_bash": HarnessToolResultDeclaration(
        text_formats=_STOP_BASH, text_formats_when_marked_as_error=_STOP_BASH_FAILED
    ),
    "view": HarnessToolResultDeclaration(
        text_formats=_VIEW, text_formats_when_marked_as_error=_VIEW_FAILED
    ),
    "create": HarnessToolResultDeclaration(
        text_formats=_CREATE, text_formats_when_marked_as_error=_CREATE_FAILED
    ),
    "edit": HarnessToolResultDeclaration(
        text_formats=_EDIT, text_formats_when_marked_as_error=_EDIT_FAILED
    ),
    "apply_patch": HarnessToolResultDeclaration(text_formats=_APPLY_PATCH),
    "task": HarnessToolResultDeclaration(text_formats=_TASK),
    "read_agent": HarnessToolResultDeclaration(
        text_formats=_READ_AGENT, text_formats_when_marked_as_error=_READ_AGENT_FAILED
    ),
}
