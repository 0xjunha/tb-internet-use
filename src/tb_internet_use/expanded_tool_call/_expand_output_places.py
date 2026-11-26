"""Expand where the output of the commands of each call of one trial shows up, i.e. in the call's own result, in the later polls of what it started and in later reads of the file where the harness saved one of those results.

A command run in the background goes on after its call returns, e.g. Claude Code `Bash` with `run_in_background`, so its output shows up in a later poll of its handle, e.g. `TaskOutput`, or in a later read of the file that the harness writes it to, e.g. `cat /tmp/x.output`.
Output that a command sends to a file it names, e.g. `curl u > log`, is not followed here, since the reads of that file are the uses of a `WrittenFile`.
A read of a harness output file is a place only when its own output reaches the reading call's result, so `cat /tmp/x.output > /dev/null` shows nothing.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tb_internet_use.expanded_tool_call._expand_poll_links import PollLinks
from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FileTouchKind,
    RanTextsOfToolCall,
)
from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_poll_result_of_several_commands_as_showing_none,
    treat_read_of_output_path_of_several_calls_as_showing_each,
    treat_script_step_output_as_not_shown_in_call_result,
)
from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    OutputPlace,
    PollInputText,
    RanShellText,
    RanText,
    ScriptStepText,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionStatus,
    PollAction,
    ResultDestination,
    RunToolScriptAction,
    ToolCall,
    ToolCallKey,
)

# A text that a call holds itself, from which the other texts of the call run, e.g. the command string of `bash fetch.sh` for the commands of fetch.sh.
type _OwnTextSource = CallCommandText | ScriptStepText | PollInputText


@dataclass(frozen=True, slots=True)
class _ResultCommandGroup:
    """Group of commands of one call whose output ends in a result, with the text of the call they run from, built by `_result_command_groups_of` so that a judgment rule is asked once per text."""

    own_text_source: _OwnTextSource
    command_ids: tuple[int, ...]


def expand_output_places(
    tool_calls: Sequence[ToolCall],
    ran_texts_of_tool_calls: Sequence[RanTextsOfToolCall],
    poll_links: PollLinks,
    *,
    judgment_rule_use_counts: Counter[str],
) -> tuple[tuple[OutputPlace, ...], ...]:
    """Expand the places where the output of each call's commands shows, one tuple per call in the order of `tool_calls`, each place once per showing call in call order.

    `ran_texts_of_tool_calls` and `poll_links` are what `expand_ran_texts` and `expand_poll_links` gave for the same calls.
    A command reaches a place when one of its output routes ends in the result, e.g. both commands of `curl u | tail -1`, and not when they all end in a file, are captured by `$(...)` or are thrown away.
    A place is a result that the trajectory holds, so a call without a result, a result without tool output text and a result that is `NOT_RUN` show nothing, and a call whose own result is `NOT_RUN` has no places.
    Every use of `treat_script_step_output_as_not_shown_in_call_result`, `treat_poll_result_of_several_commands_as_showing_none` and `treat_read_of_output_path_of_several_calls_as_showing_each` adds one to `judgment_rule_use_counts`.
    """
    tool_call_by_key = {
        tool_call.harness_tool_call.key: tool_call for tool_call in tool_calls
    }
    call_index_by_key = {
        tool_call_key: call_index
        for call_index, tool_call_key in enumerate(tool_call_by_key)
    }
    output_places_of_own_result_and_polls_of_tool_calls = [
        _expand_output_places_of_own_result_and_polls(
            tool_call,
            ran_texts_of_tool_call.ran_texts,
            poll_links,
            tool_call_by_key,
            call_index_by_key,
            judgment_rule_use_counts,
        )
        for tool_call, ran_texts_of_tool_call in zip(
            tool_calls, ran_texts_of_tool_calls, strict=True
        )
    ]
    harness_output_file_reading_tool_call_keys = (
        _harness_output_file_reading_tool_call_keys_of(
            ran_texts_of_tool_calls, tool_call_by_key, judgment_rule_use_counts
        )
    )
    return tuple(
        _merge_output_places(
            [
                *output_places_of_own_result_and_polls,
                *(
                    OutputPlace(reading_tool_call_key, output_place.command_ids)
                    for output_place in output_places_of_own_result_and_polls
                    for reading_tool_call_key in harness_output_file_reading_tool_call_keys[
                        output_place.showing_tool_call_key
                    ]
                ),
            ],
            call_index_by_key,
        )
        for output_places_of_own_result_and_polls in output_places_of_own_result_and_polls_of_tool_calls
    )


def _expand_output_places_of_own_result_and_polls(
    tool_call: ToolCall,
    ran_texts: Sequence[RanText],
    poll_links: PollLinks,
    tool_call_by_key: Mapping[ToolCallKey, ToolCall],
    call_index_by_key: Mapping[ToolCallKey, int],
    judgment_rule_use_counts: Counter[str],
) -> list[OutputPlace]:
    """Expand the results that show output of a call's commands, i.e. its own result and the results of later polls, before the reads of harness output files are added.

    The commands of the call's own command string or script steps reach every later poll of a handle the call started.
    The commands of text that a poll typed reach the later polls of a handle that the typing poll names, since they run in what that handle stands for.
    """
    if (
        tool_call.result is not None
        and tool_call.result.execution_status == ExecutionStatus.NOT_RUN
    ):
        return []
    tool_call_key = tool_call.harness_tool_call.key
    result_command_groups = _result_command_groups_of(ran_texts)
    output_places: list[OutputPlace] = []
    if _has_result_showing_output(tool_call):
        own_result_command_ids = [
            command_id
            for result_command_group in result_command_groups
            if _is_shown_in_own_result(result_command_group, judgment_rule_use_counts)
            for command_id in result_command_group.command_ids
        ]
        if own_result_command_ids:
            output_places.append(
                OutputPlace(tool_call_key, tuple(own_result_command_ids))
            )
    starter_command_ids = tuple(
        command_id
        for result_command_group in result_command_groups
        if not isinstance(result_command_group.own_text_source, PollInputText)
        for command_id in result_command_group.command_ids
    )
    output_places += _expand_output_places_of_polls(
        starter_command_ids,
        poll_links.poll_tool_call_keys_of_starter.get(tool_call_key, ()),
        tool_call_by_key,
        judgment_rule_use_counts,
    )
    for result_command_group in result_command_groups:
        own_text_source = result_command_group.own_text_source
        if (
            not isinstance(own_text_source, PollInputText)
            or own_text_source.starter_tool_call_key is None
        ):
            continue
        typing_poll_handles = _handles_of_typing_poll(
            tool_call, own_text_source.step_index
        )
        output_places += _expand_output_places_of_polls(
            result_command_group.command_ids,
            [
                poll_tool_call_key
                for poll_tool_call_key in poll_links.poll_tool_call_keys_of_starter[
                    own_text_source.starter_tool_call_key
                ]
                if call_index_by_key[poll_tool_call_key]
                > call_index_by_key[tool_call_key]
                and not typing_poll_handles.isdisjoint(
                    _polled_handles_of(tool_call_by_key[poll_tool_call_key])
                )
            ],
            tool_call_by_key,
            judgment_rule_use_counts,
        )
    return output_places


def _result_command_groups_of(
    ran_texts: Sequence[RanText],
) -> list[_ResultCommandGroup]:
    """Group the commands of a call whose stdout or stderr ends in the result by the text of the call they run from, in the order of the texts.

    A text that a command runs, e.g. the content of fetch.sh in `bash fetch.sh`, belongs to the text of its runner, since its commands print where the runner prints.
    """
    own_text_source_by_command_id: dict[int, _OwnTextSource] = {}
    command_ids_by_own_text_source: dict[_OwnTextSource, list[int]] = {}
    for ran_text in ran_texts:
        if not isinstance(ran_text, RanShellText):
            continue
        source = ran_text.source
        own_text_source = (
            source
            if isinstance(source, CallCommandText | ScriptStepText | PollInputText)
            else own_text_source_by_command_id[source.runner_command_id]
        )
        for ran_command in ran_text.ran_commands:
            command_id = ran_command.shell_command.id
            own_text_source_by_command_id[command_id] = own_text_source
            if any(
                isinstance(output_route.end, ResultDestination)
                for output_route in (
                    *ran_command.stdout_routes,
                    *ran_command.stderr_routes,
                )
            ):
                command_ids_by_own_text_source.setdefault(own_text_source, []).append(
                    command_id
                )
    return [
        _ResultCommandGroup(own_text_source, tuple(command_ids))
        for own_text_source, command_ids in command_ids_by_own_text_source.items()
    ]


def _is_shown_in_own_result(
    result_command_group: _ResultCommandGroup, judgment_rule_use_counts: Counter[str]
) -> bool:
    """Tell whether the call's own result shows the output of a group, asking `treat_script_step_output_as_not_shown_in_call_result` for a step of a tool script, whose one result is what its code prints."""
    match result_command_group.own_text_source:
        case (
            ScriptStepText(step_index=step_index)
            | PollInputText(step_index=int() as step_index)
        ):
            return not treat_script_step_output_as_not_shown_in_call_result(
                step_index, use_counts=judgment_rule_use_counts
            )
        case _:
            return True


def _expand_output_places_of_polls(
    command_ids: tuple[int, ...],
    poll_tool_call_keys: Sequence[ToolCallKey],
    tool_call_by_key: Mapping[ToolCallKey, ToolCall],
    judgment_rule_use_counts: Counter[str],
) -> list[OutputPlace]:
    """Expand the polls whose results show the output of commands that run in what they poll, asking `treat_poll_result_of_several_commands_as_showing_none` for each poll when there are several commands."""
    if not command_ids:
        return []
    return [
        OutputPlace(poll_tool_call_key, command_ids)
        for poll_tool_call_key in poll_tool_call_keys
        if _has_result_showing_output(tool_call_by_key[poll_tool_call_key])
        and (
            len(command_ids) == 1
            or not treat_poll_result_of_several_commands_as_showing_none(
                use_counts=judgment_rule_use_counts
            )
        )
    ]


def _handles_of_typing_poll(
    tool_call: ToolCall, step_index: int | None
) -> frozenset[ExecutionHandle]:
    """Give the handles that the poll typing a text names, the call's action when `step_index` is None and otherwise its 0-based step of a tool script."""
    action = tool_call.action
    if step_index is not None and isinstance(action, RunToolScriptAction):
        action = action.steps[step_index]
    if not isinstance(action, PollAction):
        raise TypeError(
            f"typed text of {tool_call.harness_tool_call.key} at step {step_index} comes from no poll"
        )
    return frozenset(action.handles)


def _polled_handles_of(tool_call: ToolCall) -> frozenset[ExecutionHandle]:
    """Give the handles that a call polls, i.e. those of its `PollAction` or of the `PollAction` steps of its tool script."""
    action = tool_call.action
    poll_actions = (
        [step for step in action.steps if isinstance(step, PollAction)]
        if isinstance(action, RunToolScriptAction)
        else [action]
        if isinstance(action, PollAction)
        else []
    )
    return frozenset(
        handle for poll_action in poll_actions for handle in poll_action.handles
    )


def _harness_output_file_reading_tool_call_keys_of(
    ran_texts_of_tool_calls: Sequence[RanTextsOfToolCall],
    tool_call_by_key: Mapping[ToolCallKey, ToolCall],
    judgment_rule_use_counts: Counter[str],
) -> defaultdict[ToolCallKey, list[ToolCallKey]]:
    """List, by the call whose result the harness saved in a file, the later calls whose results show that file's content, each once in call order.

    A read is a touch that shows content, e.g. `cat`, a read tool or a content search tool, so a touch that shows only the size, e.g. `wc -c`, is none.
    A read by a command shows the content only when its stdout ends in the reading call's result, e.g. through `| tail -1`, and not in `cat P > /dev/null`.
    A read of a file that the results of several calls name asks `treat_read_of_output_path_of_several_calls_as_showing_each` whether it shows each of them or the latest only.
    """
    reading_tool_call_keys: defaultdict[ToolCallKey, list[ToolCallKey]] = defaultdict(
        list
    )
    for ran_texts_of_tool_call in ran_texts_of_tool_calls:
        reading_tool_call_key = ran_texts_of_tool_call.tool_call_key
        if not _has_result_showing_output(tool_call_by_key[reading_tool_call_key]):
            continue
        command_ids_with_stdout_in_result = _command_ids_with_stdout_in_result_of(
            ran_texts_of_tool_call.ran_texts
        )
        for file_touch in ran_texts_of_tool_call.file_touches:
            if (
                file_touch.kind != FileTouchKind.SHOWS_CONTENT
                or not file_touch.reads_harness_output_file
                or (
                    file_touch.command_id is not None
                    and file_touch.command_id not in command_ids_with_stdout_in_result
                )
            ):
                continue
            saved_result_tool_call_keys = file_touch.harness_output_file_tool_call_keys
            if len(
                saved_result_tool_call_keys
            ) > 1 and not treat_read_of_output_path_of_several_calls_as_showing_each(
                use_counts=judgment_rule_use_counts
            ):
                saved_result_tool_call_keys = saved_result_tool_call_keys[-1:]
            for saved_result_tool_call_key in saved_result_tool_call_keys:
                if (
                    reading_tool_call_key
                    not in reading_tool_call_keys[saved_result_tool_call_key]
                ):
                    reading_tool_call_keys[saved_result_tool_call_key].append(
                        reading_tool_call_key
                    )
    return reading_tool_call_keys


def _command_ids_with_stdout_in_result_of(ran_texts: Sequence[RanText]) -> set[int]:
    """Give the ids of the commands of a call whose stdout ends in a result, alone or through pipe readers, e.g. cat of `cat P | tail -1`."""
    return {
        ran_command.shell_command.id
        for ran_text in ran_texts
        if isinstance(ran_text, RanShellText)
        for ran_command in ran_text.ran_commands
        if any(
            isinstance(output_route.end, ResultDestination)
            for output_route in ran_command.stdout_routes
        )
    }


def _has_result_showing_output(tool_call: ToolCall) -> bool:
    """Tell whether the trajectory holds a result of the call that can show output, i.e. one with tool output text that is not `NOT_RUN`, which for a poll means that the poll did nothing."""
    return (
        tool_call.result is not None
        and tool_call.result.tool_output_text is not None
        and tool_call.result.execution_status != ExecutionStatus.NOT_RUN
    )


def _merge_output_places(
    output_places: Sequence[OutputPlace], call_index_by_key: Mapping[ToolCallKey, int]
) -> tuple[OutputPlace, ...]:
    """Merge the places of one call into one per showing call, in call order and with the command ids in ascending order, e.g. a later call that both polls the call and reads its harness output file."""
    command_ids_by_showing_tool_call_key: defaultdict[ToolCallKey, set[int]] = (
        defaultdict(set)
    )
    for output_place in output_places:
        command_ids_by_showing_tool_call_key[output_place.showing_tool_call_key].update(
            output_place.command_ids
        )
    return tuple(
        OutputPlace(showing_tool_call_key, tuple(sorted(command_ids)))
        for showing_tool_call_key, command_ids in sorted(
            command_ids_by_showing_tool_call_key.items(),
            key=lambda item: call_index_by_key[item[0]],
        )
    )
