"""Tests for scripts/run_pipeline.py, e.g. the count of the main measure per task, the cells of a row, the equations between steps, the files that `main` writes and the runs of trials in worker processes, with made-up rows and made-up trial folders."""

import csv
import dataclasses
import importlib.util
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from pathlib import Path
from types import ModuleType
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
    OutputLineKind,
    UnusedOutputLineReason,
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
sys.modules[_SPEC.name] = run_pipeline  # pickle finds `TrialRun` under this name
_SPEC.loader.exec_module(run_pipeline)

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
FILE_FETCH = NetworkRequestCategory.FILE_FETCH

# The commands of a made-up trial with requests, i.e. a request for a file that runs only when the file is missing, a package of a variable and a URL of a program without a row, then a script whose text the trial does not hold, which prints a download line that no request owns.
_COMMANDS_WITH_REQUESTS = [
    (
        "test -f x.tgz || wget -O x.tgz https://files.acme.org/x.tgz; pip install $PKGS; mytool https://b.org/y",
        "Successfully installed requests-2.32.3",
    ),
    ("./setup.sh", "Downloading torch-2.3.0.whl"),
]
_ROW_FILE_NAMES = (
    "network_request_rows.csv",
    "trial_rows.csv",
    "trial_category_measure_rows.csv",
    "task_category_measures.csv",
)
# The files of the counts of the steps, which a run from saved results must write as the run that saved them did.
_COUNT_FILE_NAMES = (
    "tool_call/row_uses.csv",
    "expanded_tool_call/unknown_inputs.csv",
    "network_request/judgment_rule_uses.csv",
    "network_request/no_network_request_reasons.csv",
    "network_request_result/unused_output_lines.csv",
    "network_request_result/unowned_output_line_programs.csv",
    "export/row_uses.csv",
    "export/judgment_rule_uses.csv",
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
    """Make a request row of one category, sender and pair of bounds, whose other columns are those of a received `curl` of `https://a.org/x`."""
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
        is_among_success_line_owners_one_of_which_received=False,
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
    """Stand-in for the process pool of `run_trials`, which runs each task in the test process at once so that what a test patches on the script reaches the task, and keeps the process count it was asked for."""

    # The process counts that `main` asked for, kept across instances.
    process_counts: ClassVar[list[int]] = []

    def __init__(self, process_count: int) -> None:
        self.process_counts.append(process_count)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        pass

    def submit(self, function: Callable[[Path], Any], item: Path) -> Future:
        future: Future = Future()
        future.set_result(function(item))
        return future

    def kill_workers(self) -> None:
        pass


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


def _texts_of(out_dir: Path, file_names: Iterable[str]) -> dict[str, str]:
    return {name: (out_dir / name).read_text() for name in file_names}


def _write_raw_trials(raw_trials_dir: Path, write_trial_folder) -> None:
    """Write three made-up trial folders, t1 with requests, t2 without and t3 without a trajectory file."""
    write_trial_folder(raw_trials_dir, "t1", _COMMANDS_WITH_REQUESTS)
    write_trial_folder(raw_trials_dir, "t2", [("ls", "notes.txt")])
    write_trial_folder(raw_trials_dir, "t3", None)


def test_counts_the_main_measure_of_a_task_from_a_trial_with_requests_one_without_and_one_unreadable():
    # The trial with requests has a file fetch received and confirmed, a package of unknown internet use and a search of the provider server.
    file_fetch_row = _network_request_row(
        "t1", FILE_FETCH, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
    )
    network_request_rows = (
        file_fetch_row,
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
        # A page read that was not needed counts in neither bound and still as a request row.
        _network_request_row(
            "t1",
            NetworkRequestCategory.PAGE_READ,
            TASK_ENVIRONMENT,
            NEITHER,
            NEITHER,
            request_index=3,
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
    assert lines_by_category_and_sender["file_fetch", "task_environment"] == (
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
    # The unreadable trial counts in the upper bounds of the page read of the task environment, and the read trial whose row is in neither bound does not.
    assert lines_by_category_and_sender["page_read", "task_environment"] == (
        3,
        0,
        1,
        0,
        1,
        1,
    )
    assert {line[:2] for line in lines} == {("4-0-0", "terminal-bench/a")}


def test_a_task_without_any_main_measure_row_has_no_line():
    trial_row, measure_rows = _rows_of_trial(_trial("t2"))

    assert (
        run_pipeline.count_task_category_measures([trial_row], [], measure_rows) == []
    )


def test_writes_none_as_a_blank_a_bool_as_true_or_false_and_an_enum_as_its_value():
    trial_row, _ = _rows_of_trial(_trial("t1"))
    network_request_row = _network_request_row(
        "t1", FILE_FETCH, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
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
    ) == ("true", "", "file_fetch", 1)


def test_main_writes_the_rows_sorted_by_trial_id_and_every_equation_holds(
    tmp_path, monkeypatch, write_trial_folder, capsys
):
    _InProcessPool.process_counts.clear()
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"

    # The list names t1 twice, which runs once.
    exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t3", "t1", "t2", "t1"], out_dir
    )

    assert exit_code == 0
    # Progress goes to stderr, and stdout holds only the equations and the closing lines.
    printed = capsys.readouterr()
    assert "trials done 3 of 3, raised 0" in printed.err
    assert "trials done" not in printed.out
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
    assert _csv_rows(out_dir / "raised_trials.csv") == [["trial_id", "reason"]]
    summary_rows = _csv_rows(out_dir / "summary.csv")
    for summary_row in (
        ["trial_folders_chosen", "3"],
        ["repeated_trial_ids_dropped", "1"],
        ["trial_rows", "3"],
        ["trials_unreadable_missing", "1"],
        ["network_requests", "3"],
        ["network_request_results", "3"],
    ):
        assert summary_row in summary_rows
    # Each trial that ran from its folder has its saved file and no file is left half written.
    assert sorted(
        path.name for path in (out_dir / "network_request_results").iterdir()
    ) == ["t1.pickle", "t2.pickle", "t3.pickle"]
    # The line of setup.sh that no request owns is listed by its reason, kind and program.
    assert _csv_rows(
        out_dir / "network_request_result" / "unowned_output_line_programs.csv"
    ) == [
        [
            "reason",
            "output_line_kind",
            "program_name",
            "line_count",
            "trial_count",
            "task_count",
        ],
        ["unowned_line_in_unknown_run", "download_started", "setup.sh", "1", "1", "1"],
    ]
    # The knowledge classes of the steps before `export_rows` keep their lookups, e.g. the row of pip and the unknown mytool.
    assert [
        "program_network_requests.csv",
        '["pip", "install", "", ""]',
    ] in [row[:2] for row in _csv_rows(out_dir / "network_request" / "row_uses.csv")]
    assert any(
        "mytool" in row[1]
        for row in _csv_rows(out_dir / "expanded_tool_call" / "unknown_inputs.csv")[1:]
    )
    assert not any(
        "mytool" in row[1]
        for row in _csv_rows(out_dir / "expanded_tool_call" / "row_uses.csv")[1:]
    )
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
    first_files = _texts_of(out_dir, (*_ROW_FILE_NAMES, *_COUNT_FILE_NAMES))
    (raw_trials_dir / "t1" / "trajectory.json").unlink()

    exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir, "--export-only"
    )

    assert exit_code == 0
    # The counts of the steps before `export_rows` come from the saved results, and those of `export_rows` start empty for each trial as in the first run.
    assert _texts_of(out_dir, (*_ROW_FILE_NAMES, *_COUNT_FILE_NAMES)) == first_files
    for name in _COUNT_FILE_NAMES:
        assert len(_csv_rows(out_dir / name)) > 1, name


def test_resume_runs_only_the_trials_without_saved_results_and_export_only_names_them(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2", "t3"], out_dir)
    first_files = _texts_of(out_dir, (*_ROW_FILE_NAMES, *_COUNT_FILE_NAMES))
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
    assert _texts_of(out_dir, (*_ROW_FILE_NAMES, *_COUNT_FILE_NAMES)) == first_files
    assert (out_dir / "network_request_results" / "t1.pickle").exists()


def test_counts_the_requests_of_extract_network_requests_apart_from_their_results(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    run_steps_of_trial = run_pipeline.run_steps_of_trial

    def run_steps_of_trial_losing_a_result(trial_dir: Path, **keywords: Any):
        """Run the steps and drop the last result of a trial with requests, as a result step that lost one would."""
        output = run_steps_of_trial(trial_dir, **keywords)
        trial, network_requests, network_request_results, *rows = output
        if not network_request_results:
            return output
        return (trial, network_requests, network_request_results[:-1], *rows)

    monkeypatch.setattr(
        run_pipeline, "run_steps_of_trial", run_steps_of_trial_losing_a_result
    )

    exit_code = _run_main(monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir)

    assert exit_code == 1
    assert [
        "network_requests_equal_network_request_results",
        "3",
        "2",
        "no",
    ] in _csv_rows(out_dir / "equations.csv")
    # A run from the saved results keeps the count of the requests.
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir, "--export-only")
    assert ["network_requests", "3"] in _csv_rows(out_dir / "summary.csv")


def test_a_run_without_resume_reads_every_trial_folder_again(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir)
    (raw_trials_dir / "t2" / "trajectory.json").unlink()

    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir)

    assert [row[8] for row in _csv_rows(out_dir / "trial_rows.csv")[1:]] == [
        "",
        "missing",
    ]


def test_saved_results_of_other_code_run_again_with_resume_and_raise_with_export_only(
    tmp_path, monkeypatch, write_trial_folder
):
    raw_trials_dir = tmp_path / "raw"
    _write_raw_trials(raw_trials_dir, write_trial_folder)
    out_dir = tmp_path / "out"
    _run_main(monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir)
    # The trajectory of t2 changed after it was saved, and the code changed too.
    (raw_trials_dir / "t2" / "trajectory.json").unlink()
    monkeypatch.setattr(
        run_pipeline, "earlier_step_code_digest_of", lambda package_dir: "other"
    )

    export_only_exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir, "--export-only"
    )
    raised_by_export_only = _csv_rows(out_dir / "raised_trials.csv")[1:]
    resume_exit_code = _run_main(
        monkeypatch, raw_trials_dir, ["t1", "t2"], out_dir, "--resume"
    )

    assert (export_only_exit_code, raised_by_export_only) == (
        1,
        [
            ["t1", run_pipeline.SAVED_RESULTS_OF_OTHER_CODE],
            ["t2", run_pipeline.SAVED_RESULTS_OF_OTHER_CODE],
        ],
    )
    assert resume_exit_code == 0
    assert [row[8] for row in _csv_rows(out_dir / "trial_rows.csv")[1:]] == [
        "",
        "missing",
    ]
    # The trials ran again and were saved with the digest of the code that ran them.
    assert {
        run_pipeline.read_saved_results(
            out_dir / "network_request_results" / f"{trial_id}.pickle"
        )[0]
        for trial_id in ("t1", "t2")
    } == {"other"}


def test_the_code_digest_changes_with_a_file_that_the_earlier_steps_read_and_not_with_one_of_the_export_step(
    tmp_path,
):
    package_dir = tmp_path / "tb_internet_use"
    for relative_path in (
        "pipeline.py",
        "tool_call/_convert_tool_calls.py",
        "knowledge/catalogs/tool_call/harness_tools.csv",
        "knowledge/export_knowledge.py",
        "knowledge/catalogs/export/public_hosts.csv",
        "export/_export_rows.py",
        "README.md",
    ):
        (package_dir / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (package_dir / relative_path).write_text("a\n")
    first_digest = run_pipeline.earlier_step_code_digest_of(package_dir)

    digests_after_change = {}
    for relative_path in (
        "knowledge/catalogs/tool_call/harness_tools.csv",
        "export/_export_rows.py",
        "knowledge/catalogs/export/public_hosts.csv",
        "knowledge/export_knowledge.py",
        "README.md",
    ):
        (package_dir / relative_path).write_text("b\n")
        digests_after_change[relative_path] = run_pipeline.earlier_step_code_digest_of(
            package_dir
        )
        (package_dir / relative_path).write_text("a\n")

    assert {
        relative_path: digest != first_digest
        for relative_path, digest in digests_after_change.items()
    } == {
        "knowledge/catalogs/tool_call/harness_tools.csv": True,
        "export/_export_rows.py": False,
        "knowledge/catalogs/export/public_hosts.csv": False,
        "knowledge/export_knowledge.py": False,
        "README.md": False,
    }


def _trial_run(
    trial_id: str,
    network_request_rows: tuple[NetworkRequestRow, ...] = (),
    **changes: Any,
):
    """Make the run of a read trial whose requests and results are its request rows, one each, and whose main measure rows are those of the rows, with the fields of `changes` replaced."""
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
        earlier_step_counts=run_pipeline.EarlierStepCounts(
            network_request_count=len(network_request_rows)
        ),
    )
    return dataclasses.replace(trial_run, **changes)


def _equation_sides(
    trial_runs: list,
    chosen_trial_ids: list[str],
    written_trial_ids: list[str] | None = None,
) -> dict[str, tuple[int, int]]:
    """Give the two sides of each equation of the runs, with the trial ids of the written files those of the sum unless `written_trial_ids` gives others."""
    total = run_pipeline.PipelineRunTotal.of_trial_runs(trial_runs, chosen_trial_ids)
    return {
        name: (left, right)
        for name, left, right in total.equation_rows(
            [trial_row.trial_id for trial_row in total.trial_rows]
            if written_trial_ids is None
            else written_trial_ids,
            [trial_id for trial_id, _ in total.raised_trials],
        )
    }


_RECEIVED_ROW = _network_request_row(
    "t1", FILE_FETCH, TASK_ENVIRONMENT, LOWER_AND_UPPER, LOWER_AND_UPPER
)
_UNREADABLE_TRIAL = _trial(
    "t1", unreadable_trajectory=UnreadableTrajectory(UnreadableTrajectoryReason.MISSING)
)


def _unreadable_trial_run(trial_id: str):
    """Make the run of a trial whose trajectory is missing, with the rows that `export_rows` gives it."""
    trial = _trial(
        trial_id,
        unreadable_trajectory=UnreadableTrajectory(UnreadableTrajectoryReason.MISSING),
    )
    trial_row, measure_rows = _rows_of_trial(trial)
    return run_pipeline.TrialRun(
        trial_id,
        trial=trial,
        trial_row=trial_row,
        trial_category_measure_rows=measure_rows,
    )


def test_a_run_without_fault_holds_every_equation():
    # One category of t1 has a request sent from the task environment and one sent from the provider server, so it has two main measure rows. t2 has no request and t3 could not be read.
    trial_runs = [
        _trial_run(
            "t1",
            (
                _RECEIVED_ROW,
                dataclasses.replace(
                    _RECEIVED_ROW,
                    request_index=1,
                    sender=NetworkRequestSender.PROVIDER_SERVER,
                ),
            ),
        ),
        _trial_run("t2"),
        _unreadable_trial_run("t3"),
    ]

    sides = _equation_sides(trial_runs, ["t1", "t2", "t3"])

    assert {
        name: left_and_right
        for name, left_and_right in sides.items()
        if left_and_right[0] != left_and_right[1]
    } == {}
    assert sides["measure_rows_of_read_trials_equal_their_categories_and_senders"] == (
        2,
        2,
    )


# (equation, made-up trial runs that break it, trial ids chosen, trial ids of the written `trial_rows.csv` or None for those of the runs), one case per equation.
BROKEN_RUN_CASES = [
    # A trial that was chosen and raised.
    (
        "trial_rows_equal_trial_folders_chosen",
        [_trial_run("t1"), run_pipeline.TrialRun("t2", raise_reason="ValueError")],
        ["t1", "t2"],
        None,
    ),
    # A trial row that the sum held and the written file lost.
    (
        "written_trial_rows_equal_chosen_trials_without_written_raised_trials",
        [_trial_run("t1"), _trial_run("t2")],
        ["t1", "t2"],
        ["t1"],
    ),
    (
        "trial_rows_have_distinct_trial_ids",
        [_trial_run("t1"), _trial_run("t1")],
        ["t1"],
        None,
    ),
    (
        "network_requests_equal_network_request_results",
        [
            _trial_run(
                "t1",
                (_RECEIVED_ROW,),
                earlier_step_counts=run_pipeline.EarlierStepCounts(
                    network_request_count=2
                ),
            )
        ],
        ["t1"],
        None,
    ),
    (
        "request_rows_equal_network_request_results",
        [
            _trial_run(
                "t1",
                (_RECEIVED_ROW,),
                network_request_result_counts=Counter({None: 2}),
                earlier_step_counts=run_pipeline.EarlierStepCounts(
                    network_request_count=2
                ),
            )
        ],
        ["t1"],
        None,
    ),
    (
        "trials_with_request_rows_equal_trials_with_results",
        [
            _trial_run("t1", (_RECEIVED_ROW,)),
            _trial_run("t2", network_request_result_counts=Counter({None: 1})),
        ],
        ["t1", "t2"],
        None,
    ),
    (
        "readable_trials_equal_trials_with_request_rows_and_readable_trials_without_results",
        [_trial_run("t1", network_request_result_counts=Counter({None: 1}))],
        ["t1"],
        None,
    ),
    (
        "request_rows_of_unreadable_trials",
        [_trial_run("t1", (_RECEIVED_ROW,), trial=_UNREADABLE_TRIAL)],
        ["t1"],
        None,
    ),
    (
        "request_rows_sharing_their_first_five_columns",
        [_trial_run("t1", (_RECEIVED_ROW, _RECEIVED_ROW))],
        ["t1"],
        None,
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
        ["t1"],
        None,
    ),
    *(
        (
            equation,
            [
                _trial_run(
                    "t1",
                    (dataclasses.replace(_RECEIVED_ROW, result_view=result_view),),
                )
            ],
            ["t1"],
            None,
        )
        for equation, result_view in (
            (
                "not_received_rows_equal_failed_results",
                NetworkRequestResultView.NOT_RECEIVED,
            ),
            (
                "unknown_result_rows_equal_not_visible_results",
                NetworkRequestResultView.UNKNOWN,
            ),
            (
                "not_needed_rows_equal_not_needed_results",
                NetworkRequestResultView.NOT_NEEDED,
            ),
        )
    ),
    (
        "measure_rows_of_read_trials_equal_their_categories_and_senders",
        [_trial_run("t1", (_RECEIVED_ROW,), trial_category_measure_rows=())],
        ["t1"],
        None,
    ),
    (
        "measure_rows_of_unreadable_trials_equal_each_category_and_known_sender",
        [_trial_run("t1", trial=_UNREADABLE_TRIAL)],
        ["t1"],
        None,
    ),
]


def test_every_equation_has_a_broken_input():
    assert [case[0] for case in BROKEN_RUN_CASES] == list(run_pipeline.EQUATIONS)


@pytest.mark.parametrize(
    ("equation", "trial_runs", "chosen_trial_ids", "written_trial_ids"),
    BROKEN_RUN_CASES,
)
def test_a_broken_run_makes_its_equation_differ(
    equation, trial_runs, chosen_trial_ids, written_trial_ids
):
    left, right = _equation_sides(trial_runs, chosen_trial_ids, written_trial_ids)[
        equation
    ]

    assert left != right


def test_a_key_counts_each_trial_that_has_it_once_and_each_task_once():
    key_count_total = run_pipeline.KeyCountTotal()

    key_count_total.add_trial(Counter({"a": 3, "b": 0}), ("4-0-0", "task-1"))
    key_count_total.add_trial(Counter({"a": 1}), ("4-0-0", "task-1"))
    key_count_total.add_trial(Counter({"a": 1, "c": 1}), ("4-0-0", "task-2"))

    # A key that a trial counted 0 times stays listed with 0 trials and 0 tasks, and `d`, which no trial counted, is listed because it is asked for.
    assert key_count_total.rows(["d"]) == [
        ("a", 5, 3, 2),
        ("c", 1, 1, 1),
        ("b", 0, 0, 0),
        ("d", 0, 0, 0),
    ]


def test_lists_the_public_functions_defined_in_a_module_of_judgment_rules():
    def treat_a_as_b() -> None:
        pass

    def _treat_c_as_d() -> None:
        pass

    judgment_rules = ModuleType("made_up_judgment_rules")
    for function in (treat_a_as_b, _treat_c_as_d):
        function.__module__ = judgment_rules.__name__
        setattr(judgment_rules, function.__name__, function)
    # A function that the module imports is no rule of it.
    judgment_rules.__dict__["join"] = os.path.join

    assert run_pipeline.judgment_rule_names_of(judgment_rules) == ["treat_a_as_b"]


@pytest.mark.parametrize(
    ("word", "written_word"),
    [
        (
            "--token=ghp_xxxxxxxxxxxxxxxxxxxx",
            "--token[25 characters cut]",
        ),
        ("w" * 300, "w" * 64 + "[236 characters cut]"),
        # An option word with `=` after the 64th character is cut at the 64th.
        ("--" + "o" * 70 + "=v", "--" + "o" * 62 + "[10 characters cut]"),
        ("--max-time", "--max-time"),
        ("setup.sh", "setup.sh"),
        # A word without `-` in front keeps its `=`, e.g. a variable assignment.
        ("A=1", "A=1"),
    ],
)
def test_cuts_an_option_word_at_its_first_equals_sign_and_any_word_after_64_characters(
    word, written_word
):
    assert run_pipeline.cut_key_word(word) == written_word


def test_writes_the_words_of_unknown_inputs_and_unowned_line_programs_cut(tmp_path):
    long_word = "w" * 300
    earlier_step_counts = run_pipeline.EarlierStepCounts()
    earlier_step_counts.knowledge_uses_by_step_package[
        "expanded_tool_call"
    ].unknown_input_counts.update(
        {
            (
                "program_option_behaviors.csv",
                ("curl", "", "--token=ghp_xxxxxxxxxxxxxxxxxxxx"),
            ): 1,
            ("program_behaviors.csv", (long_word, "")): 1,
        }
    )
    earlier_step_counts.program_counts_of_unowned_output_lines[
        UnusedOutputLineReason.NO_UNKNOWN_RUN,
        OutputLineKind.DOWNLOAD_STARTED,
        long_word,
    ] = 1
    total = run_pipeline.PipelineRunTotal.of_trial_runs(
        [_trial_run("t1", earlier_step_counts=earlier_step_counts)], ["t1"]
    )

    run_pipeline.write_pipeline_run_files(total, tmp_path)

    written_text = "".join(
        (tmp_path / name).read_text()
        for name in (
            "expanded_tool_call/unknown_inputs.csv",
            "network_request_result/unowned_output_line_programs.csv",
        )
    )
    assert "ghp_" not in written_text
    assert long_word not in written_text
    assert '"--token[25 characters cut]"' in written_text
    assert written_text.count("w" * 64 + "[236 characters cut]") == 2


def _run_trial_that_exits_the_process_on_t2(trial_dir: Path):
    """Stand in for `run_trial` in a worker process, ending that process at once on the trial t2 as a crash in a C extension would, while each other trial takes a second, so that it still runs when t2 breaks the pool."""
    if trial_dir.name == "t2":
        os._exit(1)
    time.sleep(1)
    return run_pipeline.TrialRun(trial_dir.name)


def _run_trial_that_hangs_on_t2(trial_dir: Path):
    """Stand in for `run_trial` in a worker process, hanging on the trial t2."""
    if trial_dir.name == "t2":
        time.sleep(600)
    return run_pipeline.TrialRun(trial_dir.name)


_TRIAL_DIRS = [Path(f"t{number}") for number in range(1, 7)]


def test_a_trial_that_kills_its_worker_is_found_alone_and_the_others_run():
    trial_runs = list(
        run_pipeline.run_trials(
            _TRIAL_DIRS,
            _run_trial_that_exits_the_process_on_t2,
            trial_time_limit_seconds=120,
        )
    )

    assert sorted(
        (trial_run.trial_id, trial_run.raise_reason) for trial_run in trial_runs
    ) == [
        ("t1", None),
        ("t2", run_pipeline.WORKER_PROCESS_DIED),
        ("t3", None),
        ("t4", None),
        ("t5", None),
        ("t6", None),
    ]


def test_a_trial_that_runs_too_long_times_out_and_the_others_run():
    trial_runs = list(
        run_pipeline.run_trials(
            _TRIAL_DIRS, _run_trial_that_hangs_on_t2, trial_time_limit_seconds=5
        )
    )

    assert sorted(
        (trial_run.trial_id, trial_run.raise_reason) for trial_run in trial_runs
    ) == [
        ("t1", None),
        ("t2", "timed_out_after_5_seconds"),
        ("t3", None),
        ("t4", None),
        ("t5", None),
        ("t6", None),
    ]
