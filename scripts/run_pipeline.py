"""Run every step of the pipeline on raw trials and write the rows of each trial, the unknown inputs and use counts of each step, the trials that raised and the equations between steps.

Each trial runs as its own task in one of at most 4 worker processes. A trial that raises, runs longer than `--trial-time-limit-seconds` (600 unless given) or kills its worker counts as raised, and the other trials still give their rows.
The `Trial` and the network request results of each trial are saved as they come, so that a long run that stops can go on with `--resume`, and `--export-only` runs `export_rows` again on the saved results without reading a trajectory, e.g. after a rule of `export/judgment_rules.py` changed.
`--export-only` counts a trial as raised when the code digest of its saved results differs from that of the code that runs, unless `--ignore-code-digest` is given, e.g. after a commit that only renamed things. `summary.csv` then counts the trials exported from saved results of other code.
Each equation of `EQUATIONS` has its definition above its name. Progress goes to stderr, and no text of a trajectory is printed.

It writes `network_request_rows.csv`, `trial_rows.csv`, `trial_category_measure_rows.csv`, `task_category_measures.csv`, `raised_trials.csv`, `summary.csv`, `equations.csv`, `<step package>/row_uses.csv`, `<step package>/unknown_inputs.csv`, `<step package>/judgment_rule_uses.csv`, `network_request/no_network_request_reasons.csv`, `network_request_result/unused_output_lines.csv`, `network_request_result/unowned_output_line_programs.csv` and the saved results `network_request_results/<trial id>.pickle` under the output folder, `out/pipeline/` unless `--out-dir` names another, which `.gitignore` keeps out of the repo, since the rows hold targets and host names from trajectories.
The rows of each file are described above the statement that writes it in `write_pipeline_run_files`, and the saved results in `run_trial`.
The words of a key of `unknown_inputs.csv` and the program names of `unowned_output_line_programs.csv` come from trajectories, and these lists are meant to be read and passed on as the knowledge to fill, so `cut_key_word` cuts an option word at its first `=` and any word after 64 characters. A bare word that is a credential, e.g. a token given as an argument, is cut only after 64 characters.

The script ends with exit code 1 when a trial raised or an equation differs.
Run it as `nice -n 10 uv run python -I scripts/run_pipeline.py <raw_trials_dir> [--limit N | --trial-ids FILE] [--out-dir DIR] [--resume | --export-only [--ignore-code-digest]] [--trial-time-limit-seconds N]`.
"""

import argparse
import csv
import dataclasses
import functools
import hashlib
import inspect
import json
import os
import pickle
import sys
import time
from collections import Counter, deque
from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType

import tb_internet_use
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
from tb_internet_use.pipeline import PipelineKnowledge, run_steps_of_trial
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
# The folder of the package, whose files other than those of the export step make the code digest of a saved file.
PACKAGE_DIR = Path(tb_internet_use.__file__).resolve().parent
# The paths under `PACKAGE_DIR` of the export step, its catalogs and `ExportKnowledge`, which `export_rows` alone reads.
_EXPORT_STEP_PATHS = (
    Path("export"),
    Path("knowledge/catalogs/export"),
    Path("knowledge/export_knowledge.py"),
)
# The folder under the output folder that holds the saved output of the steps before `export_rows`, one file per trial.
NETWORK_REQUEST_RESULTS_DIR_NAME = "network_request_results"
# The time a trial may run unless `--trial-time-limit-seconds` gives another, far above the time of a trial of the sample, so that only a trial that hangs reaches it.
DEFAULT_TRIAL_TIME_LIMIT_SECONDS = 600
# The reasons of a trial that raised no exception of its own and still counts as raised.
WORKER_PROCESS_DIED = "worker_process_died"
SAVED_RESULTS_OF_OTHER_CODE = "saved_results_of_other_code"
# The characters of a key word that `cut_key_word` keeps at most.
KEY_WORD_LENGTH_LIMIT = 64
# Progress goes to stderr after this many trials, often enough to follow a run of 21,450 trials and seldom enough to stay short.
_PROGRESS_INTERVAL = 200
# The step packages that have a knowledge class and judgment rules, in pipeline order, with the module of their rules.
JUDGMENT_RULES_BY_STEP_PACKAGE: dict[str, ModuleType] = {
    "tool_call": tool_call_judgment_rules,
    "expanded_tool_call": expanded_tool_call_judgment_rules,
    "network_request": network_request_judgment_rules,
    "network_request_result": network_request_result_judgment_rules,
    "export": export_judgment_rules,
}
# Every equation in the order of the output.
# The comment above each name gives its left side beside its right side.
EQUATIONS = (
    # Lines of the written `trial_rows.csv` beside trial folders chosen, after a repeated trial id is dropped.
    # A run over the whole raw folder of Terminal-Bench 4.1, downloaded on 2026-11-19, must give 21,450.
    "trial_rows_equal_trial_folders_chosen",
    # Lines of the written `trial_rows.csv` beside chosen trial ids that the written `raised_trials.csv` does not name.
    "written_trial_rows_equal_chosen_trials_without_written_raised_trials",
    # Distinct trial ids of the `TrialRow`s beside `TrialRow`s.
    "trial_rows_have_distinct_trial_ids",
    # `NetworkRequest`s of `extract_network_requests` beside `NetworkRequestResult`s of `decide_network_request_results`, both counted before `export_rows`.
    "network_requests_equal_network_request_results",
    # `NetworkRequestRow`s beside `NetworkRequestResult`s, counted before `export_rows`.
    "request_rows_equal_network_request_results",
    # Trials with a `NetworkRequestRow` beside trials with a `NetworkRequestResult`.
    "trials_with_request_rows_equal_trials_with_results",
    # Trials whose trajectory could be read beside trials with a `NetworkRequestRow`, plus trials whose trajectory could be read and that have no result.
    "readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results",
    # `NetworkRequestRow`s of trials whose trajectory could not be read beside 0.
    "request_rows_of_unreadable_trials",
    # `NetworkRequestRow`s whose trial, trajectory, step, call and request index another row has too, beside 0.
    "request_rows_sharing_their_first_five_columns",
    # Request rows whose `result_view` is `received` beside results without a stop reason.
    "received_rows_equal_results_without_stop_reason",
    # Rows whose `result_view` is `not_received` beside results that stopped as `FAILED`.
    "not_received_rows_equal_failed_results",
    # Rows whose `result_view` is `unknown` beside results that stopped as `NOT_VISIBLE`.
    "unknown_result_rows_equal_not_visible_results",
    # Rows whose `result_view` is `not_needed` beside results that stopped as `NOT_NEEDED`.
    "not_needed_rows_equal_not_needed_results",
    # `TrialCategoryMeasureRow`s of trials whose trajectory could be read beside distinct trial, category and sender of the `NetworkRequestRow`s.
    "measure_rows_of_read_trials_equal_their_categories_and_senders",
    # `TrialCategoryMeasureRow`s of trials whose trajectory could not be read beside those trials times the categories times the three senders other than `unknown`.
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
        help="reuse the saved output of the steps before export_rows of each trial that has one made by the same code, and run the others from their trial folder",
    )
    reuse.add_argument(
        "--export-only",
        action="store_true",
        help="run only export_rows, on the saved output of every trial, and count a trial without one, or with one made by other code unless --ignore-code-digest is given, as raised",
    )
    parser.add_argument(
        "--ignore-code-digest",
        action="store_true",
        help="with --export-only, reuse the saved output of every trial whatever code made it",
    )
    parser.add_argument(
        "--trial-time-limit-seconds",
        type=float,
        default=DEFAULT_TRIAL_TIME_LIMIT_SECONDS,
        help="count a trial that runs longer as raised",
    )
    arguments = parser.parse_args()
    if arguments.ignore_code_digest and not arguments.export_only:
        parser.error("--ignore-code-digest needs --export-only")

    chosen_trial_dirs = chosen_trial_dirs_from(arguments)
    trial_dirs = list(dict.fromkeys(chosen_trial_dirs))
    results_dir = arguments.out_dir / NETWORK_REQUEST_RESULTS_DIR_NAME
    results_dir.mkdir(parents=True, exist_ok=True)
    run_trial_in_worker = functools.partial(
        run_trial,
        results_dir=results_dir,
        code_digest=earlier_step_code_digest_of(PACKAGE_DIR),
        reuses_saved_results=arguments.resume or arguments.export_only,
        needs_saved_results=arguments.export_only,
        ignores_code_digest=arguments.ignore_code_digest,
    )
    start_time = time.monotonic()
    trial_runs: list[TrialRun] = []
    for trial_run in run_trials(
        trial_dirs,
        run_trial_in_worker,
        trial_time_limit_seconds=arguments.trial_time_limit_seconds,
    ):
        trial_runs.append(trial_run)
        if len(trial_runs) % _PROGRESS_INTERVAL == 0 or len(trial_runs) == len(
            trial_dirs
        ):
            print(
                _progress_text(trial_runs, len(trial_dirs), start_time), file=sys.stderr
            )
    pipeline_run_total = PipelineRunTotal.of_trial_runs(
        trial_runs,
        [trial_dir.name for trial_dir in trial_dirs],
        repeated_trial_id_count=len(chosen_trial_dirs) - len(trial_dirs),
    )
    equation_rows = write_pipeline_run_files(pipeline_run_total, arguments.out_dir)
    for equation, left, right in equation_rows:
        print(f"{equation}: {left} = {right} {'holds' if left == right else 'differs'}")
    print(f"raised trials: {len(pipeline_run_total.raised_trials)}")
    if pipeline_run_total.trials_exported_from_saved_results_of_other_code:
        print(
            f"trials exported from saved results of other code: {pipeline_run_total.trials_exported_from_saved_results_of_other_code}",
            file=sys.stderr,
        )
    print(f"written under {arguments.out_dir}")
    if pipeline_run_total.raised_trials or any(
        left != right for _, left, right in equation_rows
    ):
        sys.exit(1)


def run_trials(
    trial_dirs: Sequence[Path],
    run_trial_in_worker: Callable[[Path], TrialRun],
    *,
    trial_time_limit_seconds: float,
) -> Iterator[TrialRun]:
    """Run each trial folder as its own task in worker processes and yield the run of each as it ends, in any order.

    A trial that runs longer than the time limit gives a `TrialRun` raised as timed out. The workers are then killed, since a process cannot stop a task that runs in another, and the trials that ran beside it run again in a new pool.
    When a worker process dies, e.g. by a crash in a C extension, every task of the pool fails. The trials that were running then run again one at a time in a new pool, so that only the one that kills its worker alone gives a `TrialRun` raised as `worker_process_died`.
    """
    waiting_trial_dirs = deque(trial_dirs)
    # The trials that were running when a worker died, each to run alone.
    suspected_trial_dirs: deque[Path] = deque()
    while waiting_trial_dirs or suspected_trial_dirs:
        if suspected_trial_dirs:
            broken_trial_dirs = yield from _run_trials_in_one_pool(
                suspected_trial_dirs,
                run_trial_in_worker,
                running_trial_limit=1,
                trial_time_limit_seconds=trial_time_limit_seconds,
            )
            for trial_dir in broken_trial_dirs:
                yield TrialRun(trial_dir.name, raise_reason=WORKER_PROCESS_DIED)
        else:
            suspected_trial_dirs.extend(
                (
                    yield from _run_trials_in_one_pool(
                        waiting_trial_dirs,
                        run_trial_in_worker,
                        running_trial_limit=PROCESS_COUNT,
                        trial_time_limit_seconds=trial_time_limit_seconds,
                    )
                )
            )


def _run_trials_in_one_pool(
    queued_trial_dirs: deque[Path],
    run_trial_in_worker: Callable[[Path], TrialRun],
    *,
    running_trial_limit: int,
    trial_time_limit_seconds: float,
) -> Iterator[TrialRun]:
    """Take trials from the front of the queue into one pool of worker processes, at most `running_trial_limit` at a time, and yield their runs until the queue is empty, a trial times out or the pool breaks.

    Only as many trials as there are workers are given to the pool at once, so that each starts when it is given and its time runs from then.
    A trial that times out is yielded as raised, and the trials that ran beside it go back to the front of the queue before the workers are killed.
    It returns the trials whose task failed because a worker died, and an empty list otherwise.
    """
    # The trial and the time by which it must end, of each task given to the pool.
    running: dict[Future[TrialRun], tuple[Path, float]] = {}
    with ProcessPoolExecutor(running_trial_limit) as pool:
        while queued_trial_dirs or running:
            while queued_trial_dirs and len(running) < running_trial_limit:
                trial_dir = queued_trial_dirs.popleft()
                running[pool.submit(run_trial_in_worker, trial_dir)] = (
                    trial_dir,
                    time.monotonic() + trial_time_limit_seconds,
                )
            first_end_time = min(end_time for _, end_time in running.values())
            ended, _ = wait(
                running,
                timeout=max(0.0, first_end_time - time.monotonic()),
                return_when=FIRST_COMPLETED,
            )
            broken_trial_dirs: list[Path] = []
            for future in ended:
                trial_dir, _ = running.pop(future)
                trial_run = _trial_run_of_ended_task(future, trial_dir)
                if trial_run is None:
                    broken_trial_dirs.append(trial_dir)
                else:
                    yield trial_run
            if broken_trial_dirs:
                # Every other task of a broken pool fails too, soon after.
                wait(running)
                for future, (trial_dir, _) in running.items():
                    trial_run = _trial_run_of_ended_task(future, trial_dir)
                    if trial_run is None:
                        broken_trial_dirs.append(trial_dir)
                    else:
                        yield trial_run
                return broken_trial_dirs
            now = time.monotonic()
            timed_out_futures = [
                future
                for future, (_, end_time) in running.items()
                if end_time <= now and not future.done()
            ]
            if timed_out_futures:
                for future in timed_out_futures:
                    trial_dir, _ = running.pop(future)
                    yield TrialRun(
                        trial_dir.name,
                        raise_reason=f"timed_out_after_{trial_time_limit_seconds:g}_seconds",
                    )
                queued_trial_dirs.extendleft(
                    reversed([trial_dir for trial_dir, _ in running.values()])
                )
                pool.kill_workers()
                return []
    return []


def _trial_run_of_ended_task(
    future: Future[TrialRun], trial_dir: Path
) -> TrialRun | None:
    """Give the run of a task that ended, a run raised with the type name of an exception that did not come from the steps, or None when the task failed because a worker died."""
    try:
        return future.result()
    except BrokenProcessPool:
        return None
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialRun(trial_dir.name, raise_reason=type(error).__name__)


def run_trial(
    trial_dir: Path,
    *,
    results_dir: Path,
    code_digest: str,
    reuses_saved_results: bool,
    needs_saved_results: bool,
    ignores_code_digest: bool,
) -> TrialRun:
    """Run the steps on one trial folder, or `export_rows` alone on its saved results, and return what it gave, with an exception named instead of raised.

    Saved results are reused only when their code digest is `code_digest`, or with `ignores_code_digest` whatever their digest, and the `TrialRun` then says whether the digest differed. The results of a trial that ran from its folder are saved under `results_dir` only after `run_steps_of_trial` returns, and that function runs `export_rows` too, so a trial whose `export_rows` raises has no saved results and `--export-only` counts it as raised.
    """
    trial_id = trial_dir.name
    # `network_request_results/<trial id>.pickle` holds the code digest, the `Trial`, the network request results and the counts of the steps before `export_rows` of one trial.
    # A run stopped while writing can leave a `<trial id>.partial` beside it, which no run reads.
    saved_results_path = results_dir / f"{trial_id}.pickle"
    try:
        if reuses_saved_results and saved_results_path.exists():
            saved_code_digest, trial, network_request_results, earlier_step_counts = (
                read_saved_results(saved_results_path)
            )
            if ignores_code_digest or saved_code_digest == code_digest:
                trial_run = _run_trial_from_saved_results(
                    trial, network_request_results, earlier_step_counts
                )
                trial_run.exported_from_saved_results_of_other_code = (
                    saved_code_digest != code_digest
                )
                return trial_run
            if needs_saved_results:
                return TrialRun(trial_id, raise_reason=SAVED_RESULTS_OF_OTHER_CODE)
        elif needs_saved_results:
            raise FileNotFoundError(saved_results_path.name)
        return _run_trial_from_folder(trial_dir, saved_results_path, code_digest)
    except Exception as error:  # noqa: BLE001, one trial must not stop the run
        return TrialRun(trial_id, raise_reason=type(error).__name__)


def _run_trial_from_folder(
    trial_dir: Path, saved_results_path: Path, code_digest: str
) -> TrialRun:
    """Run every step on one trial folder with the knowledge classes of this worker process, and save its `Trial`, its results and the counts of the steps before `export_rows` with the code digest."""
    pipeline_knowledge = pipeline_knowledge_of_worker_process()
    # The knowledge classes serve every trial of the worker process, so their uses start empty for each trial.
    for knowledge_field in dataclasses.fields(pipeline_knowledge):
        getattr(pipeline_knowledge, knowledge_field.name).uses = KnowledgeUses()
    trial_run = TrialRun(trial_dir.name)
    counts = trial_run.earlier_step_counts
    (
        trial,
        network_requests,
        network_request_results,
        trial_row,
        network_request_rows,
        trial_category_measure_rows,
    ) = run_steps_of_trial(
        trial_dir,
        pipeline_knowledge=pipeline_knowledge,
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
        program_counts_of_unowned_output_lines=counts.program_counts_of_unowned_output_lines,
        export_judgment_rule_use_counts=trial_run.export_judgment_rule_use_counts,
    )
    counts.network_request_count = len(network_requests)
    for step_package in counts.knowledge_uses_by_step_package:
        counts.knowledge_uses_by_step_package[step_package] = getattr(
            pipeline_knowledge, f"{step_package}_knowledge"
        ).uses
    _save_results(
        saved_results_path, code_digest, trial, network_request_results, counts
    )
    trial_run.set_output(
        trial,
        network_request_results,
        trial_row,
        network_request_rows,
        trial_category_measure_rows,
    )
    trial_run.export_knowledge_uses = pipeline_knowledge.export_knowledge.uses
    return trial_run


def _run_trial_from_saved_results(
    trial: Trial,
    network_request_results: tuple[NetworkRequestResult, ...],
    earlier_step_counts: EarlierStepCounts,
) -> TrialRun:
    """Run `export_rows` on the saved `Trial` and results of one trial with the `ExportKnowledge` of this worker process, keeping the saved counts of the steps before it."""
    export_knowledge = pipeline_knowledge_of_worker_process().export_knowledge
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
    code_digest: str,
    trial: Trial,
    network_request_results: tuple[NetworkRequestResult, ...],
    earlier_step_counts: EarlierStepCounts,
) -> None:
    """Write the code digest, the `Trial`, the results and the counts of the steps before `export_rows` of one trial to a `.partial` file beside the final one and then rename it, so that a run stopped while writing leaves no half `.pickle` file.

    The file holds a tuple of types of the package and of the standard library only, so that another script can read it, e.g. one that audits the rows.
    """
    partial_path = saved_results_path.with_suffix(".partial")
    partial_path.write_bytes(
        pickle.dumps(
            (
                code_digest,
                trial,
                network_request_results,
                *(
                    getattr(earlier_step_counts, counts_field.name)
                    for counts_field in dataclasses.fields(earlier_step_counts)
                ),
            )
        )
    )
    os.replace(partial_path, saved_results_path)


def read_saved_results(
    saved_results_path: Path,
) -> tuple[str, Trial, tuple[NetworkRequestResult, ...], EarlierStepCounts]:
    """Read the code digest, the `Trial`, the network request results and the counts of the steps before `export_rows` that `run_trial` saved for one trial.

    The file is one that this script wrote, never a file of the raw data. A file that an older version wrote, whose first item is no digest, gives a digest that matches no code.
    """
    code_digest, trial, network_request_results, *counts = pickle.loads(
        saved_results_path.read_bytes()
    )
    return code_digest, trial, network_request_results, EarlierStepCounts(*counts)


def earlier_step_code_digest_of(package_dir: Path) -> str:
    """Give the SHA-256 digest of the paths and bytes of every `.py` and `.csv` file under the package folder that the steps before `export_rows` read, i.e. all but those of the export step, its catalogs and `ExportKnowledge`."""
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*")):
        relative_path = path.relative_to(package_dir)
        if path.suffix not in (".py", ".csv") or any(
            relative_path.is_relative_to(export_step_path)
            for export_step_path in _EXPORT_STEP_PATHS
        ):
            continue
        digest.update(f"{relative_path.as_posix()}\n".encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@functools.cache
def pipeline_knowledge_of_worker_process() -> PipelineKnowledge:
    """Give the knowledge classes of this worker process, made at its first trial."""
    return PipelineKnowledge()


@dataclass(slots=True)
class EarlierStepCounts:
    """Record of what the steps before `export_rows` counted for one trial, saved with its results so that a run with `--resume` or `--export-only` still lists those counts."""

    # The lookups of the knowledge class of each step, by step package.
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
    # What `extract_network_requests` counts by reason.
    no_network_request_counts: Counter = field(default_factory=Counter)
    # What `decide_network_request_results` counts by reason and output line kind.
    unused_output_line_counts: Counter = field(default_factory=Counter)
    # What `decide_network_request_results` counts by reason, output line kind and the name of a program whose run reaches the place of a line that no request owns.
    program_counts_of_unowned_output_lines: Counter = field(default_factory=Counter)
    # The `NetworkRequest`s that `extract_network_requests` gave, counted apart from their results.
    network_request_count: int = 0


@dataclass(slots=True)
class TrialRun:
    """Result of running the steps on one trial, sent from a worker process to the main process that sums the trials."""

    trial_id: str
    # Why the trial counts as raised, i.e. the type name of the exception it raised, `WORKER_PROCESS_DIED`, a timeout or `SAVED_RESULTS_OF_OTHER_CODE`, or None when it ran.
    raise_reason: str | None = None
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
    # Whether the rows came from saved results whose code digest differs from that of the code that ran, as `--ignore-code-digest` allows.
    exported_from_saved_results_of_other_code: bool = False

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
        """Give the task of the trial, or None for a trial that counts as raised, since such a run holds no `Trial`."""
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
    """Sum of the `TrialRun` of all trials of a run in the order of their trial ids, built by `main` to write the files of the run."""

    chosen_trial_ids: list[str]
    # The number of entries of the chosen list that repeat an earlier trial id, since each trial runs once.
    repeated_trial_id_count: int = 0
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
    network_request_count: int = 0
    trial_ids_with_results: set[str] = field(default_factory=set)
    row_use_totals: dict[str, KeyCountTotal] = field(default_factory=dict)
    unknown_input_totals: dict[str, KeyCountTotal] = field(default_factory=dict)
    judgment_rule_use_totals: dict[str, KeyCountTotal[str]] = field(
        default_factory=dict
    )
    no_network_request_total: KeyCountTotal = field(default_factory=KeyCountTotal)
    unused_output_line_total: KeyCountTotal = field(default_factory=KeyCountTotal)
    unowned_output_line_program_total: KeyCountTotal = field(
        default_factory=KeyCountTotal
    )
    trials_exported_from_saved_results_of_other_code: int = 0

    @classmethod
    def of_trial_runs(
        cls,
        trial_runs: Iterable[TrialRun],
        chosen_trial_ids: Sequence[str],
        *,
        repeated_trial_id_count: int = 0,
    ) -> PipelineRunTotal:
        """Sum the runs of the trials in the order of their trial ids, whatever order they finished in."""
        total = cls(list(chosen_trial_ids), repeated_trial_id_count)
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
            trial_run.raise_reason is not None
            or trial_run.trial is None
            or trial_run.trial_row is None
            or task_key is None
        ):
            self.raised_trials.append(
                (trial_run.trial_id, trial_run.raise_reason or "")
            )
            return
        self.trials.append(trial_run.trial)
        self.trials_exported_from_saved_results_of_other_code += (
            trial_run.exported_from_saved_results_of_other_code
        )
        self.trial_rows.append(trial_run.trial_row)
        self.network_request_rows.extend(trial_run.network_request_rows)
        self.trial_category_measure_rows.extend(trial_run.trial_category_measure_rows)
        self.network_request_result_counts.update(
            trial_run.network_request_result_counts
        )
        if trial_run.network_request_result_counts.total():
            self.trial_ids_with_results.add(trial_run.trial_id)
        earlier_step_counts = trial_run.earlier_step_counts
        self.network_request_count += earlier_step_counts.network_request_count
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
        self.unowned_output_line_program_total.add_trial(
            earlier_step_counts.program_counts_of_unowned_output_lines, task_key
        )

    def equation_rows(
        self,
        written_trial_ids: Sequence[str],
        written_raised_trial_ids: Sequence[str],
    ) -> list[tuple[str, int, int]]:
        """Give each equation of `EQUATIONS` with its two sides, in its order.

        The trial ids of the written `trial_rows.csv` and `raised_trials.csv` are read back from the files, so that the first two equations compare what was written with what was chosen.
        """
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
            "trial_rows_equal_trial_folders_chosen": (
                len(written_trial_ids),
                len(self.chosen_trial_ids),
            ),
            "written_trial_rows_equal_chosen_trials_without_written_raised_trials": (
                len(written_trial_ids),
                len(set(self.chosen_trial_ids) - set(written_raised_trial_ids)),
            ),
            "trial_rows_have_distinct_trial_ids": (
                len({trial_row.trial_id for trial_row in self.trial_rows}),
                len(self.trial_rows),
            ),
            "network_requests_equal_network_request_results": (
                self.network_request_count,
                self.network_request_result_counts.total(),
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

    def summary_rows(self) -> list[tuple[str, int]]:
        """List the counts of the run that the equations rest on, each by name."""
        unreadable_reason_counts = Counter(
            trial.unreadable_trajectory.reason.value
            for trial in self.trials
            if trial.unreadable_trajectory is not None
        )
        return [
            ("trial_folders_chosen", len(self.chosen_trial_ids)),
            ("repeated_trial_ids_dropped", self.repeated_trial_id_count),
            ("trials_raised", len(self.raised_trials)),
            ("trial_rows", len(self.trial_rows)),
            (
                "trials_exported_from_saved_results_of_other_code",
                self.trials_exported_from_saved_results_of_other_code,
            ),
            *(
                (f"trials_unreadable_{reason}", count)
                for reason, count in sorted(unreadable_reason_counts.items())
            ),
            ("network_requests", self.network_request_count),
            ("network_request_results", self.network_request_result_counts.total()),
            ("network_request_rows", len(self.network_request_rows)),
            ("trial_category_measure_rows", len(self.trial_category_measure_rows)),
        ]


def write_pipeline_run_files(
    total: PipelineRunTotal, out_dir: Path
) -> list[tuple[str, int, int]]:
    """Write the files of the run from the sum of the trials, with the rows of each described above the statement that writes it, all but the saved results, which `run_trial` writes, and return the equation rows.

    The equations are counted after the rows and the raised trials are written, from the trial ids read back from those files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for file_name, row_type, rows in (
        # `network_request_rows.csv` has one row for each `NetworkRequestRow`, with the fields of the type as columns in their order.
        ("network_request_rows.csv", NetworkRequestRow, total.network_request_rows),
        # `trial_rows.csv` has one row for each `TrialRow`.
        ("trial_rows.csv", TrialRow, total.trial_rows),
        # `trial_category_measure_rows.csv` has one row for each `TrialCategoryMeasureRow`.
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
    # `task_category_measures.csv` has one row for each task, a category and a sender, with the trials of the task, the trials in each bound of the main measure and the request rows, as `count_task_category_measures` counts them.
    write_csv(
        out_dir / "task_category_measures.csv",
        TASK_CATEGORY_MEASURE_COLUMNS,
        count_task_category_measures(
            total.trial_rows,
            total.network_request_rows,
            total.trial_category_measure_rows,
        ),
    )
    # `raised_trials.csv` has one row for each trial that counts as raised, with the reason, i.e. the type name of the exception that ended its run, `worker_process_died`, `timed_out_after_<n>_seconds` or `saved_results_of_other_code`.
    write_csv(
        out_dir / "raised_trials.csv", ("trial_id", "reason"), total.raised_trials
    )
    equation_rows = total.equation_rows(
        _first_column_values_of(out_dir / "trial_rows.csv"),
        _first_column_values_of(out_dir / "raised_trials.csv"),
    )
    # `summary.csv` has one row for each count of the run, e.g. the trial folders chosen, the trial rows written, the trials exported from saved results of other code or the trials whose trajectory could not be read by reason.
    write_csv(out_dir / "summary.csv", ("count_name", "count"), total.summary_rows())
    # `equations.csv` has one row for each equation between steps of `EQUATIONS`, with its two sides and whether they are equal.
    write_csv(
        out_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        (
            (equation, left, right, "yes" if left == right else "no")
            for equation, left, right in equation_rows
        ),
    )
    for step_package, judgment_rules in JUDGMENT_RULES_BY_STEP_PACKAGE.items():
        step_dir = out_dir / step_package
        step_dir.mkdir(exist_ok=True)
        # A row key is written as a JSON array of its key column values.
        for file_name, key_column_name, key_count_total in (
            # `<step package>/row_uses.csv` has one row for each catalog row or a declared row of the knowledge class of the step that answered, with its lookups, trials and tasks.
            ("row_uses.csv", "row_key", total.row_use_totals[step_package]),
            # `<step package>/unknown_inputs.csv` has one row for each key that the knowledge class of the step found no row for, with its lookups, trials and tasks, most trials first.
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
                    (
                        source,
                        json.dumps(
                            [cut_key_word(word) for word in row_key]
                            if key_column_name == "key_asked"
                            else row_key
                        ),
                        count,
                        trial_count,
                        task_count,
                    )
                    for (
                        source,
                        row_key,
                    ), count, trial_count, task_count in key_count_total.rows()
                ),
            )
        # `<step package>/judgment_rule_uses.csv` has one row for each judgment rule of the step or a rule of another step that it counts, with its uses, trials and tasks, and 0 for a rule of the step that was never used.
        write_csv(
            step_dir / "judgment_rule_uses.csv",
            ("judgment_rule", "use_count", "trial_count", "task_count"),
            total.judgment_rule_use_totals[step_package].rows(
                judgment_rule_names_of(judgment_rules)
            ),
        )
    # `network_request/no_network_request_reasons.csv` has one row for each reason why a program run, code call or URL in code gave no request, with its count, trials and tasks.
    write_csv(
        out_dir / "network_request" / "no_network_request_reasons.csv",
        ("reason", "count", "trial_count", "task_count"),
        (
            (reason.value, count, trial_count, task_count)
            for reason, count, trial_count, task_count in total.no_network_request_total.rows()
        ),
    )
    # `network_request_result/unused_output_lines.csv` has one row for each reason and an output line kind of lines that a pattern fits and that gave no evidence, with its lines, trials and tasks.
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
    # `network_request_result/unowned_output_line_programs.csv` has one row for each reason, an output line kind and the name of a program whose run reaches the place of lines that no request owns, blank when no command reaches it, with its lines, trials and tasks.
    write_csv(
        out_dir / "network_request_result" / "unowned_output_line_programs.csv",
        (
            "reason",
            "output_line_kind",
            "program_name",
            "line_count",
            "trial_count",
            "task_count",
        ),
        (
            (
                reason.value,
                output_line_kind.value,
                cut_key_word(program_name),
                count,
                trial_count,
                task_count,
            )
            for (
                reason,
                output_line_kind,
                program_name,
            ), count, trial_count, task_count in total.unowned_output_line_program_total.rows()
        ),
    )
    return equation_rows


def _first_column_values_of(path: Path) -> list[str]:
    """Read back the first column of a written CSV file below its header, i.e. the trial ids of `trial_rows.csv` or `raised_trials.csv`."""
    with path.open(newline="") as csv_file:
        return [row[0] for row in list(csv.reader(csv_file))[1:]]


def cut_key_word(word: object) -> object:
    """Cut a word of a key from a trajectory before it is written, i.e. an option word at its first `=` and any word after `KEY_WORD_LENGTH_LIMIT` characters, marking how many characters were cut, and give any other value as it is.

    An option word is one that starts with `-`. The cut at `=` drops a value such as the token of `--token=ghp_x`, and the cut by length drops prose that a command reads as an option, e.g. a task text of 500 characters.
    e.g. `--token=ghp_x` becomes `--token[6 characters cut]`.
    The export step's `redact_credentials`, which hides only the userinfo, query values and fragment of URLs, is not called here, since its module is private to `export/`.
    """
    if not isinstance(word, str):
        return word
    kept_length = KEY_WORD_LENGTH_LIMIT
    if word.startswith("-") and "=" in word:
        kept_length = min(kept_length, word.index("="))
    if len(word) <= kept_length:
        return word
    return f"{word[:kept_length]}[{len(word) - kept_length} characters cut]"


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
    raised_count = sum(trial_run.raise_reason is not None for trial_run in trial_runs)
    return f"trials done {len(trial_runs)} of {trial_count}, raised {raised_count}, {time.monotonic() - start_time:.0f} s"


if __name__ == "__main__":
    main()
