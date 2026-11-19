"""Run `collect_trials` on raw trials, count the values of the `Trial` of each, hold them against sources that `collect_trials` does not read and compare every count with an expectation file.

Apart from its `trial_id`, which is the name of its folder, and its `unreadable_trajectory`, a `Trial` holds only what the detail and status file of a trial write, so a bug that reads the wrong key shows only beside another source.
The counts on the `Trial` values alone catch a later change of a value, and the counts beside the other sources catch a key read wrongly. `count_trials` and each `count_trials_against_` function say what they count and what they hold it against.
`--catalog` names the catalog of the collection, a JSON line per trial. `--snapshots` names the folder of the leaderboard snapshots, with a `row-<row id>-<page>.json` per page of a leaderboard row and a `board-*.json` per leaderboard. `--baseline` names the `per_trial.csv` of an earlier run. `--expected` names the expectation file of the expected counts, with the trials read by hand under `trials_read_by_hand`.

It writes `trials.csv`, `evidence_counts.csv` and `differing_trial_examples.csv` under `out/trials/`, or the folder that `--out-dir` names, which should lie under `out/` too, since `.gitignore` keeps that out of the repo. They hold trial ids, benchmark versions, task names, leaderboard row ids, harness names and versions, model names, rewards, reasons of `unreadable_trajectory`, count names and counts, never text from a trajectory.
The rows of each file are described above the call that writes it in `main`.
The script ends with exit code 1 when an expectation file is given and a count differs from it.

Run it as `nice -n 10 uv run python -I scripts/audit_trials.py <raw_trials_dir> --catalog FILE --snapshots DIR --baseline FILE [--expected FILE] [--out-dir DIR] [--limit N | --trial-ids FILE]`.
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from tb_internet_use.pipeline import read_trajectory, read_trial_file_texts
from tb_internet_use.trial import collect_trials
from tb_internet_use.trial.model import (
    Trial,
    TrialFileTexts,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    trial_dirs_of,
    write_csv,
)

# The folder is named after what one row of `trials.csv` is.
OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "trials"
# The trials kept per count and key, so that the CSV of examples stays short.
_EXAMPLE_LIMIT = 20
# The download states of the trajectory file that the status file and the catalog write.
_TRAJECTORY_DOWNLOADED = "downloaded"
_TRAJECTORY_UNAVAILABLE = "unavailable"
# The trajectory status of the earlier run's `per_trial.csv` for a trajectory that could be read.
_BASELINE_TRAJECTORY_READ = "ok"
# The fields of `Trial` compared with what another reader wrote down, i.e. all but `trial_id`, which finds the trial, and `unreadable_trajectory`, which the two files do not tell.
_FIELDS_READ_BY_HAND = (
    "benchmark_version",
    "task_name",
    "leaderboard_row_id",
    "harness",
    "harness_version",
    "model_name",
    "reward",
)

type EvidenceCount = int | Counter[str]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    arguments = parser.parse_args()

    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        trial_folder_readings = list(
            pool.map(read_trial_folder, chosen_trial_dirs_from(arguments), chunksize=20)
        )
    trials = collect_trials(
        (reading.trial_file_texts for reading in trial_folder_readings),
        {
            reading.trial_file_texts.trial_id: reading.unreadable_trajectory
            for reading in trial_folder_readings
            if reading.unreadable_trajectory is not None
        },
    )

    expected_counts: dict[str, Any] = (
        json.loads(arguments.expected.read_text())
        if arguments.expected is not None
        else {}
    )
    trials_read_by_hand = expected_counts.pop("trials_read_by_hand", [])
    total = EvidenceCountTotal()
    # The trial folders, which the trials and trial ids that `count_trials` counts are held against.
    total.counts["trial_folder_count"] = len(trial_dirs_of(arguments.raw_trials_dir))
    count_trials(total, trials)
    count_trials_against_folders(total, trials, trial_folder_readings)
    count_trials_against_catalog(
        total, trials, catalog_records_from_file_text(arguments.catalog.read_text())
    )
    count_trials_against_snapshots(
        total, trials, *snapshot_rows_from_folder(arguments.snapshots)
    )
    with arguments.baseline.open(newline="") as baseline_file:
        count_trials_against_baseline(
            total, trials, list(csv.DictReader(baseline_file))
        )
    count_trials_against_trials_read_by_hand(total, trials, trials_read_by_hand)

    evidence_rows = list(evidence_rows_of(total.counts, expected_counts))
    arguments.out_dir.mkdir(parents=True, exist_ok=True)
    # `trials.csv` has one row for each `Trial`, with its fields as columns and the reason of `unreadable_trajectory` or nothing.
    write_csv(
        arguments.out_dir / "trials.csv",
        [column.name for column in fields(Trial)],
        (_trial_row_of(trial) for trial in trials),
    )
    # `evidence_counts.csv` has one row for each count, or one key of a count by key, with the expected count from the expectation file, the count found and whether the two differ.
    # A count that the expectation file names and the run does not make, e.g. a misspelled name, shows with an empty found count and differs, and so does a count that the run makes and the expectation file lacks, with an empty expected count.
    # A count by key with no key found and none expected has no row, e.g. `trial_counts_by_field_differing_from_catalog` when no field differs.
    # A key of a count by key that the run does not find is found as 0, e.g. the reward key `below 0, above 1 or NaN`.
    write_csv(
        arguments.out_dir / "evidence_counts.csv",
        ("count_name", "key", "expected_count", "found_count", "differs"),
        evidence_rows,
    )
    # `differing_trial_examples.csv` has one row for each trial that a count of differences counted, the first 20 per count and key, and every field that differs from `trials_read_by_hand` with its trial.
    write_csv(
        arguments.out_dir / "differing_trial_examples.csv",
        ("count_name", "key", "trial_id"),
        total.differing_trial_examples,
    )
    differing_rows = [row for row in evidence_rows if row[4] == "yes"]
    for count_name, key, expected_count, found_count, _ in differing_rows:
        print(
            f"differs: {count_name} {key} expected {expected_count} found {found_count}"
        )
    print(f"trials: {len(trials)}, counts that differ: {len(differing_rows)}")
    print(f"written under {arguments.out_dir}")
    if arguments.expected is not None and differing_rows:
        sys.exit(1)


@dataclass(frozen=True, slots=True)
class TrialFolderReading:
    """Result of reading one trial folder in a worker process, which the main process passes to `collect_trials` and holds the trials against."""

    trial_file_texts: TrialFileTexts
    # The `UnreadableTrajectory` that `read_trajectory` gave in place of tool calls, or None when it read the trajectory, also one without tool calls.
    unreadable_trajectory: UnreadableTrajectory | None
    # The harness of the first tool call that `read_trajectory` gave, or None when it gave no tool call.
    first_tool_call_harness: str | None
    # The `id` of the detail file, or None when it has none.
    detail_trial_id: object
    # The `trial_id` of the status file, or None when it has none.
    status_trial_id: object
    # The `assets.trajectory.status` of the status file, or None when it has none.
    status_trajectory_status: object


def read_trial_folder(trial_dir: Path) -> TrialFolderReading:
    """Read the detail and status files and the trajectory of one trial folder, keeping from the trajectory only whether it was read and the harness of its first tool call."""
    trial_file_texts = read_trial_file_texts(trial_dir)
    harness_tool_calls = read_trajectory(trial_dir)
    detail_contents = json.loads(trial_file_texts.detail_text)
    status_contents = json.loads(trial_file_texts.status_text)
    unreadable_trajectory = (
        harness_tool_calls
        if isinstance(harness_tool_calls, UnreadableTrajectory)
        else None
    )
    first_tool_call_harness = (
        harness_tool_calls[0].tool.harness
        if not isinstance(harness_tool_calls, UnreadableTrajectory)
        and harness_tool_calls
        else None
    )
    return TrialFolderReading(
        trial_file_texts=trial_file_texts,
        unreadable_trajectory=unreadable_trajectory,
        first_tool_call_harness=first_tool_call_harness,
        detail_trial_id=_value_at(detail_contents, "id"),
        status_trial_id=_value_at(status_contents, "trial_id"),
        status_trajectory_status=_value_at(
            status_contents, "assets", "trajectory", "status"
        ),
    )


@dataclass(slots=True)
class EvidenceCountTotal:
    """Totals of one run of this script, i.e. its counts and the trials that its counts of differences counted, filled by `main` and the `count_` functions and written by `main`."""

    # A count by its name, either one number or a number per key, e.g. the trials per harness.
    counts: dict[str, EvidenceCount] = field(default_factory=dict)
    # (count name, key or "", trial id), the first `_EXAMPLE_LIMIT` per count and key, and every field that differs from a trial read by hand.
    differing_trial_examples: list[tuple[str, str, str]] = field(default_factory=list)

    def add_one(self, count_name: str, key: str = "") -> int:
        """Add one to a count, or to one key of it when a key is given, and give the new value."""
        if key:
            counter = self.counts.setdefault(count_name, Counter())
            assert isinstance(counter, Counter)
            counter[key] += 1
            return counter[key]
        number = self.counts.get(count_name, 0)
        assert isinstance(number, int)
        self.counts[count_name] = number + 1
        return number + 1

    def count_differing_trial(
        self, count_name: str, trial_id: str, key: str = ""
    ) -> None:
        """Add one trial to a count of differences, by key when one is given, and keep its id while the count and key have fewer examples than the limit."""
        if self.add_one(count_name, key) <= _EXAMPLE_LIMIT:
            self.differing_trial_examples.append((count_name, key, trial_id))

    def start_counts_at_zero(self, *count_names: str) -> None:
        """Set counts to 0, so that a count that finds no trial still shows."""
        for count_name in count_names:
            self.counts.setdefault(count_name, 0)


def count_trials(total: EvidenceCountTotal, trials: Sequence[Trial]) -> None:
    """Count the trials, their distinct values and their trials per value, from the `Trial` values alone.

    The trials per benchmark version, harness and reward, the distinct tasks, models and leaderboard rows, the trials without a model name, the trials per leaderboard row and task and the tasks per leaderboard row are held against nothing, so they catch a change of a value later.
    The leaderboard rows and tasks with several harness versions and the leaderboard rows with several harnesses or models are held against nothing too. A harness version that varies within the trials of one task of one leaderboard row breaks the premise that one run used one harness setup for every task.
    """
    total.counts["trial_count"] = len(trials)
    total.counts["distinct_trial_id_count"] = len({trial.trial_id for trial in trials})
    total.counts["trial_counts_by_benchmark_version"] = Counter(
        trial.benchmark_version for trial in trials
    )
    total.counts["trial_counts_by_harness"] = Counter(trial.harness for trial in trials)
    total.counts["distinct_task_name_count"] = len(
        {trial.task_name for trial in trials}
    )
    total.counts["distinct_benchmark_version_and_task_name_count"] = len(
        {(trial.benchmark_version, trial.task_name) for trial in trials}
    )
    total.counts["distinct_model_name_count"] = len(
        {trial.model_name for trial in trials if trial.model_name is not None}
    )
    total.counts["trial_without_model_name_count"] = sum(
        trial.model_name is None for trial in trials
    )
    total.counts["distinct_leaderboard_row_id_count"] = len(
        {trial.leaderboard_row_id for trial in trials}
    )
    trial_counts_by_leaderboard_row_and_task_name = Counter(
        (trial.leaderboard_row_id, trial.task_name) for trial in trials
    )
    total.counts["leaderboard_row_and_task_name_pair_counts_by_trial_count"] = Counter(
        str(trial_count)
        for trial_count in trial_counts_by_leaderboard_row_and_task_name.values()
    )
    total.counts["leaderboard_row_counts_by_task_name_count"] = Counter(
        str(task_name_count)
        for task_name_count in Counter(
            leaderboard_row_id
            for leaderboard_row_id, _ in trial_counts_by_leaderboard_row_and_task_name
        ).values()
    )
    total.counts["trial_counts_by_reward"] = Counter(
        reward_key_of(trial.reward) for trial in trials
    )

    harness_versions_by_leaderboard_row_and_task_name: defaultdict[
        tuple[str, str], set[str]
    ] = defaultdict(set)
    harnesses_and_model_names_by_leaderboard_row_id: defaultdict[
        str, set[tuple[str, str | None]]
    ] = defaultdict(set)
    for trial in trials:
        harness_versions_by_leaderboard_row_and_task_name[
            trial.leaderboard_row_id, trial.task_name
        ].add(trial.harness_version)
        harnesses_and_model_names_by_leaderboard_row_id[trial.leaderboard_row_id].add(
            (trial.harness, trial.model_name)
        )
    leaderboard_row_and_task_name_pairs_with_several_harness_versions = [
        leaderboard_row_and_task_name
        for (
            leaderboard_row_and_task_name,
            harness_versions,
        ) in harness_versions_by_leaderboard_row_and_task_name.items()
        if len(harness_versions) > 1
    ]
    total.counts[
        "leaderboard_row_and_task_name_pair_with_several_harness_versions_count"
    ] = len(leaderboard_row_and_task_name_pairs_with_several_harness_versions)
    total.counts[
        "leaderboard_row_counts_by_task_name_with_several_harness_versions_count"
    ] = Counter(
        str(task_name_count)
        for task_name_count in Counter(
            leaderboard_row_id
            for leaderboard_row_id, _ in (
                leaderboard_row_and_task_name_pairs_with_several_harness_versions
            )
        ).values()
    )
    total.counts["leaderboard_row_with_several_harnesses_or_model_names_count"] = sum(
        len({harness for harness, _ in harnesses_and_model_names}) > 1
        or len({model_name for _, model_name in harnesses_and_model_names}) > 1
        for harnesses_and_model_names in (
            harnesses_and_model_names_by_leaderboard_row_id.values()
        )
    )


def reward_key_of(reward: float | None) -> str:
    """Give the key under which `count_trials` counts a reward, i.e. `0.0`, `1.0`, `between 0 and 1`, `none` or `below 0, above 1 or NaN`."""
    if reward is None:
        return "none"
    if reward in (0.0, 1.0):
        return str(reward)
    if 0.0 < reward < 1.0:
        return "between 0 and 1"
    return "below 0, above 1 or NaN"


def count_trials_against_folders(
    total: EvidenceCountTotal,
    trials: Sequence[Trial],
    trial_folder_readings: Sequence[TrialFolderReading],
) -> None:
    """Hold each `Trial` against what the worker read from its folder beyond the texts that `collect_trials` reads, i.e. the trial ids in the two files, the download state of the trajectory and the harness of the first tool call.

    The trial ids are the `id` of the detail file and the `trial_id` of the status file, which `collect_trials` does not read.
    `Trial.unreadable_trajectory` is held against the download state of the trajectory file that the status file writes in `assets.trajectory.status`, and `Trial.harness` against the harness of the first tool call that `read_trajectory` gives, which `parse_trajectory` reads from the trajectory.
    """
    total.start_counts_at_zero(
        "trial_whose_folder_name_differs_from_detail_id_or_status_trial_id_count",
        "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count",
        "trial_with_tool_calls_count",
        "trial_whose_harness_differs_from_first_tool_call_harness_count",
        "readable_trial_without_tool_calls_count",
    )
    trial_counts_by_unreadable_trajectory_and_status: Counter[str] = Counter()
    for trial, reading in zip(trials, trial_folder_readings, strict=True):
        if reading.detail_trial_id != trial.trial_id or (
            reading.status_trial_id != trial.trial_id
        ):
            total.count_differing_trial(
                "trial_whose_folder_name_differs_from_detail_id_or_status_trial_id_count",
                trial.trial_id,
            )
        trial_counts_by_unreadable_trajectory_and_status[
            f"{_unreadable_trajectory_reason_of(trial)}, {reading.status_trajectory_status}"
        ] += 1
        if reading.status_trajectory_status != _trajectory_download_state_for(trial):
            total.count_differing_trial(
                "trial_whose_unreadable_trajectory_differs_from_status_trajectory_status_count",
                trial.trial_id,
            )
        if reading.first_tool_call_harness is not None:
            total.add_one("trial_with_tool_calls_count")
            if reading.first_tool_call_harness != trial.harness:
                total.count_differing_trial(
                    "trial_whose_harness_differs_from_first_tool_call_harness_count",
                    trial.trial_id,
                )
        elif trial.unreadable_trajectory is None:
            total.add_one("readable_trial_without_tool_calls_count")
    total.counts[
        "trial_counts_by_unreadable_trajectory_and_status_trajectory_status"
    ] = trial_counts_by_unreadable_trajectory_and_status


def count_trials_against_catalog(
    total: EvidenceCountTotal,
    trials: Sequence[Trial],
    catalog_records: Mapping[str, Mapping[str, Any]],
) -> None:
    """Hold each field of each `Trial` against the catalog record of its trial id, aligning the task, benchmark and model names of the catalog first.

    The catalog of the collection has a JSON line per trial that names the task without its `terminal-bench/` part, the benchmark as e.g. `TB4` and the model as `<provider>/<name>`, so these three are aligned before they are compared.
    """
    total.counts["trial_counts_by_field_differing_from_catalog"] = Counter()
    total.start_counts_at_zero("trial_missing_from_catalog_count")
    for trial in trials:
        catalog_record = catalog_records.get(trial.trial_id)
        if catalog_record is None:
            total.count_differing_trial(
                "trial_missing_from_catalog_count", trial.trial_id
            )
            continue
        for field_name in _field_names_differing_from_catalog_record_of(
            trial, catalog_record
        ):
            total.count_differing_trial(
                "trial_counts_by_field_differing_from_catalog",
                trial.trial_id,
                field_name,
            )
    total.counts["catalog_trial_not_audited_count"] = len(
        catalog_records.keys() - {trial.trial_id for trial in trials}
    )


def _field_names_differing_from_catalog_record_of(
    trial: Trial, catalog_record: Mapping[str, Any]
) -> Iterable[str]:
    """List the fields of a `Trial` that differ from its catalog record, after aligning the names of the catalog, e.g. none for the task `terminal-bench/a` beside the catalog task `a`."""
    memberships = _value_at(catalog_record, "memberships")
    catalog_leaderboard_row_id = (
        _value_at(memberships[0], "row_id")
        if isinstance(memberships, list) and len(memberships) == 1
        else None
    )
    catalog_model = _value_at(catalog_record, "model")
    catalog_values_and_trial_values = {
        "harness": (_value_at(catalog_record, "agent"), trial.harness),
        "harness_version": (
            _value_at(catalog_record, "agent_version"),
            trial.harness_version,
        ),
        "reward": (_value_at(catalog_record, "reward"), trial.reward),
        "benchmark_version": (
            _value_at(catalog_record, "benchmark"),
            f"TB{trial.benchmark_version.split('-')[0]}",
        ),
        "leaderboard_row_id": (catalog_leaderboard_row_id, trial.leaderboard_row_id),
        "task_name": (
            _value_at(catalog_record, "task"),
            trial.task_name.partition("/")[2],
        ),
        "model_name": (
            catalog_model.partition("/")[2] if isinstance(catalog_model, str) else None,
            trial.model_name,
        ),
        "trajectory_status": (
            _value_at(catalog_record, "assets", "trajectory", "status"),
            _trajectory_download_state_for(trial),
        ),
    }
    for field_name, (
        catalog_value,
        trial_value,
    ) in catalog_values_and_trial_values.items():
        if catalog_value != trial_value:
            yield field_name


def catalog_records_from_file_text(file_text: str) -> dict[str, Mapping[str, Any]]:
    """Give the records of a catalog file of JSON lines by their `trial_id`."""
    records = (json.loads(line) for line in file_text.splitlines() if line.strip())
    return {record["trial_id"]: record for record in records}


def count_trials_against_snapshots(
    total: EvidenceCountTotal,
    trials: Sequence[Trial],
    trial_ids_by_snapshot_row_id: Mapping[str, Sequence[str]],
    benchmark_version_by_snapshot_row_id: Mapping[str, str],
) -> None:
    """Hold the leaderboard row of each `Trial` against the leaderboard rows of the snapshots that list its trial id and its benchmark version against the leaderboard that holds its `leaderboard_row_id`, counting a trial that a row lists twice like one that two rows list."""
    total.counts["snapshot_leaderboard_row_count"] = len(trial_ids_by_snapshot_row_id)
    total.start_counts_at_zero(
        "trial_not_listed_exactly_once_in_snapshot_rows_count",
        "trial_whose_snapshot_row_differs_from_leaderboard_row_id_count",
        "trial_whose_snapshot_board_version_differs_from_benchmark_version_count",
    )
    snapshot_row_ids_by_trial_id: defaultdict[str, list[str]] = defaultdict(list)
    for snapshot_row_id, trial_ids in trial_ids_by_snapshot_row_id.items():
        for trial_id in trial_ids:
            snapshot_row_ids_by_trial_id[trial_id].append(snapshot_row_id)
    for trial in trials:
        snapshot_row_ids = snapshot_row_ids_by_trial_id.get(trial.trial_id, [])
        if len(snapshot_row_ids) != 1:
            total.count_differing_trial(
                "trial_not_listed_exactly_once_in_snapshot_rows_count", trial.trial_id
            )
        elif snapshot_row_ids[0] != trial.leaderboard_row_id:
            total.count_differing_trial(
                "trial_whose_snapshot_row_differs_from_leaderboard_row_id_count",
                trial.trial_id,
            )
        if (
            benchmark_version_by_snapshot_row_id.get(trial.leaderboard_row_id)
            != trial.benchmark_version
        ):
            total.count_differing_trial(
                "trial_whose_snapshot_board_version_differs_from_benchmark_version_count",
                trial.trial_id,
            )


def snapshot_rows_from_folder(
    snapshots_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Give the trial ids of each leaderboard row of the snapshots, joining the pages of a row and keeping an id that it lists twice, and the benchmark version of the leaderboard that holds each row.

    The snapshots are a `row-<row id>-<page>.json` per page of a leaderboard row that lists trial ids of the row and a `board-*.json` per leaderboard whose `leaderboard.name` is its benchmark version and whose `rows` are its leaderboard rows.
    """
    trial_ids_by_snapshot_row_id: defaultdict[str, list[str]] = defaultdict(list)
    for row_path in sorted(snapshots_dir.glob("row-*.json")):
        # The name is `row-<row id>-<page>.json`, and a row id holds dashes too.
        snapshot_row_id = row_path.stem.removeprefix("row-").rsplit("-", 1)[0]
        trial_ids_by_snapshot_row_id[snapshot_row_id].extend(
            entry["trial_id"] for entry in json.loads(row_path.read_text())
        )
    benchmark_version_by_snapshot_row_id: dict[str, str] = {}
    for board_path in sorted(snapshots_dir.glob("board-*.json")):
        board = json.loads(board_path.read_text())
        for board_row in board["rows"]:
            benchmark_version_by_snapshot_row_id[board_row["id"]] = board[
                "leaderboard"
            ]["name"]
    return dict(trial_ids_by_snapshot_row_id), benchmark_version_by_snapshot_row_id


def count_trials_against_baseline(
    total: EvidenceCountTotal,
    trials: Sequence[Trial],
    baseline_rows: Sequence[Mapping[str, str]],
) -> None:
    """Hold whether the trajectory of each `Trial` was read and its harness against the row of an earlier run's `per_trial.csv`, whose harness is empty when no tool call gave one.

    The file has the columns `trial_id`, `trajectory_status` and `harness`, with the status `ok`, `missing` or `invalid_json`.
    """
    total.start_counts_at_zero(
        "trial_missing_from_baseline_count",
        "trial_whose_unreadable_trajectory_differs_from_baseline_trajectory_status_count",
        "trial_with_baseline_harness_count",
        "trial_without_baseline_harness_count",
        "trial_whose_harness_differs_from_baseline_harness_count",
    )
    baseline_row_by_trial_id = {row["trial_id"]: row for row in baseline_rows}
    trial_counts_by_baseline_trajectory_status: Counter[str] = Counter()
    for trial in trials:
        baseline_row = baseline_row_by_trial_id.get(trial.trial_id)
        if baseline_row is None:
            total.count_differing_trial(
                "trial_missing_from_baseline_count", trial.trial_id
            )
            continue
        trial_counts_by_baseline_trajectory_status[
            baseline_row["trajectory_status"]
        ] += 1
        trajectory_status = (
            _BASELINE_TRAJECTORY_READ
            if trial.unreadable_trajectory is None
            else trial.unreadable_trajectory.reason.value
        )
        if baseline_row["trajectory_status"] != trajectory_status:
            total.count_differing_trial(
                "trial_whose_unreadable_trajectory_differs_from_baseline_trajectory_status_count",
                trial.trial_id,
            )
        if not baseline_row["harness"]:
            total.add_one("trial_without_baseline_harness_count")
            continue
        total.add_one("trial_with_baseline_harness_count")
        if baseline_row["harness"] != trial.harness:
            total.count_differing_trial(
                "trial_whose_harness_differs_from_baseline_harness_count",
                trial.trial_id,
            )
    total.counts["trial_counts_by_baseline_trajectory_status"] = (
        trial_counts_by_baseline_trajectory_status
    )
    total.counts["baseline_trial_not_audited_count"] = len(
        baseline_row_by_trial_id.keys() - {trial.trial_id for trial in trials}
    )


def count_trials_against_trials_read_by_hand(
    total: EvidenceCountTotal,
    trials: Sequence[Trial],
    trials_read_by_hand: Sequence[Mapping[str, Any]],
) -> None:
    """Hold each field of a `Trial` but `unreadable_trajectory` against the value that another reader wrote down from the detail and status files of the trial, counting the fields that differ.

    The values are those of a few trials, written down before this script ran and given in the expectation file under `trials_read_by_hand`.
    """
    total.start_counts_at_zero(
        "trial_read_by_hand_compared_count",
        "field_differing_from_trial_read_by_hand_count",
    )
    trial_by_trial_id = {trial.trial_id: trial for trial in trials}
    for trial_read_by_hand in trials_read_by_hand:
        trial = trial_by_trial_id.get(trial_read_by_hand["trial_id"])
        if trial is None:
            total.count_differing_trial(
                "trial_read_by_hand_not_audited_count", trial_read_by_hand["trial_id"]
            )
            continue
        total.add_one("trial_read_by_hand_compared_count")
        for field_name in _FIELDS_READ_BY_HAND:
            if trial_read_by_hand.get(field_name) != getattr(trial, field_name):
                # The count is one number, and the example names the field, since a trial can differ in several.
                total.add_one("field_differing_from_trial_read_by_hand_count")
                total.differing_trial_examples.append(
                    (
                        "field_differing_from_trial_read_by_hand_count",
                        field_name,
                        trial.trial_id,
                    )
                )


def evidence_rows_of(
    counts: Mapping[str, EvidenceCount], expected_counts: Mapping[str, Any]
) -> Iterable[tuple[str, str, str, str, str]]:
    """List every count and every key of a count by key as a CSV row of its name, key, expected count, found count and whether the two differ, in the order of the found counts and then of the counts only expected, leaving out a count by key with no key found and none expected."""
    for count_name in [
        *counts,
        *(name for name in expected_counts if name not in counts),
    ]:
        found_count = counts.get(count_name)
        expected_count = expected_counts.get(count_name)
        if isinstance(found_count, Counter) or isinstance(expected_count, dict):
            found_counts_by_key = (
                found_count if isinstance(found_count, Counter) else None
            )
            expected_counts_by_key = (
                expected_count if isinstance(expected_count, dict) else {}
            )
            for key in [
                *(found_counts_by_key or {}),
                *(
                    key
                    for key in expected_counts_by_key
                    if key not in (found_counts_by_key or {})
                ),
            ]:
                yield _evidence_row_of(
                    count_name,
                    key,
                    # A key that a found count by key lacks is found 0 times.
                    found_counts_by_key[key]
                    if found_counts_by_key is not None
                    else None,
                    expected_counts_by_key.get(key),
                )
        else:
            yield _evidence_row_of(count_name, "", found_count, expected_count)


def _evidence_row_of(
    count_name: str, key: str, found_count: int | None, expected_count: object
) -> tuple[str, str, str, str, str]:
    """Give the CSV row of one count or one key, which differs when the expected or the found count is missing or the two are different numbers."""
    differs = (
        expected_count is None or found_count is None or expected_count != found_count
    )
    return (
        count_name,
        key,
        "" if expected_count is None else str(expected_count),
        "" if found_count is None else str(found_count),
        "yes" if differs else "no",
    )


def _trajectory_download_state_for(trial: Trial) -> str:
    """Give the download state that the status file and the catalog must write for the trajectory of a `Trial`, i.e. unavailable for a missing file and downloaded for any other."""
    if (
        trial.unreadable_trajectory is not None
        and trial.unreadable_trajectory.reason is UnreadableTrajectoryReason.MISSING
    ):
        return _TRAJECTORY_UNAVAILABLE
    return _TRAJECTORY_DOWNLOADED


def _unreadable_trajectory_reason_of(trial: Trial) -> str:
    """Give the reason of the `unreadable_trajectory` of a `Trial`, or `none`."""
    if trial.unreadable_trajectory is None:
        return "none"
    return trial.unreadable_trajectory.reason.value


def _value_at(contents: object, *keys: str) -> object:
    """Give the value under nested keys of JSON contents, or None when a key or a JSON object on the way is missing."""
    for key in keys:
        if not isinstance(contents, dict):
            return None
        contents = contents.get(key)
    return contents


def _trial_row_of(trial: Trial) -> list[object]:
    """Give the CSV row of a `Trial`, with the reason of its `unreadable_trajectory` or an empty value."""
    return [
        (
            trial.unreadable_trajectory.reason.value
            if trial.unreadable_trajectory
            else ""
        )
        if column.name == "unreadable_trajectory"
        else getattr(trial, column.name)
        for column in fields(Trial)
    ]


if __name__ == "__main__":
    main()
