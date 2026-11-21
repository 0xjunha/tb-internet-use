"""Write a made-up run whose counts the spreadsheet tests know by hand."""

import dataclasses
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestCategory,
    NetworkRequestResultView,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialCategoryMeasureRow,
    TrialRow,
    strongest_measure_bound_of,
)
from tb_internet_use.network_request.model import (
    NetworkRequestCertainty,
    NetworkRequestTargetKind,
    NetworkRequestUncertaintyReason,
    UnknownNetworkRequestTargetReason,
)
from tb_internet_use.network_request_result.model import (
    NetworkRequestResultCertainty,
    NetworkRequestResultLevel,
    NetworkRequestResultStopReason,
)
from tb_internet_use.trial.model import UnreadableTrajectoryReason

LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER
UPPER_ONLY = MeasureBound.UPPER_ONLY
NEITHER = MeasureBound.NEITHER
TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT
HARNESS_PROCESS = NetworkRequestSender.HARNESS_PROCESS
PROVIDER_SERVER = NetworkRequestSender.PROVIDER_SERVER
UNKNOWN_SENDER = NetworkRequestSender.UNKNOWN
PACKAGE = NetworkRequestCategory.PACKAGE
FILE_FETCH = NetworkRequestCategory.FILE_FETCH
PAGE_READ = NetworkRequestCategory.PAGE_READ
SEARCH = NetworkRequestCategory.SEARCH
OTHER_WEB = NetworkRequestCategory.OTHER_WEB
ATTEMPTED = NetworkRequestResultLevel.ATTEMPTED
EXECUTED = NetworkRequestResultLevel.EXECUTED
REACHED = NetworkRequestResultLevel.REACHED
RECEIVED = NetworkRequestResultLevel.RECEIVED
FAILED = NetworkRequestResultStopReason.FAILED
NOT_VISIBLE = NetworkRequestResultStopReason.NOT_VISIBLE


def script_module(name: str) -> ModuleType:
    """Load a module of `scripts/`, registered so that its dataclasses can find it."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[2] / f"scripts/{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _trial_row(
    trial_id: str,
    task: tuple[str, str],
    harness: str,
    reward: float | None,
    request_bound: MeasureBound,
    received_bound: MeasureBound,
    *,
    unreadable: bool = False,
) -> TrialRow:
    return TrialRow(
        trial_id=trial_id,
        benchmark_version=task[0],
        task_name=task[1],
        leaderboard_row_id="row-1",
        harness=harness,
        harness_version="1",
        model_name="model-a",
        reward=reward,
        unreadable_trajectory_reason=UnreadableTrajectoryReason.MISSING
        if unreadable
        else None,
        any_category_request_measure_bound=request_bound,
        any_category_received_measure_bound=received_bound,
    )


def _request_row(
    trial_id: str,
    request_index: int,
    category: NetworkRequestCategory,
    request_bound: MeasureBound,
    received_bound: MeasureBound,
    *,
    sender: NetworkRequestSender = TASK_ENVIRONMENT,
    made_by: str = "pip install",
    target: str = "",
    unknown_target_reason: UnknownNetworkRequestTargetReason | None = None,
    host_names: str = "",
    host_service: str = "",
    package_registry: str = "",
    request_certainty: NetworkRequestCertainty = NetworkRequestCertainty.CONFIRMED,
    request_uncertainty_reason: NetworkRequestUncertaintyReason | None = None,
    level: NetworkRequestResultLevel = ATTEMPTED,
    stop_reason: NetworkRequestResultStopReason | None = NOT_VISIBLE,
) -> NetworkRequestRow:
    """Make a request row with fixed values in the columns no count reads."""
    return NetworkRequestRow(
        trial_id=trial_id,
        trajectory_id="main",
        step_id=1,
        call_index=0,
        request_index=request_index,
        source_kind=NetworkRequestSourceKind.COMMAND
        if sender == TASK_ENVIRONMENT
        else NetworkRequestSourceKind.WEB_TOOL,
        source="command 0",
        made_by=made_by,
        target=target,
        unknown_target_reason=unknown_target_reason,
        target_kind=NetworkRequestTargetKind.URL,
        host_names=host_names,
        received_content_destination="saved",
        request_certainty=request_certainty,
        request_uncertainty_reason=request_uncertainty_reason,
        level=level,
        stop_reason=stop_reason,
        level_certainty=NetworkRequestResultCertainty.CONFIRMED,
        evidence="",
        category=category,
        host_scope="",
        host_service=host_service,
        package_registry=package_registry,
        is_internet_use=True,
        sender=sender,
        result_view=NetworkRequestResultView.RECEIVED
        if stop_reason is None
        else NetworkRequestResultView.NOT_RECEIVED
        if stop_reason == FAILED
        else NetworkRequestResultView.UNKNOWN,
        request_measure_bound=request_bound,
        received_measure_bound=received_bound,
        is_among_success_line_owners_one_of_which_received=False,
    )


TASK_A_3 = ("3-0-0", "terminal-bench/a")
TASK_B_3 = ("3-0-0", "terminal-bench/b")
TASK_A_4 = ("4-0-0", "terminal-bench/a")
# Sorts first by name but last by share, to show which order `Tasks` uses.
TASK_0_4 = ("4-0-0", "terminal-bench/0")

# t1 receives a package, retries it twice with a failure before and after reaching the server, and requests an unknown host and no host name (upper only).
# t2 of Devin passes with no request.
# t3 searches through the provider and installs `Requests`, t1's package in another case.
# t4 passes with an unreadable trajectory.
# t5 fails a clone, installs from a requirements file, reads a page and requests an unknown host.
# t6 runs `npx tsc` twice, which fetches only what is missing (upper only), once failing to reach a server, fetches through the harness and searches and reads with the sender unknown.
# t7 has no reward and no request.
# t8 of Cursor passes with only a search through the provider, as t3.
TRIAL_ROWS = [
    _trial_row("t1", TASK_A_4, "claude-code", 1.0, LOWER_AND_UPPER, LOWER_AND_UPPER),
    _trial_row("t2", TASK_A_4, "devin", 1.0, NEITHER, NEITHER),
    _trial_row("t3", TASK_A_4, "codex", 0.0, LOWER_AND_UPPER, UPPER_ONLY),
    _trial_row(
        "t4", TASK_0_4, "claude-code", 1.0, UPPER_ONLY, UPPER_ONLY, unreadable=True
    ),
    _trial_row("t5", TASK_0_4, "claude-code", 0.9957, LOWER_AND_UPPER, UPPER_ONLY),
    _trial_row("t6", TASK_A_3, "codex", 1.0, UPPER_ONLY, UPPER_ONLY),
    _trial_row("t7", TASK_A_3, "codex", None, NEITHER, NEITHER),
    _trial_row("t8", TASK_B_3, "cursor-cli", 1.0, NEITHER, NEITHER),
]
NETWORK_REQUEST_ROWS = [
    *(
        _request_row(
            "t1",
            request_index,
            PACKAGE,
            LOWER_AND_UPPER,
            UPPER_ONLY,
            target="requests",
            host_service="package_registry",
            package_registry="pypi",
            level=level,
            stop_reason=FAILED,
        )
        for request_index, level in ((3, ATTEMPTED), (4, REACHED))
    ),
    _request_row(
        "t6",
        4,
        PACKAGE,
        UPPER_ONLY,
        UPPER_ONLY,
        made_by="npx",
        unknown_target_reason=UnknownNetworkRequestTargetReason.NAMED_IN_FILE,
        package_registry="npm",
        request_certainty=NetworkRequestCertainty.UNCERTAIN,
        request_uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
        level=EXECUTED,
        stop_reason=FAILED,
    ),
    _request_row(
        "t1",
        0,
        PACKAGE,
        LOWER_AND_UPPER,
        LOWER_AND_UPPER,
        target="requests",
        host_service="package_registry",
        package_registry="pypi",
        level=RECEIVED,
        stop_reason=None,
    ),
    _request_row(
        "t1",
        1,
        OTHER_WEB,
        UPPER_ONLY,
        UPPER_ONLY,
        made_by="curl",
        target="https://a.org/x",
        host_names="a.org",
        host_service="unknown",
    ),
    _request_row(
        "t1", 2, OTHER_WEB, UPPER_ONLY, UPPER_ONLY, made_by="python requests.get"
    ),
    _request_row(
        "t3",
        0,
        SEARCH,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        sender=PROVIDER_SERVER,
        made_by="web_search_call",
        target="how to x",
    ),
    _request_row(
        "t3",
        1,
        PACKAGE,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        target="Requests",
        host_service="package_registry",
        package_registry="pypi",
    ),
    _request_row(
        "t5",
        0,
        FILE_FETCH,
        LOWER_AND_UPPER,
        NEITHER,
        made_by="git clone",
        target="https://github.com/a/b",
        host_names="github.com",
        host_service="code_hosting",
        level=EXECUTED,
        stop_reason=FAILED,
    ),
    _request_row(
        "t5",
        1,
        PACKAGE,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        unknown_target_reason=UnknownNetworkRequestTargetReason.NAMED_IN_FILE,
        host_service="package_registry",
        package_registry="pypi",
        level=EXECUTED,
    ),
    _request_row(
        "t5",
        2,
        PAGE_READ,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        made_by="curl",
        target="https://github.com/a/b/blob/main/README.md",
        host_names="github.com",
        host_service="code_hosting",
        level=REACHED,
    ),
    _request_row(
        "t5",
        3,
        OTHER_WEB,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        made_by="curl",
        target="https://b.org/y",
        host_names="b.org",
        host_service="unknown",
    ),
    _request_row(
        "t6",
        0,
        PACKAGE,
        UPPER_ONLY,
        UPPER_ONLY,
        made_by="npx",
        unknown_target_reason=UnknownNetworkRequestTargetReason.NAMED_IN_FILE,
        package_registry="npm",
        request_certainty=NetworkRequestCertainty.UNCERTAIN,
        request_uncertainty_reason=NetworkRequestUncertaintyReason.FETCHES_ONLY_WHAT_IS_MISSING,
    ),
    _request_row(
        "t6",
        1,
        PAGE_READ,
        UPPER_ONLY,
        UPPER_ONLY,
        sender=HARNESS_PROCESS,
        made_by="web_fetch",
        target="https://docs.a.org/x",
        host_service="code_hosting",
    ),
    _request_row(
        "t6",
        2,
        SEARCH,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        sender=UNKNOWN_SENDER,
        made_by="exec",
        target="how to y",
    ),
    _request_row(
        "t6",
        3,
        PAGE_READ,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        sender=UNKNOWN_SENDER,
        made_by="exec",
        target="https://github.com/c/d",
        host_service="code_hosting",
    ),
    _request_row(
        "t8",
        0,
        SEARCH,
        LOWER_AND_UPPER,
        UPPER_ONLY,
        sender=PROVIDER_SERVER,
        made_by="web_search_call",
        target="how to z",
    ),
]


def _trial_category_measure_rows_of(
    trial_rows: Sequence[TrialRow], network_request_rows: Sequence[NetworkRequestRow]
) -> list[TrialCategoryMeasureRow]:
    """Compute the measure rows of the made-up run as `export_rows` does."""
    groups: dict[tuple[str, str, str], list[NetworkRequestRow]] = {}
    for row in network_request_rows:
        groups.setdefault((row.trial_id, row.category, row.sender), []).append(row)
    measure_rows = [
        TrialCategoryMeasureRow(
            trial_id=trial_id,
            category=NetworkRequestCategory(category),
            sender=NetworkRequestSender(sender),
            request_measure_bound=strongest_measure_bound_of(
                row.request_measure_bound for row in rows
            ),
            received_measure_bound=strongest_measure_bound_of(
                row.received_measure_bound for row in rows
            ),
        )
        for (trial_id, category, sender), rows in groups.items()
    ]
    for trial_row in trial_rows:
        if trial_row.unreadable_trajectory_reason is None:
            continue
        measure_rows.extend(
            TrialCategoryMeasureRow(
                trial_row.trial_id, category, sender, UPPER_ONLY, UPPER_ONLY
            )
            for category in NetworkRequestCategory
            for sender in NetworkRequestSender
            if sender != UNKNOWN_SENDER
        )
    return sorted(measure_rows, key=lambda row: row.trial_id)


# The tasks of version 3-0-0 under new names in version 4-0-0, so that the run holds one version.
_ONE_VERSION_TASK_BY_TASK = {
    TASK_A_3: ("4-0-0", "terminal-bench/c"),
    TASK_B_3: ("4-0-0", "terminal-bench/d"),
}


@pytest.fixture
def made_up_run_dir(tmp_path: Path) -> Path:
    """Write the row files of the made-up run, whose tasks come in two benchmark versions."""
    return _write_made_up_run(tmp_path / "run", TRIAL_ROWS)


@pytest.fixture
def one_version_run_dir(tmp_path: Path) -> Path:
    """Write the row files of the made-up run with the tasks of version 3-0-0 moved into version 4-0-0."""
    trial_rows = []
    for row in TRIAL_ROWS:
        version, task_name = _ONE_VERSION_TASK_BY_TASK.get(
            (row.benchmark_version, row.task_name),
            (row.benchmark_version, row.task_name),
        )
        trial_rows.append(
            dataclasses.replace(row, benchmark_version=version, task_name=task_name)
        )
    return _write_made_up_run(tmp_path / "one_version_run", trial_rows)


def _write_made_up_run(run_dir: Path, trial_rows: Sequence[TrialRow]) -> Path:
    """Write the row files of a run as `run_pipeline.py` does."""
    run_pipeline = script_module("run_pipeline")
    run_dir.mkdir()
    measure_rows = _trial_category_measure_rows_of(trial_rows, NETWORK_REQUEST_ROWS)
    for file_name, rows in (
        ("trial_rows.csv", trial_rows),
        ("network_request_rows.csv", NETWORK_REQUEST_ROWS),
        ("trial_category_measure_rows.csv", measure_rows),
    ):
        run_pipeline.write_csv(
            run_dir / file_name,
            list(type(rows[0]).__dataclass_fields__),
            [run_pipeline.csv_cells_of(row) for row in rows],
        )
    run_pipeline.write_csv(
        run_dir / "task_category_measures.csv",
        run_pipeline.TASK_CATEGORY_MEASURE_COLUMNS,
        run_pipeline.count_task_category_measures(
            trial_rows, NETWORK_REQUEST_ROWS, measure_rows
        ),
    )
    run_pipeline.write_csv(
        run_dir / "summary.csv",
        ("count_name", "count"),
        [("trial_rows", len(trial_rows))],
    )
    run_pipeline.write_csv(
        run_dir / "equations.csv",
        ("equation", "left", "right", "holds"),
        [("request_rows_equal_network_request_results", 17, 17, "yes")],
    )
    return run_dir
