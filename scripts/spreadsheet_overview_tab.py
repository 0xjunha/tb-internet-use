"""Lay out `Overview` of the spreadsheet of `build_spreadsheet.py` and `Chart data`, the tables its three charts draw.

`Overview` holds five key numbers, three charts, the tasks with the most requests other than package installs and the list of tabs, so that a reader sees the answer before any other tab.
"""

import datetime
from dataclasses import dataclass

from openpyxl.utils import get_column_letter
from spreadsheet_cells import (
    EMPTY_CELL,
    LOWER_BOUND_COLOR,
    SPREADSHEET_TITLE,
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
    sparkline_bar_formula,
)
from spreadsheet_python_counts import (
    CountedBound,
    MainMeasure,
    SolvedWithoutRequestVerdict,
    SpreadsheetPythonCounts,
    TaskKey,
    share_band_of,
)
from spreadsheet_registries_and_hosts_tab import RegistriesAndHostsTab
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
    shown_task_name_of,
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

from tb_internet_use.export.model import HostService, NetworkRequestCategory

_BAND_COUNT = 10

# The categories of a request that neither installs a package nor only checks the connection, so that a mirror of package registries does not serve it.
_CATEGORIES_OTHER_THAN_PACKAGE_AND_CONNECTIVITY_CHECK = tuple(
    category.value
    for category in NetworkRequestCategory
    if category
    not in (NetworkRequestCategory.PACKAGE, NetworkRequestCategory.CONNECTIVITY_CHECK)
)

# The registries of the key number on mirrors, the three that most trials ask.
_MIRRORED_REGISTRIES = ("pypi", "apt", "npm")
# The bars of the chart of registries and kinds of host, and the lines of the table of tasks.
_SHOWN_BAR_COUNT = 10
_SHOWN_TASK_COUNT = 10
# The hosts named on a line of the table of tasks.
_NAMED_HOST_COUNT = 3


@dataclass(frozen=True, slots=True)
class ChartRowRange:
    """Table of `Chart data` that one chart draws, its rows below the header, 1-based."""

    first_row: int
    last_row: int


@dataclass(frozen=True, slots=True)
class ChartDataTab:
    """`Chart data` tab with the tables of the three charts of `Overview`."""

    grid: TabGrid
    # Category, trials, share of trials. No chart draws it, and `Method & checks` holds other tabs against it.
    categories: ChartRowRange
    bands: ChartRowRange  # band, tasks in the lower bound
    # Registry or kind of host, trials, share of trials.
    registries_and_kinds_of_host: ChartRowRange
    verdicts: ChartRowRange  # verdict, tasks
    # Cells of the lower-bound trials of each category, e.g. `B2`.
    category_trial_cells: dict[str, str]


def lay_out_chart_data_tab(
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    tasks: TasksTab,
    registries_and_hosts: RegistriesAndHostsTab,
) -> ChartDataTab:
    """Lay out the numbers the charts of `Overview` draw, as formulas over `Tasks` and the row tabs, and as plain numbers for the registries and kinds of host, which Python counts as in `Registries and hosts`."""
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

    grid.add_row(*header_cells_of("% of trials with a request", "Tasks"))
    first_band_row = grid.next_row
    lower_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
    share_range = tasks.column_range(tasks.columns.request)
    for band in range(_BAND_COUNT):
        criteria = f'{share_range},">={band / 10}"'
        if band < _BAND_COUNT - 1:
            criteria += f',{share_range},"<{(band + 1) / 10}"'
        grid.add_row(
            TabCell(_band_label_of(band)),
            TabCell(
                sum(
                    1
                    for task in counts.tasks
                    if share_band_of(counts.task_share_of(task, lower_ids)) == band
                ),
                formula=f"COUNTIFS({criteria})",
                style=CellStyle.COUNT,
            ),
        )
    bands = ChartRowRange(first_band_row, grid.next_row - 1)
    grid.add_row()

    grid.add_row(*header_cells_of("Registry or kind of host", "Trials", "% of trials"))
    first_registry_or_kind_row = grid.next_row
    for name, trial_ids in _shown_registry_and_kind_of_host_lines_of(
        registries_and_hosts
    ):
        grid.add_row(
            TabCell(name),
            TabCell(len(trial_ids), style=CellStyle.PYTHON_COUNT),
            TabCell(len(trial_ids) / trial_count, style=CellStyle.PYTHON_SHARE),
        )
    registries_and_kinds_of_host = ChartRowRange(
        first_registry_or_kind_row, grid.next_row - 1
    )
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
    return ChartDataTab(
        grid,
        categories,
        bands,
        registries_and_kinds_of_host,
        verdicts,
        category_trial_cells,
    )


def _shown_registry_and_kind_of_host_lines_of(
    registries_and_hosts: RegistriesAndHostsTab,
) -> list[tuple[str, frozenset[str]]]:
    """Give the lines of the chart of registries and kinds of host with their trials, most trials first, one per package registry and one per other host service.

    A registry has its own line since a mirror serves one registry, while the hosts of another service are joined, e.g. `github.com` and `raw.githubusercontent.com` under `code_hosting`.
    """
    trial_ids_by_name: dict[str, frozenset[str]] = {}
    for (
        host_service,
        registry_or_host_name,
    ), trial_ids in registries_and_hosts.trial_ids_by_host_service_and_name.items():
        name = (
            registry_or_host_name
            if host_service == HostService.PACKAGE_REGISTRY
            else host_service
        )
        trial_ids_by_name[name] = trial_ids_by_name.get(name, frozenset()) | trial_ids
    return sorted(trial_ids_by_name.items(), key=lambda item: (-len(item[1]), item[0]))[
        :_SHOWN_BAR_COUNT
    ]


def _band_label_of(band: int) -> str:
    """Give the label of a 0-based band of 10 points, e.g. `20–30%`."""
    return f"{band * 10}–{(band + 1) * 10}%"


# The list of tabs at the end of `Overview`, each with what it holds.
_TAB_DESCRIPTIONS = (
    (
        TASKS_TAB_NAME,
        "Internet requests per task, and tasks solved without one",
    ),
    (REQUESTED_ITEMS_TAB_NAME, "Packages and hosts requested, per task"),
    (
        REGISTRIES_AND_HOSTS_TAB_NAME,
        "Registries and hosts requested",
    ),
    (WEB_TOOLS_TAB_NAME, "Requests of web tools, by where they are sent from"),
    (
        BOUNDS_TAB_NAME,
        "Causes of the upper bound, and how far requests got",
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
        "Limits, terms and checks of the numbers",
    ),
    (CHART_DATA_TAB_NAME, "The numbers that the charts draw"),
)

# 1-based columns of `Overview`.
_OVERVIEW_LABEL_COLUMN = 1
_OVERVIEW_LOWER_BOUND_COLUMN = 2
_OVERVIEW_UPPER_BOUND_COLUMN = 3
_OVERVIEW_NOTE_COLUMN = 4
# Wide enough for the header `Hosts requested` on one line. The notes of the key numbers run over the cells to its right.
_OVERVIEW_NOTE_COLUMN_WIDTH = 28
# Wide enough for a key number in large type and the header `Upper bound`.
_OVERVIEW_NUMBER_COLUMN_WIDTH = 12
# Wide enough for the longest label of a key number, wider than other columns may grow.
_OVERVIEW_LABEL_COLUMN_WIDTH = 70

# Sizes that put the three charts side by side on one screen.
_CHART_HEIGHT_IN_CM = 6.0
# Wide enough for the longest label, `package_registry` or `documentation`, beside its bar, since Google Sheets cuts a label at a share of the chart width.
_REGISTRY_AND_KIND_OF_HOST_CHART_WIDTH_IN_CM = 12.0
_BAND_CHART_WIDTH_IN_CM = 10.0
# Wide enough for its title on one line, since Google Sheets cuts a title that is longer than the chart is wide (at 12 cm it showed `… passed trials without a`).
_VERDICT_CHART_WIDTH_IN_CM = 16.0


def lay_out_overview_tab(
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    tasks: TasksTab,
    chart_data: ChartDataTab,
    registries_and_hosts: RegistriesAndHostsTab,
) -> TabGrid:
    """Lay out the key numbers, the three charts, the table of tasks and the list of tabs."""
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
    _add_key_numbers(grid, counts, row_tabs, registries_and_hosts)
    grid.add_row()
    grid.add_charts_below(*_overview_chart_specs_of(chart_data))
    _add_task_table(grid, counts, registries_and_hosts)
    grid.add_row()
    grid.add_row(TabCell("Tabs", style=CellStyle.SECTION))
    for tab_name, description in _TAB_DESCRIPTIONS:
        # As a note it runs over the cells to its right without widening a column of numbers.
        grid.add_row(
            TabCell(tab_name),
            TabCell(description, style=CellStyle.NOTE),
        )
    grid.fixed_column_widths = {
        _OVERVIEW_LABEL_COLUMN: _OVERVIEW_LABEL_COLUMN_WIDTH,
        _OVERVIEW_LOWER_BOUND_COLUMN: _OVERVIEW_NUMBER_COLUMN_WIDTH,
        _OVERVIEW_UPPER_BOUND_COLUMN: _OVERVIEW_NUMBER_COLUMN_WIDTH,
        _OVERVIEW_NOTE_COLUMN: _OVERVIEW_NOTE_COLUMN_WIDTH,
    }
    return grid


def _task_count_formula_of(tasks: TasksTab) -> str:
    return f"COUNTA({tasks.column_range(tasks.columns.task_name)})"


def _add_key_numbers(
    grid: TabGrid,
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    registries_and_hosts: RegistriesAndHostsTab,
) -> None:
    """Add one line per key number, its lower and upper bounds in large type and a short note.

    The line on the three registries has one number in a cell over both columns, since it is a share of the lower-bound trials and has no upper bound.
    """
    measure_rows = row_tabs.trial_category_measure_rows
    trial_count = len(counts.task_by_trial_id)
    trial_count_formula = trial_count_formula_of(row_tabs)
    web_tool_ids = {
        CountedBound.LOWER: counts.request_trial_ids_of(
            CountedBound.LOWER, senders=KNOWN_OUTSIDE_SENDERS
        ),
        CountedBound.UPPER: counts.request_trial_ids_of(
            CountedBound.UPPER, senders=OUTSIDE_SENDERS
        ),
    }
    other_category_conditions = [
        ("category", not_equal_to(category))
        for category in (
            NetworkRequestCategory.PACKAGE,
            NetworkRequestCategory.CONNECTIVITY_CHECK,
        )
    ]

    def key_share(count: int, count_formula: str) -> TabCell:
        return TabCell(
            count / trial_count,
            formula=f"{count_formula}/{trial_count_formula}",
            style=CellStyle.KEY_SHARE,
        )

    def received_share(counted_bound: CountedBound) -> TabCell:
        return key_share(
            len(counts.any_category_trial_ids[MainMeasure.RECEIVED, counted_bound]),
            count_ifs_formula(
                row_tabs.trial_rows,
                [
                    (
                        "any_category_received_measure_bound",
                        equal_to(LOWER_AND_UPPER)
                        if counted_bound == CountedBound.LOWER
                        else not_equal_to(NEITHER),
                    )
                ],
            ),
        )

    lower_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
    lower_formula = request_trial_count_formula_of(row_tabs, CountedBound.LOWER)
    # Python counts the trials, since a request row names several hosts in one cell and a host finds its registry in the host catalog.
    mirrored_registry_only_count = len(
        lower_ids
        - _trial_ids_with_a_request_outside_the_mirrored_registries(
            registries_and_hosts
        )
    )

    lines: list[tuple[str, TabCell, TabCell | None, str]] = [
        (
            "Trials with an internet request from the task environment",
            key_share(
                len(
                    counts.any_category_trial_ids[
                        MainMeasure.REQUEST, CountedBound.LOWER
                    ]
                ),
                request_trial_count_formula_of(row_tabs, CountedBound.LOWER),
            ),
            key_share(
                len(
                    counts.any_category_trial_ids[
                        MainMeasure.REQUEST, CountedBound.UPPER
                    ]
                ),
                request_trial_count_formula_of(row_tabs, CountedBound.UPPER),
            ),
            f"Lower bound: trials that certainly sent a request. Upper bound: also includes trials that may have sent one. See {BOUNDS_TAB_NAME}.",
        ),
        (
            f"… of them, trials whose requests all go to {', '.join(_MIRRORED_REGISTRIES[:-1])} or {_MIRRORED_REGISTRIES[-1]}",
            TabCell(
                mirrored_registry_only_count / len(lower_ids) if lower_ids else 0.0,
                formula=f"{mirrored_registry_only_count}/{lower_formula}",
                style=CellStyle.KEY_SHARE,
            ),
            None,
            "Mirrors of these three registries would serve every request of these trials. Counted on the lower bound, by what the commands name.",
        ),
        (
            "Trials that received what a request asked for",
            received_share(CountedBound.LOWER),
            received_share(CountedBound.UPPER),
            f"Lower bound: trials whose output shows a download, the content itself or a finished install of a named package. See {BOUNDS_TAB_NAME}.",
        ),
        (
            "Trials with a request other than a package install or a connectivity check",
            key_share(
                len(
                    counts.request_trial_ids_of(
                        CountedBound.LOWER,
                        categories=_CATEGORIES_OTHER_THAN_PACKAGE_AND_CONNECTIVITY_CHECK,
                        senders=[TASK_ENVIRONMENT],
                    )
                ),
                count_unique_ifs_formula(
                    measure_rows,
                    "trial_id",
                    [
                        ("sender", equal_to(TASK_ENVIRONMENT)),
                        *other_category_conditions,
                        ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
                    ],
                ),
            ),
            key_share(
                len(
                    counts.request_trial_ids_of(
                        CountedBound.UPPER,
                        categories=_CATEGORIES_OTHER_THAN_PACKAGE_AND_CONNECTIVITY_CHECK,
                        senders=[TASK_ENVIRONMENT, UNKNOWN_SENDER],
                    )
                ),
                count_unique_ifs_formula(
                    measure_rows,
                    "trial_id",
                    [
                        *(
                            ("sender", not_equal_to(sender))
                            for sender in KNOWN_OUTSIDE_SENDERS
                        ),
                        *other_category_conditions,
                        ("request_measure_bound", not_equal_to(NEITHER)),
                    ],
                ),
            ),
            "A mirror of package registries does not serve these, e.g. a file from GitHub, a web API or a search. The tasks with most of them are listed below.",
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
            f"Stays on when the network of the task environment is off. {_most_web_tool_trials_text_of(counts, web_tool_ids[CountedBound.LOWER])}",
        ),
    ]
    for label, lower_cell, upper_cell, note in lines:
        row = grid.add_row(
            TabCell(label),
            lower_cell,
            EMPTY_CELL if upper_cell is None else upper_cell,
            TabCell(note, style=CellStyle.NOTE),
        )
        if upper_cell is None:
            grid.merged_ranges.append(
                f"{get_column_letter(_OVERVIEW_LOWER_BOUND_COLUMN)}{row}:{get_column_letter(_OVERVIEW_UPPER_BOUND_COLUMN)}{row}"
            )


def _trial_ids_with_a_request_outside_the_mirrored_registries(
    registries_and_hosts: RegistriesAndHostsTab,
) -> set[str]:
    """Give the trials on a line of `Registries and hosts` other than the three registries, e.g. on `pytorch` or `github.com`.

    The lines hold the lower-bound requests from the task environment that are no connectivity checks, so a trial that only checked the connection is on no line and counts as one whose requests all go to the three registries, since a connectivity check asks for no content.
    """
    mirrored_lines = {
        (HostService.PACKAGE_REGISTRY.value, registry)
        for registry in _MIRRORED_REGISTRIES
    }
    return {
        trial_id
        for line, trial_ids in registries_and_hosts.trial_ids_by_host_service_and_name.items()
        if line not in mirrored_lines
        for trial_id in trial_ids
    }


def _most_web_tool_trials_text_of(
    counts: SpreadsheetPythonCounts, web_tool_trial_ids: set[str]
) -> str:
    """Say which harness has most of the lower-bound trials with a web tool request, e.g. `codex has 741 of the 906 trials of the lower bound.`, or nothing without such a trial."""
    if not web_tool_trial_ids:
        return ""
    trial_count_by_harness: dict[str, int] = {}
    for trial_id in web_tool_trial_ids:
        harness = counts.harness_by_trial_id[trial_id]
        trial_count_by_harness[harness] = trial_count_by_harness.get(harness, 0) + 1
    harness, harness_trial_count = min(
        trial_count_by_harness.items(), key=lambda item: (-item[1], item[0])
    )
    return f"{harness} has {count_text_of(harness_trial_count)} of the {count_text_of(len(web_tool_trial_ids))} trials of the lower bound."


def _add_task_table(
    grid: TabGrid,
    counts: SpreadsheetPythonCounts,
    registries_and_hosts: RegistriesAndHostsTab,
) -> None:
    """Add the tasks with the largest share of trials that requested something other than a package install or a connectivity check, each with the hosts that most of those trials asked, counted by Python.

    These are the tasks most likely to rest on what a request fetched from the web, e.g. data of a web API or a page of documentation, though a request of these categories may also fetch a tool, e.g. the Go toolchain from `go.dev`, which the named hosts let a reader tell apart.
    The trials are those of the key number of the same name, and the hosts are those of the lines of `Registries and hosts` that are no package registry.
    """
    other_category_trial_ids = counts.request_trial_ids_of(
        CountedBound.LOWER,
        categories=_CATEGORIES_OTHER_THAN_PACKAGE_AND_CONNECTIVITY_CHECK,
        senders=[TASK_ENVIRONMENT],
    )
    grid.add_row(
        TabCell(
            "Tasks with the most requests other than package installs",
            style=CellStyle.SECTION,
        )
    )
    grid.add_note(
        f"The {_SHOWN_TASK_COUNT} tasks with the largest share of trials with a lower-bound request that is neither a package install nor a connectivity check, with the hosts that most of those trials asked.",
        _OVERVIEW_NOTE_COLUMN,
    )
    grid.add_row(*header_cells_of("Task", "% of trials", "", "Hosts requested"))

    def other_category_share_of(task: TaskKey) -> float:
        return counts.task_share_of(task, other_category_trial_ids)

    for task in sorted(
        counts.tasks, key=lambda task: (-other_category_share_of(task), task)
    )[:_SHOWN_TASK_COUNT]:
        if not other_category_share_of(task):
            break
        row = grid.next_row
        task_trial_ids = counts.trial_ids_of_task(task) & other_category_trial_ids
        trial_count_by_host_name: dict[str, int] = {}
        for (
            host_service,
            registry_or_host_name,
        ), trial_ids in registries_and_hosts.trial_ids_by_host_service_and_name.items():
            # A host that gives two services is on two lines, e.g. `huggingface.co`, and takes the larger of them.
            if host_service != HostService.PACKAGE_REGISTRY and (
                trial_count := len(trial_ids & task_trial_ids)
            ):
                trial_count_by_host_name[registry_or_host_name] = max(
                    trial_count, trial_count_by_host_name.get(registry_or_host_name, 0)
                )
        grid.add_row(
            TabCell(shown_task_name_of(task[1])),
            TabCell(other_category_share_of(task), style=CellStyle.PYTHON_SHARE),
            TabCell(
                None,
                formula=sparkline_bar_formula(
                    f"{get_column_letter(_OVERVIEW_LOWER_BOUND_COLUMN)}{row}"
                ),
                style=CellStyle.BAR,
            ),
            TabCell(
                ", ".join(
                    sorted(
                        trial_count_by_host_name,
                        key=lambda host_name: (
                            -trial_count_by_host_name[host_name],
                            host_name,
                        ),
                    )[:_NAMED_HOST_COUNT]
                ),
                style=CellStyle.NOTE,
            ),
        )


def _overview_chart_specs_of(chart_data: ChartDataTab) -> list[BarChartSpec]:
    """Give the three charts of `Overview`, drawn from `Chart data`."""
    return [
        BarChartSpec(
            title="Tasks, by % of trials with a request",
            label_column=1,
            series=(BarChartSeries(2, "Lower bound", LOWER_BOUND_COLOR),),
            first_row=chart_data.bands.first_row,
            last_row=chart_data.bands.last_row,
            width_in_cm=_BAND_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            has_vertical_bars=True,
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
        BarChartSpec(
            title="% of trials, by registry or kind of host",
            label_column=1,
            series=(BarChartSeries(3, "Lower bound", LOWER_BOUND_COLOR),),
            first_row=chart_data.registries_and_kinds_of_host.first_row,
            last_row=chart_data.registries_and_kinds_of_host.last_row,
            width_in_cm=_REGISTRY_AND_KIND_OF_HOST_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            axis_number_format="0%",
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
        BarChartSpec(
            title="Solved tasks, by % of passed trials without a request",
            label_column=1,
            series=(BarChartSeries(2, "Tasks", LOWER_BOUND_COLOR),),
            first_row=chart_data.verdicts.first_row,
            last_row=chart_data.verdicts.last_row,
            width_in_cm=_VERDICT_CHART_WIDTH_IN_CM,
            height_in_cm=_CHART_HEIGHT_IN_CM,
            data_tab_name=CHART_DATA_TAB_NAME,
        ),
    ]
