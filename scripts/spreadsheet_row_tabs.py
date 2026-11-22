"""Lay out the row tabs of the spreadsheet of `build_spreadsheet.py`, and give the values and formulas over them that the other tabs share.

The tabs of results count these row tabs with formulas, so they need the row tabs first.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from spreadsheet_cells import (
    CellStyle,
    RowTab,
    TabCell,
    count_ifs_formula,
    count_unique_ifs_formula,
    equal_to,
    not_equal_to,
)
from spreadsheet_python_counts import (
    CountedBound,
    RowFiles,
    SpreadsheetPythonCounts,
    TaskKey,
    csv_dicts_of,
)
from spreadsheet_tabs import (
    EVIDENCE_TAB_COLOR,
    NETWORK_REQUEST_ROWS_TAB_NAME,
    TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME,
    TRIAL_ROWS_TAB_NAME,
)

from tb_internet_use.export.model import (
    MeasureBound,
    NetworkRequestRow,
    NetworkRequestSender,
    NetworkRequestSourceKind,
    TrialCategoryMeasureRow,
    TrialRow,
)

# Joins the benchmark version and the task name in `task_key`, which a run of several versions needs, since a task name can come in several versions.
TASK_KEY_SEPARATOR = " "

TASK_ENVIRONMENT = NetworkRequestSender.TASK_ENVIRONMENT.value
UNKNOWN_SENDER = NetworkRequestSender.UNKNOWN.value
OUTSIDE_SENDERS = tuple(
    sender.value
    for sender in NetworkRequestSender
    if sender != NetworkRequestSender.TASK_ENVIRONMENT
)
KNOWN_OUTSIDE_SENDERS = tuple(
    sender for sender in OUTSIDE_SENDERS if sender != UNKNOWN_SENDER
)
LOWER_AND_UPPER = MeasureBound.LOWER_AND_UPPER.value
UPPER_ONLY = MeasureBound.UPPER_ONLY.value
NEITHER = MeasureBound.NEITHER.value


@dataclass(frozen=True, slots=True)
class ChosenNetworkRequestRows:
    """Rows of `network_request_rows.csv` that the spreadsheet holds, with counts that `Method & checks` shows."""

    rows: list[dict[str, str]]
    file_row_count: int
    left_out_row_count_read_by_formulas: int


def choose_network_request_rows(row_files: RowFiles) -> ChosenNetworkRequestRows:
    """Choose the rows the spreadsheet holds, since all rows would fill most of the cells that Google Sheets allows."""
    rows: list[dict[str, str]] = []
    file_row_count = 0
    left_out_row_count_read_by_formulas = 0
    for row in csv_dicts_of(row_files.network_request_rows, NetworkRequestRow):
        file_row_count += 1
        if (
            row["request_measure_bound"] == LOWER_AND_UPPER
            or row["source_kind"] == NetworkRequestSourceKind.WEB_TOOL
        ):
            rows.append(row)
        elif (
            row["sender"] != TASK_ENVIRONMENT
            and row["request_measure_bound"] != NEITHER
        ):
            left_out_row_count_read_by_formulas += 1
    return ChosenNetworkRequestRows(
        rows, file_row_count, left_out_row_count_read_by_formulas
    )


@dataclass(frozen=True, slots=True)
class SpreadsheetRowTabs:
    """Row tabs that the formulas of the front tabs count."""

    trial_rows: RowTab
    trial_category_measure_rows: RowTab
    network_request_rows: RowTab
    # The column of every row tab that tells one task from another, `task_name` in a run of one benchmark version and `task_key` in a run of several.
    task_column: str

    def all(self) -> list[RowTab]:
        return [
            self.trial_rows,
            self.trial_category_measure_rows,
            self.network_request_rows,
        ]


def lay_out_row_tabs(
    row_files: RowFiles,
    counts: SpreadsheetPythonCounts,
    chosen_rows: ChosenNetworkRequestRows,
) -> SpreadsheetRowTabs:
    """Lay out the three row tabs, each with the columns that name the task of a row.

    A run of several benchmark versions gets a column `task_key` in each, since one column must tell its tasks apart for a count of tasks, and a criterion cannot hold a version alone, e.g. Google Sheets reads `4-1-0` as a date.
    """
    has_task_key = has_several_benchmark_versions(counts)
    return SpreadsheetRowTabs(
        trial_rows=_lay_out_trial_rows_tab(row_files, has_task_key=has_task_key),
        trial_category_measure_rows=_lay_out_trial_category_measure_rows_tab(
            row_files, counts, has_task_key=has_task_key
        ),
        network_request_rows=_lay_out_network_request_rows_tab(
            chosen_rows.rows, counts, has_task_key=has_task_key
        ),
        task_column="task_key" if has_task_key else "task_name",
    )


def has_several_benchmark_versions(counts: SpreadsheetPythonCounts) -> bool:
    """Tell whether the run holds tasks of more than one benchmark version, so that `Tasks` and `Requested items` show the column `benchmark_version` and the row tabs the column `task_key`."""
    return len({task[0] for task in counts.tasks}) > 1


# The last column of `trial_rows`, since few trials have a value in it.
_LAST_TRIAL_ROWS_COLUMN = "unreadable_trajectory_reason"


def _lay_out_trial_rows_tab(row_files: RowFiles, *, has_task_key: bool) -> RowTab:
    """Lay out `trial_rows.csv` with `unreadable_trajectory_reason` as its last column of the file.

    The column `task_name` shows the task name as the tabs of results do, so that a task is found by the same text in every tab.
    """
    field_names = _field_names_of(TrialRow)
    file_columns = (
        *(name for name in field_names if name != _LAST_TRIAL_ROWS_COLUMN),
        _LAST_TRIAL_ROWS_COLUMN,
    )
    rows: list[list[object]] = []
    for row in csv_dicts_of(row_files.trial_rows, TrialRow):
        task = (row["benchmark_version"], row["task_name"])
        cell_by_column = dict(
            zip(field_names, _row_tab_cells_of(row, field_names), strict=True)
        )
        cell_by_column["task_name"] = shown_task_name_of(row["task_name"])
        rows.append(
            [
                *(cell_by_column[column] for column in file_columns),
                *([task_key_of(task)] if has_task_key else []),
            ]
        )
    return RowTab(
        TRIAL_ROWS_TAB_NAME,
        (*file_columns, *(["task_key"] if has_task_key else [])),
        rows,
        tab_color=EVIDENCE_TAB_COLOR,
    )


def _lay_out_trial_category_measure_rows_tab(
    row_files: RowFiles, counts: SpreadsheetPythonCounts, *, has_task_key: bool
) -> RowTab:
    """Lay out `trial_category_measure_rows.csv` with the benchmark version and task name of each trial."""
    field_names = _field_names_of(TrialCategoryMeasureRow)
    rows = [
        [
            *_row_tab_cells_of(row, field_names),
            *_task_cells_of(counts.task_by_trial_id[row["trial_id"]], has_task_key),
        ]
        for row in csv_dicts_of(
            row_files.trial_category_measure_rows, TrialCategoryMeasureRow
        )
    ]
    return RowTab(
        TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME,
        (*field_names, *_task_columns_of(has_task_key)),
        rows,
        tab_color=EVIDENCE_TAB_COLOR,
    )


# The columns of `network_request_rows.csv` that the tab leaves out, which the file of the run folder still holds.
# The first three hold one value in every row of the tab, since it holds confirmed requests of internet use and web tool rows.
# The next three can be read from `stop_reason`, `source` and `host_names`.
# No formula reads the last four, and they need the pipeline to be understood, e.g. the index of a request within its call.
_LEFT_OUT_NETWORK_REQUEST_ROW_COLUMNS = frozenset(
    {
        "request_certainty",
        "request_uncertainty_reason",
        "is_internet_use",
        "result_view",
        "source_kind",
        "host_scope",
        "is_among_success_line_owners_one_of_which_received",
        "level_certainty",
        "received_measure_bound",
        "request_index",
    }
)


def _lay_out_network_request_rows_tab(
    chosen_rows: Sequence[dict[str, str]],
    counts: SpreadsheetPythonCounts,
    *,
    has_task_key: bool,
) -> RowTab:
    """Lay out the chosen rows of `network_request_rows.csv` without the columns of `_LEFT_OUT_NETWORK_REQUEST_ROW_COLUMNS`, with the harness, benchmark version and task name of each trial."""
    field_names = tuple(
        name
        for name in _field_names_of(NetworkRequestRow)
        if name not in _LEFT_OUT_NETWORK_REQUEST_ROW_COLUMNS
    )
    rows = [
        [
            *_row_tab_cells_of(row, field_names),
            counts.harness_by_trial_id[row["trial_id"]],
            *_task_cells_of(counts.task_by_trial_id[row["trial_id"]], has_task_key),
        ]
        for row in chosen_rows
    ]
    return RowTab(
        NETWORK_REQUEST_ROWS_TAB_NAME,
        (*field_names, "harness", *_task_columns_of(has_task_key)),
        rows,
        header_note=(
            "Only the rows of network_request_rows.csv whose request_measure_bound is lower_and_upper, "
            "and the rows whose source_kind is web_tool, without the columns that hold one value here or that no number of this file reads. "
            "The other rows and columns are in network_request_rows.csv of the run folder this file was built from."
        ),
        tab_color=EVIDENCE_TAB_COLOR,
    )


def _task_columns_of(has_task_key: bool) -> tuple[str, ...]:
    """Give the columns that name the task of a row in a row tab joined with `trial_rows`."""
    return ("benchmark_version", "task_name", *(["task_key"] if has_task_key else []))


def _task_cells_of(task: TaskKey, has_task_key: bool) -> list[object]:
    """Give the cells of `_task_columns_of` for a task, its name as the tabs of results show it."""
    return [
        task[0],
        shown_task_name_of(task[1]),
        *([task_key_of(task)] if has_task_key else []),
    ]


def task_key_of(task: TaskKey) -> str:
    """Give the `task_key` of a task, e.g. `4-1-0 atrx-vep-crispr` for the task `terminal-bench/atrx-vep-crispr` of version `4-1-0`."""
    return f"{task[0]}{TASK_KEY_SEPARATOR}{shown_task_name_of(task[1])}"


def shown_task_name_of(task_name: str) -> str:
    """Give the task name that the tabs of results show, without the part up to its first `/`, e.g. `atrx-vep-crispr` for `terminal-bench/atrx-vep-crispr`."""
    return task_name.partition("/")[2] or task_name


# Written as numbers so that formulas can compare them.
_NUMBER_COLUMNS = {"step_id", "call_index", "request_index", "reward"}


def _row_tab_cells_of(row: dict[str, str], field_names: Sequence[str]) -> list[object]:
    """Give the cells of the named fields of one row of a row file."""
    return [
        _number_or_none_of(row[name])
        if name in _NUMBER_COLUMNS
        else (row[name] or None)
        for name in field_names
    ]


def _number_or_none_of(text: str) -> float | int | None:
    if not text:
        return None
    number = float(text)
    return int(number) if number.is_integer() and "." not in text else number


def _field_names_of(
    row_type: type[TrialRow | TrialCategoryMeasureRow | NetworkRequestRow],
) -> tuple[str, ...]:
    return tuple(row_field.name for row_field in dataclasses.fields(row_type))


def header_cells_of(*texts: str) -> list[TabCell]:
    return [TabCell(text, style=CellStyle.HEADER) for text in texts]


def trial_count_formula_of(row_tabs: SpreadsheetRowTabs) -> str:
    """Give the formula of the number of trials, which every share of trials divides by."""
    return f"COUNTA({row_tabs.trial_rows.column_range('trial_id')})"


def request_trial_count_formula_of(
    row_tabs: SpreadsheetRowTabs,
    counted_bound: CountedBound,
    *,
    task_criterion: str | None = None,
) -> str:
    """Give the `COUNTIFS` of the trials with a request from the task environment in a bound, of all tasks or of the task whose criterion for `SpreadsheetRowTabs.task_column` is given."""
    return count_ifs_formula(
        row_tabs.trial_rows,
        [
            *(
                [(row_tabs.task_column, task_criterion)]
                if task_criterion is not None
                else []
            ),
            (
                "any_category_request_measure_bound",
                equal_to(LOWER_AND_UPPER)
                if counted_bound == CountedBound.LOWER
                else not_equal_to(NEITHER),
            ),
        ],
    )


def web_tool_trial_count_formula_of(
    row_tabs: SpreadsheetRowTabs,
    counted_bound: CountedBound,
    *,
    task_criterion: str | None = None,
) -> str:
    """Give the `COUNTUNIQUEIFS` of the trials with a web tool request sent from outside the task environment in a bound, of all tasks or of one.

    The lower bound counts requests in the lower bound from a known sender outside the task environment. The upper bound also counts those in the upper bound alone and those of sender `unknown`, e.g. a web tool of a harness that does not say where it runs, and the rows that an unreadable trajectory gives.
    """
    sender_conditions = (
        [
            ("sender", not_equal_to(TASK_ENVIRONMENT)),
            ("sender", not_equal_to(UNKNOWN_SENDER)),
            ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
        ]
        if counted_bound == CountedBound.LOWER
        else [
            ("sender", not_equal_to(TASK_ENVIRONMENT)),
            ("request_measure_bound", not_equal_to(NEITHER)),
        ]
    )
    return count_unique_ifs_formula(
        row_tabs.trial_category_measure_rows,
        "trial_id",
        [
            *(
                [(row_tabs.task_column, task_criterion)]
                if task_criterion is not None
                else []
            ),
            *sender_conditions,
        ],
    )
