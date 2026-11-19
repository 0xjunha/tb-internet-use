"""Read the text of one trial's ATIF trajectory file into harness tool calls paired with their results.

Harness converters turn these into common types.
A message that the harness writes to the agent outside the results of calls is read like a call too, since the end of a command can show up only there, e.g. the end of an Antigravity CLI background task with its exit code and output.
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
# The `extra.antigravity_type` of a step that Antigravity CLI writes to tell the agent something, e.g. that a background task ended, and the tool name its `HarnessToolCall` gets.
# Steps of the other type that Antigravity CLI writes, `ERROR_MESSAGE`, report errors of the model's responses and are not read.
_ANTIGRAVITY_SYSTEM_MESSAGE = "SYSTEM_MESSAGE"
# The tag of the block in which Claude Code writes the end of a background task, a line of a `Monitor` and the like to the agent, and the tool name its `HarnessToolCall` gets.
_CLAUDE_CODE_TASK_NOTIFICATION = "task-notification"
# The start of a `user` step in which Claude Code writes several task notifications, a line that marks the step as no input of the user, before the blocks.
# A step that only quotes a task notification starts otherwise, e.g. the summary of the conversation that Claude Code writes when it compacts it, and is not read.
_CLAUDE_CODE_SYSTEM_NOTIFICATION_STEP_START = "[SYSTEM NOTIFICATION - NOT USER INPUT]"
# The tag of the block in which Grok Build writes the end of a background task and other notes to the agent, e.g. the workflows it offers, and the tool name its `HarnessToolCall` gets.
# Grok Build adds such blocks to tool results too, which the result formats of the tool cut as notices.
_GROK_BUILD_SYSTEM_REMINDER = "system-reminder"
# The agent id of the steps of a trajectory that belong to no subagent.
_MAIN_AGENT = "main"
# The tool name of the `HarnessToolCall` of a message that a harness writes to the agent, by harness, which is the name the harness gives the message in the trajectory.
_HARNESS_MESSAGE_TOOL_NAMES = {
    "antigravity-cli": _ANTIGRAVITY_SYSTEM_MESSAGE,
    "claude-code": _CLAUDE_CODE_TASK_NOTIFICATION,
    "grok-build": _GROK_BUILD_SYSTEM_REMINDER,
}


def parse_trajectory(
    trajectory_text: str | bytes, trial_id: str
) -> tuple[HarnessToolCall, ...] | UnreadableTrajectory:
    """Read the text of one trial's trajectory file into its tool calls, or into an `UnreadableTrajectory` when the text is not JSON.

    The text can be the bytes of the file, so that broken UTF-8 is reported like broken JSON.
    A message that the harness writes to the agent, e.g. an Antigravity CLI `SYSTEM_MESSAGE` that reports the end of a background task, is read as a call too.
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
    """Yield the tool calls of a trajectory, then those of its subagents.

    The first `user` step of an agent is the prompt that the user or the parent agent wrote, so it is never read as messages of the harness.
    Each message that the harness wrote to the agent in a step gives one `HarnessToolCall` after the calls of the step, in the order of the messages, with the tool name of `_HARNESS_MESSAGE_TOOL_NAMES`, `is_harness_message` true, no `tool_call_id`, no arguments and the text of the message as the `content` of its result, since the message holds no call and stands where a result would.
    """
    agent_ids_with_prompt: set[str] = set()
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
        if _is_prompt_step(step, agent_ids_with_prompt):
            continue
        for message_index, message in enumerate(_harness_messages_of(harness, step)):
            yield HarnessToolCall(
                key=ToolCallKey(
                    trial_id,
                    trajectory_id,
                    step["step_id"],
                    len(pairs) + message_index,
                ),
                tool=HarnessTool(harness, _HARNESS_MESSAGE_TOOL_NAMES[harness]),
                tool_call_id="",
                args={},
                result={"content": message},
                is_subagent=is_subagent or is_subagent_step,
                is_harness_message=True,
            )

    for index, subagent in enumerate(trajectory.get("subagent_trajectories") or []):
        yield from _walk_trajectory(
            subagent, trial_id, harness, f"{trajectory_id}/sub{index}", True
        )


def _is_prompt_step(step: dict[str, Any], agent_ids_with_prompt: set[str]) -> bool:
    """Tell whether a step is the first `user` step of its agent, i.e. the task for the main agent or the prompt that the parent agent wrote for a subagent, and record its agent in `agent_ids_with_prompt`.

    The steps of a trajectory belong to one agent, except that Claude Code keeps the steps of its subagents in the main trajectory with `extra.is_sidechain` true and `extra.agent_id` naming the subagent.
    A sidechain step without `extra.agent_id` names no agent, so it is never taken for a prompt.
    """
    if step.get("source") != "user":
        return False
    step_extra = step.get("extra") or {}
    agent_id = (
        step_extra.get("agent_id") if step_extra.get("is_sidechain") else _MAIN_AGENT
    )
    if not isinstance(agent_id, str) or agent_id in agent_ids_with_prompt:
        return False
    agent_ids_with_prompt.add(agent_id)
    return True


def _harness_messages_of(harness: str, step: dict[str, Any]) -> tuple[Any, ...]:
    """List the messages that the harness wrote to the agent in a step of a trajectory, each as the step holds it, or none for a harness without such messages."""
    match harness:
        case "antigravity-cli":
            return _antigravity_system_messages_of(step)
        case "claude-code":
            return _claude_code_task_notifications_of(step)
        case "grok-build":
            return _whole_user_step_with_tag_of(step, _GROK_BUILD_SYSTEM_REMINDER)
        case _:
            return ()


def _antigravity_system_messages_of(step: dict[str, Any]) -> tuple[Any, ...]:
    """List the message of a step that Antigravity CLI marks with `SYSTEM_MESSAGE` in `extra.antigravity_type`, or none for any other step."""
    step_extra = step.get("extra") or {}
    if step_extra.get("antigravity_type") != _ANTIGRAVITY_SYSTEM_MESSAGE:
        return ()
    return (step.get("message"),)


def _claude_code_task_notifications_of(step: dict[str, Any]) -> tuple[str, ...]:
    """List the `<task-notification>` blocks of a `user` step that starts with one or with the line that marks the step as no input of the user, or none for any other step.

    A step that starts with a block holds that one block and nothing else, so the whole message is the block, and a closing tag that the command output in its `<event>` holds cannot end it early.
    A step that starts with the marking line holds one or more blocks after some lines of text, each block on lines of its own and the blocks apart by an empty line, so it is split only where a line that ends a block, an empty line and a line that starts a block meet.
    """
    whole_block = _whole_user_step_with_tag_of(step, _CLAUDE_CODE_TASK_NOTIFICATION)
    if whole_block:
        return whole_block
    message = _message_of_user_step(step)
    if message is None or not message.startswith(
        _CLAUDE_CODE_SYSTEM_NOTIFICATION_STEP_START
    ):
        return ()
    opening, closing = (
        f"<{_CLAUDE_CODE_TASK_NOTIFICATION}>",
        f"</{_CLAUDE_CODE_TASK_NOTIFICATION}>",
    )
    first_block_start = message.find("\n" + opening + "\n")
    if first_block_start < 0:
        return ()
    blocks = message[first_block_start + 1 :].split(f"{closing}\n\n{opening}\n")
    return tuple(
        (opening + "\n" if index else "")
        + block
        + (closing if index < len(blocks) - 1 else "")
        for index, block in enumerate(blocks)
    )


def _whole_user_step_with_tag_of(step: dict[str, Any], tag: str) -> tuple[str, ...]:
    """List the message of a `user` step that starts with the opening tag, e.g. `<system-reminder>`, as one block, or none for any other step.

    The harness writes such a step itself to tell the agent about earlier work, one block to a step. A block can hold text that the agent's commands printed, e.g. the `<event>` of a Claude Code `Monitor`, so its end is the end of the step and not the first closing tag in it.
    """
    message = _message_of_user_step(step)
    if message is None or not message.startswith(f"<{tag}>"):
        return ()
    return (message,)


def _message_of_user_step(step: dict[str, Any]) -> str | None:
    """Read the message of a `user` step of a trajectory, or None for another step or a message that is no text."""
    message = step.get("message")
    if step.get("source") != "user" or not isinstance(message, str):
        return None
    return message


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
