"""Tests for scripts/audit_trials.py, with made-up trials and made-up values of the other sources that break each count of differences."""

import csv
import dataclasses
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Self

import pytest

from tb_internet_use.trial.model import (
    Trial,
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

_SPEC = importlib.util.spec_from_file_location(
    "audit_trials", Path(__file__).parents[2] / "scripts/audit_trials.py"
)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = audit  # registered as an import would do
_SPEC.loader.exec_module(audit)

_MISSING = UnreadableTrajectory(UnreadableTrajectoryReason.MISSING)
_INVALID_JSON = UnreadableTrajectory(UnreadableTrajectoryReason.INVALID_JSON)


def _trial(trial_id: str = "t1", **changes: Any) -> Trial:
    """Give a made-up `Trial` of the task `terminal-bench/fix-git` in the leaderboard row `row-1`, with the given fields changed."""
    trial = Trial(
        trial_id=trial_id,
        benchmark_version="4-0-0",
        task_name="terminal-bench/fix-git",
        leaderboard_row_id="row-1",
        harness="claude-code",
        harness_version="2.1.0",
        model_name="model-a",
        reward=1.0,
        unreadable_trajectory=None,
    )
    return dataclasses.replace(trial, **changes)


def _folder_reading(trial: Trial, **changes: Any) -> Any:
    """Give the made-up reading of the folder of a trial that agrees with it in every value, with the given values changed."""
    reading = audit.TrialFolderReading(
        trial_file_texts=TrialFileTexts(trial.trial_id, b"", b""),
        unreadable_trajectory=trial.unreadable_trajectory,
        first_tool_call_harness=None if trial.unreadable_trajectory else trial.harness,
        detail_trial_id=trial.trial_id,
        status_trial_id=trial.trial_id,
        status_trajectory_status="unavailable"
        if trial.unreadable_trajectory == _MISSING
        else "downloaded",
    )
    return dataclasses.replace(reading, **changes)


def _catalog_record(**changes: Any) -> dict[str, Any]:
    """Give the made-up catalog record that agrees with `_trial()`, in the catalog's own names, with the given keys changed."""
    record = {
        "trial_id": "t1",
        "task": "fix-git",
        "benchmark": "TB4",
        "agent": "claude-code",
        "agent_version": "2.1.0",
        "model": "provider-a/model-a",
        "reward": 1.0,
        "memberships": [{"version": "4-0-0", "row_id": "row-1"}],
        "assets": {"trajectory": {"status": "downloaded"}},
    }
    return record | changes


def _baseline_row(
    trial_id: str = "t1", trajectory_status: str = "ok", harness: str = "claude-code"
) -> dict[str, str]:
    return {
        "trial_id": trial_id,
        "trajectory_status": trajectory_status,
        "harness": harness,
    }


def _trial_read_by_hand(**changes: Any) -> dict[str, Any]:
    """Give the values another reader wrote down for `_trial()`, with the reward written as the integer 1 as a detail file may write it."""
    return {
        "trial_id": "t1",
        "benchmark_version": "4-0-0",
        "task_name": "terminal-bench/fix-git",
        "leaderboard_row_id": "row-1",
        "harness": "claude-code",
        "harness_version": "2.1.0",
        "model_name": "model-a",
        "reward": 1,
    } | changes


def _counts_of(count_function: Any, *arguments: Any) -> dict[str, Any]:
    total = audit.EvidenceCountTotal()
    count_function(total, *arguments)
    return total.counts


def _data_dir(tmp_path: Path, *, catalog_agent_of_t1: str = "claude-code") -> Path:
    """Make a made-up data folder of two trials that every source agrees on, t1 with a trajectory of one Claude Code call and t2 without a trajectory, with the given harness for t1 in the catalog."""
    data_dir = tmp_path / "data"
    for trial_id, reward in (("t1", 1.0), ("t2", 0.0)):
        trial_dir = data_dir / "raw" / trial_id
        trial_dir.mkdir(parents=True)
        (trial_dir / "detail.json").write_text(
            json.dumps(
                {
                    "id": trial_id,
                    "task_name": "terminal-bench/fix-git",
                    "agent_info": {
                        "name": "claude-code",
                        "version": "2.1.0",
                        "model_info": {"name": "model-a"},
                    },
                    "verifier_result": {"rewards": {"reward": reward}},
                }
            )
        )
        trajectory_status = "downloaded" if trial_id == "t1" else "unavailable"
        (trial_dir / "status.json").write_text(
            json.dumps(
                {
                    "trial_id": trial_id,
                    "memberships": [{"version": "4-0-0", "row_id": "row-1"}],
                    "assets": {"trajectory": {"status": trajectory_status}},
                }
            )
        )
    tool_call = {"tool_call_id": "a", "function_name": "Bash", "arguments": {}}
    (data_dir / "raw" / "t1" / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "claude-code"},
                "steps": [{"step_id": 1, "tool_calls": [tool_call]}],
            }
        )
    )
    catalog_records = [
        _catalog_record(agent=catalog_agent_of_t1),
        _catalog_record(
            trial_id="t2",
            reward=0.0,
            assets={"trajectory": {"status": "unavailable"}},
        ),
    ]
    (data_dir / "catalog.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in catalog_records)
    )
    snapshots_dir = data_dir / "snapshots"
    snapshots_dir.mkdir()
    (snapshots_dir / "row-row-1-0.json").write_text(
        json.dumps([{"trial_id": "t1"}, {"trial_id": "t2"}])
    )
    (snapshots_dir / "board-4-0-0-0.json").write_text(
        json.dumps({"leaderboard": {"name": "4-0-0"}, "rows": [{"id": "row-1"}]})
    )
    (data_dir / "per_trial.csv").write_text(
        "trial_id,trajectory_status,harness\nt1,ok,claude-code\nt2,missing,\n"
    )
    return data_dir


class _InProcessPool:
    """Stand-in for the process pool of `main`, which maps in the test process so that a test starts no worker process."""

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


def _run_main(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, out_dir: Path, *options: str
) -> None:
    monkeypatch.setattr(audit, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_trials",
            str(data_dir / "raw"),
            "--catalog",
            str(data_dir / "catalog.jsonl"),
            "--snapshots",
            str(data_dir / "snapshots"),
            "--baseline",
            str(data_dir / "per_trial.csv"),
            "--out-dir",
            str(out_dir),
            *options,
        ],
    )
    audit.main()


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def _expected_counts_from_evidence_rows(
    evidence_rows: list[list[str]],
) -> dict[str, Any]:
    """Give the expectation file that the found counts of the rows of `evidence_counts.csv` make, with a count by key as an object."""
    expected_counts: dict[str, Any] = {}
    for count_name, key, _, found_count, _ in evidence_rows[1:]:
        if key:
            expected_counts.setdefault(count_name, {})[key] = int(found_count)
        else:
            expected_counts[count_name] = int(found_count)
    return expected_counts


# (made-up trial, a folder reading that breaks one count against it, the broken count)
FOLDER_DIFFERENCES = [
    pytest.param(
        _trial(),
        {"detail_trial_id": "t9"},
        "trial_whose_folder_name_differs_from_detail_id_or_status_trial_id_count",
        id="detail id",
    ),
    pytest.param(
        _trial(),
        {"status_trial_id": None},
        "trial_whose_folder_name_differs_from_detail_id_or_status_trial_id_count",
        id="status trial id",
    ),
    pytest.param(
        _trial(),
        {"status_trajectory_status": "unavailable"},
        "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count",
        id="read but unavailable",
    ),
    pytest.param(
        _trial(unreadable_trajectory=_MISSING),
        {"status_trajectory_status": "downloaded"},
        "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count",
        id="missing but downloaded",
    ),
    pytest.param(
        _trial(unreadable_trajectory=_INVALID_JSON),
        {"status_trajectory_status": "unavailable"},
        "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count",
        id="invalid but unavailable",
    ),
    pytest.param(
        _trial(),
        {"first_tool_call_harness": "codex"},
        "trial_whose_harness_differs_from_first_tool_call_harness_count",
        id="harness",
    ),
]

# (catalog keys that break one field, the field)
CATALOG_DIFFERENCES = [
    pytest.param({"agent": "codex"}, "harness", id="harness"),
    pytest.param({"agent_version": "2.2.0"}, "harness_version", id="harness version"),
    pytest.param({"reward": 0.0}, "reward", id="reward"),
    pytest.param({"reward": None}, "reward", id="reward missing"),
    pytest.param({"benchmark": "TB3"}, "benchmark_version", id="benchmark"),
    pytest.param(
        {"memberships": [{"row_id": "row-2"}]},
        "leaderboard_row_id",
        id="leaderboard row",
    ),
    pytest.param(
        {"memberships": [{"row_id": "row-1"}, {"row_id": "row-1"}]},
        "leaderboard_row_id",
        id="two memberships",
    ),
    pytest.param(
        {"task": "terminal-bench/fix-git"}, "task_name", id="task with its prefix"
    ),
    pytest.param({"model": "model-a"}, "model_name", id="model without provider"),
    pytest.param({"model": None}, "model_name", id="no model"),
    pytest.param(
        {"assets": {"trajectory": {"status": "unavailable"}}},
        "trajectory_status",
        id="trajectory status",
    ),
]

# (trial ids that each snapshot row lists, the broken count)
SNAPSHOT_DIFFERENCES = [
    pytest.param(
        {"row-1": ["t1"], "row-2": ["t1"]},
        "trial_not_listed_exactly_once_in_snapshot_rows_count",
        id="in two rows",
    ),
    pytest.param(
        {"row-1": ["t1", "t1"]},
        "trial_not_listed_exactly_once_in_snapshot_rows_count",
        id="twice in one row",
    ),
    pytest.param(
        {"row-1": []},
        "trial_not_listed_exactly_once_in_snapshot_rows_count",
        id="in no row",
    ),
    pytest.param(
        {"row-2": ["t1"]},
        "trial_whose_snapshot_row_differs_from_leaderboard_row_id_count",
        id="in another row",
    ),
]

# (made-up trial, baseline rows, the broken count)
BASELINE_DIFFERENCES = [
    pytest.param(
        _trial(),
        [_baseline_row(trajectory_status="missing")],
        "trial_whose_unreadable_trajectory_differs_from_baseline_trajectory_status_count",
        id="status",
    ),
    pytest.param(
        _trial(unreadable_trajectory=_INVALID_JSON),
        [_baseline_row(trajectory_status="missing")],
        "trial_whose_unreadable_trajectory_differs_from_baseline_trajectory_status_count",
        id="reason",
    ),
    pytest.param(
        _trial(),
        [_baseline_row(harness="codex")],
        "trial_whose_harness_differs_from_baseline_harness_count",
        id="harness",
    ),
    pytest.param(_trial(), [], "trial_missing_from_baseline_count", id="missing"),
]


def test_main_ends_with_exit_code_1_only_when_a_count_differs_from_its_expectation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data_dir = _data_dir(tmp_path)
    _run_main(monkeypatch, data_dir, tmp_path / "first")
    expected_counts = _expected_counts_from_evidence_rows(
        _csv_rows(tmp_path / "first" / "evidence_counts.csv")
    )
    expected_file = tmp_path / "expected.json"

    # The counts that the first run wrote agree, unless it left out of the CSV a count that has a value, which the second run would then find without an expectation.
    expected_file.write_text(json.dumps(expected_counts))
    _run_main(
        monkeypatch, data_dir, tmp_path / "second", "--expected", str(expected_file)
    )
    expected_file.write_text(json.dumps(expected_counts | {"trial_count": 3}))
    with pytest.raises(SystemExit) as exit_info:
        _run_main(
            monkeypatch, data_dir, tmp_path / "third", "--expected", str(expected_file)
        )

    assert expected_counts["trial_count"] == 2
    second_evidence_rows = _csv_rows(tmp_path / "second" / "evidence_counts.csv")
    assert {differs for *_, differs in second_evidence_rows[1:]} == {"no"}
    assert exit_info.value.code == 1


def test_main_writes_every_trial_with_its_unreadable_trajectory_and_every_differing_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    data_dir = _data_dir(tmp_path, catalog_agent_of_t1="codex")

    _run_main(monkeypatch, data_dir, tmp_path / "out")

    common_values = ["4-0-0", "terminal-bench/fix-git", "row-1", "claude-code"]
    assert _csv_rows(tmp_path / "out" / "trials.csv") == [
        [field.name for field in dataclasses.fields(Trial)],
        ["t1", *common_values, "2.1.0", "model-a", "1.0", ""],
        ["t2", *common_values, "2.1.0", "model-a", "0.0", "missing"],
    ]
    assert _csv_rows(tmp_path / "out" / "differing_trial_examples.csv") == [
        ["count_name", "key", "trial_id"],
        ["trial_counts_by_field_differing_from_catalog", "harness", "t1"],
    ]


def test_main_counts_every_trial_folder_beside_the_trials_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _run_main(monkeypatch, _data_dir(tmp_path), tmp_path / "out", "--limit", "1")

    found_counts = {
        count_name: found_count
        for count_name, key, _, found_count, _ in _csv_rows(
            tmp_path / "out" / "evidence_counts.csv"
        )
        if not key
    }
    assert (found_counts["trial_folder_count"], found_counts["trial_count"]) == (
        "2",
        "1",
    )


def test_reads_a_trial_folder_and_the_harness_of_its_first_tool_call(tmp_path):
    trial_dir = tmp_path / "t1"
    trial_dir.mkdir()
    (trial_dir / "detail.json").write_text(json.dumps({"id": "d1"}))
    (trial_dir / "status.json").write_text(
        json.dumps(
            {"trial_id": "s1", "assets": {"trajectory": {"status": "downloaded"}}}
        )
    )
    tool_call = {"tool_call_id": "a", "function_name": "bash", "arguments": {}}
    (trial_dir / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.7",
                "agent": {"name": "codex"},
                "steps": [{"step_id": 1, "tool_calls": [tool_call]}],
            }
        )
    )

    reading = audit.read_trial_folder(trial_dir)

    assert (reading.unreadable_trajectory, reading.first_tool_call_harness) == (
        None,
        "codex",
    )
    assert (
        reading.detail_trial_id,
        reading.status_trial_id,
        reading.status_trajectory_status,
    ) == ("d1", "s1", "downloaded")


def test_reads_a_trial_folder_without_a_trajectory_as_missing(tmp_path):
    trial_dir = tmp_path / "t1"
    trial_dir.mkdir()
    (trial_dir / "detail.json").write_text("{}")
    (trial_dir / "status.json").write_text("{}")

    reading = audit.read_trial_folder(trial_dir)

    assert (reading.unreadable_trajectory, reading.first_tool_call_harness) == (
        _MISSING,
        None,
    )
    assert (
        reading.detail_trial_id,
        reading.status_trial_id,
        reading.status_trajectory_status,
    ) == (None, None, None)


def test_reads_no_value_under_a_json_value_that_is_no_object(tmp_path):
    trial_dir = tmp_path / "t1"
    trial_dir.mkdir()
    (trial_dir / "detail.json").write_text("[]")
    (trial_dir / "status.json").write_text(
        json.dumps({"assets": {"trajectory": "downloaded"}})
    )

    reading = audit.read_trial_folder(trial_dir)

    assert (reading.detail_trial_id, reading.status_trajectory_status) == (None, None)


def test_keeps_at_most_the_example_limit_of_trials_per_count_and_key():
    total = audit.EvidenceCountTotal()

    for index in range(audit._EXAMPLE_LIMIT + 1):
        total.count_differing_trial("c", f"t{index}", "k")
    total.count_differing_trial("c", "u", "other key")

    assert total.counts["c"] == {"k": audit._EXAMPLE_LIMIT + 1, "other key": 1}
    assert len(total.differing_trial_examples) == audit._EXAMPLE_LIMIT + 1


def test_counts_trials_by_value_on_made_up_trials():
    # Two harnesses, three models, four tasks, five leaderboard rows and six pairs of benchmark version and task, so a count taken from the wrong field differs.
    trials = [
        _trial("t1"),
        _trial("t2", reward=0.0),
        _trial("t3", task_name="terminal-bench/b", reward=0.25),
        _trial(
            "t4",
            benchmark_version="3-0-0",
            leaderboard_row_id="row-2",
            harness="codex",
            model_name="model-b",
            reward=None,
        ),
        # Another leaderboard row of the same benchmark version and task, which only the leaderboard row tells apart.
        _trial("t5", leaderboard_row_id="row-3"),
        _trial(
            "t6",
            task_name="terminal-bench/c",
            leaderboard_row_id="row-4",
            harness="codex",
            model_name="model-c",
        ),
        _trial(
            "t7",
            benchmark_version="3-0-0",
            task_name="terminal-bench/d",
            leaderboard_row_id="row-5",
            model_name="model-c",
        ),
        _trial(
            "t8",
            task_name="terminal-bench/d",
            leaderboard_row_id="row-5",
            model_name="model-c",
        ),
    ]

    counts = _counts_of(audit.count_trials, trials)

    assert counts["trial_count"] == 8
    assert counts["distinct_trial_id_count"] == 8
    assert counts["trial_counts_by_benchmark_version"] == {"4-0-0": 6, "3-0-0": 2}
    assert counts["trial_counts_by_harness"] == {"claude-code": 6, "codex": 2}
    assert counts["distinct_task_name_count"] == 4
    assert counts["distinct_benchmark_version_and_task_name_count"] == 6
    assert counts["distinct_model_name_count"] == 3
    assert counts["distinct_leaderboard_row_id_count"] == 5
    assert counts["leaderboard_row_and_task_name_pair_counts_by_trial_count"] == {
        "2": 2,
        "1": 4,
    }
    assert counts["leaderboard_row_counts_by_task_name_count"] == {"2": 1, "1": 4}
    assert counts["trial_counts_by_reward"] == {
        "1.0": 5,
        "0.0": 1,
        "between 0 and 1": 1,
        "none": 1,
    }


def test_counts_a_repeated_trial_id_once_among_the_distinct_ids():
    counts = _counts_of(audit.count_trials, [_trial("t1"), _trial("t1")])

    assert (counts["trial_count"], counts["distinct_trial_id_count"]) == (2, 1)


def test_counts_tasks_of_a_leaderboard_row_with_several_harness_versions_per_row():
    # row-1 has two such tasks and row-2 one other task, so counting per task instead of per row gives three tasks of one row each.
    trials = [
        _trial("t1"),
        _trial("t2", harness_version="2.2.0"),
        _trial("t3", task_name="terminal-bench/b"),
        _trial("t4", task_name="terminal-bench/b", harness_version="2.2.0"),
        _trial("t5", task_name="terminal-bench/c"),
        _trial(
            "t6",
            task_name="terminal-bench/d",
            leaderboard_row_id="row-2",
            harness_version="9",
        ),
        _trial(
            "t7",
            task_name="terminal-bench/d",
            leaderboard_row_id="row-2",
            harness_version="8",
        ),
    ]

    counts = _counts_of(audit.count_trials, trials)

    assert (
        counts["leaderboard_row_and_task_name_pair_with_several_harness_versions_count"]
        == 3
    )
    assert counts[
        "leaderboard_row_counts_by_task_name_with_several_harness_versions_count"
    ] == {"2": 1, "1": 1}
    assert counts["leaderboard_row_with_several_harnesses_or_model_names_count"] == 0


@pytest.mark.parametrize("change", [{"harness": "codex"}, {"model_name": "model-b"}])
def test_counts_a_leaderboard_row_with_several_harnesses_or_model_names(change):
    counts = _counts_of(audit.count_trials, [_trial("t1"), _trial("t2", **change)])

    assert counts["leaderboard_row_with_several_harnesses_or_model_names_count"] == 1


@pytest.mark.parametrize(
    ("reward", "key"),
    [
        (0.0, "0.0"),
        (1.0, "1.0"),
        (0.5, "between 0 and 1"),
        (None, "none"),
        (-0.5, "below 0, above 1 or NaN"),
        (2.0, "below 0, above 1 or NaN"),
        (float("nan"), "below 0, above 1 or NaN"),
    ],
)
def test_reward_key_puts_each_reward_under_its_key(reward, key):
    assert audit.reward_key_of(reward) == key


def test_trials_that_agree_with_their_folders_count_no_difference():
    trials = [
        _trial("t1"),
        _trial("t2", unreadable_trajectory=_MISSING),
        _trial("t3", unreadable_trajectory=_INVALID_JSON),
    ]

    counts = _counts_of(
        audit.count_trials_against_folders,
        trials,
        [_folder_reading(trial) for trial in trials],
    )

    assert counts == {
        "trial_whose_folder_name_differs_from_detail_id_or_status_trial_id_count": 0,
        "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count": 0,
        "trial_with_tool_calls_count": 1,
        "trial_whose_harness_differs_from_first_tool_call_harness_count": 0,
        "readable_trial_without_tool_calls_count": 0,
        "trial_counts_by_unreadable_trajectory_and_status_trajectory_status": {
            "none, downloaded": 1,
            "missing, unavailable": 1,
            "invalid_json, downloaded": 1,
        },
    }


@pytest.mark.parametrize(("trial", "change", "count_name"), FOLDER_DIFFERENCES)
def test_a_folder_reading_that_differs_counts_the_trial(trial, change, count_name):
    total = audit.EvidenceCountTotal()

    audit.count_trials_against_folders(
        total, [trial], [_folder_reading(trial, **change)]
    )

    assert total.counts[count_name] == 1
    assert total.differing_trial_examples == [(count_name, "", trial.trial_id)]


def test_a_readable_trajectory_without_tool_calls_is_counted_apart():
    trial = _trial()

    counts = _counts_of(
        audit.count_trials_against_folders,
        [trial],
        [_folder_reading(trial, first_tool_call_harness=None)],
    )

    assert (
        counts["readable_trial_without_tool_calls_count"],
        counts["trial_with_tool_calls_count"],
    ) == (1, 0)


def test_a_catalog_record_in_its_own_names_agrees_in_every_field():
    counts = _counts_of(
        audit.count_trials_against_catalog, [_trial()], {"t1": _catalog_record()}
    )

    assert counts == {
        "trial_counts_by_field_differing_from_catalog": {},
        "trial_missing_from_catalog_count": 0,
        "catalog_trial_not_audited_count": 0,
    }


def test_a_model_name_with_a_slash_agrees_with_the_catalog_model_after_its_provider():
    counts = _counts_of(
        audit.count_trials_against_catalog,
        [_trial(model_name="org/model-a")],
        {"t1": _catalog_record(model="provider-a/org/model-a")},
    )

    assert counts["trial_counts_by_field_differing_from_catalog"] == {}


@pytest.mark.parametrize(("change", "field_name"), CATALOG_DIFFERENCES)
def test_a_catalog_record_that_differs_counts_the_field(change, field_name):
    total = audit.EvidenceCountTotal()

    audit.count_trials_against_catalog(
        total, [_trial()], {"t1": _catalog_record(**change)}
    )

    assert total.counts["trial_counts_by_field_differing_from_catalog"] == {
        field_name: 1
    }
    assert total.differing_trial_examples == [
        ("trial_counts_by_field_differing_from_catalog", field_name, "t1")
    ]


def test_counts_trials_missing_from_the_catalog_and_catalog_trials_not_audited():
    counts = _counts_of(
        audit.count_trials_against_catalog,
        [_trial("t1")],
        {"t2": _catalog_record(trial_id="t2")},
    )

    assert counts["trial_missing_from_catalog_count"] == 1
    assert counts["catalog_trial_not_audited_count"] == 1


def test_reads_the_catalog_records_by_trial_id():
    file_text = '{"trial_id": "t1", "agent": "a"}\n\n{"trial_id": "t2", "agent": "b"}\n'

    records = audit.catalog_records_from_file_text(file_text)

    assert {trial_id: record["agent"] for trial_id, record in records.items()} == {
        "t1": "a",
        "t2": "b",
    }


@pytest.mark.parametrize(
    ("trial_ids_by_snapshot_row_id", "count_name"), SNAPSHOT_DIFFERENCES
)
def test_a_trial_not_listed_once_by_its_own_snapshot_row_alone_is_counted(
    trial_ids_by_snapshot_row_id, count_name
):
    counts = _counts_of(
        audit.count_trials_against_snapshots,
        [_trial()],
        trial_ids_by_snapshot_row_id,
        {"row-1": "4-0-0", "row-2": "4-0-0"},
    )

    assert counts[count_name] == 1


def test_a_trial_listed_by_its_snapshot_row_of_its_board_counts_no_difference():
    counts = _counts_of(
        audit.count_trials_against_snapshots,
        [_trial()],
        {"row-1": ["t1"], "row-2": []},
        {"row-1": "4-0-0"},
    )

    assert counts == {
        "snapshot_leaderboard_row_count": 2,
        "trial_not_listed_exactly_once_in_snapshot_rows_count": 0,
        "trial_whose_snapshot_row_differs_from_leaderboard_row_id_count": 0,
        "trial_whose_snapshot_board_version_differs_from_benchmark_version_count": 0,
    }


@pytest.mark.parametrize(
    "benchmark_version_by_snapshot_row_id", [{"row-1": "3-0-0"}, {}]
)
def test_a_board_of_another_version_or_none_counts_the_trial(
    benchmark_version_by_snapshot_row_id,
):
    counts = _counts_of(
        audit.count_trials_against_snapshots,
        [_trial()],
        {"row-1": ["t1"]},
        benchmark_version_by_snapshot_row_id,
    )

    assert (
        counts[
            "trial_whose_snapshot_board_version_differs_from_benchmark_version_count"
        ]
        == 1
    )


def test_reads_snapshot_rows_joining_pages_and_the_version_of_their_board(tmp_path):
    (tmp_path / "row-ab-12-0.json").write_text(json.dumps([{"trial_id": "t1"}]))
    (tmp_path / "row-ab-12-1.json").write_text(
        json.dumps([{"trial_id": "t2"}, {"trial_id": "t1"}])
    )
    (tmp_path / "board-3-0-0-1.json").write_text(
        json.dumps({"leaderboard": {"name": "3-0-0"}, "rows": [{"id": "ab-12"}]})
    )

    trial_ids_by_snapshot_row_id, benchmark_version_by_snapshot_row_id = (
        audit.snapshot_rows_from_folder(tmp_path)
    )

    # Both pages list t1, and both ids stay.
    assert trial_ids_by_snapshot_row_id == {"ab-12": ["t1", "t2", "t1"]}
    assert benchmark_version_by_snapshot_row_id == {"ab-12": "3-0-0"}


def test_baseline_rows_that_agree_count_no_difference():
    trials = [_trial("t1"), _trial("t2", unreadable_trajectory=_MISSING)]

    counts = _counts_of(
        audit.count_trials_against_baseline,
        trials,
        [_baseline_row("t1"), _baseline_row("t2", "missing", ""), _baseline_row("t3")],
    )

    assert counts == {
        "trial_missing_from_baseline_count": 0,
        "trial_whose_unreadable_trajectory_differs_from_baseline_trajectory_status_count": 0,
        "trial_with_baseline_harness_count": 1,
        "trial_without_baseline_harness_count": 1,
        "trial_whose_harness_differs_from_baseline_harness_count": 0,
        "trial_counts_by_baseline_trajectory_status": {"ok": 1, "missing": 1},
        "baseline_trial_not_audited_count": 1,
    }


@pytest.mark.parametrize(("trial", "baseline_rows", "count_name"), BASELINE_DIFFERENCES)
def test_a_baseline_row_that_differs_counts_the_trial(trial, baseline_rows, count_name):
    counts = _counts_of(audit.count_trials_against_baseline, [trial], baseline_rows)

    assert counts[count_name] == 1


def test_values_read_by_hand_that_agree_count_no_field():
    counts = _counts_of(
        audit.count_trials_against_trials_read_by_hand,
        [_trial()],
        [_trial_read_by_hand()],
    )

    assert counts == {
        "trial_read_by_hand_compared_count": 1,
        "field_differing_from_trial_read_by_hand_count": 0,
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "benchmark_version",
        "task_name",
        "leaderboard_row_id",
        "harness",
        "harness_version",
        "model_name",
        "reward",
    ],
)
def test_a_value_read_by_hand_that_differs_counts_its_field(field_name):
    total = audit.EvidenceCountTotal()

    audit.count_trials_against_trials_read_by_hand(
        total, [_trial()], [_trial_read_by_hand(**{field_name: "other"})]
    )

    assert total.counts["field_differing_from_trial_read_by_hand_count"] == 1
    assert total.differing_trial_examples == [
        ("field_differing_from_trial_read_by_hand_count", field_name, "t1")
    ]


def test_a_trial_read_by_hand_that_was_not_audited_is_counted_apart():
    counts = _counts_of(
        audit.count_trials_against_trials_read_by_hand, [], [_trial_read_by_hand()]
    )

    assert counts == {
        "trial_read_by_hand_compared_count": 0,
        "field_differing_from_trial_read_by_hand_count": 0,
        "trial_read_by_hand_not_audited_count": 1,
    }


def test_evidence_rows_compare_each_count_and_key_with_the_expected_count():
    counts = {"a": 3, "b": 1, "by_key": Counter({"x": 2, "y": 1})}
    expected_counts = {
        "a": 3,
        "by_key": {"x": 2, "z": 0},
        "only_expected": 0,
        "only_expected_by_key": {"k": 0},
    }

    rows = list(audit.evidence_rows_of(counts, expected_counts))

    assert rows == [
        ("a", "", "3", "3", "no"),
        ("b", "", "", "1", "yes"),
        ("by_key", "x", "2", "2", "no"),
        ("by_key", "y", "", "1", "yes"),
        # A key that a found count by key lacks is found 0 times.
        ("by_key", "z", "0", "0", "no"),
        # A count that the run does not make, e.g. a misspelled name, differs even when 0 is expected.
        ("only_expected", "", "0", "", "yes"),
        ("only_expected_by_key", "k", "0", "", "yes"),
    ]
