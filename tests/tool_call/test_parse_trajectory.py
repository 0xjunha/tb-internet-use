"""Tests for parse_trajectory.py."""

import json
from typing import Any

import pytest

from tb_internet_use.tool_call.model import ToolCallKey
from tb_internet_use.tool_call.parse_trajectory import (
    _drop_agent_loop_messages,
    _pair_calls_with_results,
    _walk_trajectory,
    parse_trajectory,
)
from tb_internet_use.trial.model import UnreadableTrajectory, UnreadableTrajectoryReason

LOOP_MESSAGE = {"content": "Tool call error:\n\n<error>No tool calls found</error>"}


def _call(tool_call_id: str = "a") -> dict[str, Any]:
    return {"tool_call_id": tool_call_id, "function_name": "bash", "arguments": {}}


OUTPUT_TOKEN_LIMIT_LOOP_MESSAGE = {
    "content": "Your previous response reached the output token limit (finish_reason=length) before you produced a tool call, so it was cut off."
}


@pytest.mark.parametrize(
    "loop_message",
    [
        pytest.param(LOOP_MESSAGE, id="tool call error"),
        pytest.param(OUTPUT_TOKEN_LIMIT_LOOP_MESSAGE, id="output token limit"),
    ],
)
def test_drops_loop_message_for_mini_swe_agent(loop_message):
    result = {"content": '{"returncode": 0, "output": "ok"}'}
    assert _drop_agent_loop_messages("mini-swe-agent", [result, loop_message]) == [
        result
    ]


def test_a_step_of_mini_swe_agent_with_loop_messages_pairs_its_call_with_the_bash_result():
    # A made-up step of one call whose step also holds two later responses without a usable tool call, as trajectories of mini-swe-agent show.
    result = {"content": '{"returncode": 0, "output": "ok"}'}
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "tool_calls": [_call()],
                "observation": {
                    "results": [result, OUTPUT_TOKEN_LIMIT_LOOP_MESSAGE, LOOP_MESSAGE]
                },
            }
        ]
    }

    harness_tool_calls = list(
        _walk_trajectory(trajectory, "t", "mini-swe-agent", "main", False)
    )

    assert [harness_tool_call.result for harness_tool_call in harness_tool_calls] == [
        result
    ]


def test_keeps_loop_message_text_for_other_harness():
    assert _drop_agent_loop_messages("codex", [LOOP_MESSAGE]) == [LOOP_MESSAGE]


def test_pairs_by_id_in_call_order():
    a, b = _call("a"), _call("b")
    result_a, result_b = {"source_call_id": "a"}, {"source_call_id": "b"}
    assert _pair_calls_with_results([a, b], [result_b, result_a]) == [
        (a, result_a),
        (b, result_b),
    ]


def test_repeated_id_pairs_in_order():
    first, second = _call("a"), _call("a")
    result_1 = {"source_call_id": "a", "content": "1"}
    result_2 = {"source_call_id": "a", "content": "2"}
    assert _pair_calls_with_results([first, second], [result_1, result_2]) == [
        (first, result_1),
        (second, result_2),
    ]


def test_result_without_id_pairs_by_position():
    a, b = _call("a"), _call("b")
    result_1, result_2 = {"content": "1"}, {"content": "2"}
    assert _pair_calls_with_results([a, b], [result_1, result_2]) == [
        (a, result_1),
        (b, result_2),
    ]


def test_call_without_result_gets_none():
    call = _call()
    assert _pair_calls_with_results([call], []) == [(call, None)]


def test_unpairable_results_raise():
    with pytest.raises(ValueError, match="unmatched"):
        _pair_calls_with_results([_call()], [{"content": "1"}, {"content": "2"}])


def test_subagent_calls_are_yielded_once():
    # Several main steps must not walk the subagent again.
    trajectory = {
        "steps": [{"step_id": 1}, {"step_id": 2}],
        "subagent_trajectories": [{"steps": [{"step_id": 1, "tool_calls": [_call()]}]}],
    }
    harness_tool_calls = list(
        _walk_trajectory(trajectory, "t", "muse-code", "main", False)
    )

    assert [
        harness_tool_call.key.trajectory_id for harness_tool_call in harness_tool_calls
    ] == ["main/sub0"]
    assert harness_tool_calls[0].is_subagent is True


@pytest.mark.parametrize(
    ("harness", "subagent_step_extra"),
    [
        pytest.param("claude-code", {"is_sidechain": True}, id="claude code sidechain"),
        # The id of the `task` call that started the subagent, which Copilot CLI writes on the steps of the subagent.
        pytest.param(
            "copilot-cli",
            {"parentToolCallId": "toolu_task"},
            id="copilot cli parent tool call",
        ),
    ],
)
def test_step_marked_as_one_of_a_subagent_is_subagent(harness, subagent_step_extra):
    trajectory = {
        "steps": [
            {"step_id": 1, "tool_calls": [_call()], "extra": {}},
            {"step_id": 2, "tool_calls": [_call()], "extra": subagent_step_extra},
        ]
    }
    harness_tool_calls = list(_walk_trajectory(trajectory, "t", harness, "main", False))

    assert [
        harness_tool_call.is_subagent for harness_tool_call in harness_tool_calls
    ] == [
        False,
        True,
    ]


@pytest.mark.parametrize("schema_version", ["ATIF-v1.6", "ATIF-v1.7"])
def test_reads_the_calls_of_a_trajectory_text(schema_version):
    step = {
        "step_id": 3,
        "tool_calls": [_call("a")],
        "observation": {"results": [{"source_call_id": "a", "content": "ok"}]},
    }
    trajectory = {
        "schema_version": schema_version,
        "agent": {"name": "codex"},
        "steps": [step],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert not isinstance(harness_tool_calls, UnreadableTrajectory)
    [harness_tool_call] = harness_tool_calls
    assert harness_tool_call.key == ToolCallKey("trial-1", "main", 3, 0)
    assert harness_tool_call.tool.harness == "codex"
    assert harness_tool_call.args == {}
    assert harness_tool_call.result == {"source_call_id": "a", "content": "ok"}


def test_reads_every_call_key_and_pairing_of_a_v1_8_trial():
    def step(step_id, calls, results):
        return {
            "step_id": step_id,
            "tool_calls": calls,
            "observation": {"results": results},
        }

    main_steps = [
        step(
            1,
            [_call("a"), _call("b"), _call("c")],
            # b pairs by id, and the unknown id and the result without one fill a and c
            [{"source_call_id": "b"}, {"source_call_id": "zz"}, {"content": "3"}],
        ),
        step(2, [], [LOOP_MESSAGE]),  # a loop message in a step without calls
    ]
    trajectory = {
        "schema_version": "ATIF-v1.8",
        "agent": {"name": "mini-swe-agent"},
        "steps": main_steps,
        "subagent_trajectories": [
            {
                "steps": [step(1, [_call("s")], [])],
                "subagent_trajectories": [{"steps": [step(1, [_call("t")], [])]}],
            },
            {"steps": [step(1, [_call("u")], [])]},
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert not isinstance(harness_tool_calls, UnreadableTrajectory)
    assert [
        (c.key.trajectory_id, c.key.step_id, c.key.call_index, c.tool_call_id)
        for c in harness_tool_calls
    ] == [
        ("main", 1, 0, "a"),
        ("main", 1, 1, "b"),
        ("main", 1, 2, "c"),
        ("main/sub0", 1, 0, "s"),
        ("main/sub0/sub0", 1, 0, "t"),
        ("main/sub1", 1, 0, "u"),
    ]
    assert [c.result for c in harness_tool_calls[:3]] == [
        {"source_call_id": "zz"},
        {"source_call_id": "b"},
        {"content": "3"},
    ]
    assert [c.is_subagent for c in harness_tool_calls] == [False] * 3 + [True] * 3


def test_trajectory_without_calls_is_empty_and_not_unreadable():
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex"},
        "steps": [],
    }

    assert parse_trajectory(json.dumps(trajectory), "trial-1") == ()


@pytest.mark.parametrize(
    "trajectory_text",
    [
        "{not json",
        "",
        # The bytes of a file that is not UTF-8, as `read_trajectory` passes them.
        b'{"steps": "\xff"}',
    ],
)
def test_text_that_is_not_json_is_an_unreadable_trajectory(trajectory_text):
    assert parse_trajectory(trajectory_text, "trial-1") == UnreadableTrajectory(
        UnreadableTrajectoryReason.INVALID_JSON
    )


def test_unknown_schema_raises_with_trial_id():
    trajectory = {"schema_version": "ATIF-v9", "agent": {"name": "codex"}, "steps": []}

    with pytest.raises(ValueError, match="ATIF-v9") as error:
        parse_trajectory(json.dumps(trajectory), "trial-1")
    assert "trial_id: trial-1" in error.value.__notes__


def test_call_keeps_its_tool_name_and_arguments():
    call = {
        "tool_call_id": "a",
        "function_name": "bash",
        "arguments": {"command": "ls"},
    }
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex"},
        "steps": [{"step_id": 1, "tool_calls": [call]}],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")
    assert isinstance(harness_tool_calls, tuple)
    assert (harness_tool_calls[0].tool.name, harness_tool_calls[0].args) == (
        "bash",
        {"command": "ls"},
    )


def test_result_without_an_id_does_not_pair_with_a_call_whose_id_is_null():
    first = {"tool_call_id": "a", "function_name": "bash", "arguments": {}}
    second = {"tool_call_id": None, "function_name": "bash", "arguments": {}}
    result_1, result_2 = {"content": "1"}, {"content": "2"}
    assert _pair_calls_with_results([first, second], [result_1, result_2]) == [
        (first, result_1),
        (second, result_2),
    ]


def test_a_system_message_step_of_antigravity_cli_is_read_as_a_call_and_an_error_message_step_is_not():
    # A made-up background command, the step that reports its end and a step that reports an error of the model's response, as Antigravity CLI writes them.
    run_command = {
        "tool_call_id": "a",
        "function_name": "run_command",
        "arguments": {"CommandLine": "python3 run.py"},
    }
    system_message_step = {
        "step_id": 2,
        "source": "system",
        "message": 'Task id "c1/task-1" finished with result:\nCommand exited with code 0.',
        "extra": {"antigravity_type": "SYSTEM_MESSAGE", "status": "DONE"},
    }
    error_message_step = {
        "step_id": 3,
        "source": "system",
        "message": "Error: The stream was interrupted.",
        "extra": {"antigravity_type": "ERROR_MESSAGE", "status": "DONE"},
    }
    trajectory = {
        "schema_version": "ATIF-v1.6",
        "agent": {"name": "antigravity-cli"},
        "steps": [
            {"step_id": 1, "source": "agent", "tool_calls": [run_command]},
            system_message_step,
            error_message_step,
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert isinstance(harness_tool_calls, tuple)
    assert [
        (c.key, c.tool.name, c.tool_call_id, c.args, c.is_harness_message)
        for c in harness_tool_calls
    ] == [
        (
            ToolCallKey("trial-1", "main", 1, 0),
            "run_command",
            "a",
            {"CommandLine": "python3 run.py"},
            False,
        ),
        (ToolCallKey("trial-1", "main", 2, 0), "SYSTEM_MESSAGE", "", {}, True),
    ]
    assert harness_tool_calls[1].result == {"content": system_message_step["message"]}


def test_each_task_notification_of_a_claude_code_step_of_its_own_is_read_as_a_call_and_a_quoted_one_is_not():
    # Made-up steps that Claude Code writes, one block alone, two blocks after the line that marks them as no input of the user, and a summary of the conversation that quotes a block.
    first = "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"
    second = "<task-notification>\n<task-id>b2</task-id>\n<status>killed</status>\n</task-notification>"
    trajectory = {
        "schema_version": "ATIF-v1.6",
        "agent": {"name": "claude-code"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "Fix the build."},
            {"step_id": 2, "source": "user", "message": first},
            {
                "step_id": 3,
                "source": "user",
                "message": "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event.\n\n"
                + first
                + "\n\n"
                + second,
            },
            {
                "step_id": 4,
                "source": "user",
                "message": "This session is being continued from a previous conversation.\n"
                + first,
            },
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert isinstance(harness_tool_calls, tuple)
    assert [
        (c.key, c.tool.name, c.tool_call_id, c.args, c.result)
        for c in harness_tool_calls
    ] == [
        (
            ToolCallKey("trial-1", "main", 2, 0),
            "task-notification",
            "",
            {},
            {"content": first},
        ),
        (
            ToolCallKey("trial-1", "main", 3, 0),
            "task-notification",
            "",
            {},
            {"content": first},
        ),
        (
            ToolCallKey("trial-1", "main", 3, 1),
            "task-notification",
            "",
            {},
            {"content": second},
        ),
    ]


def test_a_system_reminder_of_a_grok_build_step_of_its_own_is_read_as_a_call_and_one_in_a_result_is_not():
    # A made-up background command whose result ends with a reminder, which its result formats cut as a notice, and a step that Grok Build writes with a reminder alone.
    reminder = '<system-reminder>\nBackground task "call1" completed (exit code: 0).\n</system-reminder>'
    run_terminal_command = {
        "tool_call_id": "call1",
        "function_name": "run_terminal_command",
        "arguments": {"command": "sleep 1", "background": True},
    }
    trajectory = {
        "schema_version": "ATIF-v1.6",
        "agent": {"name": "grok-build"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "Fix the build."},
            {
                "step_id": 2,
                "source": "agent",
                "tool_calls": [run_terminal_command],
                "observation": {
                    "results": [
                        {"source_call_id": "call1", "content": "exit: 0\n" + reminder}
                    ]
                },
            },
            {"step_id": 3, "source": "user", "message": reminder},
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert isinstance(harness_tool_calls, tuple)
    assert [(c.key, c.tool.name, c.result) for c in harness_tool_calls] == [
        (
            ToolCallKey("trial-1", "main", 2, 0),
            "run_terminal_command",
            {"source_call_id": "call1", "content": "exit: 0\n" + reminder},
        ),
        (
            ToolCallKey("trial-1", "main", 3, 0),
            "system-reminder",
            {"content": reminder},
        ),
    ]


def _messages_of_claude_code_steps(*steps: dict[str, Any]) -> list[Any]:
    """Read the messages that Claude Code wrote in made-up steps after the task step."""
    trajectory = {
        "schema_version": "ATIF-v1.6",
        "agent": {"name": "claude-code"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "Fix the build."},
            *steps,
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")
    assert isinstance(harness_tool_calls, tuple)
    return [c.result for c in harness_tool_calls if c.is_harness_message]


def test_a_closing_and_an_opening_tag_in_the_output_of_a_monitor_event_do_not_split_its_block():
    # A made-up `Monitor` whose command printed the two tags, as a command that greps a log of Claude Code could.
    event = (
        "<task-notification>\n<task-id>m1</task-id>\n"
        '<summary>Monitor event: "log"</summary>\n'
        "<event>a</task-notification>\n<task-notification>\nb</event>\n</task-notification>"
    )
    assert _messages_of_claude_code_steps(
        {"step_id": 2, "source": "user", "message": event}
    ) == [{"content": event}]


def test_a_closing_and_an_opening_tag_on_lines_of_their_own_in_an_event_do_not_split_a_step_of_several_blocks():
    first = (
        "<task-notification>\n<task-id>m1</task-id>\n"
        "<event>a\n</task-notification>\n<task-notification>\nb</event>\n</task-notification>"
    )
    second = "<task-notification>\n<task-id>b2</task-id>\n</task-notification>"
    message = (
        "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event.\n\n"
        + first
        + "\n\n"
        + second
    )
    assert _messages_of_claude_code_steps(
        {"step_id": 2, "source": "user", "message": message}
    ) == [{"content": first}, {"content": second}]


def test_the_first_user_step_of_an_agent_is_its_prompt_and_never_a_message_of_the_harness():
    # Made-up prompts that start like a task notification, of the main agent, of a subagent whose steps Claude Code keeps in the main trajectory and of a subagent trajectory.
    block = "<task-notification>\n<task-id>b1</task-id>\n</task-notification>"
    sidechain = {"is_sidechain": True, "agent_id": "a1"}
    trajectory = {
        "schema_version": "ATIF-v1.6",
        "agent": {"name": "claude-code"},
        "steps": [
            {"step_id": 1, "source": "user", "message": block},
            {"step_id": 2, "source": "user", "message": block, "extra": sidechain},
            {"step_id": 3, "source": "user", "message": block, "extra": sidechain},
            {"step_id": 4, "source": "user", "message": block},
        ],
        "subagent_trajectories": [
            {"steps": [{"step_id": 1, "source": "user", "message": block}]}
        ],
    }
    harness_tool_calls = parse_trajectory(json.dumps(trajectory), "trial-1")

    assert isinstance(harness_tool_calls, tuple)
    assert [c.key for c in harness_tool_calls if c.is_harness_message] == [
        ToolCallKey("trial-1", "main", 3, 0),
        ToolCallKey("trial-1", "main", 4, 0),
    ]
