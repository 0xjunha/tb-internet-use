"""Lay out `Overview` of the spreadsheet of `build_spreadsheet.py` and `Chart data`, the tables its three charts draw.

`Overview` fits one screen, five key numbers, three charts and the list of tabs, so that a reader sees the answer before any table.
"""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from spreadsheet_cells import (
    EMPTY_CELL,
    LOWER_BOUND_COLOR,
    SPREADSHEET_TITLE,
    UPPER_BOUND_ONLY_COLOR,
    BarChartSeries,
    BarChartSpec,
    CellStyle,
    TabCell,
    TabGrid,
    count_ifs_formula,
    count_text_formula,
    count_text_of,
    count_unique_ifs_formula,
    equal_to,
    not_equal_to,
)
from spreadsheet_python_counts import (
    CountedBound,
    MainMeasure,
    SolvedWithoutRequestVerdict,
    SpreadsheetPythonCounts,
    share_band_of,
)
from spreadsheet_result_tabs import TasksTab
from spreadsheet_row_tabs import (
    KNOWN_OUTSIDE_SENDERS,
    LOWER_AND_UPPER,
    NEITHER,
    OUTSIDE_SENDERS,
    TASK_ENVIRONMENT,
    UNKNOWN_SENDER,
    SpreadsheetRowTabs,
    header_cells_of,
    request_trial_count_formula_of,
    trial_count_formula_of,
    web_tool_trial_count_formula_of,
)
from spreadsheet_tabs import (
    APPENDIX_TAB_COLOR,
    BOUNDS_TAB_NAME,
    CHART_DATA_TAB_NAME,
    METHOD_AND_CHECKS_TAB_NAME,
    NETWORK_REQUEST_ROWS_TAB_NAME,
    OVERVIEW_TAB_COLOR,
    OVERVIEW_TAB_NAME,
    REGISTRIES_AND_HOSTS_TAB_NAME,
    REQUESTED_ITEMS_TAB_NAME,
    TASKS_TAB_NAME,
    TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME,
    TRIAL_ROWS_TAB_NAME,
    WEB_TOOLS_TAB_NAME,
)

from tb_internet_use.export.model import NetworkRequestCategory

# The share of trials with a request at which a task counts among the key numbers.
_HALF_OF_THE_TRIALS = 0.5

_BAND_COUNT = 10

_OTHER_CATEGORIES_THAN_PACKAGE = tuple(
    category.value
    for category in NetworkRequestCategory
    if category != NetworkRequestCategory.PACKAGE
)


@dataclass(frozen=True, slots=True)
class ChartRowRange:
    """Table of `Chart data` that one chart draws, its rows below the header, 1-based."""

    first_row: int
    last_row: int


@dataclass(frozen=True, slots=True)
class ChartDataTab:
    """`Chart data` tab with the tables of the three charts of `Overview`."""

    grid: TabGrid
    categories: ChartRowRange  # category, trials, share of trials
    bands: ChartRowRange  # band, tasks in the lower bound, tasks in the upper bound
    verdicts: ChartRowRange  # verdict, chart label, tasks
    # Cells of the lower-bound trials of each category, e.g. `B2`.
    category_trial_cells: dict[str, str]


def lay_out_chart_data_tab(
    counts: SpreadsheetPythonCounts, row_tabs: SpreadsheetRowTabs, tasks: TasksTab
) -> ChartDataTab:
    """Lay out the numbers the charts of `Overview` draw, as formulas over `Tasks` and the row tabs."""
    grid = TabGrid(CHART_DATA_TAB_NAME, tab_color=APPENDIX_TAB_COLOR)
    trial_count = len(counts.task_by_trial_id)
    trial_count_formula = trial_count_formula_of(row_tabs)

    grid.add_row(*header_cells_of("Category", "Trials", "% of trials"))
    category_trial_ids = {
        category.value: counts.request_trial_ids_of(
            CountedBound.LOWER, categories=[category.value], senders=[TASK_ENVIRONMENT]
        )
        for category in NetworkRequestCategory
    }
    category_trial_cells: dict[str, str] = {}
    first_category_row = grid.next_row
    for category, trial_ids in sorted(
        category_trial_ids.items(), key=lambda item: -len(item[1])
    ):
        if not trial_ids:
            continue
        row = grid.next_row
        category_trial_cells[category] = f"B{row}"
        trials_formula = count_ifs_formula(
            row_tabs.trial_category_measure_rows,
            [
                ("category", equal_to(category)),
                ("sender", equal_to(TASK_ENVIRONMENT)),
                ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
            ],
        )
        grid.add_row(
            TabCell(category),
            TabCell(len(trial_ids), formula=trials_formula, style=CellStyle.COUNT),
            TabCell(
                len(trial_ids) / trial_count,
                formula=f"B{row}/{trial_count_formula}",
                style=CellStyle.SHARE,
            ),
        )
    categories = ChartRowRange(first_category_row, grid.next_row - 1)
    grid.add_row()

    grid.add_row(
        *header_cells_of("% of trials with a request", "Lower bound", "Upper bound")
    )
    first_band_row = grid.next_row
    for band in range(_BAND_COUNT):
        cells = [TabCell(_band_label_of(band))]
        for column, counted_bound in (
            (tasks.columns.request, CountedBound.LOWER),
            (tasks.columns.request_upper_bound, CountedBound.UPPER),
        ):
            share_range = tasks.column_range(column)
            criteria = f'{share_range},">={band / 10}"'
            if band < _BAND_COUNT - 1:
                criteria += f',{share_range},"<{(band + 1) / 10}"'
            band_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, counted_bound]
            cells.append(
                TabCell(
                    sum(
                        1
                        for task in counts.tasks
                        if share_band_of(counts.task_share_of(task, band_ids)) == band
                    ),
                    formula=f"COUNTIFS({criteria})",
                    style=CellStyle.COUNT,
                )
            )
        grid.add_row(*cells)
    bands = ChartRowRange(first_band_row, grid.next_row - 1)
    grid.add_row()

    grid.add_row(*header_cells_of("Solved without a request?", "Tasks"))
    verdict_counts = {verdict: 0 for verdict in SolvedWithoutRequestVerdict}
    for task in counts.tasks:
        verdict_counts[counts.passed_trial_counts_of(task).verdict] += 1
    first_verdict_row = grid.next_row
    for verdict, task_count in verdict_counts.items():
        grid.add_row(
            TabCell(verdict.value),
            TabCell(
                task_count,
                formula=f"COUNTIFS({tasks.column_range(tasks.columns.verdict)},{equal_to(verdict.value)})",
                style=CellStyle.COUNT,
            ),
        )
    verdicts = ChartRowRange(first_verdict_row, grid.next_row - 1)
    return ChartDataTab(grid, categories, bands, verdicts, category_trial_cells)


def _band_label_of(band: int) -> str:
    """Give the label of a 0-based band of 10 points, e.g. `20–30%`."""
    return f"{band * 10}–{(band + 1) * 10}%"


# The list of tabs at the end of `Overview`, by the questions they answer.
_TAB_QUESTIONS = (
    (
        TASKS_TAB_NAME,
        "Which tasks send internet requests, and were they solved without one?",
    ),
    (REQUESTED_ITEMS_TAB_NAME, "What did the trials of each task ask for?"),
    (
        REGISTRIES_AND_HOSTS_TAB_NAME,
        "What would a mirror or the image have to serve?",
    ),
    (WEB_TOOLS_TAB_NAME, "Which requests leave from outside the task environment?"),
    (
        BOUNDS_TAB_NAME,
        "Why is the upper bound higher, and how far did the requests get?",
    ),
    (TRIAL_ROWS_TAB_NAME, "The rows of trials that every count reads"),
    (
        TRIAL_CATEGORY_MEASURE_ROWS_TAB_NAME,
        "The bounds of each trial, category and sender",
    ),
    (
        NETWORK_REQUEST_ROWS_TAB_NAME,
        "The requests of the lower bound and those of web tools",
    ),
    (
        METHOD_AND_CHECKS_TAB_NAME,
        "What do the numbers rest on, and what can they not say?",
    ),
    (CHART_DATA_TAB_NAME, "The numbers that the charts draw"),
)

# 1-based columns of `Overview`.
_OVERVIEW_LABEL_COLUMN = 1
_OVERVIEW_LOWER_BOUND_COLUMN = 2
_OVERVIEW_UPPER_BOUND_COLUMN = 3
# Wide enough for a key number in large type and the header `Upper bound`.
_OVERVIEW_NUMBER_COLUMN_WIDTH = 12
# Wide enough for the longest label of a key number, wider than other columns may grow.
_OVERVIEW_LABEL_COLUMN_WIDTH = 70

# Sizes that put the three charts side by side on one screen.
_CHART_HEIGHT_IN_CM = 6.0
# Wide enough for the longest category, `connectivity_check`, beside its bar, since Google Sheets cuts a label at a share of the chart width (at 9 cm it showed `connectivity`).
_CATEGORY_CHART_WIDTH_IN_CM = 14.0
_BAND_CHART_WIDTH_IN_CM = 10.0
# Wide enough for the longest verdict, `never solved`, on one line beside its bar.
_VERDICT_CHART_WIDTH_IN_CM = 10.0


def lay_out_overview_tab(
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    tasks: TasksTab,
    chart_data: ChartDataTab,
) -> TabGrid:
    """Lay out the key numbers, the three charts and the list of tabs."""
    grid = TabGrid(OVERVIEW_TAB_NAME, tab_color=OVERVIEW_TAB_COLOR)
    trial_count = len(counts.task_by_trial_id)
    task_count = len(counts.tasks)
    versions = sorted({task[0] for task in counts.tasks})
    grid.add_row(TabCell(SPREADSHEET_TITLE, style=CellStyle.TITLE))
    versions_text = f" tasks, benchmark version{'s' if len(versions) > 1 else ''} {' and '.join(versions)}, built {datetime.date.today().isoformat()}."
    grid.add_note(
        TabCell(
            f"{count_text_of(trial_count)} trials of {count_text_of(task_count)}{versions_text}",
            formula=f'{count_text_formula(trial_count_formula_of(row_tabs))}&" trials of "&{count_text_formula(_task_count_formula_of(tasks))}&"{versions_text}"',
            style=CellStyle.NOTE,
        ),
        4,
    )
    grid.add_row()
    grid.add_row(*header_cells_of("Key numbers", "Lower bound", "Upper bound", ""))
    _add_key_numbers(grid, counts, row_tabs, tasks)
    grid.add_row()
    grid.add_charts_below(*_overview_chart_specs_of(chart_data))
    grid.add_row(TabCell("Tabs", style=CellStyle.SECTION))
    for tab_name, question in _TAB_QUESTIONS:
        # As a note it runs over the cells to its right without widening a column of numbers.
        grid.add_row(
            TabCell(tab_name),
            TabCell(question, style=CellStyle.NOTE),
        )
    grid.fixed_column_widths = {
        _OVERVIEW_LABEL_COLUMN: _OVERVIEW_LABEL_COLUMN_WIDTH,
        _OVERVIEW_LOWER_BOUND_COLUMN: _OVERVIEW_NUMBER_COLUMN_WIDTH,
        _OVERVIEW_UPPER_BOUND_COLUMN: _OVERVIEW_NUMBER_COLUMN_WIDTH,
    }
    return grid


def _task_count_formula_of(tasks: TasksTab) -> str:
    return f"COUNTA({tasks.column_range(tasks.columns.task_name)})"


def _add_key_numbers(
    grid: TabGrid,
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    tasks: TasksTab,
) -> None:
    """Add one line per key number, its lower and upper bounds in large type and, except on the line on packages, a short note."""
    measure_rows = row_tabs.trial_category_measure_rows
    trial_count = len(counts.task_by_trial_id)
    trial_count_formula = trial_count_formula_of(row_tabs)
    lower_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
    upper_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.UPPER]
    lower_formula = request_trial_count_formula_of(row_tabs, CountedBound.LOWER)
    upper_formula = request_trial_count_formula_of(row_tabs, CountedBound.UPPER)
    # Lower-bound trials with a lower-bound row of a category other than `package` from the task environment, which the upper column of the line on packages leaves out.
    certain_other_category_ids = lower_ids & counts.request_trial_ids_of(
        CountedBound.LOWER,
        categories=_OTHER_CATEGORIES_THAN_PACKAGE,
        senders=[TASK_ENVIRONMENT],
    )
    # Lower-bound trials with a row of a category other than `package` in either bound that the task environment may have sent, which the lower column leaves out too.
    possible_other_category_ids = lower_ids & counts.request_trial_ids_of(
        CountedBound.UPPER,
        categories=_OTHER_CATEGORIES_THAN_PACKAGE,
        senders=[TASK_ENVIRONMENT, UNKNOWN_SENDER],
    )
    package_only_lower_count = len(lower_ids - possible_other_category_ids)
    package_only_upper_count = len(lower_ids - certain_other_category_ids)
    certain_other_category_formula = count_unique_ifs_formula(
        measure_rows,
        "trial_id",
        [
            ("sender", equal_to(TASK_ENVIRONMENT)),
            ("category", not_equal_to(NetworkRequestCategory.PACKAGE)),
            ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
        ],
    )
    possible_other_category_formula = count_unique_ifs_formula(
        measure_rows,
        "trial_id",
        [
            (
                "trial_rows.any_category_request_measure_bound",
                equal_to(LOWER_AND_UPPER),
            ),
            *(("sender", not_equal_to(sender)) for sender in KNOWN_OUTSIDE_SENDERS),
            ("category", not_equal_to(NetworkRequestCategory.PACKAGE)),
            ("request_measure_bound", not_equal_to(NEITHER)),
        ],
    )
    package_only_lower_formula = f"{lower_formula}-{possible_other_category_formula}"
    package_only_upper_formula = f"{lower_formula}-{certain_other_category_formula}"
    task_shares = {
        counted_bound: [counts.task_share_of(task, ids) for task in counts.tasks]
        for counted_bound, ids in (
            (CountedBound.LOWER, lower_ids),
            (CountedBound.UPPER, upper_ids),
        )
    }
    verdicts = [counts.passed_trial_counts_of(task).verdict for task in counts.tasks]
    solved_count = sum(
        1 for verdict in verdicts if verdict != SolvedWithoutRequestVerdict.NEVER_SOLVED
    )
    web_tool_ids = {
        CountedBound.LOWER: counts.request_trial_ids_of(
            CountedBound.LOWER, senders=KNOWN_OUTSIDE_SENDERS
        ),
        CountedBound.UPPER: counts.request_trial_ids_of(
            CountedBound.UPPER, senders=OUTSIDE_SENDERS
        ),
    }

    def package_only_share(count: int, count_formula: str) -> TabCell:
        return TabCell(
            count / len(lower_ids) if lower_ids else 0.0,
            formula=f"({count_formula})/{lower_formula}",
            style=CellStyle.KEY_SHARE,
        )

    def solved_task_count(
        verdicts_counted: Sequence[SolvedWithoutRequestVerdict],
    ) -> TabCell:
        return TabCell(
            sum(1 for verdict in verdicts if verdict in verdicts_counted),
            formula="+".join(
                f"COUNTIFS({tasks.column_range(tasks.columns.verdict)},{equal_to(verdict)})"
                for verdict in verdicts_counted
            ),
            style=CellStyle.KEY_COUNT,
        )

    def key_share(count: int, count_formula: str) -> TabCell:
        return TabCell(
            count / trial_count,
            formula=f"{count_formula}/{trial_count_formula}",
            style=CellStyle.KEY_SHARE,
        )

    def tasks_at_key_share(column: int, counted_bound: CountedBound) -> TabCell:
        return TabCell(
            sum(
                1
                for share in task_shares[counted_bound]
                if share >= _HALF_OF_THE_TRIALS
            ),
            formula=f'COUNTIFS({tasks.column_range(column)},">={_HALF_OF_THE_TRIALS}")',
            style=CellStyle.KEY_COUNT,
        )

    lines: list[tuple[str, TabCell, TabCell, str | TabCell]] = [
        (
            "Trials with an internet request from the task environment",
            key_share(len(lower_ids), lower_formula),
            key_share(len(upper_ids), upper_formula),
            f"Lower bound: trials that certainly sent a request. Upper bound: also includes trials that may have sent one. See {BOUNDS_TAB_NAME}.",
        ),
        (
            "… of them, trials that only installed packages",
            package_only_share(package_only_lower_count, package_only_lower_formula),
            package_only_share(package_only_upper_count, package_only_upper_formula),
            EMPTY_CELL,
        ),
        (
            "Tasks where at least half of the trials sent a request",
            tasks_at_key_share(tasks.columns.request, CountedBound.LOWER),
            tasks_at_key_share(tasks.columns.request_upper_bound, CountedBound.UPPER),
            TabCell(
                f"of {count_text_of(len(counts.tasks))} tasks",
                formula=f'"of "&{count_text_formula(_task_count_formula_of(tasks))}&" tasks"',
                style=CellStyle.NOTE,
            ),
        ),
        (
            "Solved tasks that were solved at least once without a request",
            solved_task_count([SolvedWithoutRequestVerdict.YES]),
            solved_task_count(
                [SolvedWithoutRequestVerdict.YES, SolvedWithoutRequestVerdict.MAYBE]
            ),
            TabCell(
                f"of {count_text_of(solved_count)} solved tasks, see {TASKS_TAB_NAME}",
                formula=f'"of "&{count_text_formula(f"""COUNTIFS({tasks.column_range(tasks.columns.passed)},">0")""")}&" solved tasks, see {TASKS_TAB_NAME}"',
                style=CellStyle.NOTE,
            ),
        ),
        (
            "Trials with a web tool request sent from outside the task environment",
            key_share(
                len(web_tool_ids[CountedBound.LOWER]),
                web_tool_trial_count_formula_of(row_tabs, CountedBound.LOWER),
            ),
            key_share(
                len(web_tool_ids[CountedBound.UPPER]),
                web_tool_trial_count_formula_of(row_tabs, CountedBound.UPPER),
            ),
            "stays on when the network of the task environment is off",
        ),
    ]
    for label, lower_cell, upper_cell, note in lines:
        grid.add_row(
            TabCell(label),
            lower_cell,
            upper_cell,
            note if isinstance(note, TabCell) else TabCell(note, style=CellStyle.NOTE),
        )


def _overview_chart_specs_of(chart_data: ChartDataTab) -> list[BarChartSpec]:
    """Give the three charts of `Overview`, drawn from `Chart data`."""
    return [
        BarChartSpec(
            title="% of trials, by category",
            label_column=1,
            series=(BarChartSeries(3, "Lower bound", LOWER_BOUND_COLOR),),
            first_row=chart_data.categories.first_row,
            last_row=chart_data.categories.last_row,
            width_in_cm=_CATEGORY_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            axis_number_format="0%",
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
        BarChartSpec(
            title="Tasks, by % of trials with a request",
            label_column=1,
            series=(
                BarChartSeries(2, "Lower bound", LOWER_BOUND_COLOR),
                BarChartSeries(3, "Upper bound", UPPER_BOUND_ONLY_COLOR),
            ),
            first_row=chart_data.bands.first_row,
            last_row=chart_data.bands.last_row,
            width_in_cm=_BAND_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            has_vertical_bars=True,
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
        BarChartSpec(
            title="Tasks, solved without a request?",
            label_column=1,
            series=(BarChartSeries(2, "Tasks", LOWER_BOUND_COLOR),),
            first_row=chart_data.verdicts.first_row,
            last_row=chart_data.verdicts.last_row,
            width_in_cm=_VERDICT_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
    ]
