"""Link each poll of one trial to the earlier call of its trajectory that started what it polls, and each such call to the later calls that poll it.

A command run in the background goes on after its call returns, e.g. Claude Code `Bash` with `run_in_background` or Codex `exec_command`, and its output, its end and the text typed into it show up only in later polls of its handle, e.g. Claude Code `TaskOutput` or Codex `write_stdin`.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tb_internet_use.expanded_tool_call.judgment_rules import (
    treat_calls_of_other_trajectory_as_not_linked,
    treat_poll_as_reading_latest_earlier_start_of_handle,
    treat_script_poll_step_naming_no_handle_as_polling_none,
)
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    PollAction,
    RunCommandAction,
    RunToolScriptAction,
    StartSubagentAction,
    ToolCall,
    ToolCallAction,
    ToolCallKey,
    indexed_action_steps_of,
)

# The trajectory of a call, i.e. its `ToolCallKey.trajectory_id` and its `HarnessToolCall.is_subagent`.
# Claude Code keeps the calls of its subagents in the main trajectory as steps marked as subagent ones, so the id alone does not tell them apart.
type Trajectory = tuple[str, bool]


@dataclass(frozen=True, slots=True)
class PollLinks:
    """Links between the polls of one trial and the calls that started what they poll, read by the pieces of `expand_tool_calls` that follow typed text and output."""

    # By poll call and the 0-based step index of the poll in a tool script, None when the poll is the call's action.
    # One starter per polled handle that an earlier call of the same trajectory started, in handle order.
    # Every poll is a key, with an empty tuple when no handle it names has a starter.
    starter_tool_call_keys_of_poll: Mapping[
        tuple[ToolCallKey, int | None], tuple[ToolCallKey, ...]
    ]
    # By starter, the later calls that poll a handle it started, in call order.
    poll_tool_call_keys_of_starter: Mapping[ToolCallKey, tuple[ToolCallKey, ...]]


@dataclass(frozen=True, slots=True)
class _HandleStart:
    """Start of a handle by one call of the trial, found before the polls are linked so that a start in another trajectory is seen wherever it sits."""

    call_index: int  # 0-based position of the call in the trial
    trajectory: Trajectory
    starter_tool_call_key: ToolCallKey


@dataclass(frozen=True, slots=True)
class _PolledHandles:
    """Handles that one poll of a call reads, found once per call so that a judgment rule asked about them is counted once."""

    # The 0-based index of the poll in a tool script, None when the poll is the call's action.
    step_index: int | None
    handles: tuple[ExecutionHandle, ...]


def expand_poll_links(
    tool_calls: Sequence[ToolCall], *, judgment_rule_use_counts: Counter[str]
) -> PollLinks:
    """Link each poll of one trial to the calls that started the handles it names, and each starter to its later polls, in the order of `tool_calls`.

    A handle is matched by its id and its kind, since `ExecutionHandle` carries both and a command and a subagent can have the same id.
    Every use of `treat_script_poll_step_naming_no_handle_as_polling_none`, `treat_poll_as_reading_latest_earlier_start_of_handle` and `treat_calls_of_other_trajectory_as_not_linked` adds one to `judgment_rule_use_counts`.
    """
    polled_handles_of_tool_calls = [
        _polled_handles_of(tool_call, judgment_rule_use_counts)
        for tool_call in tool_calls
    ]
    handle_starts_by_handle = _handle_starts_of(
        tool_calls, polled_handles_of_tool_calls
    )
    starter_tool_call_keys_of_poll: dict[
        tuple[ToolCallKey, int | None], tuple[ToolCallKey, ...]
    ] = {}
    # A dict for each starter keeps its polls in call order and each once.
    poll_tool_call_keys_of_starter: defaultdict[
        ToolCallKey, dict[ToolCallKey, None]
    ] = defaultdict(dict)
    for call_index, (tool_call, polled_handles_of_tool_call) in enumerate(
        zip(tool_calls, polled_handles_of_tool_calls, strict=True)
    ):
        poll_tool_call_key = tool_call.harness_tool_call.key
        for polled_handles in polled_handles_of_tool_call:
            starter_tool_call_keys: list[ToolCallKey] = []
            for handle in polled_handles.handles:
                starter_tool_call_key = _choose_linked_starter_tool_call_key(
                    handle_starts_by_handle.get(handle, ()),
                    call_index,
                    trajectory_of(tool_call),
                    judgment_rule_use_counts,
                )
                if starter_tool_call_key is not None:
                    starter_tool_call_keys.append(starter_tool_call_key)
                    poll_tool_call_keys_of_starter[starter_tool_call_key][
                        poll_tool_call_key
                    ] = None
            starter_tool_call_keys_of_poll[
                (poll_tool_call_key, polled_handles.step_index)
            ] = tuple(starter_tool_call_keys)
    return PollLinks(
        starter_tool_call_keys_of_poll,
        {
            starter_tool_call_key: tuple(poll_tool_call_keys)
            for starter_tool_call_key, poll_tool_call_keys in poll_tool_call_keys_of_starter.items()
        },
    )


def _polled_handles_of(
    tool_call: ToolCall, judgment_rule_use_counts: Counter[str]
) -> tuple[_PolledHandles, ...]:
    """List the handles that each poll of a call reads, in step order, each handle once.

    A poll reads the handles it names. A poll that names none and is the call's action reads those its result names, since the result of a poll names its target, e.g. a Codex `wait` without arguments.
    A poll step of a tool script that names none reads those its script's result names only when `treat_script_poll_step_naming_no_handle_as_polling_none` says otherwise, and the rule is asked only when that result names a handle.
    """
    result_handles = (
        ()
        if tool_call.result is None
        else tuple(dict.fromkeys(tool_call.result.handles))
    )
    polled_handles_of_tool_call: list[_PolledHandles] = []
    for step_index, action in indexed_action_steps_of(tool_call.action):
        if not isinstance(action, PollAction):
            continue
        if step_index is None:
            handles = handles_of_poll_action(action, result_handles)
        elif action.handles:
            handles = tuple(dict.fromkeys(action.handles))
        elif (
            result_handles
            and not treat_script_poll_step_naming_no_handle_as_polling_none(
                use_counts=judgment_rule_use_counts
            )
        ):
            handles = result_handles
        else:
            handles = ()
        polled_handles_of_tool_call.append(_PolledHandles(step_index, handles))
    return tuple(polled_handles_of_tool_call)


def handles_of_poll_action(
    poll_action: PollAction, result_handles: tuple[ExecutionHandle, ...]
) -> tuple[ExecutionHandle, ...]:
    """List the handles that a poll which is the call's action reads, each once, i.e. those it names, or those its result names when it names none, e.g. a Codex `wait` without arguments."""
    return tuple(dict.fromkeys(poll_action.handles or result_handles))


def _handle_starts_of(
    tool_calls: Sequence[ToolCall],
    polled_handles_of_tool_calls: Sequence[tuple[_PolledHandles, ...]],
) -> dict[ExecutionHandle, list[_HandleStart]]:
    """List the starts of handles in the trial by handle, each list in call order."""
    handle_starts_by_handle: defaultdict[ExecutionHandle, list[_HandleStart]] = (
        defaultdict(list)
    )
    for call_index, (tool_call, polled_handles_of_tool_call) in enumerate(
        zip(tool_calls, polled_handles_of_tool_calls, strict=True)
    ):
        for handle in _started_handles_of(tool_call, polled_handles_of_tool_call):
            handle_starts_by_handle[handle].append(
                _HandleStart(
                    call_index,
                    trajectory_of(tool_call),
                    tool_call.harness_tool_call.key,
                )
            )
    return handle_starts_by_handle


def _started_handles_of(
    tool_call: ToolCall, polled_handles_of_tool_call: Sequence[_PolledHandles]
) -> tuple[ExecutionHandle, ...]:
    """List the handles a call started, i.e. those its result names that an action of the call can start and that no poll of the call reads.

    A call that only polls names a handle in its result because it reads or reports it, e.g. a Codex `exec` script whose only step polls a running session.
    """
    if tool_call.result is None:
        return ()
    handles_read_by_polls = {
        handle
        for polled_handles in polled_handles_of_tool_call
        for handle in polled_handles.handles
    }
    return tuple(
        handle
        for handle in dict.fromkeys(tool_call.result.handles)
        if handle not in handles_read_by_polls
        and _has_action_starting_handle_kind(tool_call.action, handle.kind)
    )


def _has_action_starting_handle_kind(
    action: ToolCallAction, handle_kind: ExecutionHandleKind
) -> bool:
    """Tell whether an action or one of its script steps starts work that a handle of the kind names.

    A command handle names a command that a `RunCommandAction` runs, a script handle names the code of a `RunToolScriptAction` itself, and a subagent handle names what a `StartSubagentAction` starts.
    A handle of unknown kind is started by no action, since what it names is not known.
    No other action starts work, e.g. a `PollAction` only reads, types into or stops what another call started.
    """
    steps = [step for _, step in indexed_action_steps_of(action)]
    runs_command = any(isinstance(step, RunCommandAction) for step in steps)
    is_tool_script = isinstance(action, RunToolScriptAction)
    starts_subagent = any(isinstance(step, StartSubagentAction) for step in steps)
    match handle_kind:
        case ExecutionHandleKind.COMMAND:
            return runs_command
        case ExecutionHandleKind.SCRIPT:
            return is_tool_script
        case ExecutionHandleKind.SUBAGENT:
            return starts_subagent
        case ExecutionHandleKind.UNKNOWN:
            return False


def _choose_linked_starter_tool_call_key(
    handle_starts: Sequence[_HandleStart],
    poll_call_index: int,
    poll_trajectory: Trajectory,
    judgment_rule_use_counts: Counter[str],
) -> ToolCallKey | None:
    """Choose the call that started one handle that a poll reads, among the starts of that handle, None when no start is linked.

    Only an earlier call of the poll's own trajectory is linked, unless `treat_calls_of_other_trajectory_as_not_linked` says otherwise for a handle that only other trajectories start.
    """
    earlier_handle_starts = [
        handle_start
        for handle_start in handle_starts
        if handle_start.call_index < poll_call_index
    ]
    earlier_handle_starts_of_trajectory = [
        handle_start
        for handle_start in earlier_handle_starts
        if handle_start.trajectory == poll_trajectory
    ]
    if earlier_handle_starts_of_trajectory:
        return _choose_latest_starter_tool_call_key(
            earlier_handle_starts_of_trajectory, judgment_rule_use_counts
        )
    # A start in another trajectory counts wherever it sits in the trial, since the order of calls across trajectories is not in the trajectory, e.g. Muse puts the calls of a subagent after all calls of the main trajectory.
    if not any(
        handle_start.trajectory != poll_trajectory for handle_start in handle_starts
    ):
        return None
    if treat_calls_of_other_trajectory_as_not_linked(
        use_counts=judgment_rule_use_counts
    ):
        return None
    if not earlier_handle_starts:
        return None
    return _choose_latest_starter_tool_call_key(
        earlier_handle_starts, judgment_rule_use_counts
    )


def _choose_latest_starter_tool_call_key(
    earlier_handle_starts: Sequence[_HandleStart],
    judgment_rule_use_counts: Counter[str],
) -> ToolCallKey | None:
    """Choose the latest of the earlier calls that started a handle, asking `treat_poll_as_reading_latest_earlier_start_of_handle` when there are several."""
    if len(earlier_handle_starts) == 1:
        return earlier_handle_starts[0].starter_tool_call_key
    if treat_poll_as_reading_latest_earlier_start_of_handle(
        use_counts=judgment_rule_use_counts
    ):
        return earlier_handle_starts[-1].starter_tool_call_key
    return None


def trajectory_of(tool_call: ToolCall) -> Trajectory:
    """Give the trajectory of a call, as its trajectory id and whether it is a subagent call."""
    return (
        tool_call.harness_tool_call.key.trajectory_id,
        tool_call.harness_tool_call.is_subagent,
    )
