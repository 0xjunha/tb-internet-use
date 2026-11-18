"""Tests for pipeline.py, with made-up trial folders and made-up tool calls run through the steps with the doors made from the catalogs of the repo."""

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CallCommandText,
    FileText,
    FileUse,
    FileUseKind,
    RanShellText,
)
from tb_internet_use.network_request.model import (
    FromCommand,
    NetworkRequestCertainty,
    NoNetworkRequestReason,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineKind,
    UnusedOutputLineReason,
)
from tb_internet_use.pipeline import (
    KnowledgeDoors,
    read_trajectory,
    read_trial_file_texts,
    run_steps_to_expanded_tool_calls,
    run_steps_to_network_request_results,
    run_steps_to_network_requests,
)
from tb_internet_use.tool_call.model import (
    HarnessTool,
    HarnessToolCall,
    RunCommandAction,
    ToolCallKey,
    WriteFileAction,
)
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
        knowledge_doors=KnowledgeDoors(),
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


def test_each_step_counts_its_lookups_in_its_own_door_and_its_rules_in_its_own_counter():
    knowledge_doors = KnowledgeDoors()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    expanded_tool_call_judgment_rule_use_counts: Counter[str] = Counter()

    run_steps_to_expanded_tool_calls(
        _claude_code_tool_calls_running_a_script_in_the_background(),
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
    )

    # The two `Bash` calls ask `convert_tool_calls` the row of the tool, and cat in fetch.sh asks `expand_tool_calls` the row of the program.
    assert (
        knowledge_doors.tool_call_knowledge.uses.row_use_counts[
            "harness_tools.csv", ("claude-code", "Bash")
        ]
        == 2
    )
    assert (
        knowledge_doors.expanded_tool_call_knowledge.uses.row_use_counts[
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


def test_new_doors_count_only_their_own_lookups():
    first_doors = KnowledgeDoors()
    run_steps_to_network_requests(
        _claude_code_tool_calls_writing_and_running_a_script(),
        knowledge_doors=first_doors,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )

    second_doors = KnowledgeDoors()

    assert first_doors.tool_call_knowledge.uses.row_use_counts
    assert first_doors.expanded_tool_call_knowledge.uses.row_use_counts
    assert first_doors.network_request_knowledge.uses.row_use_counts
    assert not second_doors.tool_call_knowledge.uses.row_use_counts
    assert not second_doors.expanded_tool_call_knowledge.uses.row_use_counts
    assert not second_doors.network_request_knowledge.uses.row_use_counts


def test_runs_the_extraction_of_network_requests_after_the_expansion_with_its_own_door_and_counters():
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
    knowledge_doors = KnowledgeDoors()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    expanded_tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    network_request_judgment_rule_use_counts: Counter[str] = Counter()
    no_network_request_counts: Counter[NoNetworkRequestReason] = Counter()

    network_requests = run_steps_to_network_requests(
        (write_call, background_bash_call, task_output_call, later_bash_call),
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=expanded_tool_call_judgment_rule_use_counts,
        network_request_judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=no_network_request_counts,
    )

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
        knowledge_doors.network_request_knowledge.uses.row_use_counts[
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


def test_runs_the_decision_of_request_results_after_the_extraction_with_its_own_door_and_counters():
    # pip prints that it installed x, and the later call runs a script whose text the trial does not hold, which prints a download line.
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
    )
    knowledge_doors = KnowledgeDoors()
    tool_call_judgment_rule_use_counts: Counter[str] = Counter()
    network_request_judgment_rule_use_counts: Counter[str] = Counter()
    network_request_result_judgment_rule_use_counts: Counter[str] = Counter()
    unused_output_line_counts: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind]
    ] = Counter()
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ] = Counter()

    (network_request_result,) = run_steps_to_network_request_results(
        harness_tool_calls,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=tool_call_judgment_rule_use_counts,
        expanded_tool_call_judgment_rule_use_counts=Counter(),
        network_request_judgment_rule_use_counts=network_request_judgment_rule_use_counts,
        no_network_request_counts=Counter(),
        network_request_result_judgment_rule_use_counts=network_request_result_judgment_rule_use_counts,
        unused_output_line_counts=unused_output_line_counts,
        program_counts_of_unowned_output_lines=program_counts_of_unowned_output_lines,
    )

    assert network_request_result.network_request.target == "x"
    assert (
        network_request_result.level,
        network_request_result.stop_reason,
        network_request_result.level_certainty,
    ) == (
        NetworkRequestResultLevel.EXECUTED,
        NetworkRequestResultStopReason.NOT_VISIBLE,
        NetworkRequestResultCertainty.CONFIRMED,
    )
    assert (
        knowledge_doors.network_request_result_knowledge.uses.row_use_counts[
            "output_line_patterns", ("program_output", "pip_successfully_installed")
        ]
        == 1
    )
    # The result of a Claude Code `Bash` call gives no exit code, so no evidence shows that pip ran beyond its own line.
    assert network_request_result_judgment_rule_use_counts == Counter(
        {
            "treat_installed_line_as_no_evidence_of_download": 1,
            "treat_command_without_own_evidence_as_no_evidence_of_run": 1,
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
    # The rules of the earlier steps stay in their own counters.
    assert network_request_judgment_rule_use_counts == Counter()
    assert tool_call_judgment_rule_use_counts == Counter(
        {"treat_bash_output_without_exit_code_line_as_finished": 2}
    )
