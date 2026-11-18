"""Tests for scripts/audit_network_request_results.py, with a made-up trial run through the steps on the catalogs of the repo, made-up results that break one equation each, and made-up trial folders run through `audit_trial` and `main`.

The equations hold whatever the catalogs say, so the cases use the catalogs of the repo and assert only counts of rows that they hold, e.g. `wget` and `curl -I` without other options.
"""

import csv
import dataclasses
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tb_internet_use.expanded_tool_call.model import ExpandedToolCall
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.network_request_result_knowledge import (
    NetworkRequestResultKnowledge,
)
from tb_internet_use.network_request import extract_network_requests
from tb_internet_use.network_request.model import (
    NetworkRequest,
    NetworkRequestCertainty,
    NetworkRequestUncertaintyReason,
    NoContentRequested,
)
from tb_internet_use.network_request_result import decide_network_request_results
from tb_internet_use.network_request_result.model import (
    ExitCodeEvidence,
    NetworkRequestResult,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
    OutputLineEvidence,
    OutputLineKind,
    UnusedOutputLineReason,
)
from tb_internet_use.pipeline import KnowledgeDoors, run_steps_to_expanded_tool_calls
from tb_internet_use.tool_call.model import HarnessTool, HarnessToolCall, ToolCallKey

_SPEC = importlib.util.spec_from_file_location(
    "audit_network_request_results",
    Path(__file__).parents[2] / "scripts/audit_network_request_results.py",
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # dataclasses look the module up while it loads
_SPEC.loader.exec_module(audit)


def _key(step_id: int) -> ToolCallKey:
    return ToolCallKey("t1", "main", step_id, 0)


def _bash_call(
    step_id: int, command: str, output: str, *, returncode: int = 0
) -> HarnessToolCall:
    """Make a mini-swe-agent `bash` call whose result gives its exit code and output."""
    return HarnessToolCall(
        _key(step_id),
        HarnessTool("mini-swe-agent", "bash"),
        str(step_id),
        {"command": command},
        {"content": json.dumps({"returncode": returncode, "output": output})},
    )


# A made-up mini-swe-agent trial. The comments name what each call adds.
_MADE_UP_TRIAL = (
    # A confirmed received result with exit code 0.
    _bash_call(1, "wget https://a.org/x.tgz", "'x.tgz' saved [1024/1024]"),
    # A request that asks for no content and succeeds at reached.
    _bash_call(2, "curl -I https://b.org", "HTTP/1.1 200 OK"),
    # A program that is not installed.
    _bash_call(3, "pip3 install x", "bash: pip3: command not found", returncode=127),
    # A line that no request owns, in the output of a script the trial does not hold.
    _bash_call(4, "./setup.sh", "Downloading torch-2.3.0.whl"),
    # A call that did not run.
    HarnessToolCall(
        _key(5),
        HarnessTool("mini-swe-agent", "bash"),
        "5",
        {"command": "curl https://c.org/z"},
        {"content": json.dumps({"exception_info": "action was not executed"})},
    ),
)


@dataclasses.dataclass(slots=True)
class _Steps:
    """Output of the steps on made-up calls, which a broken input changes before the check."""

    expanded_tool_calls: tuple[ExpandedToolCall, ...]
    network_requests: tuple[NetworkRequest, ...]
    network_request_results: tuple[NetworkRequestResult, ...]
    judgment_rule_use_counts: Counter[str]
    unused_output_line_counts: Counter[tuple[UnusedOutputLineReason, OutputLineKind]]
    program_counts_of_unowned_output_lines: Counter[
        tuple[UnusedOutputLineReason, OutputLineKind, str]
    ]


def _steps() -> _Steps:
    knowledge_doors = KnowledgeDoors()
    expanded_tool_calls = run_steps_to_expanded_tool_calls(
        _MADE_UP_TRIAL,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=Counter(),
        expanded_tool_call_judgment_rule_use_counts=Counter(),
    )
    network_requests = extract_network_requests(
        expanded_tool_calls,
        knowledge=knowledge_doors.network_request_knowledge,
        judgment_rule_use_counts=Counter(),
        no_network_request_counts=Counter(),
    )
    steps = _Steps(
        expanded_tool_calls, network_requests, (), Counter(), Counter(), Counter()
    )
    steps.network_request_results = decide_network_request_results(
        expanded_tool_calls,
        network_requests,
        knowledge=knowledge_doors.network_request_result_knowledge,
        judgment_rule_use_counts=steps.judgment_rule_use_counts,
        unused_output_line_counts=steps.unused_output_line_counts,
        program_counts_of_unowned_output_lines=steps.program_counts_of_unowned_output_lines,
    )
    return steps


def _checked(steps: _Steps) -> Any:
    """Check the output of the steps as `audit_trial` does and give the trial audit."""
    trial_audit = audit.TrialAudit(
        "t1",
        audit.DECIDED,
        harness="mini-swe-agent",
        task="4-0-0 terminal-bench/a",
        judgment_rule_use_counts=steps.judgment_rule_use_counts,
        unused_output_line_counts=steps.unused_output_line_counts,
        program_counts_of_unowned_output_lines=steps.program_counts_of_unowned_output_lines,
    )
    audit.TrialChecker(
        trial_audit,
        steps.expanded_tool_calls,
        steps.network_requests,
        steps.network_request_results,
        NetworkRequestResultKnowledge(),
    ).check()
    return trial_audit


def _differing_equations(trial_audit: Any) -> set[str]:
    return {
        equation
        for equation, _ in trial_audit.equation_sides
        if trial_audit.equation_sides[equation, "left"]
        != trial_audit.equation_sides[equation, "right"]
    }


def _result_of_step(steps: _Steps, step_id: int) -> NetworkRequestResult:
    (result,) = (
        result
        for result in steps.network_request_results
        if result.network_request.tool_call_key == _key(step_id)
    )
    return result


def test_every_equation_holds_on_a_made_up_trial():
    steps = _steps()

    trial_audit = _checked(steps)

    assert _differing_equations(trial_audit) == set()
    assert trial_audit.counts["all", "results"] == 4
    assert trial_audit.counts["all", "results received none confirmed"] == 1
    assert trial_audit.counts["all", "results reached none confirmed"] == 1
    assert trial_audit.counts["all", "results attempted failed confirmed"] == 2
    assert trial_audit.counts["all", "requests in the view received confirmed"] == 2
    assert trial_audit.received_trial_columns == {
        "with request",
        "with received",
        "with confirmed received",
        "with confirmed received of confirmed request",
    }
    assert trial_audit.has_unowned_line_in_unknown_run
    # The equations that this trial reaches have a value on their left side, so that each holds on something.
    assert {
        equation
        for equation in audit.EQUATIONS
        if trial_audit.equation_sides[equation, "left"] == 0
    } == {
        "results_outside_the_result_table",
        "confirmed_received_results_without_own_download_or_content_use",
        "confirmed_reached_successes_without_own_status",
        "lifted_requests_without_own_line",
    }


def test_the_docstring_table_lists_every_equation_in_order():
    table_rows = [
        line
        for line in (audit.__doc__ or "").splitlines()
        if line.startswith("| `") and line.count("|") == 4
    ]

    assert [row.split("`")[1] for row in table_rows] == list(audit.EQUATIONS)


def _with_result(steps: _Steps, step_id: int, result: NetworkRequestResult) -> _Steps:
    """Put a result in place of the result of the request of one call."""
    steps.network_request_results = tuple(
        result
        if old_result.network_request.tool_call_key == _key(step_id)
        else old_result
        for old_result in steps.network_request_results
    )
    return steps


def _unchecked_result(**fields: Any) -> NetworkRequestResult:
    """Make a result that `NetworkRequestResult.__post_init__` would refuse, as a broken step could give it."""
    result = object.__new__(NetworkRequestResult)
    for name, value in fields.items():
        object.__setattr__(result, name, value)
    return result


def _result_dropped(steps: _Steps) -> _Steps:
    steps.network_request_results = steps.network_request_results[:-1]
    return steps


def _result_with_the_key_of_another(steps: _Steps) -> _Steps:
    # The requests of pip3 and of the call that did not run both fail at attempted, so the result stays valid with the other request.
    not_run_request = _result_of_step(steps, 5).network_request
    return _with_result(
        steps,
        3,
        dataclasses.replace(_result_of_step(steps, 3), network_request=not_run_request),
    )


def _unused_lines_not_counted(steps: _Steps) -> _Steps:
    steps.unused_output_line_counts = Counter()
    return steps


def _exit_code_evidence_dropped(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 1)
    return _with_result(
        steps,
        1,
        dataclasses.replace(
            result,
            evidence=tuple(
                evidence
                for evidence in result.evidence
                if not isinstance(evidence, ExitCodeEvidence)
            ),
        ),
    )


def _not_run_result_without_its_status(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 5)
    return _with_result(
        steps,
        5,
        dataclasses.replace(
            result,
            stop_reason=NetworkRequestResultStopReason.NOT_VISIBLE,
            evidence=(),
        ),
    )


def _content_request_reached_without_stop_reason(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 1)
    return _with_result(
        steps,
        1,
        _unchecked_result(
            **{
                field.name: getattr(result, field.name)
                for field in dataclasses.fields(result)
            }
            | {"level": NetworkRequestResultLevel.REACHED}
        ),
    )


def _confirmed_received_on_a_shared_line(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 1)
    return _with_result(
        steps,
        1,
        dataclasses.replace(
            result,
            evidence=(
                OutputLineEvidence(_key(1), 0, None, OutputLineKind.DOWNLOADED, True),
            ),
        ),
    )


def _confirmed_reached_success_on_exit_code_alone(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 2)
    assert isinstance(
        result.network_request.received_content_destination, NoContentRequested
    )
    return _with_result(
        steps,
        2,
        dataclasses.replace(result, evidence=(ExitCodeEvidence(_key(2), 0, False),)),
    )


def _uncertain_request_lifted_without_a_line(steps: _Steps) -> _Steps:
    result = _result_of_step(steps, 1)
    return _with_result(
        steps,
        1,
        _unchecked_result(
            **{
                field.name: getattr(result, field.name)
                for field in dataclasses.fields(result)
            }
            | {
                "network_request": dataclasses.replace(
                    result.network_request,
                    certainty=NetworkRequestCertainty.UNCERTAIN,
                    uncertainty_reason=NetworkRequestUncertaintyReason.UNKNOWN_PROGRAM,
                ),
                "evidence": (ExitCodeEvidence(_key(1), 0, False),),
            }
        ),
    )


def _rule_of_another_step_counted(steps: _Steps) -> _Steps:
    steps.judgment_rule_use_counts["treat_dotted_host_name_as_public"] += 1
    return steps


# One broken input per equation, in the order of `EQUATIONS`.
BROKEN_INPUT_CASES: list[tuple[str, Callable[[_Steps], _Steps]]] = [
    ("results_equal_requests", _result_dropped),
    ("each_request_has_one_result_with_its_key", _result_with_the_key_of_another),
    ("matched_lines_equal_evidence_lines_and_unused_lines", _unused_lines_not_counted),
    (
        "exit_zero_requests_equal_results_with_exit_zero_evidence",
        _exit_code_evidence_dropped,
    ),
    (
        "not_run_requests_equal_not_run_failed_results",
        _not_run_result_without_its_status,
    ),
    (
        "results_outside_the_result_table",
        _content_request_reached_without_stop_reason,
    ),
    (
        "confirmed_received_results_without_own_download_or_content_use",
        _confirmed_received_on_a_shared_line,
    ),
    (
        "confirmed_reached_successes_without_own_status",
        _confirmed_reached_success_on_exit_code_alone,
    ),
    ("lifted_requests_without_own_line", _uncertain_request_lifted_without_a_line),
    ("judgment_rule_names_are_of_this_step", _rule_of_another_step_counted),
]


def test_every_equation_has_a_broken_input():
    assert [equation for equation, _ in BROKEN_INPUT_CASES] == list(audit.EQUATIONS)


@pytest.mark.parametrize(
    ("equation", "broken_input_of"),
    BROKEN_INPUT_CASES,
    ids=[equation for equation, _ in BROKEN_INPUT_CASES],
)
def test_a_broken_input_makes_its_equation_differ(equation, broken_input_of):
    trial_audit = _checked(broken_input_of(_steps()))

    assert equation in _differing_equations(trial_audit)


def test_lists_lines_by_kind_and_use_and_unowned_lines_by_program():
    trial_audit = _checked(_steps())

    unowned = (
        UnusedOutputLineReason.UNOWNED_LINE_IN_UNKNOWN_RUN.value,
        OutputLineKind.DOWNLOAD_STARTED.value,
    )
    assert (
        trial_audit.list_counts["output lines by kind", unowned[1:] + ("matched",)] == 1
    )
    assert (
        trial_audit.list_counts[
            "output lines by kind",
            (OutputLineKind.DOWNLOAD_STARTED.value, f"unused {unowned[0]}"),
        ]
        == 1
    )
    assert (
        trial_audit.list_counts[
            "output lines by kind",
            (OutputLineKind.DOWNLOADED.value, "evidence of one request"),
        ]
        == 1
    )
    assert trial_audit.list_counts["unowned output lines", (*unowned, "")] == 1
    assert trial_audit.list_counts["unowned output lines", (*unowned, "setup.sh")] == 1
    assert trial_audit.list_counts["evidence kinds", ("output line downloaded",)] == 1


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def test_writes_each_differing_call_with_its_trial_and_exits_1_only_then(tmp_path):
    differing = audit.TrialAudit("t1", audit.DECIDED)
    differing.add_sides("results_outside_the_result_table", 1, 0, _key(3))
    holding = audit.TrialAudit("t2", audit.DECIDED)
    holding.add_sides("results_outside_the_result_table", 0, 0, _key(3))
    total_of_holding = audit.TrialAuditTotal()
    total_of_holding.add_trial(holding)
    total = audit.TrialAuditTotal()
    total.add_trial(differing)
    total.add_trial(holding)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "equation_examples.csv") == [
        ["equation", "trial_id", "tool_call_key"],
        ["results_outside_the_result_table", "t1", "main:3:0"],
    ]
    assert not total_of_holding.has_exception_or_differing_equation()
    assert total.has_exception_or_differing_equation()


def test_writes_lists_rules_unknown_inputs_and_unowned_lines_by_task_over_trials(
    tmp_path,
):
    unowned_key = (
        "unowned output lines",
        ("unowned_line_in_unknown_run", "installed", ""),
    )
    unknown_input = ("program_output_lines.csv", ("pip", "install", "-q"))
    total = audit.TrialAuditTotal()
    for trial_id, task, has_request in (
        ("t1", "task a", True),
        ("t2", "task a", False),
        ("t3", "task b", True),
    ):
        knowledge_uses = KnowledgeUses()
        knowledge_uses.unknown_input_counts[unknown_input] += 2
        trial_audit = audit.TrialAudit(
            trial_id,
            audit.DECIDED,
            harness="codex",
            task=task,
            judgment_rule_use_counts=Counter(
                {"treat_installed_line_as_no_evidence_of_download": 1}
            ),
            knowledge_uses=knowledge_uses,
        )
        trial_audit.list_counts[unowned_key] += 3
        trial_audit.has_unowned_line_in_unknown_run = True
        if has_request:
            trial_audit.received_trial_columns.add("with request")
        total.add_trial(trial_audit)

    audit.write_audit_files(total, tmp_path)

    assert _csv_rows(tmp_path / "unowned_output_lines.csv")[1:] == [
        ["unowned_line_in_unknown_run", "installed", "", "9", "3", "2"],
    ]
    # The task whose trial without a request shows such a line comes first.
    assert _csv_rows(tmp_path / "unowned_output_lines_by_task.csv")[1:] == [
        ["task a", "2", "1"],
        ["task b", "1", "0"],
    ]
    assert _csv_rows(tmp_path / "judgment_rule_uses.csv")[1:] == [
        ["treat_installed_line_as_no_evidence_of_download", "3", "3", "2"],
    ]
    assert _csv_rows(tmp_path / "unknown_inputs.csv")[1:] == [
        ["program_output_lines.csv", "pip | install | -q", "6", "3", "2"],
    ]
    assert ["all", "3", "2", "0", "0", "0", "0"] in _csv_rows(
        tmp_path / "received_trials.csv"
    )


def test_every_equation_starts_at_zero_for_a_trial_that_was_not_decided():
    trial_audit = audit.TrialAudit("t1", audit.NOT_FOUND)

    assert list(trial_audit.equation_sides) == [
        (equation, side) for equation in audit.EQUATIONS for side in ("left", "right")
    ]


def test_an_unknown_equation_name_raises():
    with pytest.raises(ValueError, match="no equation"):
        audit.TrialAudit("t1", audit.DECIDED).add_sides("results", 1, 1, None)


def _raw_trials_dir(tmp_path: Path) -> Path:
    """Make a raw trials folder with the made-up trial t1, a Claude Code `Bash` call that runs pip."""
    trial_dir = tmp_path / "raw" / "t1"
    trial_dir.mkdir(parents=True)
    (trial_dir / "detail.json").write_text(
        json.dumps(
            {
                "id": "t1",
                "task_name": "terminal-bench/fix-git",
                "agent_info": {
                    "name": "claude-code",
                    "version": "2.1.0",
                    "model_info": {"name": "model-a"},
                },
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        )
    )
    (trial_dir / "status.json").write_text(
        json.dumps(
            {
                "trial_id": "t1",
                "memberships": [{"version": "4-0-0", "row_id": "row-1"}],
                "assets": {"trajectory": {"status": "downloaded"}},
            }
        )
    )
    trajectory = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "claude-code"},
        "steps": [
            {
                "step_id": 1,
                "tool_calls": [
                    {
                        "tool_call_id": "a",
                        "function_name": "Bash",
                        "arguments": {"command": "pip install x"},
                    }
                ],
                "observation": {
                    "results": [
                        {
                            "source_call_id": "a",
                            "content": "Successfully installed x-1.0",
                        }
                    ]
                },
            }
        ],
    }
    (trial_dir / "trajectory.json").write_text(json.dumps(trajectory))
    return tmp_path / "raw"


def test_audit_trial_decides_and_checks_a_trial_folder(tmp_path):
    trial_audit = audit.audit_trial(_raw_trials_dir(tmp_path) / "t1")

    assert trial_audit.outcome == audit.DECIDED
    assert trial_audit.harness == "claude-code"
    assert trial_audit.task == "4-0-0 terminal-bench/fix-git"
    assert _differing_equations(trial_audit) == set()
    assert trial_audit.counts["all", "results executed not_visible confirmed"] == 1
    assert (
        trial_audit.judgment_rule_use_counts[
            "treat_installed_line_as_no_evidence_of_download"
        ]
        == 1
    )


def test_audit_trial_gives_the_same_lookups_for_a_trial_audited_twice(tmp_path):
    trial_dir = _raw_trials_dir(tmp_path) / "t1"

    first = audit.audit_trial(trial_dir)
    second = audit.audit_trial(trial_dir)

    assert first.knowledge_uses.row_use_counts
    assert second.knowledge_uses == first.knowledge_uses


def test_audit_trial_names_a_missing_folder_apart_from_a_missing_trajectory(
    tmp_path,
):
    raw_trials_dir = _raw_trials_dir(tmp_path)
    (raw_trials_dir / "t2").mkdir()

    assert audit.audit_trial(raw_trials_dir / "t9").outcome == audit.NOT_FOUND
    assert audit.audit_trial(raw_trials_dir / "t2").outcome == "unreadable missing"


class _InProcessPool:
    """Stand-in for the process pool of `main`, which maps in the test process since a worker process could not import the script by its file path, and keeps the process count it was asked for."""

    # The process counts that `main` asked for, kept across instances.
    process_counts: ClassVar[list[int]] = []

    def __init__(self, process_count: int) -> None:
        self.process_counts.append(process_count)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def map(
        self, function: Callable[[Path], Any], items: Iterable[Path], chunksize: int
    ) -> Iterator[Any]:
        return map(function, items)


def _run_main(
    monkeypatch: pytest.MonkeyPatch, raw_trials_dir: Path, out_dir: Path
) -> None:
    """Run `main` on the trial ids t1, t1 again and t9, which names no folder."""
    trial_ids_file = raw_trials_dir.parent / "trial_ids.txt"
    trial_ids_file.write_text("t1\tclaude-code\nt1\nt9\n")
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_network_request_results",
            str(raw_trials_dir),
            "--trial-ids",
            str(trial_ids_file),
            "--out-dir",
            str(out_dir),
        ],
    )
    audit.main()


def test_main_runs_a_repeated_trial_once_and_names_a_missing_one(tmp_path, monkeypatch):
    _InProcessPool.process_counts.clear()
    out_dir = tmp_path / "out"

    _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert _InProcessPool.process_counts
    assert max(_InProcessPool.process_counts) <= 4
    assert _csv_rows(out_dir / "trial_outcomes.csv") == [
        ["outcome", "trial_count", "first_trial_ids"],
        ["decided", "1", "t1"],
        ["not found", "1", "t9"],
    ]
    equation_rows = _csv_rows(out_dir / "equations.csv")[1:]
    assert [row[0] for row in equation_rows] == list(audit.EQUATIONS)
    assert {row[3] for row in equation_rows} == {"yes"}
    assert ["all", "results", "1"] in _csv_rows(out_dir / "counts_by_harness.csv")


def test_main_names_a_trial_that_raised_and_exits_1(tmp_path, monkeypatch):
    def raise_error(*arguments: object, **keywords: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(audit, "decide_network_request_results", raise_error)
    out_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, _raw_trials_dir(tmp_path), out_dir)

    assert exit_info.value.code == 1
    assert _csv_rows(out_dir / "trials_not_decided.csv") == [
        ["trial_id", "outcome"],
        ["t1", "exception RuntimeError"],
        ["t9", "not found"],
    ]
