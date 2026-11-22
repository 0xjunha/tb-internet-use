"""Lay out the tabs of results of the spreadsheet of `build_spreadsheet.py`, one per question that `Overview` lists.

Each tab opens with its title and the question it answers, then one table, except `Bounds`, which holds two.
"""

from collections import Counter
from dataclasses import dataclass

from openpyxl.utils import get_column_letter
from spreadsheet_cells import (
    EMPTY_CELL,
    CellStyle,
    TabCell,
    TabGrid,
    count_ifs_formula,
    count_unique_ifs_formula,
    equal_to,
    equal_to_formula_value,
    equal_to_number,
    formula_text_of,
    not_equal_to,
    refuse_keys_equal_apart_from_case,
    sparkline_bar_formula,
)
from spreadsheet_python_counts import (
    PASSED_REWARD,
    BestRequestResult,
    CountedBound,
    MainMeasure,
    RegistryOrHostServiceLineKey,
    SolvedWithoutRequestVerdict,
    SpreadsheetPythonCounts,
    TaskKey,
    UpperBoundOnlyCause,
    WebToolLineKey,
    registry_or_host_service_column_of,
)
from spreadsheet_row_tabs import (
    KNOWN_OUTSIDE_SENDERS,
    LOWER_AND_UPPER,
    NEITHER,
    OUTSIDE_SENDERS,
    TASK_ENVIRONMENT,
    TASK_KEY_SEPARATOR,
    UNKNOWN_SENDER,
    UPPER_ONLY,
    SpreadsheetRowTabs,
    header_cells_of,
    request_trial_count_formula_of,
    shown_task_name_of,
    task_key_of,
    trial_count_formula_of,
    web_tool_trial_count_formula_of,
)
from spreadsheet_tabs import (
    BOUNDS_TAB_NAME,
    REQUESTED_ITEMS_TAB_NAME,
    RESULTS_TAB_COLOR,
    TASKS_TAB_NAME,
    WEB_TOOLS_TAB_NAME,
)

from tb_internet_use.export.model import NetworkRequestCategory

# The examples of a cause in `Bounds`.
_EXAMPLE_COUNT = 3


def _add_title_and_question(grid: TabGrid, question: str, last_column: int) -> None:
    """Add the title of a tab in row 1 and the question it answers in row 2."""
    grid.add_row(TabCell(grid.name, style=CellStyle.TITLE))
    grid.add_note(question, last_column)


def _share_cell(
    count_formula: str, count: int, trials_cell: str, trial_count: int
) -> TabCell:
    return TabCell(
        count / trial_count,
        formula=f"{count_formula}/{trials_cell}",
        style=CellStyle.SHARE,
    )


@dataclass(frozen=True, slots=True)
class TasksColumns:
    """Columns of `Tasks`, 1-based, which depend on whether the column `benchmark_version` is shown and on the categories that have a column."""

    shows_benchmark_version: bool
    categories: tuple[str, ...]

    @property
    def task_name(self) -> int:
        return 2 if self.shows_benchmark_version else 1

    @property
    def trials(self) -> int:
        return self.task_name + 1

    @property
    def request(self) -> int:
        return self.task_name + 2

    @property
    def bar(self) -> int:
        return self.task_name + 3

    @property
    def request_upper_bound(self) -> int:
        return self.task_name + 4

    @property
    def column_by_category(self) -> dict[str, int]:
        return {
            category: self.task_name + 5 + index
            for index, category in enumerate(self.categories)
        }

    @property
    def web_tool(self) -> int:
        return self.task_name + 5 + len(self.categories)

    @property
    def passed(self) -> int:
        return self.web_tool + 1

    @property
    def passed_without_request(self) -> int:
        return self.web_tool + 2

    @property
    def verdict(self) -> int:
        return self.web_tool + 3

    @property
    def bar_lower_bound(self) -> int:
        """Give the first of two hidden columns that the bar draws, the lower bound and the rest of the upper bound."""
        return self.web_tool + 4


@dataclass(frozen=True, slots=True)
class TasksTab:
    """`Tasks` tab with the columns that `Overview`, `Chart data` and `Method & checks` read."""

    grid: TabGrid
    first_line_row: int
    last_line_row: int
    columns: TasksColumns

    def column_range(self, column: int) -> str:
        return self.grid.range_of(column, self.first_line_row, self.last_line_row)


def lay_out_tasks_tab(
    counts: SpreadsheetPythonCounts, row_tabs: SpreadsheetRowTabs
) -> TasksTab:
    """Lay out one line per task, with its shares of trials with a request and whether it was solved without one.

    The column `benchmark_version` comes first only when the run holds several versions, since with one it would repeat the same text on every line.
    """
    grid = TabGrid(TASKS_TAB_NAME, tab_color=RESULTS_TAB_COLOR)
    columns = TasksColumns(
        _has_several_benchmark_versions(counts),
        tuple(
            category.value
            for category in NetworkRequestCategory
            if counts.request_trial_ids.get(
                (category.value, TASK_ENVIRONMENT, CountedBound.LOWER)
            )
        ),
    )
    # The question wraps within the frozen columns, so that it stays whole while the others scroll.
    _add_title_and_question(
        grid,
        "Which tasks send internet requests from the task environment, and were they solved without one?",
        columns.task_name,
    )
    header_row = grid.add_row(
        *header_cells_of(
            *(["benchmark_version"] if columns.shows_benchmark_version else []),
            "task_name",
            "Trials",
            "Request, lower bound",
            "Request bounds",
            "Request, upper bound",
            *columns.categories,
            "Web tool from outside",
            "Reward=1",
            "Reward=1 without a request",
            "Solved without a request?",
            "Bar, lower bound",
            "Bar, upper bound only",
        )
    )
    any_lower_ids = counts.any_category_trial_ids[
        MainMeasure.REQUEST, CountedBound.LOWER
    ]

    def sort_key_of(task: TaskKey) -> tuple[str, float, str]:
        return (task[0], -counts.task_share_of(task, any_lower_ids), task[1])

    for task in sorted(counts.tasks, key=sort_key_of):
        cells = _tasks_line_cells_of(counts, row_tabs, columns, task, grid.next_row)
        grid.add_row(
            *(cells.get(column, EMPTY_CELL) for column in range(1, max(cells) + 1))
        )
    first_line_row = header_row + 1
    last_line_row = grid.next_row - 1
    grid.frozen_cell = f"{get_column_letter(columns.trials)}{first_line_row}"
    grid.filter_range = (
        f"A{header_row}:{get_column_letter(columns.verdict)}{last_line_row}"
    )
    grid.hidden_columns = {columns.bar_lower_bound, columns.bar_lower_bound + 1}
    grid.fixed_column_widths = {columns.bar: 16}
    grid.share_color_scale_ranges = [
        f"{get_column_letter(first)}{first_line_row}:{get_column_letter(last)}{last_line_row}"
        for first, last in (
            (columns.request, columns.request),
            (columns.request_upper_bound, columns.web_tool),
        )
    ]
    return TasksTab(grid, first_line_row, last_line_row, columns)


def _tasks_line_cells_of(
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    columns: TasksColumns,
    task: TaskKey,
    row: int,
) -> dict[int, TabCell]:
    """Give the cells of the line of one task by 1-based column."""
    trial_rows = row_tabs.trial_rows
    measure_rows = row_tabs.trial_category_measure_rows
    trial_ids = counts.trial_ids_of_task(task)
    task_name_cell = f"${get_column_letter(columns.task_name)}{row}"
    # Without the column `benchmark_version`, the one version of the run stands in the formula.
    version_formula = (
        f"$A{row}" if columns.shows_benchmark_version else formula_text_of(task[0])
    )
    task_key = equal_to_formula_value(
        f'{version_formula}&"{TASK_KEY_SEPARATOR}"&{task_name_cell}',
        task_key_of(task),
    )
    trials_cell = f"${get_column_letter(columns.trials)}{row}"
    trial_count = len(trial_ids)

    def share(count_formula: str, counted_ids: set[str]) -> TabCell:
        return _share_cell(
            count_formula, len(trial_ids & counted_ids), trials_cell, trial_count
        )

    task_trial_conditions = [("task_key", task_key)]
    task_measure_conditions = [("trial_rows.task_key", task_key)]
    cells: dict[int, TabCell] = {
        columns.task_name: TabCell(shown_task_name_of(task[1])),
        columns.trials: TabCell(
            trial_count,
            formula=count_ifs_formula(trial_rows, task_trial_conditions),
            style=CellStyle.COUNT,
        ),
        columns.request: share(
            request_trial_count_formula_of(
                row_tabs, CountedBound.LOWER, task_key=task_key
            ),
            counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER],
        ),
        columns.request_upper_bound: share(
            request_trial_count_formula_of(
                row_tabs, CountedBound.UPPER, task_key=task_key
            ),
            counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.UPPER],
        ),
        columns.web_tool: share(
            web_tool_trial_count_formula_of(
                row_tabs, CountedBound.LOWER, task_key=task_key
            ),
            counts.request_trial_ids_of(
                CountedBound.LOWER, senders=KNOWN_OUTSIDE_SENDERS
            ),
        ),
    }
    if columns.shows_benchmark_version:
        cells[1] = TabCell(task[0])
    for category, column in columns.column_by_category.items():
        cells[column] = share(
            count_ifs_formula(
                measure_rows,
                [
                    *task_measure_conditions,
                    ("category", equal_to(category)),
                    ("sender", equal_to(TASK_ENVIRONMENT)),
                    ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
                ],
            ),
            counts.request_trial_ids_of(
                CountedBound.LOWER, categories=[category], senders=[TASK_ENVIRONMENT]
            ),
        )
    bar_lower_column = columns.bar_lower_bound
    request_letter = get_column_letter(columns.request)
    upper_letter = get_column_letter(columns.request_upper_bound)
    lower_share = cells[columns.request].value
    upper_share = cells[columns.request_upper_bound].value
    assert isinstance(lower_share, float) and isinstance(upper_share, float)
    cells[columns.bar] = TabCell(
        None,
        formula=sparkline_bar_formula(
            f"{get_column_letter(bar_lower_column)}{row}:{get_column_letter(bar_lower_column + 1)}{row}"
        ),
        style=CellStyle.BAR,
    )
    cells[bar_lower_column] = TabCell(
        lower_share, formula=f"{request_letter}{row}", style=CellStyle.SHARE
    )
    cells[bar_lower_column + 1] = TabCell(
        upper_share - lower_share,
        formula=f"{upper_letter}{row}-{request_letter}{row}",
        style=CellStyle.SHARE,
    )

    passed_counts = counts.passed_trial_counts_of(task)
    passed_conditions = [
        *task_trial_conditions,
        ("reward", equal_to_number(PASSED_REWARD)),
    ]
    cells[columns.passed] = TabCell(
        passed_counts.passed_trial_count,
        formula=count_ifs_formula(trial_rows, passed_conditions),
        style=CellStyle.COUNT,
    )
    cells[columns.passed_without_request] = TabCell(
        passed_counts.without_request_trial_count,
        formula=count_ifs_formula(
            trial_rows,
            [
                *passed_conditions,
                ("any_category_request_measure_bound", equal_to(NEITHER)),
            ],
        ),
        style=CellStyle.COUNT,
    )
    passed_upper_bound_only_formula = count_ifs_formula(
        trial_rows,
        [
            *passed_conditions,
            ("any_category_request_measure_bound", equal_to(UPPER_ONLY)),
        ],
    )
    verdict = SolvedWithoutRequestVerdict
    passed_cell = f"{get_column_letter(columns.passed)}{row}"
    passed_without_cell = f"{get_column_letter(columns.passed_without_request)}{row}"
    cells[columns.verdict] = TabCell(
        passed_counts.verdict.value,
        formula=(
            f'IF({passed_cell}=0,"{verdict.NEVER_SOLVED}",'
            f'IF({passed_without_cell}>0,"{verdict.YES}",'
            f'IF({passed_upper_bound_only_formula}>0,"{verdict.MAYBE}",'
            f'"{verdict.NO}")))'
        ),
    )
    return cells


_CATEGORY_ORDER = {
    category.value: index for index, category in enumerate(NetworkRequestCategory)
}


def registry_or_host_service_label_of(line_key: RegistryOrHostServiceLineKey) -> str:
    """Give the shown registry or host service of a line, a word in parentheses when the row leaves it blank."""
    if line_key.registry_or_host_service:
        return line_key.registry_or_host_service
    if registry_or_host_service_column_of(line_key.category) == "host_service":
        return "(no host name)"
    return "(no registry)"


@dataclass(frozen=True, slots=True)
class TrialCountLinesTab:
    """Front tab of one line per key with a count of trials, whose lines `Method & checks` holds against the count of their category or sender."""

    grid: TabGrid
    first_line_row: int
    last_line_row: int
    # 1-based, the category in `Requested items`, the sender in `Web tools`.
    category_or_sender_column: int
    trials_column: int

    def column_range(self, column: int) -> str:
        return self.grid.range_of(column, self.first_line_row, self.last_line_row)


@dataclass(frozen=True, slots=True)
class _RequestedItemsColumns:
    """Columns of `Requested items`, 1-based, which depend on whether the column `benchmark_version` is shown."""

    shows_benchmark_version: bool

    @property
    def task_name(self) -> int:
        return 2 if self.shows_benchmark_version else 1

    @property
    def category(self) -> int:
        return self.task_name + 1

    @property
    def registry_or_host_service(self) -> int:
        return self.task_name + 2

    @property
    def trials(self) -> int:
        return self.task_name + 4

    @property
    def share(self) -> int:
        return self.task_name + 5

    @property
    def last(self) -> int:
        return self.task_name + 6


@dataclass(frozen=True, slots=True)
class RequestedItemsTab:
    """`Requested items` tab with the columns that `Method & checks` reads."""

    lines_tab: TrialCountLinesTab
    registry_or_host_service_column: int


def lay_out_requested_items_tab(counts: SpreadsheetPythonCounts) -> RequestedItemsTab:
    """Lay out one line per task and item that its lower-bound requests from the task environment asked for, counted by Python.

    About four thousand lines of `COUNTUNIQUEIFS` over the request rows would make Google Sheets slow, so the counts are plain numbers, and `Method & checks` holds the trials of each category against `Chart data`.
    The column `benchmark_version` comes first only when the run holds several versions, as in `Tasks`.
    """
    grid = TabGrid(REQUESTED_ITEMS_TAB_NAME, tab_color=RESULTS_TAB_COLOR)
    columns = _RequestedItemsColumns(_has_several_benchmark_versions(counts))
    _add_title_and_question(
        grid,
        "Packages and hosts that the trials of each task requested from the task environment.",
        columns.last,
    )
    header_row = grid.add_row(
        *header_cells_of(
            *(["benchmark_version"] if columns.shows_benchmark_version else []),
            "task_name",
            "Category",
            "Registry or host service",
            "Item",
            "Trials",
            "% of the task's trials",
            "Tasks that requested it",
        )
    )
    task_counts = Counter(
        (key.registry_or_host_service_line_key, key.requested_item)
        for key in counts.requested_item_trial_ids
    )
    line_keys = sorted(
        counts.requested_item_trial_ids,
        key=lambda key: (
            key.task,
            -len(counts.requested_item_trial_ids[key]),
            _CATEGORY_ORDER[key.registry_or_host_service_line_key.category],
            key.registry_or_host_service_line_key.registry_or_host_service,
            key.requested_item,
        ),
    )
    for key in line_keys:
        trial_count = len(counts.requested_item_trial_ids[key])
        line_key = key.registry_or_host_service_line_key
        grid.add_row(
            *([TabCell(key.task[0])] if columns.shows_benchmark_version else []),
            TabCell(shown_task_name_of(key.task[1])),
            TabCell(line_key.category),
            TabCell(registry_or_host_service_label_of(line_key)),
            TabCell(key.requested_item),
            TabCell(trial_count, style=CellStyle.COUNT),
            TabCell(
                trial_count / len(counts.trial_ids_of_task(key.task)),
                style=CellStyle.SHARE,
            ),
            TabCell(task_counts[line_key, key.requested_item], style=CellStyle.COUNT),
        )
    first_line_row = header_row + 1
    last_line_row = max(grid.next_row - 1, first_line_row)
    grid.frozen_cell = f"A{first_line_row}"
    grid.filter_range = (
        f"A{header_row}:{get_column_letter(columns.last)}{last_line_row}"
    )
    share_letter = get_column_letter(columns.share)
    grid.share_color_scale_ranges = [
        f"{share_letter}{first_line_row}:{share_letter}{last_line_row}"
    ]
    return RequestedItemsTab(
        TrialCountLinesTab(
            grid,
            first_line_row,
            last_line_row,
            category_or_sender_column=columns.category,
            trials_column=columns.trials,
        ),
        registry_or_host_service_column=columns.registry_or_host_service,
    )


def _has_several_benchmark_versions(counts: SpreadsheetPythonCounts) -> bool:
    """Tell whether the run holds tasks of more than one benchmark version, so that `Tasks` and `Requested items` show the column `benchmark_version`."""
    return len({task[0] for task in counts.tasks}) > 1


# 1-based columns of `Web tools`.
_WEB_TOOLS_SENDER_COLUMN = 3
_WEB_TOOLS_TRIALS_COLUMN = 5
_WEB_TOOLS_LAST_COLUMN = 7


def lay_out_web_tools_tab(
    counts: SpreadsheetPythonCounts, row_tabs: SpreadsheetRowTabs
) -> TrialCountLinesTab:
    """Lay out one line per harness, tool, sender and category of requests that do not leave from the task environment.

    A line of a known sender counts the lower bound. A line of sender `unknown` counts the upper bound, since such a tool is in no lower bound.
    """
    grid = TabGrid(WEB_TOOLS_TAB_NAME, tab_color=RESULTS_TAB_COLOR)
    _add_title_and_question(
        grid,
        "Which web tools send requests that turning off the network of the task environment does not block? For sender unknown it is not known where the tool runs, so its lines count the upper bound.",
        _WEB_TOOLS_LAST_COLUMN,
    )
    header_row = grid.add_row(
        *header_cells_of(
            "Harness", "Tool", "Sender", "Category", "Trials", "Tasks", "Requests"
        )
    )
    request_rows = row_tabs.network_request_rows
    sender_order = {sender: index for index, sender in enumerate(OUTSIDE_SENDERS)}

    def shown_trial_ids_of(key: WebToolLineKey) -> set[str]:
        line = counts.web_tool_lines[key]
        return (
            line.upper_trial_ids
            if key.sender == UNKNOWN_SENDER
            else line.lower_trial_ids
        )

    line_keys = sorted(
        (key for key in counts.web_tool_lines if shown_trial_ids_of(key)),
        key=lambda key: (
            sender_order[key.sender],
            key.harness,
            -len(shown_trial_ids_of(key)),
            key.made_by,
            key.category,
        ),
    )
    refuse_keys_equal_apart_from_case(
        [(key.harness, key.made_by, key.sender, key.category) for key in line_keys]
    )
    for key in line_keys:
        line = counts.web_tool_lines[key]
        is_upper_bound = key.sender == UNKNOWN_SENDER
        conditions = [
            ("trial_rows.harness", equal_to(key.harness)),
            ("made_by", equal_to(key.made_by)),
            ("sender", equal_to(key.sender)),
            ("category", equal_to(key.category)),
            (
                "request_measure_bound",
                not_equal_to(NEITHER) if is_upper_bound else equal_to(LOWER_AND_UPPER),
            ),
        ]
        trial_ids = shown_trial_ids_of(key)
        grid.add_row(
            TabCell(key.harness),
            TabCell(key.made_by),
            TabCell(key.sender),
            TabCell(key.category),
            TabCell(
                len(trial_ids),
                formula=count_unique_ifs_formula(request_rows, "trial_id", conditions),
                style=CellStyle.COUNT,
            ),
            TabCell(
                len(counts.tasks_of(trial_ids)),
                formula=count_unique_ifs_formula(
                    request_rows, "trial_rows.task_key", conditions
                ),
                style=CellStyle.COUNT,
            ),
            TabCell(
                line.upper_row_count if is_upper_bound else line.lower_row_count,
                formula=count_ifs_formula(request_rows, conditions),
                style=CellStyle.COUNT,
            ),
        )
    first_line_row = header_row + 1
    grid.frozen_cell = f"A{first_line_row}"
    return TrialCountLinesTab(
        grid,
        first_line_row,
        max(grid.next_row - 1, first_line_row),
        category_or_sender_column=_WEB_TOOLS_SENDER_COLUMN,
        trials_column=_WEB_TOOLS_TRIALS_COLUMN,
    )


@dataclass(frozen=True, slots=True)
class BoundsTab:
    """`Bounds` tab with the cells that `Method & checks` holds against the bounds."""

    grid: TabGrid
    cause_total_cell: str
    first_result_row: int
    last_result_row: int
    trials_column: int

    def result_trials_range(self) -> str:
        return self.grid.range_of(
            self.trials_column, self.first_result_row, self.last_result_row
        )


# 1-based columns of `Bounds`.
_BOUNDS_TRIALS_COLUMN = 3
_BOUNDS_LAST_COLUMN = 5
# Wide enough for the longest cause on one line.
_BOUNDS_CAUSE_COLUMN_WIDTH = 90


def lay_out_bounds_tab(
    counts: SpreadsheetPythonCounts, row_tabs: SpreadsheetRowTabs
) -> BoundsTab:
    """Lay out the trials only in the upper bound by cause, and the trials of the lower bound by how far their requests got."""
    grid = TabGrid(BOUNDS_TAB_NAME, tab_color=RESULTS_TAB_COLOR)
    _add_title_and_question(
        grid,
        "Why is the upper bound higher than the lower bound, and how far did the requests of the lower bound get?",
        _BOUNDS_LAST_COLUMN,
    )
    trial_count = len(counts.task_by_trial_id)
    trial_count_formula = trial_count_formula_of(row_tabs)
    grid.add_row()
    grid.add_row(
        TabCell(
            "Trials only in the upper bound, each by the first cause that matches",
            style=CellStyle.SECTION,
        )
    )
    grid.add_row(*header_cells_of("Cause", "Example", "Trials", "", "% of trials"))
    cause_counts = Counter(counts.upper_bound_only_cause_by_trial_id.values())
    first_cause_row = grid.next_row
    last_cause_row = first_cause_row + len(UpperBoundOnlyCause) - 1
    for cause in UpperBoundOnlyCause:
        examples = counts.example_counts_by_upper_bound_only_cause.get(cause, Counter())
        grid.add_row(
            TabCell(cause.value),
            TabCell(
                ", ".join(
                    example for example, _ in examples.most_common(_EXAMPLE_COUNT)
                )
                or None
            ),
            TabCell(cause_counts[cause], style=CellStyle.PYTHON_COUNT),
            _bounds_bar_cell(grid.next_row, first_cause_row, last_cause_row),
            TabCell(cause_counts[cause] / trial_count, style=CellStyle.PYTHON_SHARE),
        )
    cause_total = sum(cause_counts.values())
    trials_letter = get_column_letter(_BOUNDS_TRIALS_COLUMN)
    total_row = grid.add_row(
        TabCell("Total"),
        EMPTY_CELL,
        # A sum, so that the check of the total against the upper bound also holds each cause.
        TabCell(
            cause_total,
            formula=f"SUM({trials_letter}{first_cause_row}:{trials_letter}{last_cause_row})",
            style=CellStyle.COUNT,
        ),
        EMPTY_CELL,
        TabCell(cause_total / trial_count, style=CellStyle.PYTHON_SHARE),
    )
    grid.add_row()
    grid.add_row(
        TabCell(
            "Trials of the lower bound, by the furthest that one of their requests got",
            style=CellStyle.SECTION,
        )
    )
    grid.add_row(*header_cells_of("Result", "", "Trials", "", "% of trials"))
    result_counts = Counter(counts.best_request_result_by_trial_id.values())
    first_result_row = grid.next_row
    last_result_row = first_result_row + len(BestRequestResult) - 1
    for result in BestRequestResult:
        if result == BestRequestResult.RECEIVED:
            received_formula = count_ifs_formula(
                row_tabs.trial_rows,
                [("any_category_received_measure_bound", equal_to(LOWER_AND_UPPER))],
            )
            trials_cell = TabCell(
                result_counts[result],
                formula=received_formula,
                style=CellStyle.COUNT,
            )
            share_cell = _share_cell(
                received_formula,
                result_counts[result],
                f"{trial_count_formula}",
                trial_count,
            )
        else:
            trials_cell = TabCell(result_counts[result], style=CellStyle.PYTHON_COUNT)
            share_cell = TabCell(
                result_counts[result] / trial_count, style=CellStyle.PYTHON_SHARE
            )
        grid.add_row(
            TabCell(result.value),
            EMPTY_CELL,
            trials_cell,
            _bounds_bar_cell(grid.next_row, first_result_row, last_result_row),
            share_cell,
        )
    grid.fixed_column_widths = {
        1: _BOUNDS_CAUSE_COLUMN_WIDTH,
        _BOUNDS_TRIALS_COLUMN + 1: 16,
    }
    return BoundsTab(
        grid,
        cause_total_cell=f"{get_column_letter(_BOUNDS_TRIALS_COLUMN)}{total_row}",
        first_result_row=first_result_row,
        last_result_row=last_result_row,
        trials_column=_BOUNDS_TRIALS_COLUMN,
    )


def _bounds_bar_cell(row: int, first_row: int, last_row: int) -> TabCell:
    """Give the bar of the trials of a line of `Bounds`, on the scale of the largest line of its table."""
    trials_letter = get_column_letter(_BOUNDS_TRIALS_COLUMN)
    return TabCell(
        None,
        formula=sparkline_bar_formula(
            f"{trials_letter}{row}",
            scale_maximum=f"MAX(${trials_letter}${first_row}:${trials_letter}${last_row})",
        ),
        style=CellStyle.BAR,
    )
