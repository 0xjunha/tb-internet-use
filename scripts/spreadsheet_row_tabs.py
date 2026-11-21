"""Lay out the row tabs of the spreadsheet of `build_spreadsheet.py`, and give the values and formulas over them that the other tabs share.

The tabs of results count these row tabs with formulas, so they need the row tabs first.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from openpyxl.utils import get_column_letter
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

# Joins the benchmark version and the task name in `task_key`, since a task name can come in several versions.
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
    """Lay out the three row tabs."""
    return SpreadsheetRowTabs(
        trial_rows=_lay_out_trial_rows_tab(row_files),
        trial_category_measure_rows=_lay_out_trial_category_measure_rows_tab(
            row_files, counts
        ),
        network_request_rows=_lay_out_network_request_rows_tab(
            chosen_rows.rows, counts
        ),
    )


def _lay_out_trial_rows_tab(row_files: RowFiles) -> RowTab:
    """Lay out `trial_rows.csv` with a column `task_key`, which the other tabs count tasks by."""
    columns = (*_field_names_of(TrialRow), "task_key")
    version_letter = get_column_letter(columns.index("benchmark_version") + 1)
    task_letter = get_column_letter(columns.index("task_name") + 1)
    rows: list[list[object]] = []
    for row_number, row in enumerate(
        csv_dicts_of(row_files.trial_rows, TrialRow), start=2
    ):
        rows.append(
            [
                *_row_tab_cells_of(row, TrialRow),
                TabCell(
                    task_key_of((row["benchmark_version"], row["task_name"])),
                    formula=f'{version_letter}{row_number}&"{TASK_KEY_SEPARATOR}"&{task_letter}{row_number}',
                ),
            ]
        )
    return RowTab(TRIAL_ROWS_TAB_NAME, columns, rows, tab_color=EVIDENCE_TAB_COLOR)


def _lay_out_trial_category_measure_rows_tab(
    row_files: RowFiles, counts: SpreadsheetPythonCounts
) -> RowTab:
    """Lay out `trial_category_measure_rows.csv` with columns from `trial_rows.csv`.

    The column `trial_rows.any_category_request_measure_bound` lets a count keep the rows of trials in the lower bound, e.g. the trials of the lower bound that also have a row of a category other than `package`.
    """
    trial_rows_by_trial_id = {
        row["trial_id"]: row for row in csv_dicts_of(row_files.trial_rows, TrialRow)
    }
    rows = [
        [
            *_row_tab_cells_of(row, TrialCategoryMeasureRow),
            task_key_of(counts.task_by_trial_id[row["trial_id"]]),
            counts.harness_by_trial_id[row["trial_id"]],
            _number_or_none_of(trial_rows_by_trial_id[row["trial_id"]]["reward"]),
            trial_rows_by_trial_id[row["trial_id"]][
                "any_category_request_measure_bound"
            ],
        ]
        for row in csv_dicts_of(
            row_files.trial_category_measure_rows, TrialCategoryMeasureRow
        )
    ]
    return RowTab(
        TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME,
        (
            *_field_names_of(TrialCategoryMeasureRow),
            "trial_rows.task_key",
            "trial_rows.harness",
            "trial_rows.reward",
            "trial_rows.any_category_request_measure_bound",
        ),
        rows,
        tab_color=EVIDENCE_TAB_COLOR,
    )


def _lay_out_network_request_rows_tab(
    chosen_rows: Sequence[dict[str, str]], counts: SpreadsheetPythonCounts
) -> RowTab:
    """Lay out the chosen rows of `network_request_rows.csv` with columns from `trial_rows.csv`."""
    rows = [
        [
            *_row_tab_cells_of(row, NetworkRequestRow),
            task_key_of(counts.task_by_trial_id[row["trial_id"]]),
            counts.harness_by_trial_id[row["trial_id"]],
        ]
        for row in chosen_rows
    ]
    return RowTab(
        NETWORK_REQUEST_ROWS_TAB_NAME,
        (
            *_field_names_of(NetworkRequestRow),
            "trial_rows.task_key",
            "trial_rows.harness",
        ),
        rows,
        header_note=(
            "Only the rows of network_request_rows.csv whose request_measure_bound is lower_and_upper, "
            "and the rows whose source_kind is web_tool. The other rows are in network_request_rows.csv of the run folder this file was built from."
        ),
        tab_color=EVIDENCE_TAB_COLOR,
    )


def task_key_of(task: TaskKey) -> str:
    """Give the `task_key` of a task, e.g. `4-0-0 terminal-bench/a`."""
    return f"{task[0]}{TASK_KEY_SEPARATOR}{task[1]}"


# Written as numbers so that formulas can compare them.
_NUMBER_COLUMNS = {"step_id", "call_index", "request_index", "reward"}


def _row_tab_cells_of(
    row: dict[str, str],
    row_type: type[TrialRow | TrialCategoryMeasureRow | NetworkRequestRow],
) -> list[object]:
    """Give the cells of one row of a row file."""
    return [
        _number_or_none_of(row[name])
        if name in _NUMBER_COLUMNS
        else (row[name] or None)
        for name in _field_names_of(row_type)
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
    task_key: str | None = None,
) -> str:
    """Give the `COUNTIFS` of the trials with a request from the task environment in a bound, of all tasks or of the task whose `task_key` criterion is given."""
    return count_ifs_formula(
        row_tabs.trial_rows,
        [
            *([("task_key", task_key)] if task_key is not None else []),
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
    task_key: str | None = None,
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
            *([("trial_rows.task_key", task_key)] if task_key is not None else []),
            *sender_conditions,
        ],
    )
