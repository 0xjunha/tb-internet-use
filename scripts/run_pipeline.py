"""Run every step of the pipeline on raw trials and write the rows of each trial, the unknown inputs and use counts of each step, the trials that raised and the equations between steps.

Each trial runs `run_steps_of_trial` in one of at most 4 worker processes, whose doors are made once per process and start empty for each trial.
The `Trial` and the network request results of each trial are saved as they come, so that a long run that stops can go on with `--resume`, and `--export-only` runs `export_rows` again on the saved results without reading a trajectory, e.g. after a rule of `export/judgment_rules.py` changed.
The rows are written once all trials are done, sorted by trial id, so that they do not depend on the order in which the trials finished.
Progress goes to stderr every few hundred trials. No text of a trajectory is printed.

It writes these files under the output folder, `out/pipeline/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo, since the rows hold targets and host names from trajectories.

| File | One row |
|---|---|
| `network_request_rows.csv` | A `NetworkRequestRow`, with the fields of the type as columns in their order |
| `trial_rows.csv` | A `TrialRow` |
| `trial_category_measure_rows.csv` | A `TrialCategoryMeasureRow` |
| `task_category_measures.csv` | A task, a category and a sender, with the trials of the task and the trials in each bound of the main measure, as `count_task_category_measures` counts them |
| `raised_trials.csv` | A trial whose steps raised, with the type name of the exception |
| `summary.csv` | A count of the run, e.g. the trials whose trajectory could not be read by reason |
| `equations.csv` | An equation between steps of the table below, with its two sides and whether they are equal |
| `<step package>/row_uses.csv` | A catalog row or a declared row of the door of the step that answered, with its lookups, trials and tasks |
| `<step package>/unknown_inputs.csv` | A key that the door of the step found no row for, with its lookups, trials and tasks, most trials first |
| `<step package>/judgment_rule_uses.csv` | A judgment rule of the step or a rule of another step that it counts, with its uses, trials and tasks, and 0 for a rule of the step that was never used |
| `network_request/no_network_request_reasons.csv` | A reason why a program run, code call or URL in code gave no request, with its count, trials and tasks |
| `network_request_result/unused_output_lines.csv` | A reason and an output line kind of lines that a pattern fits and that gave no evidence, with its lines, trials and tasks |
| `network_request_results/<trial id>.pickle` | The `Trial`, the network request results and the counts of the steps before `export_rows` of one trial |

A row key is written as a JSON array of its key column values. In the row files, None is a blank cell, an enum is its value and a bool is `true` or `false`.

| Equation | Left | Right |
|---|---|---|
| `trial_rows_equal_trials_that_did_not_raise` | `TrialRow`s | Trials chosen, less those that raised |
| `trial_rows_have_distinct_trial_ids` | Distinct trial ids of the `TrialRow`s | `TrialRow`s |
| `request_rows_equal_network_request_results` | `NetworkRequestRow`s | `NetworkRequestResult`s, counted before `export_rows` |
| `trials_with_request_rows_equal_trials_with_results` | Trials with a `NetworkRequestRow` | Trials with a `NetworkRequestResult` |
| `readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results` | Trials whose trajectory could be read | Trials with a `NetworkRequestRow`, plus trials whose trajectory could be read and that have no result |
| `request_rows_of_unreadable_trials` | `NetworkRequestRow`s of trials whose trajectory could not be read | 0 |
| `request_rows_sharing_their_first_five_columns` | `NetworkRequestRow`s whose trial, trajectory, step, call and request index another row has too | 0 |
| `received_rows_equal_results_without_stop_reason` | Request rows whose `result_view` is `received` | Results without a stop reason |
| `not_received_rows_equal_failed_results` | Rows whose `result_view` is `not_received` | Results that stopped as `FAILED` |
| `unknown_result_rows_equal_not_visible_results` | Rows whose `result_view` is `unknown` | Results that stopped as `NOT_VISIBLE` |
| `not_needed_rows_equal_not_needed_results` | Rows whose `result_view` is `not_needed` | Results that stopped as `NOT_NEEDED` |
| `measure_rows_of_read_trials_equal_their_categories_and_senders` | `TrialCategoryMeasureRow`s of trials whose trajectory could be read | Distinct trial, category and sender of the `NetworkRequestRow`s |
| `measure_rows_of_unreadable_trials_equal_each_category_and_known_sender` | `TrialCategoryMeasureRow`s of trials whose trajectory could not be read | Those trials times the categories times the three senders other than `unknown` |

The script ends with exit code 1 when a trial raised or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/run_pipeline.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR] [--resume | --export-only]`.
"""

import argparse
import dataclasses
import functools
import inspect
import json
import os
import pickle
import sys
import time
from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType

from tb_internet_use.expanded_tool_call import (
    judgment_rules as expanded_tool_call_judgment_rules,
)
from tb_internet_use.export import export_rows
from tb_internet_use.export import judgment_rules as export_judgment_rules
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.network_request import (
    judgment_rules as network_request_judgment_rules,
)
from tb_internet_use.network_request_result import (
    judgment_rules as network_request_result_judgment_rules,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResult,
    NetworkRequestResultStopReason,
)
from tb_internet_use.pipeline import KnowledgeDoors, run_steps_of_trial
from tb_internet_use.tool_call import judgment_rules as tool_call_judgment_rules
from tb_internet_use.trial.model import Trial

# `python -I` leaves the folder of this script off `sys.path`, so the script puts it there to import the module beside it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial_folders_and_csv_files import (
    PROCESS_COUNT,
    add_trial_choice_arguments,
    chosen_trial_dirs_from,
    write_csv,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "pipeline"
# The folder under the output folder that holds the saved output of the steps before `export_rows`, one file per trial.
NETWORK_REQUEST_RESULTS_DIR_NAME = "network_request_results"
# Progress goes to stderr after this many trials, often enough to follow a run of 15,990 trials and seldom enough to stay short.
_PROGRESS_INTERVAL = 200
# The step packages that have a door and judgment rules, in pipeline order, with the module of their rules.
JUDGMENT_RULES_BY_STEP_PACKAGE: dict[str, ModuleType] = {
    "tool_call": tool_call_judgment_rules,
    "expanded_tool_call": expanded_tool_call_judgment_rules,
    "network_request": network_request_judgment_rules,
    "network_request_result": network_request_result_judgment_rules,
    "export": export_judgment_rules,
}
# Every equation of the module docstring, in its order, which is also the order of the output.
EQUATIONS = (
    "trial_rows_equal_trials_that_did_not_raise",
    "trial_rows_have_distinct_trial_ids",
    "request_rows_equal_network_request_results",
    "trials_with_request_rows_equal_trials_with_results",
    "readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results",
    "request_rows_of_unreadable_trials",
    "request_rows_sharing_their_first_five_columns",
    "received_rows_equal_results_without_stop_reason",
    "not_received_rows_equal_failed_results",
    "unknown_result_rows_equal_not_visible_results",
    "not_needed_rows_equal_not_needed_results",
    "measure_rows_of_read_trials_equal_their_categories_and_senders",
    "measure_rows_of_unreadable_trials_equal_each_category_and_known_sender",
)
# The result view of a request row for each stop reason of its result, None for none, as the equations compare them.
_RESULT_VIEW_EQUATIONS = (
    (
        "received_rows_equal_results_without_stop_reason",
        NetworkRequestResultView.RECEIVED,
        None,
    ),
    (
        "not_received_rows_equal_failed_results",
        NetworkRequestResultView.NOT_RECEIVED,
        NetworkRequestResultStopReason.FAILED,
    ),
    (
        "unknown_result_rows_equal_not_visible_results",
        NetworkRequestResultView.UNKNOWN,
        NetworkRequestResultStopReason.NOT_VISIBLE,
    ),
    (
        "not_needed_rows_equal_not_needed_results",
        NetworkRequestResultView.NOT_NEEDED,
        NetworkRequestResultStopReason.NOT_NEEDED,
    ),
)
TASK_CATEGORY_MEASURE_COLUMNS = (
    "benchmark_version",
    "task_name",
    "category",
    "sender",
    "trial_count",
    "request_lower_trial_count",
    "request_upper_trial_count",
    "received_lower_trial_count",
    "received_upper_trial_count",
    "request_row_count",
)

# A task, named by its benchmark version and its task name, since one task name occurs in two benchmark versions.
type TaskKey = tuple[str, str]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_trial_choice_arguments(parser)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument(
        "--resume",
        action="store_true",
        help="reuse the saved output of the steps before export_rows of each trial that has one, and run the others from their trial folder",
    )
    reuse.add_argument(
        "--export-only",
        action="store_true",
        help="run only export_rows, on the saved output of every trial, and count a trial without one as raised",
    )
    arguments = parser.parse_args()

    trial_dirs = list(dict.fromkeys(chosen_trial_dirs_from(arguments)))
    results_dir = arguments.out_dir / NETWORK_REQUEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True, exist_ok=True)
    run_trial_in_worker = functools.partial(
        run_trial,
        results_dir=results_dir,
        reuses_saved_results=arguments.resume or arguments.export_only,
        needs_saved_results=arguments.export_only,
    )
    start_time = time.monotonic()
    trial_runs: list[TrialRun] = []
    with ProcessPoolExecutor(PROCESS_COUNT) as pool:
        for trial_run in pool.map(run_trial_in_worker, trial_dirs, chunksize=4):
            trial_runs.append(trial_run)
            if len(trial_runs) % _PROGRESS_INTERVAL == 0 or len(trial_runs) == len(
                trial_dirs
            ):
                print(
                    _progress_text(trial_runs, len(trial_dirs), start_time),
                    file=sys.stderr,
                )
    pipeline_run_total = PipelineRunTotal.of_trial_runs(trial_runs, len(trial_dirs))
    write_pipeline_run_files(pipeline_run_total, arguments.out_dir)
    for equation, left, right in pipeline_run_total.equation_rows():
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"raised trials: {len(pipeline_run_total.raised_trials)}")
    print(f"written under {arguments.out_dir}")
    if pipeline_run_total.has_raised_trial_or_differing_equation():
        sys.exit(1)


def run_trial(
    trial_dir: Path,
    *,
    results_dir: Path,
    reuses_saved_results: bool,
    needs_saved_results: bool,
) -> TrialRun:
    """Run the steps on one trial folder, or `export_rows` alone on its saved results, and return what it gave, with an exception named instead of raised.

    The results of a trial that ran from its folder are saved under `results_dir` before `export_rows` runs, so that a stop in `export_rows` keeps them.
    """
    trial_id = trial_dir.name
    saved_results_path = results_dir / f"{trial_id}.pickle"
    try:
        if reuses_saved_results and saved_results_path.exists():
            return _run_trial_from_saved_results(saved_results_path)
        if needs_saved_results:
            raise FileNotFoundError(saved_results_path.name)
        return _run_trial_from_folder(trial_dir, saved_results_path)
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialRun(trial_id, exception_type_name=type(error).__name__)


def _run_trial_from_folder(trial_dir: Path, saved_results_path: Path) -> TrialRun:
    """Run every step on one trial folder with the doors of this worker process, and save its `Trial`, its results and the counts of the steps before `export_rows`."""
    knowledge_doors = knowledge_doors_of_worker()
    # The doors serve every trial of the worker process, so their uses start empty for each trial.
    for door_field in dataclasses.fields(knowledge_doors):
        getattr(knowledge_doors, door_field.name).uses = KnowledgeUses()
    trial_run = TrialRun(trial_dir.name)
    counts = trial_run.earlier_step_counts
    (
        trial,
        network_request_results,
        trial_row,
        network_request_rows,
        trial_category_measure_rows,
    ) = run_steps_of_trial(
        trial_dir,
        knowledge_doors=knowledge_doors,
        tool_call_judgment_rule_use_counts=counts.judgment_rule_use_counts_by_step_package[
            "tool_call"
        ],
        expanded_tool_call_judgment_rule_use_counts=counts.judgment_rule_use_counts_by_step_package[
            "expanded_tool_call"
        ],
        network_request_judgment_rule_use_counts=counts.judgment_rule_use_counts_by_step_package[
            "network_request"
        ],
        no_network_request_counts=counts.no_network_request_counts,
        network_request_result_judgment_rule_use_counts=counts.judgment_rule_use_counts_by_step_package[
            "network_request_result"
        ],
        unused_output_line_counts=counts.unused_output_line_counts,
        program_counts_of_unowned_output_lines=Counter(),
        export_judgment_rule_use_counts=trial_run.export_judgment_rule_use_counts,
    )
    for step_package in counts.knowledge_uses_by_step_package:
        counts.knowledge_uses_by_step_package[step_package] = getattr(
            knowledge_doors, f"{step_package}_knowledge"
        ).uses
    _save_results(saved_results_path, trial, network_request_results, counts)
    trial_run.set_output(
        trial,
        network_request_results,
        trial_row,
        network_request_rows,
        trial_category_measure_rows,
    )
    trial_run.export_knowledge_uses = knowledge_doors.export_knowledge.uses
    return trial_run


def _run_trial_from_saved_results(saved_results_path: Path) -> TrialRun:
    """Run `export_rows` on the saved `Trial` and results of one trial with the export door of this worker process, keeping the saved counts of the steps before it."""
    trial, network_request_results, earlier_step_counts = load_saved_results(
        saved_results_path
    )
    export_knowledge = knowledge_doors_of_worker().export_knowledge
    export_knowledge.uses = KnowledgeUses()
    trial_run = TrialRun(trial.trial_id, earlier_step_counts=earlier_step_counts)
    trial_row, network_request_rows, trial_category_measure_rows = export_rows(
        trial,
        network_request_results,
        knowledge=export_knowledge,
        judgment_rule_use_counts=trial_run.export_judgment_rule_use_counts,
    )
    trial_run.set_output(
        trial,
        network_request_results,
        trial_row,
        network_request_rows,
        trial_category_measure_rows,
    )
    trial_run.export_knowledge_uses = export_knowledge.uses
    return trial_run


def _save_results(
    saved_results_path: Path,
    trial: Trial,
    network_request_results: tuple[NetworkRequestResult, ...],
    earlier_step_counts: EarlierStepCounts,
) -> None:
    """Write the `Trial`, the results and the counts of the steps before `export_rows` of one trial to a file beside the final one and then rename it, so that a run stopped while writing leaves no half file.

    The file holds a tuple of types of the package and of the standard library only, so that another script can read it, e.g. one that audits the rows.
    """
    partial_path = saved_results_path.with_suffix(".partial")
    partial_path.write_bytes(
        pickle.dumps(
            (
                trial,
                network_request_results,
                earlier_step_counts.knowledge_uses_by_step_package,
                earlier_step_counts.judgment_rule_use_counts_by_step_package,
                earlier_step_counts.no_network_request_counts,
                earlier_step_counts.unused_output_line_counts,
            )
        )
    )
    os.replace(partial_path, saved_results_path)


def load_saved_results(
    saved_results_path: Path,
) -> tuple[Trial, tuple[NetworkRequestResult, ...], EarlierStepCounts]:
    """Read the `Trial`, the network request results and the counts of the steps before `export_rows` that `run_trial` saved for one trial.

    The file is one that this script wrote, never a file of the raw data.
    """
    trial, network_request_results, *counts = pickle.loads(
        saved_results_path.read_bytes()
    )
    return trial, network_request_results, EarlierStepCounts(*counts)


@functools.cache
def knowledge_doors_of_worker() -> KnowledgeDoors:
    """Give the doors of this worker process, made at its first trial, since reading the catalogs again for each trial is slow."""
    return KnowledgeDoors()


@dataclass(slots=True)
class EarlierStepCounts:
    """Record of what the steps before `export_rows` counted for one trial, saved with its results so that a run with `--resume` or `--export-only` still lists those counts."""

    # The lookups of the door of each step, by step package.
    knowledge_uses_by_step_package: dict[str, KnowledgeUses] = field(
        default_factory=lambda: {
            step_package: KnowledgeUses()
            for step_package in list(JUDGMENT_RULES_BY_STEP_PACKAGE)[:-1]
        }
    )
    # The uses of each judgment rule by its function name, by step package.
    judgment_rule_use_counts_by_step_package: dict[str, Counter[str]] = field(
        default_factory=lambda: {
            step_package: Counter()
            for step_package in list(JUDGMENT_RULES_BY_STEP_PACKAGE)[:-1]
        }
    )
    # What `extract_network_requests` counts by reason, by the value of the reason.
    no_network_request_counts: Counter = field(default_factory=Counter)
    # What `decide_network_request_results` counts by reason and output line kind.
    unused_output_line_counts: Counter = field(default_factory=Counter)


@dataclass(slots=True)
class TrialRun:
    """Result of running the steps on one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # The type name of the exception the trial raised, or None when it ran.
    exception_type_name: str | None = None
    trial: Trial | None = None
    # The results counted before `export_rows`, by stop reason, None for none.
    network_request_result_counts: Counter[NetworkRequestResultStopReason | None] = (
        field(default_factory=Counter)
    )
    trial_row: TrialRow | None = None
    network_request_rows: tuple[NetworkRequestRow, ...] = ()
    trial_category_measure_rows: tuple[TrialCategoryMeasureRow, ...] = ()
    earlier_step_counts: EarlierStepCounts = field(default_factory=EarlierStepCounts)
    export_knowledge_uses: KnowledgeUses = field(default_factory=KnowledgeUses)
    export_judgment_rule_use_counts: Counter[str] = field(default_factory=Counter)

    def set_output(
        self,
        trial: Trial,
        network_request_results: Sequence[NetworkRequestResult],
        trial_row: TrialRow,
        network_request_rows: tuple[NetworkRequestRow, ...],
        trial_category_measure_rows: tuple[TrialCategoryMeasureRow, ...],
    ) -> None:
        """Keep the trial, the count of its results by stop reason and its rows, and drop the results, which the main process does not need."""
        self.trial = trial
        self.network_request_result_counts = Counter(
            network_request_result.stop_reason
            for network_request_result in network_request_results
        )
        self.trial_row = trial_row
        self.network_request_rows = network_request_rows
        self.trial_category_measure_rows = trial_category_measure_rows

    @property
    def task_key(self) -> TaskKey | None:
        """Give the task of the trial, or None for a trial that raised before its `Trial` was made."""
        if self.trial is None:
            return None
        return (self.trial.benchmark_version, self.trial.task_name)


@dataclass(slots=True)
class KeyCountTotal[Key: Hashable]:
    """Sum of the counts of keys over trials, with the trials and the tasks that have each key, built by `PipelineRunTotal` for each list it writes."""

    counts: Counter[Key] = field(default_factory=Counter)
    # The number of trials that counted the key at least once.
    trial_counts: Counter[Key] = field(default_factory=Counter)
    task_keys: dict[Key, set[TaskKey]] = field(default_factory=dict)

    def add_trial(self, counts: Counter[Key], task_key: TaskKey) -> None:
        """Add the counts of one trial, counting the trial and its task once for each key it has."""
        self.counts.update(counts)
        for key, count in counts.items():
            if count:
                self.trial_counts[key] += 1
                self.task_keys.setdefault(key, set()).add(task_key)

    def rows(self, keys: Iterable[Key] = ()) -> list[tuple[Key, int, int, int]]:
        """List each key with its count, trials and tasks, the given keys too when no trial counted them, most trials first and then most counts."""
        all_keys = set(self.counts) | set(keys)
        return [
            (
                key,
                self.counts[key],
                self.trial_counts[key],
                len(self.task_keys.get(key, ())),
            )
            for key in sorted(
                all_keys,
                key=lambda key: (-self.trial_counts[key], -self.counts[key], str(key)),
            )
        ]


@dataclass(slots=True)
class PipelineRunTotal:
    """Sum of the `TrialRun` of all trials of a run in the order of their trial ids, built by `main` to write the files of the module docstring."""

    trial_count: int
    trials: list[Trial] = field(default_factory=list)
    raised_trials: list[tuple[str, str]] = field(default_factory=list)
    trial_rows: list[TrialRow] = field(default_factory=list)
    network_request_rows: list[NetworkRequestRow] = field(default_factory=list)
    trial_category_measure_rows: list[TrialCategoryMeasureRow] = field(
        default_factory=list
    )
    network_request_result_counts: Counter[NetworkRequestResultStopReason | None] = (
        field(default_factory=Counter)
    )
    trial_ids_with_results: set[str] = field(default_factory=set)
    row_use_totals: dict[str, KeyCountTotal] = field(default_factory=dict)
    unknown_input_totals: dict[str, KeyCountTotal] = field(default_factory=dict)
    judgment_rule_use_totals: dict[str, KeyCountTotal[str]] = field(
        default_factory=dict
    )
    no_network_request_total: KeyCountTotal = field(default_factory=KeyCountTotal)
    unused_output_line_total: KeyCountTotal = field(default_factory=KeyCountTotal)

    @classmethod
    def of_trial_runs(
        cls, trial_runs: Iterable[TrialRun], trial_count: int
    ) -> PipelineRunTotal:
        """Sum the runs of the trials in the order of their trial ids, whatever order they finished in."""
        total = cls(trial_count)
        for step_package in JUDGMENT_RULES_BY_STEP_PACKAGE:
            total.row_use_totals[step_package] = KeyCountTotal()
            total.unknown_input_totals[step_package] = KeyCountTotal()
            total.judgment_rule_use_totals[step_package] = KeyCountTotal()
        for trial_run in sorted(trial_runs, key=lambda trial_run: trial_run.trial_id):
            total.add_trial_run(trial_run)
        return total

    def add_trial_run(self, trial_run: TrialRun) -> None:
        """Add the rows and counts of one trial, or name it as raised."""
        task_key = trial_run.task_key
        if (
            trial_run.exception_type_name is not None
            or trial_run.trial is None
            or trial_run.trial_row is None
            or task_key is None
        ):
            self.raised_trials.append(
                (trial_run.trial_id, trial_run.exception_type_name or "")
            )
            return
        self.trials.append(trial_run.trial)
        self.trial_rows.append(trial_run.trial_row)
        self.network_request_rows.extend(trial_run.network_request_rows)
        self.trial_category_measure_rows.extend(trial_run.trial_category_measure_rows)
        self.network_request_result_counts.update(
            trial_run.network_request_result_counts
        )
        if trial_run.network_request_result_counts.total():
            self.trial_ids_with_results.add(trial_run.trial_id)
        earlier_step_counts = trial_run.earlier_step_counts
        knowledge_uses_by_step_package = {
            **earlier_step_counts.knowledge_uses_by_step_package,
            "export": trial_run.export_knowledge_uses,
        }
        judgment_rule_use_counts_by_step_package = {
            **earlier_step_counts.judgment_rule_use_counts_by_step_package,
            "export": trial_run.export_judgment_rule_use_counts,
        }
        for step_package, knowledge_uses in knowledge_uses_by_step_package.items():
            self.row_use_totals[step_package].add_trial(
                knowledge_uses.row_use_counts, task_key
            )
            self.unknown_input_totals[step_package].add_trial(
                knowledge_uses.unknown_input_counts, task_key
            )
        for (
            step_package,
            judgment_rule_use_counts,
        ) in judgment_rule_use_counts_by_step_package.items():
            self.judgment_rule_use_totals[step_package].add_trial(
                judgment_rule_use_counts, task_key
            )
        self.no_network_request_total.add_trial(
            earlier_step_counts.no_network_request_counts, task_key
        )
        self.unused_output_line_total.add_trial(
            earlier_step_counts.unused_output_line_counts, task_key
        )

    def equation_rows(self) -> list[tuple[str, int, int]]:
        """Give each equation of the module docstring with its two sides, in the order of `EQUATIONS`."""
        readable_trial_ids = {
            trial.trial_id
            for trial in self.trials
            if trial.unreadable_trajectory is None
        }
        unreadable_trial_count = len(self.trials) - len(readable_trial_ids)
        trial_ids_with_request_rows = {
            network_request_row.trial_id
            for network_request_row in self.network_request_rows
        }
        first_five_columns = Counter(
            (
                row.trial_id,
                row.trajectory_id,
                row.step_id,
                row.call_index,
                row.request_index,
            )
            for row in self.network_request_rows
        )
        result_view_counts = Counter(
            row.result_view for row in self.network_request_rows
        )
        sides_by_equation: dict[str, tuple[int, int]] = {
            "trial_rows_equal_trials_that_did_not_raise": (
                len(self.trial_rows),
                self.trial_count - len(self.raised_trials),
            ),
            "trial_rows_have_distinct_trial_ids": (
                len({trial_row.trial_id for trial_row in self.trial_rows}),
                len(self.trial_rows),
            ),
            "request_rows_equal_network_request_results": (
                len(self.network_request_rows),
                self.network_request_result_counts.total(),
            ),
            "trials_with_request_rows_equal_trials_with_results": (
                len(trial_ids_with_request_rows),
                len(self.trial_ids_with_results),
            ),
            "readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results": (
                len(readable_trial_ids),
                len(trial_ids_with_request_rows)
                + len(readable_trial_ids - self.trial_ids_with_results),
            ),
            "request_rows_of_unreadable_trials": (
                sum(
                    row.trial_id not in readable_trial_ids
                    for row in self.network_request_rows
                ),
                0,
            ),
            "request_rows_sharing_their_first_five_columns": (
                sum(count for count in first_five_columns.values() if count > 1),
                0,
            ),
            "measure_rows_of_read_trials_equal_their_categories_and_senders": (
                sum(
                    row.trial_id in readable_trial_ids
                    for row in self.trial_category_measure_rows
                ),
                len(
                    {
                        (row.trial_id, row.category, row.sender)
                        for row in self.network_request_rows
                    }
                ),
            ),
            "measure_rows_of_unreadable_trials_equal_each_category_and_known_sender": (
                sum(
                    row.trial_id not in readable_trial_ids
                    for row in self.trial_category_measure_rows
                ),
                unreadable_trial_count
                * len(NetworkRequestCategory)
                * (len(NetworkRequestSender) - 1),
            ),
        }
        for equation, result_view, stop_reason in _RESULT_VIEW_EQUATIONS:
            sides_by_equation[equation] = (
                result_view_counts[result_view],
                self.network_request_result_counts[stop_reason],
            )
        return [(equation, *sides_by_equation[equation]) for equation in EQUATIONS]

    def has_raised_trial_or_differing_equation(self) -> bool:
        """Tell whether a trial raised or an equation differs, which makes the script exit with 1."""
        return bool(self.raised_trials) or any(
            left != right for _, left, right in self.equation_rows()
        )

    def summary_rows(self) -> list[tuple[str, int]]:
        """List the counts of the run that the equations rest on, each by name."""
        unreadable_reason_counts = Counter(
            trial.unreadable_trajectory.reason.value
            for trial in self.trials
            if trial.unreadable_trajectory is not None
        )
        return [
            ("trials_chosen", self.trial_count),
            ("trials_raised", len(self.raised_trials)),
            ("trial_rows", len(self.trial_rows)),
            *(
                (f"trials_unreadable_{reason}", count)
                for reason, count in sorted(unreadable_reason_counts.items())
            ),
            ("network_request_results", self.network_request_result_counts.total()),
            ("network_request_rows", len(self.network_request_rows)),
            ("trial_category_measure_rows", len(self.trial_category_measure_rows)),
        ]


def write_pipeline_run_files(total: PipelineRunTotal, out_dir: Path) -> None:
    """Write the files of the module docstring from the sum of the trials, all but the saved results, which `run_trial` writes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for file_name, row_type, rows in (
        ("network_request_rows.csv", NetworkRequestRow, total.network_request_rows),
        ("trial_rows.csv", TrialRow, total.trial_rows),
        (
            "trial_category_measure_rows.csv",
            TrialCategoryMeasureRow,
            total.trial_category_measure_rows,
        ),
    ):
        write_csv(
            out_dir / file_name,
            [row_field.name for row_field in dataclasses.fields(row_type)],
            (csv_cells_of(row) for row in rows),
        )
    write_csv(
        out_dir / "task_category_measures.csv",
        TASK_CATEGORY_MEASURE_COLUMNS,
        count_task_category_measures(
            total.trial_rows,
            total.network_request_rows,
            total.trial_category_measure_rows,
        ),
    )
    write_csv(
        out_dir / "raised_trials.csv",
        ("trial_id", "exception_type"),
        total.raised_trials,
    )
    write_csv(out_dir / "summary.csv", ("count_name", "count"), total.summary_rows())
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in total.equation_rows()
        ),
    )
    for step_package, judgment_rules in JUDGMENT_RULES_BY_STEP_PACKAGE.items():
        step_dir = out_dir / step_package
        step_dir.mkdir(exist_ok=True)
        for file_name, key_column_name, key_count_total in (
            ("row_uses.csv", "row_key", total.row_use_totals[step_package]),
            (
                "unknown_inputs.csv",
                "key_asked",
                total.unknown_input_totals[step_package],
            ),
        ):
            write_csv(
                step_dir / file_name,
                (
                    "source",
                    key_column_name,
                    "lookup_count",
                    "trial_count",
                    "task_count",
                ),
                (
                    (source, json.dumps(row_key), count, trial_count, task_count)
                    for (
                        source,
                        row_key,
                    ), count, trial_count, task_count in key_count_total.rows()
                ),
            )
        write_csv(
            step_dir / "judgment_rule_uses.csv",
            ("judgment_rule", "use_count", "trial_count", "task_count"),
            total.judgment_rule_use_totals[step_package].rows(
                judgment_rule_names_of(judgment_rules)
            ),
        )
    write_csv(
        out_dir / "network_request" / "no_network_request_reasons.csv",
        ("reason", "count", "trial_count", "task_count"),
        (
            (reason.value, count, trial_count, task_count)
            for reason, count, trial_count, task_count in total.no_network_request_total.rows()
        ),
    )
    write_csv(
        out_dir / "network_request_result" / "unused_output_lines.csv",
        ("reason", "output_line_kind", "line_count", "trial_count", "task_count"),
        (
            (reason.value, output_line_kind.value, count, trial_count, task_count)
            for (
                reason,
                output_line_kind,
            ), count, trial_count, task_count in total.unused_output_line_total.rows()
        ),
    )


def count_task_category_measures(
    trial_rows: Sequence[TrialRow],
    network_request_rows: Sequence[NetworkRequestRow],
    trial_category_measure_rows: Sequence[TrialCategoryMeasureRow],
) -> list[tuple[str, str, str, str, int, int, int, int, int, int]]:
    """Count for each task, category and sender the trials of the task and those in each bound of the main measure, with the request rows, in the columns of `TASK_CATEGORY_MEASURE_COLUMNS`.

    It only counts the values of the rows. A lower bound counts the `TrialCategoryMeasureRow`s with `LOWER_AND_UPPER`, and an upper bound adds those with `UPPER_ONLY`.
    `request_row_count` counts the `NetworkRequestRow`s of the group whatever their bounds. A task without any `TrialCategoryMeasureRow` has no line.
    """
    task_key_by_trial_id = {
        trial_row.trial_id: (trial_row.benchmark_version, trial_row.task_name)
        for trial_row in trial_rows
    }
    trial_counts = Counter(task_key_by_trial_id.values())
    request_row_counts = Counter(
        (task_key_by_trial_id[row.trial_id], row.category, row.sender)
        for row in network_request_rows
    )
    bound_counts: dict[
        tuple[TaskKey, NetworkRequestCategory, NetworkRequestSender], Counter[str]
    ] = {}
    for row in trial_category_measure_rows:
        counts = bound_counts.setdefault(
            (task_key_by_trial_id[row.trial_id], row.category, row.sender), Counter()
        )
        for bound_name, measure_bound in (
            ("request", row.request_measure_bound),
            ("received", row.received_measure_bound),
        ):
            if measure_bound == MeasureBound.LOWER_AND_UPPER:
                counts[f"{bound_name}_lower"] += 1
            if measure_bound != MeasureBound.NEITHER:
                counts[f"{bound_name}_upper"] += 1
    return [
        (
            task_key[0],
            task_key[1],
            category.value,
            sender.value,
            trial_counts[task_key],
            counts["request_lower"],
            counts["request_upper"],
            counts["received_lower"],
            counts["received_upper"],
            request_row_counts[task_key, category, sender],
        )
        for (task_key, category, sender), counts in sorted(bound_counts.items())
    ]


def csv_cells_of(
    row: NetworkRequestRow | TrialRow | TrialCategoryMeasureRow,
) -> list[object]:
    """Give the cells of a row in the order of its fields, with None as a blank, an enum as its value and a bool as `true` or `false`."""
    return [
        _csv_cell_of(getattr(row, row_field.name))
        for row_field in dataclasses.fields(row)
    ]


def _csv_cell_of(value: object) -> object:
    """Give the cell of one value, as `csv_cells_of` writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Enum):
        return value.value
    return value


def judgment_rule_names_of(judgment_rules: ModuleType) -> list[str]:
    """List the public functions defined in a module of judgment rules, i.e. its rules."""
    return [
        name
        for name, function in inspect.getmembers(judgment_rules, inspect.isfunction)
        if function.__module__ == judgment_rules.__name__ and not name.startswith("_")
    ]


def _progress_text(
    trial_runs: Sequence[TrialRun], trial_count: int, start_time: float
) -> str:
    """Give one line of progress, i.e. the trials done of all, those that raised and the seconds since the start."""
    raised_count = sum(
        trial_run.exception_type_name is not None for trial_run in trial_runs
    )
    return f"trials done {len(trial_runs)} of {trial_count}, raised {raised_count}, {time.monotonic() - start_time:.0f} s"


if __name__ == "__main__":
    main()
