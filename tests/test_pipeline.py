"""Tests for pipeline.py, with made-up trial folders and made-up tool calls run through the steps with the knowledge classes made from the catalogs of the repo."""

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call import (
    judgment_rules as expanded_tool_call_judgment_rules,
)
from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    CommandTextStatus,
    FileText,
    FileUse,
    FileUseKind,
    OutputPlace,
    RanShellText,
)
from tb_internet_use.export import _export_network_request_row
from tb_internet_use.export import judgment_rules as export_judgment_rules
from tb_internet_use.export.model import MeasureBound, NetworkRequestCategory
from tb_internet_use.network_request import (
    judgment_rules as network_request_judgment_rules,
)
from tb_internet_use.network_request.judgment_rules import (
    treat_dotted_host_name_as_public,
)
from tb_internet_use.network_request.model import (
    FromCommand,
    NetworkRequestCertainty,
    NoNetworkRequestReason,
)
from tb_internet_use.network_request_result import (
    judgment_rules as network_request_result_judgment_rules,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    OutputLineKind,
    UnusedOutputLineReason,
)
from tb_internet_use.pipeline import (
    PipelineKnowledge,
    read_trajectory,
    read_trial_file_texts,
    run_steps_of_trial,
    run_steps_to_expanded_tool_calls,
    run_steps_to_network_request_results,
)
from tb_internet_use.tool_call import judgment_rules as tool_call_judgment_rules
from tb_internet_use.tool_call.model import (
    ExecutionHandle,
    ExecutionHandleKind,
    ExecutionStatus,
    HarnessTool,
    HarnessToolCall,
    PollAction,
    RunCommandAction,
    ToolCallKey,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_trajectory import parse_trajectory
from tb_internet_use.trial.model import (
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

# Made-up detail and status files whose ids differ from the folder name `trial-1`, so that a trial id read from a file instead of the folder name fails.
_DETAIL_BYTES = json.dumps(
    {"id": "detail-id", "task_name": "terminal-bench/a"}
).encode()
_STATUS_BYTES = json.dumps({"trial_id": "status-id", "memberships": []}).encode()


def _trial_dir(tmp_path: Path, bytes_by_file_name: Mapping[str, bytes]) -> Path:
    """Make a trial folder named `trial-1` that holds the given files."""
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    for file_name, file_bytes in bytes_by_file_name.items():
        (trial_dir / file_name).write_bytes(file_bytes)
    return trial_dir


def test_reads_the_calls_of_the_trajectory_file_with_the_folder_name_as_trial_id(
    tmp_path,
):
    trajectory_tool_call = {
        "tool_call_id": "a",
        "function_name": "bash",
        "arguments": {},
    }
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "codex"},
        "steps": [{"step_id": 3, "tool_calls": [trajectory_tool_call]}],
    }

    harness_tool_calls = read_trajectory(
        _trial_dir(tmp_path, {"trajectory.json": json.dumps(trajectory).encode()})
    )

    assert not isinstance(harness_tool_calls, UnreadableTrajectory)
    assert [harness_tool_call.key for harness_tool_call in harness_tool_calls] == [
        ToolCallKey("trial-1", "main", 3, 0)
    ]


def test_folder_without_a_trajectory_file_is_unreadable_as_missing(tmp_path):
    assert read_trajectory(_trial_dir(tmp_path, {})) == UnreadableTrajectory(
        UnreadableTrajectoryReason.MISSING
    )


def test_trajectory_file_that_is_not_utf8_is_unreadable_as_invalid_json(tmp_path):
    trial_dir = _trial_dir(tmp_path, {"trajectory.json": b'{"steps": "\xff"}'})

    assert read_trajectory(trial_dir) == UnreadableTrajectory(
        UnreadableTrajectoryReason.INVALID_JSON
    )


def test_reads_the_bytes_of_the_detail_and_status_files_with_the_folder_name_as_trial_id(
    tmp_path,
):
    trial_dir = _trial_dir(
        tmp_path, {"detail.json": _DETAIL_BYTES, "status.json": _STATUS_BYTES}
    )

    assert read_trial_file_texts(trial_dir) == TrialFileTexts(
        "trial-1", _DETAIL_BYTES, _STATUS_BYTES
    )


def test_keeps_bytes_that_are_not_utf8_for_the_reading_functions(tmp_path):
    trial_dir = _trial_dir(
        tmp_path,
        {"detail.json": b'{"task_name": "\xff"}', "status.json": b'{"x": "\xfe"}'},
    )

    trial_file_texts = read_trial_file_texts(trial_dir)

    assert trial_file_texts.detail_text == b'{"task_name": "\xff"}'
    assert trial_file_texts.status_text == b'{"x": "\xfe"}'


@pytest.mark.parametrize("missing_file_name", ["detail.json", "status.json"])
def test_folder_without_the_detail_or_status_file_raises(tmp_path, missing_file_name):
    bytes_by_file_name = {"detail.json": _DETAIL_BYTES, "status.json": _STATUS_BYTES}
    del bytes_by_file_name[missing_file_name]

    with pytest.raises(FileNotFoundError, match=missing_file_name):
        read_trial_file_texts(_trial_dir(tmp_path, bytes_by_file_name))


def _claude_code_tool_calls_writing_and_running_a_script() -> tuple[
    HarnessToolCall, HarnessToolCall
]:
    """Give a made-up Claude Code `Write` of fetch.sh and a later `Bash` call that runs it, both with a result the harness result formats read."""
    return (
        HarnessToolCall(
            ToolCallKey("t1", "main", 1, 0),
            HarnessTool("claude-code", "Write"),
            "a",
            {"file_path": "fetch.sh", "content": "cat notes.txt"},
            {"content": "File created successfully at: fetch.sh"},
        ),
        HarnessToolCall(
            ToolCallKey("t1", "main", 2, 0),
            HarnessTool("claude-code", "Bash"),
            "b",
            {"command": "bash fetch.sh"},
            {"content": "hello"},
        ),
    )


def test_runs_the_conversion_and_then_the_expansion_of_the_tool_calls():
    harness_tool_calls = _claude_code_tool_calls_writing_and_running_a_script()

    write_call, bash_call = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )

    assert write_call.tool_call.action == WriteFileAction("fetch.sh", "cat notes.txt")
    assert isinstance(bash_call.tool_call.action, RunCommandAction)
    assert [ran_text.source for ran_text in bash_call.ran_texts] == [
        CallCommandText(),
        FileText(0, "fetch.sh", ToolCallKey("t1", "main", 1, 0)),
    ]
    ran_file_text = bash_call.ran_texts[1]
    assert isinstance(ran_file_text, RanShellText)
    assert [
        ran_command.shell_command.words for ran_command in ran_file_text.ran_commands
    ] == [("cat", "notes.txt")]
    assert write_call.written_files[0].file_uses == (
        FileUse(ToolCallKey("t1", "main", 2, 0), 0, FileUseKind.USES_CONTENT, False),
    )


def _claude_code_tool_calls_running_a_script_in_the_background() -> tuple[
    HarnessToolCall, ...
]:
    """Give the made-up `Write` and `Bash` calls of `_claude_code_tool_calls_writing_and_running_a_script` with the `Bash` call run in the background, a later `TaskOutput` call that saw it end and a later `Bash` call whose result has no exit code line."""
    write_call, bash_call = _claude_code_tool_calls_writing_and_running_a_script()
    background_bash_call = HarnessToolCall(
        bash_call.key,
        bash_call.tool,
        bash_call.tool_call_id,
        {"command": "bash fetch.sh", "run_in_background": True},
        {
            "content": "Command running in background with ID: b1. Output is being written to: /tmp/b1.output. You will be notified when it completes. To check interim output, use Read on that file path."
        },
    )
    task_output_call = HarnessToolCall(
        ToolCallKey("t1", "main", 3, 0),
        HarnessTool("claude-code", "TaskOutput"),
        "c",
        {"task_id": "b1"},
        {
            "content": "(harbor view)",
            "extra": {
                "tool_result_metadata": {
                    "raw_tool_result": {
                        "type": "tool_result",
                        "content": "<retrieval_status>success</retrieval_status>",
                    },
                    "tool_use_result": {
                        "retrieval_status": "success",
                        "task": {
                            "task_id": "b1",
                            "task_type": "local_bash",
                            "status": "completed",
                            "output": "hello",
                            "exitCode": 0,
                        },
                    },
                }
            },
        },
    )
    later_bash_call = HarnessToolCall(
        ToolCallKey("t1", "main", 4, 0),
        bash_call.tool,
        "d",
        {"command": "echo done"},
        {"content": "hello"},
    )
    return write_call, background_bash_call, task_output_call, later_bash_call


def test_each_step_counts_its_lookups_in_its_own_knowledge_class_and_its_rules_in_its_own_counter():
    pipeline_knowledge = PipelineKnowledge()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    expanded_tool_call_judgment_rule_use_counts: Counter[str] = Counter()

    run_steps_to_expanded_tool_calls(
        _claude_code_tool_calls_running_a_script_in_the_background(),
        pipeline_knowledge=pipeline_knowledge,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
    )

    # The two `Bash` calls ask `convert_tool_calls` the row of the tool, and cat in fetch.sh asks `expand_tool_calls` the row of the program.
    assert (
        pipeline_knowledge.tool_call_knowledge.uses.row_use_counts[
            "harness_tools.csv", ("claude-code", "Bash")
        ]
        == 2
    )
    assert (
        pipeline_knowledge.expanded_tool_call_knowledge.uses.row_use_counts[
            "program_behaviors.csv", ("cat", "")
        ]
        == 1
    )
    # The end state of the background `Bash` call comes from the `TaskOutput` call that saw it end, and that call shows the output of both commands the `Bash` call ran, which rules of `expand_tool_calls` choose.
    assert expanded_tool_call_judgment_rule_use_counts == Counter(
        {
            "treat_first_poll_that_saw_end_as_command_text_status": 1,
            "treat_poll_result_as_showing_every_command_of_starter": 1,
        }
    )
    # The last `Bash` result has no exit code line, which a rule of `convert_tool_calls` reads.
    assert tool_call_judgment_rule_use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_finished": 1}
    )


def test_new_pipeline_knowledge_counts_only_its_own_lookups():
    first_pipeline_knowledge = PipelineKnowledge()
    run_steps_to_network_request_results(
        _claude_code_tool_calls_writing_and_running_a_script(),
        pipeline_knowledge=first_pipeline_knowledge,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
        network_request_result_judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    second_pipeline_knowledge = PipelineKnowledge()

    assert first_pipeline_knowledge.tool_call_knowledge.uses.row_use_counts
    assert first_pipeline_knowledge.expanded_tool_call_knowledge.uses.row_use_counts
    assert first_pipeline_knowledge.network_request_knowledge.uses.row_use_counts
    assert not second_pipeline_knowledge.tool_call_knowledge.uses.row_use_counts
    assert (
        not second_pipeline_knowledge.expanded_tool_call_knowledge.uses.row_use_counts
    )
    assert not second_pipeline_knowledge.network_request_knowledge.uses.row_use_counts


def test_runs_the_extraction_of_network_requests_after_the_expansion_with_its_own_knowledge_class_and_counters():
    write_call, background_bash_call, task_output_call, later_bash_call = (
        _claude_code_tool_calls_running_a_script_in_the_background()
    )
    # fetch.sh fetches a page with curl, which the catalogs of the repo say fetches, runs mytool, which has no row, on a URL and reads a file with cat, which they say does not fetch.
    write_call = HarnessToolCall(
        write_call.key,
        write_call.tool,
        write_call.tool_call_id,
        {
            "file_path": "fetch.sh",
            "content": "curl https://a.org/x; mytool https://b.org/y; cat notes.txt",
        },
        write_call.result,
    )
    pipeline_knowledge = PipelineKnowledge()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    expanded_tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    network_request_judgment_rule_use_counts: Counter[str] = Counter()
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()

    _, network_request_results = run_steps_to_network_request_results(
        (write_call, background_bash_call, task_output_call, later_bash_call),
        pipeline_knowledge=pipeline_knowledge,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
        network_request_judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
        network_request_result_judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )
    network_requests = [
        network_request_result.network_request
        for network_request_result in network_request_results
    ]

    assert [
        (
            network_request.tool_call_key,
            network_request.target,
            network_request.certainty,
        )
        for network_request in network_requests
    ] == [
        (
            background_bash_call.key,
            "https://a.org/x",
            NetworkRequestCertainty.CONFIRMED,
        ),
        (
            background_bash_call.key,
            "https://b.org/y",
            NetworkRequestCertainty.UNCERTAIN,
        ),
    ]
    assert isinstance(network_requests[0].source, FromCommand)
    assert network_requests[0].source.ran_text_source == FileText(
        0, "fetch.sh", write_call.key
    )
    assert (
        pipeline_knowledge.network_request_knowledge.uses.row_use_counts[
            "program_network_requests.csv", ("curl", "", "", "")
        ]
        == 1
    )
    # bash runs fetch.sh, whose commands give the requests, and neither cat nor the later `echo done` fetches.
    assert no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.PROGRAM_RUNS_SOMETHING_ELSE: 1,
            NoNetworkRequestReason.NON_FETCHING_PROGRAM: 2,
        }
    )
    # Each step counts its own rules in its own counter, e.g. the dotted host of the URL of mytool in that of `extract_network_requests`.
    assert network_request_judgment_rule_use_counts == Counter(
        {"treat_dotted_host_name_as_public": 1}
    )
    assert expanded_tool_call_judgment_rule_use_counts == Counter(
        {
            "treat_first_poll_that_saw_end_as_command_text_status": 1,
            "treat_poll_result_as_showing_every_command_of_starter": 1,
        }
    )
    assert tool_call_judgment_rule_use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_finished": 1}
    )


def test_runs_the_decision_of_request_results_after_the_extraction_with_its_own_knowledge_class_and_counters():
    # pip prints that it installed x, and the later call runs a script whose text the trial does not hold, which prints a download line.
    # The last call runs mytool, which has no row, on a URL, which `extract_network_requests` counts under one of its rules, and cat, which gives no request.
    harness_tool_calls = (
        HarnessToolCall(
            ToolCallKey("t1", "main", 1, 0),
            HarnessTool("claude-code", "Bash"),
            "a",
            {"command": "pip install x"},
            {"content": "Successfully installed x-1.0"},
        ),
        HarnessToolCall(
            ToolCallKey("t1", "main", 2, 0),
            HarnessTool("claude-code", "Bash"),
            "b",
            {"command": "./setup.sh"},
            {"content": "Downloading torch-2.3.0.whl"},
        ),
        HarnessToolCall(
            ToolCallKey("t1", "main", 3, 0),
            HarnessTool("claude-code", "Bash"),
            "c",
            {"command": "mytool https://b.org/y; cat notes.txt"},
            {"content": ""},
        ),
    )
    pipeline_knowledge = PipelineKnowledge()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    network_request_judgment_rule_use_counts: Counter[str] = Counter()
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()
    network_request_result_judgment_rule_use_counts: Counter[str] = Counter()
    unused_output_line_counts: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind]
    ] = Counter()
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ] = Counter()

    (
        (network_request, mytool_network_request),
        (network_request_result, mytool_network_request_result),
    ) = run_steps_to_network_request_results(
        harness_tool_calls,
        pipeline_knowledge=pipeline_knowledge,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
        network_request_result_judgment_rule_use_counts=network_request_result_judgment_rule_use_counts,
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )

    # The requests of `extract_network_requests` come back beside their results, one result each.
    assert network_request_result.network_request == network_request
    assert mytool_network_request_result.network_request == mytool_network_request
    assert network_request.target == "x"
    assert mytool_network_request.target == "https://b.org/y"
    assert (
        network_request_result.level,
        network_request_result.stop_reason,
        network_request_result.level_certainty,
    ) == (
        NetworkRequestResultLevel.RECEIVED,
        None,
        NetworkRequestResultCertainty.CONFIRMED,
    )
    assert (
        pipeline_knowledge.network_request_result_knowledge.uses.row_use_counts[
            "output_line_patterns", ("program_output", "pip_successfully_installed")
        ]
        == 1
    )
    # The results of these Claude Code `Bash` calls have neither an `Exit code` line nor a structured result, so they give no exit code and no evidence shows that pip or mytool ran beyond the line of pip.
    assert network_request_result_judgment_rule_use_counts == Counter(
        {
            "treat_pip_or_apt_installed_line_of_named_package_as_received": 1,
            "treat_command_without_own_evidence_as_no_evidence_of_run": 2,
        }
    )
    assert unused_output_line_counts == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
            ): 1
        }
    )
    assert program_counts_of_unowned_output_lines == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
                "setup.sh",
            ): 1
        }
    )
    # The rules and the runs without a request of the earlier steps stay in their own counters, e.g. the dotted host of the URL of mytool, cat, and ./setup.sh, which has no row and no URL.
    assert network_request_judgment_rule_use_counts == Counter(
        {"treat_dotted_host_name_as_public": 1}
    )
    assert no_network_request_counts == Counter(
        {
            NoNetworkRequestReason.NON_FETCHING_PROGRAM: 1,
            NoNetworkRequestReason.NO_URL_THAT_MAY_BE_PUBLIC: 1,
        }
    )
    assert tool_call_judgment_rule_use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_finished": 3}
    )


def _antigravity_cli_trajectory_text_of_background_install(
    *, has_end_message: bool
) -> str:
    """Make the text of a made-up Antigravity CLI trajectory whose `run_command` call sends `pip install x` to the background, with or without the step in which the harness reports the end of that task."""
    task_id = "c1/task-3"
    log_path = (
        "/root/.gemini/antigravity-cli/brain/c1/.system_generated/tasks/task-3.log"
    )
    run_command_step = {
        "step_id": 1,
        "source": "agent",
        "tool_calls": [
            {
                "tool_call_id": "a",
                "function_name": "run_command",
                "arguments": {"CommandLine": "pip install x"},
            }
        ],
        "observation": {
            "results": [
                {
                    "source_call_id": "a",
                    "content": "Created At: 2026-11-13T02:21:08Z\n"
                    + f"Tool is running as a background task with task id: {task_id}\n"
                    + "Task Description: pip install x\n"
                    + f"Task logs are available at: file://{log_path}",
                }
            ]
        },
    }
    end_message_step = {
        "step_id": 2,
        "source": "system",
        "message": "The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important information to pay attention to.\n\n"
        + f"<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-13T02:22:08Z sender={task_id} priority=MESSAGE_PRIORITY_HIGH "
        + f'content=Task id "{task_id}" finished with result:\n'
        + "Command exited with code 0.\n\nCommand output:\nSuccessfully installed x-1.0\n"
        + f"\nLog: file://{log_path}\n</SYSTEM_MESSAGE>",
        "extra": {"antigravity_type": "SYSTEM_MESSAGE", "status": "DONE"},
    }
    steps = (
        [run_command_step, end_message_step] if has_end_message else [run_command_step]
    )
    return json.dumps(
        {
            "schema_version": "ATIF-v1.6",
            "agent": {"name": "antigravity-cli"},
            "steps": steps,
        }
    )


@pytest.mark.parametrize(
    ("has_end_message", "expected_level"),
    [
        pytest.param(True, NetworkRequestResultLevel.RECEIVED, id="with the end"),
        pytest.param(False, NetworkRequestResultLevel.ATTEMPTED, id="without it"),
    ],
)
def test_the_end_of_an_antigravity_cli_background_task_that_the_harness_reports_in_a_step_decides_the_result_of_its_request(
    has_end_message, expected_level
):
    # Without that step, nothing in the trajectory says that pip ended or what it printed.
    harness_tool_calls = parse_trajectory(
        _antigravity_cli_trajectory_text_of_background_install(
            has_end_message=has_end_message
        ),
        "t1",
    )
    assert not isinstance(harness_tool_calls, UnreadableTrajectory)

    _, (network_request_result,) = run_steps_to_network_request_results(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
        network_request_result_judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert network_request_result.network_request.target == "x"
    assert network_request_result.level == expected_level


def test_the_step_that_reports_the_end_of_an_antigravity_cli_background_task_is_a_poll_linked_to_the_call_that_started_it():
    harness_tool_calls = parse_trajectory(
        _antigravity_cli_trajectory_text_of_background_install(has_end_message=True),
        "t1",
    )
    assert not isinstance(harness_tool_calls, UnreadableTrajectory)

    run_command_call, end_message_call = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )

    end_message_tool_call_key = ToolCallKey("t1", "main", 2, 0)
    assert end_message_call.tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "c1/task-3"),)
    )
    # The end and the output of pip come from the step, not from the result of the call, which says only that the task runs.
    assert run_command_call.command_text_status == CommandTextStatus(
        ExecutionStatus.FINISHED, 0, end_message_tool_call_key
    )
    assert OutputPlace(end_message_tool_call_key, (0,)) in (
        run_command_call.output_places
    )


# The first step of a made-up trajectory, the task, which comes before any message that the harness writes.
_TASK_STEP = {"step_id": 1, "source": "user", "message": "Install x."}


def _claude_code_trajectory_text_of_background_install(
    *, has_task_notification: bool
) -> str:
    """Make the text of a made-up Claude Code trajectory whose `Bash` call sends `pip install x` to the background, with or without the step in which the harness reports the end of that task."""
    output_path = "/tmp/claude-0/-app/tasks/b1.output"
    bash_step = {
        "step_id": 2,
        "source": "agent",
        "tool_calls": [
            {
                "tool_call_id": "toolu_01",
                "function_name": "Bash",
                "arguments": {"command": "pip install x", "run_in_background": True},
            }
        ],
        "observation": {
            "results": [
                {
                    "source_call_id": "toolu_01",
                    "content": f"Command running in background with ID: b1. Output is being written to: {output_path}. "
                    + "You will be notified when it completes. To check interim output, use Read on that file path.",
                }
            ]
        },
    }
    task_notification_step = {
        "step_id": 3,
        "source": "user",
        "message": "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>toolu_01</tool-use-id>\n"
        + f"<output-file>{output_path}</output-file>\n<status>completed</status>\n"
        + '<summary>Background command "pip install x" completed (exit code 0)</summary>\n</task-notification>',
        "extra": {"is_sidechain": False},
    }
    steps = (
        [_TASK_STEP, bash_step, task_notification_step]
        if has_task_notification
        else [_TASK_STEP, bash_step]
    )
    return json.dumps(
        {
            "schema_version": "ATIF-v1.6",
            "agent": {"name": "claude-code"},
            "steps": steps,
        }
    )


@pytest.mark.parametrize(
    ("has_task_notification", "expected_level"),
    [
        pytest.param(True, NetworkRequestResultLevel.EXECUTED, id="with the end"),
        pytest.param(False, NetworkRequestResultLevel.ATTEMPTED, id="without it"),
    ],
)
def test_the_end_of_a_claude_code_background_task_that_the_harness_reports_in_a_task_notification_decides_the_result_of_its_request(
    has_task_notification, expected_level
):
    # Without that step, nothing in the trajectory says that pip ended.
    harness_tool_calls = parse_trajectory(
        _claude_code_trajectory_text_of_background_install(
            has_task_notification=has_task_notification
        ),
        "t1",
    )
    assert not isinstance(harness_tool_calls, UnreadableTrajectory)

    _, (network_request_result,) = run_steps_to_network_request_results(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
        network_request_result_judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert network_request_result.network_request.target == "x"
    assert network_request_result.level == expected_level


def test_the_task_notification_of_a_claude_code_background_task_is_a_poll_linked_to_the_call_that_started_it():
    harness_tool_calls = parse_trajectory(
        _claude_code_trajectory_text_of_background_install(has_task_notification=True),
        "t1",
    )
    assert not isinstance(harness_tool_calls, UnreadableTrajectory)

    bash_call, task_notification_call = run_steps_to_expanded_tool_calls(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )

    task_notification_tool_call_key = ToolCallKey("t1", "main", 3, 0)
    assert task_notification_call.tool_call.action == PollAction(
        (ExecutionHandle(ExecutionHandleKind.COMMAND, "b1"),)
    )
    # The end and the exit code of pip come from the step, which names the output file but holds no output.
    assert bash_call.command_text_status == CommandTextStatus(
        ExecutionStatus.FINISHED, 0, task_notification_tool_call_key
    )


def _grok_build_trajectory_text_of_background_install(
    *, has_system_reminder: bool
) -> str:
    """Make the text of a made-up Grok Build trajectory whose `run_terminal_command` call sends `pip install x` to the background, with or without the step in which the harness reports the end of that task."""
    run_terminal_command_step = {
        "step_id": 2,
        "source": "agent",
        "tool_calls": [
            {
                "tool_call_id": "call-1",
                "function_name": "run_terminal_command",
                "arguments": {"command": "pip install x", "background": True},
            }
        ],
        "observation": {
            "results": [
                {
                    "source_call_id": "call-1",
                    "content": "<task-id>call-1</task-id>\n<task-type>bash</task-type>\n<output-file>/tmp/call-1.log</output-file>\n"
                    + '<status>running</status>\n<summary>Command "pip install x" is running in the background.</summary>\n'
                    + 'Use get_command_or_subagent_output with task_ids=["call-1"] when you need the output.',
                }
            ]
        },
    }
    system_reminder_step = {
        "step_id": 3,
        "source": "user",
        "message": '<system-reminder>\nBackground task "call-1" completed (exit code: 0).\nCommand: pip install x | Duration: 3.0s\n'
        + 'Use get_command_or_subagent_output("call-1") to see the full output.\n</system-reminder>',
    }
    steps = (
        [_TASK_STEP, run_terminal_command_step, system_reminder_step]
        if has_system_reminder
        else [_TASK_STEP, run_terminal_command_step]
    )
    return json.dumps(
        {"schema_version": "ATIF-v1.6", "agent": {"name": "grok-build"}, "steps": steps}
    )


@pytest.mark.parametrize(
    ("has_system_reminder", "expected_level"),
    [
        pytest.param(True, NetworkRequestResultLevel.EXECUTED, id="with the end"),
        pytest.param(False, NetworkRequestResultLevel.ATTEMPTED, id="without it"),
    ],
)
def test_the_end_of_a_grok_build_background_task_that_the_harness_reports_in_a_system_reminder_decides_the_result_of_its_request(
    has_system_reminder, expected_level
):
    # Without that step, nothing in the trajectory says that pip ended.
    harness_tool_calls = parse_trajectory(
        _grok_build_trajectory_text_of_background_install(
            has_system_reminder=has_system_reminder
        ),
        "t1",
    )
    assert not isinstance(harness_tool_calls, UnreadableTrajectory)

    _, (network_request_result,) = run_steps_to_network_request_results(
        harness_tool_calls,
        pipeline_knowledge=PipelineKnowledge(),
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
        network_request_result_judgment_rule_use_counts=Counter(),
        unused_output_line_counts=Counter(),
        program_counts_of_unowned_output_lines=Counter(),
    )

    assert network_request_result.network_request.target == "x"
    assert network_request_result.level == expected_level


# The keyword arguments of `run_steps_of_trial` that hold a counter, which a test fills with empty counters.
_COUNTER_ARGUMENT_NAMES = (
    "tool_call_judgment_rule_use_counts",
    "expanded_tool_call_judgment_rule_use_counts",
    "network_request_judgment_rule_use_counts",
    "no_network_request_counts",
    "network_request_result_judgment_rule_use_counts",
    "unused_output_line_counts",
    "program_counts_of_unowned_output_lines",
    "export_judgment_rule_use_counts",
)
# The module of the judgment rules of each step whose rule counter `run_steps_of_trial` takes.
_JUDGMENT_RULES_BY_COUNTER_ARGUMENT_NAME = {
    "tool_call_judgment_rule_use_counts": tool_call_judgment_rules,
    "expanded_tool_call_judgment_rule_use_counts": expanded_tool_call_judgment_rules,
    "network_request_judgment_rule_use_counts": network_request_judgment_rules,
    "network_request_result_judgment_rule_use_counts": network_request_result_judgment_rules,
    "export_judgment_rule_use_counts": export_judgment_rules,
}


def _run_steps_of_trial_with_new_counters(
    trial_dir: Path,
) -> tuple[tuple, PipelineKnowledge, dict[str, Counter]]:
    """Run `run_steps_of_trial` with a new `PipelineKnowledge` and new counters, and return its output with the `PipelineKnowledge` and the counters by argument name."""
    pipeline_knowledge = PipelineKnowledge()
    counters: dict[str, Counter] = {name: Counter() for name in _COUNTER_ARGUMENT_NAMES}
    output = run_steps_of_trial(
        trial_dir, pipeline_knowledge=pipeline_knowledge, **counters
    )
    return output, pipeline_knowledge, counters


def test_runs_every_step_on_a_trial_folder_and_keeps_the_counters_of_each_step_apart(
    tmp_path, write_trial_folder
):
    # wget runs only when x.tgz is missing, pip installs packages of a variable, and mytool has no row of a catalog. A later call runs a script whose text the trial does not hold, which prints a download line that no request owns.
    trial_dir = write_trial_folder(
        tmp_path,
        "trial-1",
        [
            (
                "test -f x.tgz || wget -O x.tgz https://files.acme.org/x.tgz; pip install $PKGS; mytool https://b.org/y",
                "Successfully installed requests-2.32.3",
            ),
            ("./setup.sh", "Downloading torch-2.3.0.whl"),
        ],
    )

    (
        (
            trial,
            network_requests,
            network_request_results,
            trial_row,
            network_request_rows,
            trial_category_measure_rows,
        ),
        pipeline_knowledge,
        counters,
    ) = _run_steps_of_trial_with_new_counters(trial_dir)

    assert (trial.trial_id, trial.task_name, trial.unreadable_trajectory) == (
        "trial-1",
        "terminal-bench/a",
        None,
    )
    assert [
        network_request_result.network_request.tool_call_key
        for network_request_result in network_request_results
    ] == [ToolCallKey("trial-1", "main", 1, 0)] * 3
    # The requests of `extract_network_requests` come back beside their results, one result each.
    assert network_requests == tuple(
        network_request_result.network_request
        for network_request_result in network_request_results
    )
    assert [
        (row.made_by, row.target, row.category) for row in network_request_rows
    ] == [
        ("wget", "https://files.acme.org/x.tgz", NetworkRequestCategory.CONTENT_FETCH),
        ("pip install", "", NetworkRequestCategory.PACKAGE),
        ("mytool", "https://b.org/y", NetworkRequestCategory.OTHER_WEB),
    ]
    assert trial_row.any_category_request_measure_bound == MeasureBound.LOWER_AND_UPPER
    assert {
        (row.category, row.request_measure_bound) for row in trial_category_measure_rows
    } == {
        # files.acme.org has no row of `public_hosts.csv`, so the internet use of wget is unknown.
        (NetworkRequestCategory.CONTENT_FETCH, MeasureBound.UPPER_ONLY),
        (NetworkRequestCategory.PACKAGE, MeasureBound.LOWER_AND_UPPER),
        # mytool is an uncertain request.
        (NetworkRequestCategory.OTHER_WEB, MeasureBound.UPPER_ONLY),
    }
    # Every step uses a rule of its own and counts no rule of another step, except that `export_rows` counts the rule of `extract_network_requests` that reads a dotted host name as public.
    for name, judgment_rules in _JUDGMENT_RULES_BY_COUNTER_ARGUMENT_NAME.items():
        own_rule_names = {
            name
            for name, function in vars(judgment_rules).items()
            if callable(function)
            and getattr(function, "__module__", None) == judgment_rules.__name__
        }
        if judgment_rules is export_judgment_rules:
            own_rule_names.add(treat_dotted_host_name_as_public.__name__)
        assert counters[name], f"{name} counted no rule"
        assert set(counters[name]) <= own_rule_names, name
    # The dotted host of mytool's URL counts in the counter of `extract_network_requests`, and the hosts of wget, mytool and `pypi.org` of `pip install` in that of `export_rows`.
    assert (
        counters["network_request_judgment_rule_use_counts"][
            treat_dotted_host_name_as_public.__name__
        ]
        == 1
    )
    assert (
        counters["export_judgment_rule_use_counts"][
            treat_dotted_host_name_as_public.__name__
        ]
        == 3
    )
    assert counters["no_network_request_counts"]
    # `decide_network_request_results` counts the line of setup.sh in both of its line counters.
    assert counters["unused_output_line_counts"] == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
            ): 1
        }
    )
    assert counters["program_counts_of_unowned_output_lines"] == Counter(
        {
            (
                UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN,
                OutputLineKind.DOWNLOAD_STARTED,
                "setup.sh",
            ): 1
        }
    )
    # Each knowledge class counts its own lookups, e.g. `ExportKnowledge` the default registry of `pip install`.
    assert pipeline_knowledge.export_knowledge.uses.row_use_counts == Counter(
        {("program_package_registries.csv", ("pip", "install")): 1}
    )
    for knowledge_field_name in (
        "tool_call_knowledge",
        "expanded_tool_call_knowledge",
        "network_request_knowledge",
        "network_request_result_knowledge",
    ):
        assert getattr(pipeline_knowledge, knowledge_field_name).uses.row_use_counts, (
            knowledge_field_name
        )


def test_a_readable_trial_without_requests_keeps_its_trial_row_alone(
    tmp_path, write_trial_folder
):
    trial_dir = write_trial_folder(tmp_path, "trial-1", [("ls", "notes.txt")])

    (
        (
            trial,
            network_requests,
            network_request_results,
            trial_row,
            network_request_rows,
            measure_rows,
        ),
        (_),
        _,
    ) = _run_steps_of_trial_with_new_counters(trial_dir)

    assert trial.unreadable_trajectory is None
    assert (
        network_requests,
        network_request_results,
        network_request_rows,
        measure_rows,
    ) == ((), (), (), ())
    assert (
        trial_row.unreadable_trajectory_reason,
        trial_row.any_category_request_measure_bound,
        trial_row.any_category_received_measure_bound,
    ) == (None, MeasureBound.NEITHER, MeasureBound.NEITHER)


@pytest.mark.parametrize(
    ("trajectory", "reason"),
    [
        (None, UnreadableTrajectoryReason.MISSING),
        (b'{"steps": [', UnreadableTrajectoryReason.INVALID_JSON),
    ],
)
def test_an_unreadable_trajectory_gives_its_reason_no_results_and_the_upper_bounds_of_every_category(
    tmp_path, write_trial_folder, trajectory, reason
):
    trial_dir = write_trial_folder(tmp_path, "trial-1", trajectory)

    (
        (
            trial,
            network_requests,
            network_request_results,
            trial_row,
            network_request_rows,
            measure_rows,
        ),
        pipeline_knowledge,
        counters,
    ) = _run_steps_of_trial_with_new_counters(trial_dir)

    assert trial.unreadable_trajectory == UnreadableTrajectory(reason)
    assert trial.task_name == "terminal-bench/a"
    assert (network_requests, network_request_results, network_request_rows) == (
        (),
        (),
        (),
    )
    assert trial_row.unreadable_trajectory_reason == reason
    assert trial_row.any_category_request_measure_bound == MeasureBound.UPPER_ONLY
    # One row per category and each sender other than unknown, all in the upper bounds only.
    assert len(measure_rows) == len(NetworkRequestCategory) * 3
    assert {
        (row.request_measure_bound, row.received_measure_bound) for row in measure_rows
    } == {(MeasureBound.UPPER_ONLY, MeasureBound.UPPER_ONLY)}
    # Only `collect_trials` and `export_rows` ran, and neither used a judgment rule or a knowledge class, so no counter and no knowledge class counted anything.
    assert not any(counters.values())
    assert not pipeline_knowledge.tool_call_knowledge.uses.row_use_counts
    assert not pipeline_knowledge.tool_call_knowledge.uses.unknown_input_counts


def test_a_trial_folder_without_a_detail_file_raises(tmp_path, write_trial_folder):
    trial_dir = write_trial_folder(
        tmp_path, "trial-1", [("ls", "notes.txt")], has_detail_file=False
    )

    with pytest.raises(FileNotFoundError, match="detail.json"):
        _run_steps_of_trial_with_new_counters(trial_dir)


@pytest.mark.parametrize(
    ("command", "output", "category", "counts_trial_in_received_lower_bound"),
    [
        # A run that is not read beside the two `curl` may have printed the line, since other programs print it too.
        pytest.param(
            "curl -sI https://a.org/x; curl -sI https://b.org/y; ./check.sh",
            "HTTP/1.1 200 OK",
            NetworkRequestCategory.CONNECTIVITY_CHECK,
            False,
            id="curl -sI beside a script",
        ),
        pytest.param(
            "curl -sI https://a.org/x; curl -sI https://b.org/y; python3 run.py",
            "HTTP/1.1 200 OK",
            NetworkRequestCategory.CONNECTIVITY_CHECK,
            False,
            id="curl -sI beside code",
        ),
        pytest.param(
            "curl -s -o /dev/null -w '%{http_code}' https://a.org/x; curl -s -o /dev/null -w '%{http_code}' https://b.org/y; ./check.sh",
            "200",
            NetworkRequestCategory.CONNECTIVITY_CHECK,
            False,
            id="curl -w beside a script",
        ),
        pytest.param(
            "curl -sI https://a.org/x; curl -sI https://b.org/y",
            "HTTP/1.1 200 OK",
            NetworkRequestCategory.CONNECTIVITY_CHECK,
            True,
            id="curl -sI alone",
        ),
        # Only wget and apt print these lines, so a line is taken as printed by the wget or apt command of the call, as it is for a single request, although the script may run one of them too.
        pytest.param(
            "wget https://a.org/x.tgz https://a.org/y.tgz; ./check.sh",
            "'x.tgz' saved [1024/1024]",
            NetworkRequestCategory.CONTENT_FETCH,
            True,
            id="wget saved beside a script",
        ),
        pytest.param(
            "apt-get install -y aaa bbb; ./check.sh",
            "Fetched 10 kB in 1s (10 kB/s)",
            NetworkRequestCategory.PACKAGE,
            True,
            id="apt Fetched beside a script",
        ),
    ],
)
def test_a_shared_line_of_success_counts_the_trial_in_the_received_lower_bound_only_when_no_run_that_is_not_read_may_have_printed_it(
    tmp_path,
    write_trial_folder,
    monkeypatch,
    command,
    output,
    category,
    counts_trial_in_received_lower_bound,
):
    # a.org and b.org have no row of `public_hosts.csv`, so they are read here as listed public hosts, which counts their requests in the lower bound.
    monkeypatch.setattr(
        _export_network_request_row,
        "treat_dotted_host_name_without_public_host_row_as_unknown_internet_use",
        lambda network_request, *, use_counts: False,
    )
    trial_dir = write_trial_folder(tmp_path, "trial-1", [(command, output)])

    (
        (_, _, network_request_results, _, network_request_rows, measure_rows),
        _,
        _,
    ) = _run_steps_of_trial_with_new_counters(trial_dir)

    # Each request alone stays assumed and only in the upper bound of received.
    assert [
        (
            result.level_certainty,
            row.received_measure_bound,
            row.is_among_success_line_owners_one_of_which_received,
        )
        for result, row in zip(
            network_request_results, network_request_rows, strict=True
        )
    ] == [
        (
            NetworkRequestResultCertainty.ASSUMED,
            MeasureBound.UPPER_ONLY,
            counts_trial_in_received_lower_bound,
        )
    ] * 2
    assert [(row.category, row.received_measure_bound) for row in measure_rows] == [
        (
            category,
            MeasureBound.LOWER_AND_UPPER
            if counts_trial_in_received_lower_bound
            else MeasureBound.UPPER_ONLY,
        )
    ]


def test_apt_download_and_install_lines_that_the_update_and_the_install_own_count_the_trial_in_the_received_lower_bound(
    tmp_path, write_trial_folder
):
    # `apt-get update` names no package, so it owns both lines of curl too, and only the two together show that the package arrived.
    trial_dir = write_trial_folder(
        tmp_path,
        "trial-1",
        [
            (
                "apt-get update && apt-get install -y curl",
                "Get:1 http://deb.debian.org/debian bookworm/main amd64 curl amd64 7.88.1-10 [10 kB]\nSetting up curl (7.88.1-10) ...",
            )
        ],
    )

    (
        (_, _, network_request_results, trial_row, network_request_rows, measure_rows),
        _,
        counters,
    ) = _run_steps_of_trial_with_new_counters(trial_dir)

    # Each request alone stays assumed and only in the upper bound of received.
    assert [
        (
            result.network_request.target,
            result.level,
            result.level_certainty,
            row.received_measure_bound,
            row.is_among_success_line_owners_one_of_which_received,
        )
        for result, row in zip(
            network_request_results, network_request_rows, strict=True
        )
    ] == [
        (
            target,
            NetworkRequestResultLevel.RECEIVED,
            NetworkRequestResultCertainty.ASSUMED,
            MeasureBound.UPPER_ONLY,
            True,
        )
        for target in (None, "curl")
    ]
    assert [(row.category, row.received_measure_bound) for row in measure_rows] == [
        (NetworkRequestCategory.PACKAGE, MeasureBound.LOWER_AND_UPPER)
    ]
    assert trial_row.any_category_received_measure_bound == MeasureBound.LOWER_AND_UPPER
    assert (
        counters["network_request_result_judgment_rule_use_counts"][
            network_request_result_judgment_rules.treat_apt_download_and_install_lines_shared_by_requests_of_several_commands_as_received.__name__
        ]
        == 2
    )
    assert (
        counters["export_judgment_rule_use_counts"][
            export_judgment_rules.treat_trial_with_success_line_shared_by_confirmed_requests_as_received.__name__
        ]
        == 1
    )
