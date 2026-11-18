"""Tests for scripts/run_pipeline.py, i.e. the count of the main measure per task, the cells of a row, the equations between steps and the files that `main` writes, with made-up rows and made-up trial folders."""

import csv
import dataclasses
import importlib.util
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tb_internet_use.export import export_rows
from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialCategoryMeasureRow,
    TrialRow,
)
from tb_internet_use.knowledge.export_knowledge import ExportKnowledge
from tb_internet_use.network_request.model import (
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)
from tb_internet_use.trial.model import (
    Trial,
    UnreadableTrajectory,
    UnreadableTrajectoryReason,
)

_SPEC = importlib.util.spec_from_file_location(
    "run_pipeline", Path(__file__).parents[2] / "scripts/run_pipeline.py"
)
assert _SPEC is not None and _SPEC.loader is not None
run_pipeline = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = run_pipeline  # dataclasses look the module up while it loads
_SPEC.loader.exec_module(run_pipeline)

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
FETCHED_FILE = NetworkRequestCategory.FETCHED_FILE

# The commands of a made-up trial with requests, i.e. a request for a file that runs only when the file is missing, a package of a variable and a URL of a program without a row.
_COMMANDS_WITH_REQUESTS = [
    (
        "test -f x.tgz || wget -O x.tgz https://files.acme.org/x.tgz; pip install $PKGS; mytool https://b.org/y",
        "Successfully installed requests-2.32.3",
    )
]
_ROW_FILE_NAMES = (
    "network_request_rows.csv",
    "trial_rows.csv",
    "trial_category_measure_rows.csv",
    "task_category_measures.csv",
)


def _trial(
    trial_id: str, *, unreadable_trajectory: UnreadableTrajectory | None = None
) -> Trial:
    return Trial(
        trial_id=trial_id,
        benchmark_version="4-0-0",
        task_name="terminal-bench/a",
        leaderboard_row_id="row-1",
        harness="claude-code",
        harness_version="2.1.0",
        model_name="model-a",
        reward=1.0,
        unreadable_trajectory=unreadable_trajectory,
    )


def _network_request_row(
    trial_id: str,
    category: NetworkRequestCategory,
    sender: NetworkRequestSender,
    request_measure_bound: MeasureBound,
    received_measure_bound: MeasureBound,
    *,
    request_index: int = 0,
) -> NetworkRequestRow:
    """Make a request row of one category, sender and pair of bounds, whose other columns no count of the script reads."""
    return NetworkRequestRow(
        trial_id=trial_id,
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=request_index,
        source_kind=NetworkRequestSourceKind.COMMAND,
        source="command 0",
        made_by="curl",
        target="https://a.org/x",
        unknown_target_reason=None,
        target_kind=NetworkRequestTargetKind.URL,
        host_names="a.org",
        received_content_destination="saved",
        request_certainty=NetworkRequestCertainty.CONFIRMED,
        request_uncertainty_reason=None,
        level=NetworkRequestResultLevel.RECEIVED,
        stop_reason=None,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence="",
        category=category,
        host_scope="public",
        host_service="unknown",
        package_registry="",
        is_internet_use=True,
        sender=sender,
        result_view=NetworkRequestResultView.RECEIVED,
        request_measure_bound=request_measure_bound,
        received_measure_bound=received_measure_bound,
    )


def _rows_of_trial(
    trial: Trial, network_request_rows: tuple[NetworkRequestRow, ...] = ()
) -> tuple[TrialRow, tuple[TrialCategoryMeasureRow, ...]]:
    """Give the trial row and the main measure rows that `export_rows` gives a trial with no results, or the main measure rows of the given request rows."""
    trial_row, _, trial_category_measure_rows = export_rows(
        trial, (), knowledge=ExportKnowledge(), judgment_rule_use_counts=Counter()
    )
    if network_request_rows:
        trial_category_measure_rows = tuple(
            TrialCategoryMeasureRow(
                row.trial_id,
                row.category,
                row.sender,
                row.request_measure_bound,
                row.received_measure_bound,
            )
            for row in network_request_rows
        )
    return trial_row, trial_category_measure_rows


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
    monkeypatch: pytest.MonkeyPatch,
    raw_trials_dir: Path,
    trial_ids: Iterable[str],
    out_dir: Path,
    *options: str,
) -> int:
    """Run `main` on the trial ids in their order and give its exit code, 0 when it returns."""
    trial_ids_file = raw_trials_dir.parent / "trial_ids.txt"
    trial_ids_file.write_text("".join(f"{trial_id}\n" for trial_id in trial_ids))
    monkeypatch.setattr(run_pipeline, "ProcessPoolExecutor", _InProcessPool)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            str(raw_trials_dir),
            "--trial-ids",
            str(trial_ids_file),
            "--out-dir",
            str(out_dir),
            *options,
        ],
    )
    try:
        run_pipeline.main()
    except SystemExit as exit_info:
        assert isinstance(exit_info.code, int)
        return exit_info.code
    return 0


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="") as csv_file:
        return list(csv.reader(csv_file))


def _write_raw_trials(raw_trials_dir: Path, write_trial_folder) -> None:
    """Write three made-up trial folders, t1 with requests, t2 without and t3 without a trajectory file."""
    write_trial_folder(raw_trials_dir, "t1", _COMMANDS_WITH_REQUESTS)
    write_trial_folder(raw_trials_dir, "t2", [("ls", "notes.txt")])
    write_trial_folder(raw_trials_dir, "t3", None)


def test_counts_the_main_measure_of_a_task_from_a_trial_with_requests_one_without_and_one_unreadable():
    # The trial with requests has a fetched file received and confirmed, a package of unknown internet use and a search of the provider server.
    fetched_file_row = _network_request_row(
        "t1", FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
    )
    network_request_rows = (
        fetched_file_row,
        _network_request_row(
            "t1",
            NetworkRequestCategory.PACKAGE,
            TASK_ENVIRONMENT,
            UPPER_ONLY,
            UPPER_ONLY,
            request_index=1,
        ),
        _network_request_row(
            "t1",
            NetworkRequestCategory.SEARCH,
            NetworkRequestSender.PROVIDER_SERVER,
            LOWER_AND_UPPER,
            LOWER_AND_UPPER,
            request_index=2,
        ),
    )
    trial_rows: list[TrialRow] = []
    trial_category_measure_rows: list[TrialCategoryMeasureRow] = []
    for trial, rows in (
        (_trial("t1"), network_request_rows),
        (_trial("t2"), ()),
        (
            _trial(
                "t3",
                unreadable_trajectory=UnreadableTrajectory(
                    UnreadableTrajectoryReason.MISSING
                ),
            ),
            (),
        ),
    ):
        trial_row, measure_rows = _rows_of_trial(trial, rows)
        trial_rows.append(trial_row)
        trial_category_measure_rows.extend(measure_rows)

    lines = run_pipeline.count_task_category_measures(
        trial_rows, network_request_rows, trial_category_measure_rows
    )

    lines_by_category_and_sender = {(line[2], line[3]): line[4:] for line in lines}
    # Trials, request lower and upper, received lower and upper, request rows.
    assert lines_by_category_and_sender["fetched_file", "task_environment"] == (
        3,
        1,
        2,
        1,
        2,
        1,
    )
    assert lines_by_category_and_sender["package", "task_environment"] == (
        3,
        0,
        2,
        0,
        2,
        1,
    )
    # Only the unreadable trial counts in a category that no request has, and not for the sender `unknown`.
    assert lines_by_category_and_sender["page_read", "harness_process"] == (
        3,
        0,
        1,
        0,
        1,
        0,
    )
    assert ("page_read", "unknown") not in lines_by_category_and_sender
    assert {line[:2] for line in lines} == {("4-0-0", "terminal-bench/a")}


def test_a_task_without_any_main_measure_row_has_no_line():
    trial_row, measure_rows = _rows_of_trial(_trial("t2"))

    assert (
        run_pipeline.count_task_category_measures([trial_row], [], measure_rows) == []
    )


def test_writes_none_as_a_blank_a_bool_as_true_or_false_and_an_enum_as_its_value():
    trial_row, _ = _rows_of_trial(_trial("t1"))
    network_request_row = _network_request_row(
        "t1", FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
    )

    trial_cells = run_pipeline.csv_cells_of(trial_row)
    request_cells = dict(
        zip(
            [row_field.name for row_field in dataclasses.fields(NetworkRequestRow)],
            run_pipeline.csv_cells_of(network_request_row),
            strict=True,
        )
    )

    assert trial_cells[-4:] == [1.0, "", "neither", "neither"]
    assert (
        request_cells["is_internet_use"],
        request_cells["unknown_target_reason"],
        request_cells["category"],
        request_cells["step_id"],
    ) == ("true", "", "fetched_file", 1)


def test_main_writes_the_rows_sorted_by_trial_id_and_every_equation_holds(
    tmp_path, monkeypatch, write_trial_folder
):
    _InProcessPool.process_counts.clear()
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"

    exit_code = _run_main(monkeypatch, raw_trials_dir, ["t3", "t1", "t2"], out_dir)

    assert exit_code == 0
    assert 0 < max(_InProcessPool.process_counts) <= 4
    trial_rows = _csv_rows(out_dir / "trial_rows.csv")
    assert trial_rows[0] == [
        row_field.name for row_field in dataclasses.fields(TrialRow)
    ]
    assert [(row[0], row[8]) for row in trial_rows[1:]] == [
        ("t1", ""),
        ("t2", ""),
        ("t3", "missing"),
    ]
    request_rows = _csv_rows(out_dir / "network_request_rows.csv")[1:]
    assert [(row[0], row[4]) for row in request_rows] == [
        ("t1", "0"),
        ("t1", "1"),
        ("t1", "2"),
    ]
    equation_rows = _csv_rows(out_dir / "equations.csv")[1:]
    assert [row[0] for row in equation_rows] == list(run_pipeline.EQUATIONS)
    assert {row[3] for row in equation_rows} == {"yes"}
    assert _csv_rows(out_dir / "raised_trials.csv") == [["trial_id", "exception_type"]]
    assert ["trials_unreadable_missing", "1"] in _csv_rows(out_dir / "summary.csv")
    # The unreadable trial has one main measure row per category and each sender other than unknown.
    measure_rows = _csv_rows(out_dir / "trial_category_measure_rows.csv")[1:]
    assert (
        sum(row[0] == "t3" for row in measure_rows) == len(NetworkRequestCategory) * 3
    )
    # Each step lists its rules, also those never used, with their trials and tasks.
    export_rule_rows = _csv_rows(out_dir / "export" / "judgment_rule_uses.csv")
    assert export_rule_rows[0] == [
        "judgment_rule",
        "use_count",
        "trial_count",
        "task_count",
    ]
    assert [
        "treat_request_without_host_name_as_sent_to_default_registry_host",
        "1",
        "1",
        "1",
    ] in export_rule_rows
    assert [
        "treat_reserved_host_name_as_unknown_internet_use",
        "0",
        "0",
        "0",
    ] in export_rule_rows
    assert ["treat_dotted_host_name_as_public", "1", "1", "1"] in _csv_rows(
        out_dir / "network_request" / "judgment_rule_uses.csv"
    )
    assert _csv_rows(out_dir / "export" / "row_uses.csv")[1:] == [
        ["program_package_registries.csv", '["pip", "install"]', "1", "1", "1"]
    ]
    assert _csv_rows(out_dir / "export" / "unknown_inputs.csv")[0] == [
        "source",
        "key_asked",
        "lookup_count",
        "trial_count",
        "task_count",
    ]
    for step_package in run_pipeline.JUDGMENT_RULES_BY_STEP_PACKAGE:
        assert (out_dir / step_package / "unknown_inputs.csv").exists()


def test_main_names_the_trials_that_raised_and_exits_1(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    write_trial_folder(raw_trials_dir, "t4", [("ls", "")], has_detail_file=False)
    out_dir = tmp_path / "out"

    exit_code = _run_main(monkeypatch, raw_trials_dir, ["t1", "t4", "t9"], out_dir)

    assert exit_code == 1
    # t4 has no detail file and t9 names no folder.
    assert _csv_rows(out_dir / "raised_trials.csv")[1:] == [
        ["t4", "FileNotFoundError"],
        ["t9", "FileNotFoundError"],
    ]
    assert [row[0] for row in _csv_rows(out_dir / "trial_rows.csv")[1:]] == ["t1"]
    assert not (out_dir / "network_request_results" / "t4.pickle").exists()


def test_export_only_reads_no_trajectory_and_gives_the_same_rows(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir)
    first_files = {name: (out_dir / name).read_text() for name in _ROW_FILE_NAMES}
    first_rule_uses = (out_dir / "tool_call" / "judgment_rule_uses.csv").read_text()
    (raw_trials_dir / "t1" / "trajectory.json").unlink()

    exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir, "--export-only"
    )

    assert exit_code == 0
    assert {
        name: (out_dir / name).read_text() for name in _ROW_FILE_NAMES
    } == first_files
    # The counts of the steps before `export_rows` come from the saved results.
    assert (
        out_dir / "tool_call" / "judgment_rule_uses.csv"
    ).read_text() == first_rule_uses


def test_resume_runs_only_the_trials_without_saved_results_and_export_only_names_them(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir)
    first_files = {name: (out_dir / name).read_text() for name in _ROW_FILE_NAMES}
    (out_dir / "network_request_results" / "t1.pickle").unlink()
    # A trajectory that changed after t2 was saved shows whether t2 ran again.
    (raw_trials_dir / "t2" / "trajectory.json").unlink()

    export_only_exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir, "--export-only"
    )
    raised_by_export_only = _csv_rows(out_dir / "raised_trials.csv")[1:]
    resume_exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir, "--resume"
    )

    assert (export_only_exit_code, raised_by_export_only) == (
        1,
        [["t1", "FileNotFoundError"]],
    )
    assert resume_exit_code == 0
    assert {
        name: (out_dir / name).read_text() for name in _ROW_FILE_NAMES
    } == first_files
    assert (out_dir / "network_request_results" / "t1.pickle").exists()


def _trial_run(
    trial_id: str,
    network_request_rows: tuple[NetworkRequestRow, ...] = (),
    **changes: Any,
):
    """Make the run of a read trial whose results are its request rows, one each, and whose main measure rows are those of the rows, with the fields of `changes` replaced."""
    trial = _trial(trial_id)
    trial_row, measure_rows = _rows_of_trial(trial, network_request_rows)
    trial_run = run_pipeline.TrialRun(
        trial_id,
        trial=trial,
        network_request_result_counts=Counter(
            row.stop_reason for row in network_request_rows
        ),
        trial_row=trial_row,
        network_request_rows=network_request_rows,
        trial_category_measure_rows=measure_rows,
    )
    return dataclasses.replace(trial_run, **changes)


_RECEIVED_ROW = _network_request_row(
    "t1", FETCHED_FILE, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
)

# (equation, made-up trial runs that break it, number of trials chosen), one case per equation.
BROKEN_RUN_CASES = [
    # A trial that was chosen and gave no run.
    ("trial_rows_equal_trials_that_did_not_raise", [_trial_run("t1")], 2),
    (
        "trial_rows_have_distinct_trial_ids",
        [_trial_run("t1"), _trial_run("t1")],
        1,
    ),
    (
        "request_rows_equal_network_request_results",
        [
            _trial_run(
                "t1", (_RECEIVED_ROW,), network_request_result_counts=Counter({None: 2})
            )
        ],
        1,
    ),
    (
        "trials_with_request_rows_equal_trials_with_results",
        [
            _trial_run("t1", (_RECEIVED_ROW,)),
            _trial_run("t2", network_request_result_counts=Counter({None: 1})),
        ],
        1,
    ),
    (
        "readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results",
        [_trial_run("t1", network_request_result_counts=Counter({None: 1}))],
        1,
    ),
    (
        "request_rows_of_unreadable_trials",
        [
            _trial_run(
                "t1",
                (_RECEIVED_ROW,),
                trial=_trial(
                    "t1",
                    unreadable_trajectory=UnreadableTrajectory(
                        UnreadableTrajectoryReason.MISSING
                    ),
                ),
            )
        ],
        1,
    ),
    (
        "request_rows_sharing_their_first_five_columns",
        [_trial_run("t1", (_RECEIVED_ROW, _RECEIVED_ROW))],
        1,
    ),
    (
        "received_rows_equal_results_without_stop_reason",
        [
            _trial_run(
                "t1",
                (_RECEIVED_ROW,),
                network_request_result_counts=Counter(
                    {NetworkRequestResultStopReason.FAILED: 1}
                ),
            )
        ],
        1,
    ),
    (
        "not_received_rows_equal_failed_results",
        [
            _trial_run(
                "t1",
                (
                    dataclasses.replace(
                        _RECEIVED_ROW, result_view=NetworkRequestResultView.NOT_RECEIVED
                    ),
                ),
            )
        ],
        1,
    ),
    (
        "unknown_result_rows_equal_not_visible_results",
        [
            _trial_run(
                "t1",
                (
                    dataclasses.replace(
                        _RECEIVED_ROW, result_view=NetworkRequestResultView.UNKNOWN
                    ),
                ),
            )
        ],
        1,
    ),
    (
        "not_needed_rows_equal_not_needed_results",
        [
            _trial_run(
                "t1",
                (
                    dataclasses.replace(
                        _RECEIVED_ROW, result_view=NetworkRequestResultView.NOT_NEEDED
                    ),
                ),
            )
        ],
        1,
    ),
    (
        "measure_rows_of_read_trials_equal_their_categories_and_senders",
        [_trial_run("t1", (_RECEIVED_ROW,), trial_category_measure_rows=())],
        1,
    ),
    (
        "measure_rows_of_unreadable_trials_equal_each_category_and_known_sender",
        [
            _trial_run(
                "t1",
                trial=_trial(
                    "t1",
                    unreadable_trajectory=UnreadableTrajectory(
                        UnreadableTrajectoryReason.MISSING
                    ),
                ),
            )
        ],
        1,
    ),
]


def test_every_equation_has_a_broken_input():
    assert [case[0] for case in BROKEN_RUN_CASES] == list(run_pipeline.EQUATIONS)


@pytest.mark.parametrize(("equation", "trial_runs", "trial_count"), BROKEN_RUN_CASES)
def test_a_broken_run_makes_its_equation_differ(equation, trial_runs, trial_count):
    total = run_pipeline.PipelineRunTotal.of_trial_runs(trial_runs, trial_count)

    sides = {name: (left, right) for name, left, right in total.equation_rows()}

    assert sides[equation][0] != sides[equation][1]
    assert total.has_raised_trial_or_differing_equation()
