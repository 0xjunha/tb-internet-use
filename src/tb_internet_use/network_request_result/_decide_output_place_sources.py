"""Decide the sources of each output place of one trial, i.e. for each call whose result shows output, every command of every call whose output reaches that result.

`expand_tool_calls` gives the places from the side of the commands, e.g. call 1 `curl u` shows its output in the result of call 1 and of a later poll call 4. Choosing the owner of a line needs the other side, i.e. every command whose output can be in the result of call 4.
Output sent to a file reaches a later call that shows the file, e.g. `make > build.log` in call 1 and `cat build.log` in call 3, so the writers of that file are sources of call 3 too.
"""

from collections.abc import Iterator, Sequence

from tb_internet_use.expanded_tool_call.model import (
    ExpandedToolCall,
    FileUseKind,
    FileWriteChannel,
    RanCommand,
    RanShellText,
)
from tb_internet_use.network_request_result.model import (
    OutputPlaceSourceCommands,
    OutputPlaceSources,
)
from tb_internet_use.tool_call.model import (
    ExecutionStatus,
    ResultDestination,
    RunCommandAction,
    RunToolScriptAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    WebFetchAction,
    WebFindAction,
    WebSearchAction,
    indexed_action_steps_of,
)

# The channels of a written file that carry what a command printed, so a later read of the file shows output of that command.
_PRINTED_OUTPUT_CHANNELS = frozenset({FileWriteChannel.STDOUT, FileWriteChannel.STDERR})
# The channels of a written file that carry content which no command printed as it ran, e.g. the page of `curl -o page.html u` or the text of a write tool.
_FILE_CONTENT_CHANNELS = frozenset(
    {FileWriteChannel.OWN_OUTPUT_FILE, FileWriteChannel.TOOL_ARGUMENT}
)


def decide_output_place_sources(
    expanded_tool_calls: Sequence[ExpandedToolCall],
) -> tuple[OutputPlaceSources, ...]:
    """Decide the sources of every output place of a trial, one `OutputPlaceSources` per showing call in the order of `expanded_tool_calls`.

    A place is the result of a call that some `OutputPlace` names or that shows a file which commands printed into, and also each result with tool output text that is not `NOT_RUN` of a tool script or of a call made only of web tool actions, whose lines are read even when no command reaches them.
    A place that no request reaches is returned too, since a line there can still be counted as a line that gave no evidence.
    The source commands of a place are grouped by the call that ran them, in call order and with ascending command ids.
    """
    expanded_tool_call_by_key = {
        expanded_tool_call.tool_call.harness_tool_call.key: expanded_tool_call
        for expanded_tool_call in expanded_tool_calls
    }
    command_ids_by_source_key_by_showing_key: dict[
        ToolCallKey, dict[ToolCallKey, set[int]]
    ] = {}
    for showing_tool_call_key, output_place_source_commands in (
        *_output_place_sources_from_output_places(expanded_tool_calls),
        *_output_place_sources_from_written_files(
            expanded_tool_calls, expanded_tool_call_by_key
        ),
    ):
        command_ids_by_source_key_by_showing_key.setdefault(
            showing_tool_call_key, {}
        ).setdefault(output_place_source_commands.tool_call_key, set()).update(
            output_place_source_commands.command_ids
        )
    call_index_by_key = {
        tool_call_key: call_index
        for call_index, tool_call_key in enumerate(expanded_tool_call_by_key)
    }
    output_place_sources: list[OutputPlaceSources] = []
    for showing_tool_call_key, expanded_tool_call in expanded_tool_call_by_key.items():
        command_ids_by_source_key = command_ids_by_source_key_by_showing_key.get(
            showing_tool_call_key, {}
        )
        if not command_ids_by_source_key and not _is_result_of_tool_script_or_web_tools(
            expanded_tool_call.tool_call
        ):
            continue
        action = expanded_tool_call.tool_call.action
        output_place_sources.append(
            OutputPlaceSources(
                showing_tool_call_key=showing_tool_call_key,
                source_commands=tuple(
                    OutputPlaceSourceCommands(
                        source_tool_call_key, tuple(sorted(command_ids))
                    )
                    for source_tool_call_key, command_ids in sorted(
                        command_ids_by_source_key.items(),
                        key=lambda item: call_index_by_key[item[0]],
                    )
                ),
                may_show_file_content=_has_shown_file_content(
                    expanded_tool_call, expanded_tool_calls
                ),
                may_show_page_text=_has_web_step_beside_commands(action),
                is_web_tool_result=_has_only_web_tool_actions(action),
            )
        )
    return tuple(output_place_sources)


def _output_place_sources_from_output_places(
    expanded_tool_calls: Sequence[ExpandedToolCall],
) -> Iterator[tuple[ToolCallKey, OutputPlaceSourceCommands]]:
    """List the source commands that the `output_places` of every call give, each with the call that shows them.

    They are the call's own result, the later polls of what it started and the later reads of the file where the harness saved one of its results. A read of that file is found only here, since no `FileUse` records it.
    """
    for expanded_tool_call in expanded_tool_calls:
        for output_place in expanded_tool_call.output_places:
            yield (
                output_place.showing_tool_call_key,
                OutputPlaceSourceCommands(
                    expanded_tool_call.tool_call.harness_tool_call.key,
                    output_place.command_ids,
                ),
            )


def _output_place_sources_from_written_files(
    expanded_tool_calls: Sequence[ExpandedToolCall],
    expanded_tool_call_by_key: dict[ToolCallKey, ExpandedToolCall],
) -> Iterator[tuple[ToolCallKey, OutputPlaceSourceCommands]]:
    """List the commands that printed into a written file as sources of each later call whose result shows that file, e.g. make of `make > build.log` for the call of `cat build.log`.

    Only writers by stdout or stderr printed into the file, so `curl -o page.html u` gives no source to `cat page.html`.
    A use shows the file only when it is a read tool or its command's stdout ends in the result of a call that the trajectory holds, so `cat build.log > /dev/null` gives none.
    A written file of a call that did not run has no uses, so it gives no source.
    """
    for expanded_tool_call in expanded_tool_calls:
        for written_file in expanded_tool_call.written_files:
            printing_command_ids = tuple(
                written_file_writer.command_id
                for written_file_writer in written_file.writers
                if written_file_writer.channel in _PRINTED_OUTPUT_CHANNELS
                and written_file_writer.command_id is not None
            )
            if not printing_command_ids:
                continue
            for file_use in written_file.file_uses:
                using_expanded_tool_call = expanded_tool_call_by_key[
                    file_use.using_tool_call_key
                ]
                if (
                    file_use.kind == FileUseKind.SHOWS_CONTENT
                    and _has_result_showing_output(using_expanded_tool_call.tool_call)
                    and _is_use_shown_in_result(
                        using_expanded_tool_call, file_use.command_id
                    )
                ):
                    yield (
                        file_use.using_tool_call_key,
                        OutputPlaceSourceCommands(
                            expanded_tool_call.tool_call.harness_tool_call.key,
                            printing_command_ids,
                        ),
                    )


def _has_shown_file_content(
    showing_expanded_tool_call: ExpandedToolCall,
    expanded_tool_calls: Sequence[ExpandedToolCall],
) -> bool:
    """Tell whether the result of a call shows content of a file that no command printed as it ran.

    That is a file that no call of the trial wrote, e.g. README.md of the task image in `cat README.md`, or a written file with a writer that is a write or edit tool or a program writing its own output file, e.g. page.html of `curl -o page.html u`.
    A use counts only when it shows in the result, as for the sources of a written file.
    """
    showing_tool_call_key = showing_expanded_tool_call.tool_call.harness_tool_call.key
    if any(
        file_use_without_known_writer.kind == FileUseKind.SHOWS_CONTENT
        and _is_use_shown_in_result(
            showing_expanded_tool_call, file_use_without_known_writer.command_id
        )
        for file_use_without_known_writer in showing_expanded_tool_call.file_uses_without_known_writer
    ):
        return True
    return any(
        file_use.using_tool_call_key == showing_tool_call_key
        and file_use.kind == FileUseKind.SHOWS_CONTENT
        and _is_use_shown_in_result(showing_expanded_tool_call, file_use.command_id)
        for expanded_tool_call in expanded_tool_calls
        for written_file in expanded_tool_call.written_files
        if any(
            written_file_writer.channel in _FILE_CONTENT_CHANNELS
            for written_file_writer in written_file.writers
        )
        for file_use in written_file.file_uses
    )


def _is_use_shown_in_result(
    using_expanded_tool_call: ExpandedToolCall, command_id: int | None
) -> bool:
    """Tell whether a file use of a call shows in the call's result, i.e. it is a tool use, whose result is what the tool read, or the stdout of the using command ends in the result, alone or through pipe readers, e.g. cat of `cat log | tail -1`.

    In a tool script the stdout of a step's command ends in the result only as far as the script's code prints it, so the command must also be among the commands that the call's `OutputPlace` for its own result names.
    `expand_tool_calls` asks a judgment rule for that when it builds the place, e.g. `cat build.log` as a step of a Codex `exec`.
    """
    if command_id is None:
        return True
    if isinstance(
        using_expanded_tool_call.tool_call.action, RunToolScriptAction
    ) and not _is_in_own_result_output_place(using_expanded_tool_call, command_id):
        return False
    return any(
        isinstance(output_route.end, ResultDestination)
        for output_route in _ran_command_of(
            using_expanded_tool_call, command_id
        ).stdout_routes
    )


def _is_in_own_result_output_place(
    expanded_tool_call: ExpandedToolCall, command_id: int
) -> bool:
    """Tell whether the `OutputPlace` of a call for its own result names a command of the call."""
    tool_call_key = expanded_tool_call.tool_call.harness_tool_call.key
    return any(
        output_place.showing_tool_call_key == tool_call_key
        and command_id in output_place.command_ids
        for output_place in expanded_tool_call.output_places
    )


def _ran_command_of(
    expanded_tool_call: ExpandedToolCall, command_id: int
) -> RanCommand:
    """Find the command of a call with an id, which a file use of the call names."""
    for ran_text in expanded_tool_call.ran_texts:
        if not isinstance(ran_text, RanShellText):
            continue
        for ran_command in ran_text.ran_commands:
            if ran_command.shell_command.id == command_id:
                return ran_command
    raise ValueError(
        f"{expanded_tool_call.tool_call.harness_tool_call.key} has no command {command_id}"
    )


def _has_web_step_beside_commands(action: ToolCallAction) -> bool:
    """Tell whether a tool script has both a web tool step and a command step, so that its one result mixes page text into what the commands printed, e.g. a Codex `exec` that fetches a page and runs `curl`."""
    if not isinstance(action, RunToolScriptAction):
        return False
    return any(_is_web_tool_action(step) for step in action.steps) and any(
        isinstance(step, RunCommandAction) for step in action.steps
    )


def _has_only_web_tool_actions(action: ToolCallAction) -> bool:
    """Tell whether a call is made of one or more web tool actions and nothing else, so that its result is page text."""
    steps = [step for _, step in indexed_action_steps_of(action)]
    return bool(steps) and all(_is_web_tool_action(step) for step in steps)


def _is_web_tool_action(action: ToolCallAction) -> bool:
    """Tell whether an action is a web search, a web fetch or a find in a page."""
    return isinstance(action, WebSearchAction | WebFetchAction | WebFindAction)


def _is_result_of_tool_script_or_web_tools(tool_call: ToolCall) -> bool:
    """Tell whether a call is a tool script or made only of web tool actions and has a result that can show output, which is a place even when no command's output reaches it, e.g. a Codex `exec` without command steps."""
    return _has_result_showing_output(tool_call) and (
        isinstance(tool_call.action, RunToolScriptAction)
        or _has_only_web_tool_actions(tool_call.action)
    )


def _has_result_showing_output(tool_call: ToolCall) -> bool:
    """Tell whether the trajectory holds a result of the call that can show output, i.e. one with tool output text that is not `NOT_RUN`."""
    return (
        tool_call.result is not None
        and tool_call.result.tool_output_text is not None
        and tool_call.result.execution_status != ExecutionStatus.NOT_RUN
    )
