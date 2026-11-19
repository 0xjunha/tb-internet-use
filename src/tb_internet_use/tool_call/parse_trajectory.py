"""Read the text of one trial's ATIF trajectory file into harness tool calls paired with their results.

Harness converters turn these into common types.
"""

import json
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Any

from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    ToolCallKey,
)
from tb_internet_use.trial.model import UnreadableTrajectory, UnreadableTrajectoryReason

_SUPPORTED_SCHEMA_VERSIONS = {"ATIF-v1.6", "ATIF-v1.7", "ATIF-v1.8"}
# The starts of the messages that the mini-swe-agent loop writes to the model beside the results of the calls of a step, e.g. after a response without a tool call.
_AGENT_LOOP_MESSAGE_PREFIXES = (
    "Tool call error",
    "Your previous response reached the output token limit",
)
_MINI_SWE_AGENT = "mini-swe-agent"


def parse_trajectory(
    trajectory_text: str | bytes, trial_id: str
) -> tuple[HarnessToolCall, ...] | UnreadableTrajectory:
    """Read the text of one trial's trajectory file into its tool calls, or into an `UnreadableTrajectory` when the text is not JSON.

    The text can be the bytes of the file, so that broken UTF-8 is reported like broken JSON.
    A trajectory of an unsupported schema version raises ValueError, with the trial id as a note.
    """
    try:
        trajectory = json.loads(trajectory_text)
    except ValueError:  # broken JSON or UTF-8
        return UnreadableTrajectory(UnreadableTrajectoryReason.INVALID_JSON)

    try:
        return tuple(_iter_tool_calls(trajectory, trial_id))
    except Exception as error:
        error.add_note(f"trial_id: {trial_id}")
        raise


def _iter_tool_calls(
    trajectory: dict[str, Any], trial_id: str
) -> Iterator[HarnessToolCall]:
    """Yield every tool call in a trajectory, including its subagents' calls."""
    version = trajectory["schema_version"]
    if version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported ATIF schema version: {version}")

    harness = trajectory["agent"]["name"]
    yield from _walk_trajectory(trajectory, trial_id, harness, "main", False)


def _walk_trajectory(
    trajectory: dict[str, Any],
    trial_id: str,
    harness: str,
    trajectory_id: str,
    is_subagent: bool,
) -> Iterator[HarnessToolCall]:
    """Yield the tool calls of a trajectory, then those of its subagents."""
    for step in trajectory["steps"]:
        calls = step.get("tool_calls") or []
        results = (step.get("observation") or {}).get("results") or []
        results = _drop_agent_loop_messages(harness, results)
        is_subagent_step = _is_subagent_step(step)

        pairs = _pair_calls_with_results(calls, results)
        for call_index, (call, result) in enumerate(pairs):
            yield HarnessToolCall(
                key=ToolCallKey(trial_id, trajectory_id, step["step_id"], call_index),
                tool=HarnessTool(harness, call["function_name"]),
                tool_call_id=call["tool_call_id"],
                args=call["arguments"],
                result=result,
                is_subagent=is_subagent or is_subagent_step,
            )

    for index, subagent in enumerate(trajectory.get("subagent_trajectories") or []):
        yield from _walk_trajectory(
            subagent, trial_id, harness, f"{trajectory_id}/sub{index}", True
        )


def _is_subagent_step(step: dict[str, Any]) -> bool:
    """Tell whether a step of a trajectory holds the calls of a subagent, as Claude Code and Copilot CLI mark them in the main trajectory.

    Claude Code sets `extra.is_sidechain` to true. Copilot CLI sets `extra.parentToolCallId` to the id of the `task` call that started the subagent, e.g. on the `bash` calls of a subagent that a `task` call with that id launched.
    """
    step_extra = step.get("extra") or {}
    return (
        bool(step_extra.get("is_sidechain"))
        or step_extra.get("parentToolCallId") is not None
    )


def _drop_agent_loop_messages(
    harness: str, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove mini-swe-agent's loop messages, which are not results of any tool call.

    mini-swe-agent results carry no `source_call_id`, so a loop message left in would take the place of a call's result when results pair by position. A step holds such a message when one of its responses had no usable tool call, e.g. `Tool call error` with `No tool calls found in the response` or `Your previous response reached the output token limit`.
    """
    if harness != _MINI_SWE_AGENT:
        return results
    return [
        r
        for r in results
        if not str(r.get("content")).startswith(_AGENT_LOOP_MESSAGE_PREFIXES)
    ]


def _pair_calls_with_results(
    calls: list[dict[str, Any]], results: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Pair each call with its result, in call order. A call without a result gets None."""

    # A tool_call_id can repeat in a step, so keep a queue of call indexes per id.
    # e.g. calls `[a, b, a]` give `{"a": [0, 2], "b": [1]}`.
    call_indexes_by_id: dict[str, deque[int]] = defaultdict(deque)
    for idx, call in enumerate(calls):
        call_indexes_by_id[call["tool_call_id"]].append(idx)

    paired: list[dict[str, Any] | None] = [None] * len(calls)

    unmatched = []
    for result in results:
        source_id = result.get("source_call_id")
        call_indexes = None if source_id is None else call_indexes_by_id.get(source_id)
        if call_indexes:
            paired[call_indexes.popleft()] = result
        else:
            unmatched.append(result)

    # Results without a matching id fill the remaining calls in order.
    if unmatched:
        call_indexes_without_result = [
            idx for idx, result in enumerate(paired) if result is None
        ]
        if len(unmatched) != len(call_indexes_without_result):
            raise ValueError(
                f"{len(unmatched)} unmatched results for "
                f"{len(call_indexes_without_result)} calls without a result"
            )
        for idx, result in zip(call_indexes_without_result, unmatched, strict=True):
            paired[idx] = result

    return list(zip(calls, paired, strict=True))
