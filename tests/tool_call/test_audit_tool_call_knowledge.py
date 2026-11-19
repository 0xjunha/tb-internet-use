"""Tests for scripts/audit_tool_call_knowledge.py, i.e. the audit of one trial, the sum over trials, the judgment rule rows and the CSVs that `main` writes, with made-up trials and made-up counts."""

import csv
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Self

import pytest

from tb_internet_use.knowledge.catalog import KnowledgeUses

_SPEC = importlib.util.spec_from_file_location(
    "audit_tool_call_knowledge",
    Path(__file__).parents[2] / "scripts/audit_tool_call_knowledge.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # registered as an import would do
_SPEC.loader.exec_module(audit)

# A made-up Claude Code trajectory with one `Bash` call, whose result has no `Exit code` line and a structured result that lets the rules give exit code 0.
_BASH_TRAJECTORY = {
    "schema_version": "ATIF-v1.7",
    "agent": {"name": "claude-code"},
    "steps": [
        {
            "step_id": 1,
            "tool_calls": [
                {
                    "tool_call_id": "a",
                    "function_name": "Bash",
                    "arguments": {"command": "echo hello"},
                }
            ],
            "observation": {
                "results": [
                    {
                        "source_call_id": "a",
                        "content": "hello",
                        "extra": {
                            "tool_result_metadata": {
                                "raw_tool_result": {"content": "hello"},
                                "tool_use_result": {
                                    "stdout": "hello",
                                    "interrupted": False,
                                },
                            }
                        },
                    }
                ]
            },
        }
    ],
}
_BASH_RULE_USES = {
    "treat_bash_output_without_exit_code_line_as_finished": 1,
    "treat_bash_output_without_exit_code_line_as_exit_code_0": 1,
}


def _trajectory_with_bash_and_unknown_tool(
    timeout: Any, *, step_count: int
) -> dict[str, Any]:
    """Give a made-up Claude Code trajectory of `step_count` steps, each with the `Bash` call of `_BASH_TRAJECTORY` and the given `timeout` argument, and a call without a result of a tool that the catalog has no row for."""
    [step] = _BASH_TRAJECTORY["steps"]
    [bash_call] = step["tool_calls"]
    [bash_result] = step["observation"]["results"]
    steps = []
    # Step ids are 1-based, as in the trajectories.
    for step_id in range(1, step_count + 1):
        bash_call_id = f"a{step_id}"
        bash_call_of_step = {
            **bash_call,
            "tool_call_id": bash_call_id,
            "arguments": {**bash_call["arguments"], "timeout": timeout},
        }
        unknown_call = {
            "tool_call_id": f"b{step_id}",
            "function_name": "NoSuchTool",
            "arguments": {"x": 1},
        }
        steps.append(
            {
                **step,
                "step_id": step_id,
                "tool_calls": [bash_call_of_step, unknown_call],
                "observation": {
                    "results": [{**bash_result, "source_call_id": bash_call_id}]
                },
            }
        )
    return {**_BASH_TRAJECTORY, "steps": steps}


def _trial_audit(
    judgment_rule_use_counts: dict[str, int], arguments: list[tuple[str, str, int]]
):
    """Give a made-up audit of one converted trial with the given rule uses and `Bash` arguments, each with the JSON type of its value and its number of calls."""
    return audit.TrialAudit(
        "converted",
        KnowledgeUses(),
        Counter(
            {
                ("claude-code", "Bash", name, type_name): calls
                for name, type_name, calls in arguments
            }
        ),
        Counter(judgment_rule_use_counts),
    )


class _InProcessPool:
    """Stand-in for the process pool of `main`, which maps in the test process so that the test starts no worker process."""

    def __init__(self, process_count: int) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def map(
        self, function: Callable[[Path], Any], items: Iterable[Path], chunksize: int
    ) -> Iterator[Any]:
        return map(function, items)


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as f:
        return list(csv.reader(f))


def test_audit_trial_returns_the_uses_of_the_door_the_rules_and_the_arguments(
    tmp_path: Path,
):
    trial_dir = tmp_path / "trial-1"
    trial_dir.mkdir()
    (trial_dir / "trajectory.json").write_text(json.dumps(_BASH_TRAJECTORY))
    trial_audit = audit.audit_trial(trial_dir)
    assert trial_audit.outcome == "converted"
    assert trial_audit.judgment_rule_use_counts == Counter(_BASH_RULE_USES)
    assert trial_audit.argument_value_call_counts == Counter(
        {("claude-code", "Bash", "command", "string"): 1}
    )
    assert (
        trial_audit.knowledge_uses.row_use_counts[
            "harness_result_formats", ("claude-code", "Bash", "bare_output")
        ]
        == 1
    )
    assert audit.audit_trial(tmp_path / "no-such-trial").outcome == "unreadable missing"


def test_trial_audit_total_adds_the_uses_and_counts_each_trial_once():
    total = audit.TrialAuditTotal()
    total.add_trial(_trial_audit({"r": 3}, [("command", "string", 2)]))
    # One trial whose calls give `timeout` values of two types counts once for it.
    total.add_trial(
        _trial_audit(
            {"r": 2, "s": 1},
            [
                ("command", "string", 1),
                ("timeout", "integer", 1),
                ("timeout", "string", 1),
            ],
        )
    )
    total.add_trial(audit.TrialAudit("unreadable missing"))
    assert total.outcome_counts == Counter({"converted": 2, "unreadable missing": 1})
    assert total.judgment_rule_use_counts == Counter({"r": 5, "s": 1})
    assert total.judgment_rule_trial_counts == Counter({"r": 2, "s": 1})
    assert total.argument_value_call_counts == Counter(
        {
            ("claude-code", "Bash", "command", "string"): 3,
            ("claude-code", "Bash", "timeout", "integer"): 1,
            ("claude-code", "Bash", "timeout", "string"): 1,
        }
    )
    assert total.argument_trial_counts == Counter(
        {("claude-code", "Bash", "command"): 2, ("claude-code", "Bash", "timeout"): 1}
    )


def test_judgment_rule_rows_list_every_rule_with_the_most_used_first_and_0_for_unused():
    use_counts = Counter(
        {
            "treat_negative_exit_code_as_killed": 5,
            "treat_web_fetch_text_as_finished": 7,
        }
    )
    trial_counts = Counter(
        {
            "treat_negative_exit_code_as_killed": 2,
            "treat_web_fetch_text_as_finished": 3,
        }
    )

    rows = list(audit.judgment_rule_rows(use_counts, trial_counts))

    assert rows[:2] == [
        ("treat_web_fetch_text_as_finished", 7, 3),
        ("treat_negative_exit_code_as_killed", 5, 2),
    ]
    # Every other rule follows with 0, by name.
    unused_names = [name for name, _, _ in rows[2:]]
    assert rows[2:] == [(name, 0, 0) for name in sorted(unused_names)]
    assert "treat_wait_on_several_tasks_as_their_shared_status" in unused_names


def test_main_writes_the_uses_the_unknown_inputs_the_arguments_and_the_rule_uses_of_the_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    raw_trials_dir = tmp_path / "raw"
    # The first trial has two steps, so each count of a lookup, a call or a rule use differs from its count of trials.
    for trial_name, timeout, step_count in (("trial-1", 5, 2), ("trial-2", "5", 1)):
        trial_dir = raw_trials_dir / trial_name
        trial_dir.mkdir(parents=True)
        trajectory = _trajectory_with_bash_and_unknown_tool(
            timeout, step_count=step_count
        )
        (trial_dir / "trajectory.json").write_text(json.dumps(trajectory))
    out_dir = tmp_path / "out"
    monkeypatch.setattr(audit, "OUT_DIR", out_dir)
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(sys, "argv", ["audit", str(raw_trials_dir)])

    audit.main()

    # Three rows of 3 lookups in 2 trials, in the order of their source and key.
    assert _csv_rows(out_dir / "row_uses.csv") == [
        ["source", "row_key", "lookup_count", "trial_count"],
        ["harness_result_formats", '["claude-code", "Bash", "bare_output"]', "3", "2"],
        ["harness_tool_arguments.csv", '["claude-code", "Bash", "command"]', "3", "2"],
        ["harness_tools.csv", '["claude-code", "Bash"]', "3", "2"],
    ]
    assert _csv_rows(out_dir / "unknown_inputs.csv") == [
        ["source", "key_asked", "lookup_count", "trial_count"],
        ["harness_tools.csv", '["claude-code", "NoSuchTool"]', "3", "2"],
    ]
    # `timeout` is an integer in one trial and a string in the other.
    assert _csv_rows(out_dir / "harness_tool_arguments_in_data.csv") == [
        [
            "harness",
            "tool",
            "argument",
            "call_count",
            "trial_count",
            "value_types",
            "action_field",
        ],
        ["claude-code", "Bash", "command", "3", "2", "string", "command_str"],
        ["claude-code", "Bash", "timeout", "3", "2", "integer|string", ""],
        ["claude-code", "NoSuchTool", "x", "3", "2", "integer", ""],
    ]
    judgment_rule_rows = _csv_rows(out_dir / "judgment_rule_uses.csv")
    assert judgment_rule_rows[:3] == [
        ["judgment_rule", "use_count", "trial_count"],
        ["treat_bash_output_without_exit_code_line_as_exit_code_0", "3", "2"],
        ["treat_bash_output_without_exit_code_line_as_finished", "3", "2"],
    ]
    assert {(uses, trials) for _, uses, trials in judgment_rule_rows[3:]} == {
        ("0", "0")
    }
