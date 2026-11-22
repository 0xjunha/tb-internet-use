"""Lay out `Method & checks` of the spreadsheet of `build_spreadsheet.py`, with what the numbers cannot say, the terms, the checks and what the rows rest on.

Each check is a formula that Google Sheets computes again when it opens the file, so that a changed cell shows up there and not only in the build.
"""

import csv
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from run_pipeline import JUDGMENT_RULES_BY_STEP_PACKAGE, judgment_rule_names_of
from spreadsheet_cells import (
    ALL_CHECKS_HOLD_LABEL,
    HOLDS_HEADER,
    PYTHON_COPY_TAB_SUFFIX,
    CellStyle,
    TabCell,
    TabGrid,
    count_ifs_formula,
    count_unique_ifs_formula,
    equal_to,
    not_equal_to,
    tab_range_of,
)
from spreadsheet_overview_tab import ChartDataTab
from spreadsheet_python_counts import (
    PASSED_REWARD,
    CountedBound,
    MainMeasure,
    RowFiles,
    SpreadsheetPythonCounts,
    differing_task_category_measure_line_count_of,
)
from spreadsheet_registries_and_hosts_tab import RegistriesAndHostsTab
from spreadsheet_result_tabs import (
    BoundsTab,
    RequestedItemsTab,
    TasksTab,
    TrialCountLinesTab,
)
from spreadsheet_row_tabs import (
    KNOWN_OUTSIDE_SENDERS,
    LOWER_AND_UPPER,
    TASK_ENVIRONMENT,
    UPPER_ONLY,
    ChosenNetworkRequestRows,
    SpreadsheetRowTabs,
    request_trial_count_formula_of,
    trial_count_formula_of,
)
from spreadsheet_tabs import (
    APPENDIX_TAB_COLOR,
    METHOD_AND_CHECKS_TAB_NAME,
)

from tb_internet_use.export.model import MeasureBound, NetworkRequestCategory

# What the trajectory of each harness lacks, as a phrase that completes "lacks …", measured on the raw trajectories.
# In antigravity-cli, 15 of 1,306 readable TB 4.1 trials call `invoke_subagent` (22 calls), and the trajectory holds only the launch and its result.
# In grok-build, none of the 238 TB 4.1 trials with a compaction marker has a tool call before it.
# In copilot-cli, 28 `read_bash` or `stop_bash` calls in about 12 of 330 TB 4.1 trials name a shell that no call starts.
# Devin and cursor-cli keep the earlier finding on TB 3.0 and 4.0.
MISSING_CALLS_BY_HARNESS = {
    "devin": "the calls of subagents and those before a compaction",
    "grok-build": "the calls of subagents and those before a compaction",
    "cursor-cli": "the inner calls of subagents",
    "antigravity-cli": "the calls of subagents, which run as a separate conversation",
    "copilot-cli": "the start of some shells that a later call reads",
}

# What the numbers of the front tabs cannot say, one line each, before and after the lines of harnesses whose trajectories lack calls.
_CANNOT_SAY_LINES_BEFORE_HARNESSES = (
    "Whether a trial without a visible request sent none, since a script or binary whose content the trajectory does not show may have.",
    "Whether a request was needed to solve the task. Trials with a reward of 1 and requests are correlated only.",
    "Requests outside the trajectory, e.g. of the image build or the verifier.",
)
_CANNOT_SAY_LINES_AFTER_HARNESSES = (
    "How harnesses compare, since their tools differ, or how benchmark versions compare, since their tasks differ.",
    "Whether a web tool received what it asked for, since its result is assumed.",
    "Packages installed without being named, e.g. dependencies, or a registry changed by configuration that the trajectory does not show.",
    "Whether the rows are right. The checks below show only that this file counts the rows as Python does.",
)


# Defined once here, so that the other tabs need not.
TERM_MEANINGS = (
    (
        "Lower bound",
        "Trials whose trajectory confirms it, e.g. a request that is internet use",
    ),
    (
        "Upper bound",
        "Also trials where it is uncertain, assumed or unknown, and every trial whose trajectory could not be read",
    ),
    (
        "Task environment",
        "The container that runs the agent's commands. Turning its internet off blocks their requests",
    ),
    (
        "Web tool from outside",
        "A web tool of the harness (harness_process) or the model provider (provider_server). unknown: no fact places it",
    ),
    (
        "connectivity_check",
        "A request that only checks that a host answers, e.g. ping, or a URL without path or query to a registry or search engine",
    ),
    (
        "remote_api_call",
        "A request to a web API host, also one that fetches one record by its ID, e.g. rest.uniprot.org/uniprotkb/P12345.fasta",
    ),
    ("Reward=1", f"A trial whose reward is {PASSED_REWARD}"),
    (
        "Requests",
        "Rows of network_request_rows. Retries and loops inflate them, so the other numbers count trials",
    ),
    (
        "Grey italics",
        "Counted by Python from the full CSV files, since the rows are not in this file or no formula can count them",
    ),
)

_NOTE_LAST_COLUMN = 5


@dataclass(frozen=True, slots=True)
class CheckedTabs:
    """Tabs of the spreadsheet that `Method & checks` checks."""

    overview: TabGrid
    tasks: TasksTab
    requested_items: RequestedItemsTab
    registries_and_hosts: RegistriesAndHostsTab
    web_tools: TrialCountLinesTab
    bounds: BoundsTab
    chart_data: ChartDataTab

    def front_grids(self) -> list[TabGrid]:
        """Give the tabs before the row tabs, in order."""
        return [
            self.overview,
            self.tasks.grid,
            self.requested_items.lines_tab.grid,
            self.registries_and_hosts.grid,
            self.web_tools.grid,
            self.bounds.grid,
        ]

    def grids_with_formulas(self) -> list[TabGrid]:
        """Give the tabs that hold formulas, which get a copy with Python's counts."""
        return [
            grid
            for grid in (*self.front_grids(), self.chart_data.grid)
            if grid.numeric_formula_runs()
        ]


class MethodAndChecksTab:
    """State of `Method & checks` while it is laid out, with the rows that the cell of all checks reads."""

    def __init__(self) -> None:
        self.grid = TabGrid(METHOD_AND_CHECKS_TAB_NAME, tab_color=APPENDIX_TAB_COLOR)
        self.check_rows: list[int] = []

    def add_section(self, title: str) -> None:
        self.grid.add_row(TabCell(title, style=CellStyle.SECTION))
        self.grid.add_row(
            *(
                TabCell(text, style=CellStyle.HEADER)
                for text in ("Check", "Left", "Right", HOLDS_HEADER, "How")
            )
        )

    def add_check(
        self,
        check: str,
        left: TabCell,
        right: TabCell,
        how: str,
        *,
        holds_formula_template: str = "B{row}=C{row}",
    ) -> None:
        """Add a check whose cell in the column Holds compares its two sides, e.g. `B{row}>=C{row}`."""
        row = self.grid.next_row
        self.check_rows.append(row)
        self.grid.wrapped_rows.add(row)
        self.grid.add_row(
            TabCell(check),
            left,
            right,
            TabCell(
                True,
                formula=holds_formula_template.format(row=row),
                style=CellStyle.HOLDS,
            ),
            TabCell(how, style=CellStyle.NOTE),
        )

    def add_zero_check(self, check: str, terms: list[str], how: str = "") -> None:
        """Add a check that a sum of terms, each above 0 when something is wrong, is 0."""
        self.add_check(
            check,
            TabCell(0, formula="+".join(terms) or "0", style=CellStyle.COUNT),
            TabCell(0, style=CellStyle.COUNT),
            how,
        )


def lay_out_method_and_checks_tab(
    row_files: RowFiles,
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    chosen_rows: ChosenNetworkRequestRows,
    checked_tabs: CheckedTabs,
) -> TabGrid:
    """Lay out what the numbers cannot say, the terms, the checks and what the numbers rest on."""
    method_and_checks = MethodAndChecksTab()
    grid = method_and_checks.grid
    grid.add_row(TabCell(METHOD_AND_CHECKS_TAB_NAME, style=CellStyle.TITLE))
    grid.add_note(
        "What do the numbers rest on, what can they not say, and does every formula give the value Python counted?",
        _NOTE_LAST_COLUMN,
    )
    grid.add_row()
    grid.add_row(TabCell("What the numbers cannot say", style=CellStyle.SECTION))
    for line in _cannot_say_lines_of(counts):
        grid.add_note(line, _NOTE_LAST_COLUMN)
    grid.add_row()
    grid.add_row(TabCell("Terms", style=CellStyle.SECTION))
    for term, meaning in TERM_MEANINGS:
        # As a note it runs over the cells to its right without widening the column Left.
        grid.add_row(TabCell(term), TabCell(meaning, style=CellStyle.NOTE))
    grid.add_row()
    all_hold_row = grid.add_row(TabCell(ALL_CHECKS_HOLD_LABEL, style=CellStyle.SECTION))
    grid.add_row()

    method_and_checks.add_section("Formulas against the counts of Python")
    for tab in checked_tabs.grids_with_formulas():
        runs = tab.numeric_formula_runs()
        python_copy_name = f"{tab.name}{PYTHON_COPY_TAB_SUFFIX}"
        method_and_checks.add_check(
            f"{tab.name}: cells that differ from {python_copy_name}",
            TabCell(
                0,
                formula="+".join(
                    f"SUMPRODUCT((ABS({tab.range_of(column, first_row, last_row)}-{tab_range_of(python_copy_name, column, first_row, last_row)})>0.000000001)*1)"
                    for column, first_row, last_row in runs
                ),
                style=CellStyle.COUNT,
            ),
            TabCell(0, style=CellStyle.COUNT),
            f"{sum(last - first + 1 for _, first, last in runs):,} formula cells",
        )

    method_and_checks.add_section("Sums and order")
    _add_sum_and_order_checks(method_and_checks, counts, row_tabs, checked_tabs)

    method_and_checks.add_section("Checks that Python made on the full files")
    _add_python_checks(method_and_checks, row_files, counts, row_tabs, chosen_rows)
    grid.rows[all_hold_row - 1].append(
        TabCell(
            True,
            formula="AND("
            + ",".join(f"D{row}" for row in method_and_checks.check_rows)
            + ")",
            style=CellStyle.HOLDS,
        )
    )
    grid.add_row()

    _add_premise_table(grid, counts)
    grid.add_row()
    _add_catalog_review_table(grid, counts, row_tabs)
    grid.add_row()
    _add_judgment_rule_table(grid, row_files)
    grid.fixed_column_widths = {1: 80, 2: 12, 3: 12, 4: 12, 5: 80}
    return grid


def _add_sum_and_order_checks(
    method_and_checks: MethodAndChecksTab,
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    checked_tabs: CheckedTabs,
) -> None:
    """Add the checks that hold the counts of one tab against another, or one count against another that bounds it."""
    tasks = checked_tabs.tasks
    columns = tasks.columns
    chart_data = checked_tabs.chart_data
    trial_rows = row_tabs.trial_rows
    measure_rows = row_tabs.trial_category_measure_rows
    trial_count = len(counts.task_by_trial_id)
    trial_rows_count_cell = TabCell(
        trial_count, formula=trial_count_formula_of(row_tabs), style=CellStyle.COUNT
    )
    lower_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
    upper_ids = counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.UPPER]
    lower_count_cell = TabCell(
        len(lower_ids),
        formula=request_trial_count_formula_of(row_tabs, CountedBound.LOWER),
        style=CellStyle.COUNT,
    )
    method_and_checks.add_check(
        "Tasks: trials = rows of trial_rows",
        TabCell(
            trial_count,
            formula=f"SUM({tasks.column_range(columns.trials)})",
            style=CellStyle.COUNT,
        ),
        trial_rows_count_cell,
        "Also the tasks without a request",
    )
    method_and_checks.add_check(
        "trial_rows: rows by request bound = rows",
        TabCell(
            trial_count,
            formula="+".join(
                count_ifs_formula(
                    trial_rows,
                    [("any_category_request_measure_bound", equal_to(bound.value))],
                )
                for bound in MeasureBound
            ),
            style=CellStyle.COUNT,
        ),
        trial_rows_count_cell,
        "",
    )
    method_and_checks.add_check(
        "Tasks: trials of the lower bound, summed = trial_rows",
        TabCell(
            None,
            formula=f"SUMPRODUCT({tasks.column_range(columns.request)},{tasks.column_range(columns.trials)})",
            style=CellStyle.COUNT,
        ),
        lower_count_cell,
        "Shares times trials, so to 0.000001",
        holds_formula_template="ABS(B{row}-C{row})<0.000001",
    )
    request_range = tasks.column_range(columns.request)
    category_ranges = [
        tasks.column_range(column) for column in columns.column_by_category.values()
    ]
    method_and_checks.add_zero_check(
        "Tasks: a category above Request, or Request above the sum of the categories",
        [
            *(
                f"SUMPRODUCT(({category_range}>{request_range})*1)"
                for category_range in category_ranges
            ),
            f"SUMPRODUCT(({request_range}>{'+'.join(category_ranges) or '0'}+0.000000001)*1)",
        ],
        "Lower bounds",
    )
    category_range = chart_data.grid.range_of(
        1, chart_data.categories.first_row, chart_data.categories.last_row
    )
    category_trials_range = chart_data.grid.range_of(
        2, chart_data.categories.first_row, chart_data.categories.last_row
    )

    def category_count_formula_of(category: str) -> str:
        return f"SUMIFS({category_trials_range},{category_range},{equal_to(category)})"

    registries_and_hosts_trial_count = len(checked_tabs.registries_and_hosts.trial_ids)
    method_and_checks.add_check(
        "Registries and hosts: trials of all lines (Python) = network_request_rows",
        TabCell(registries_and_hosts_trial_count, style=CellStyle.PYTHON_COUNT),
        TabCell(
            registries_and_hosts_trial_count,
            formula=count_unique_ifs_formula(
                row_tabs.network_request_rows,
                "trial_id",
                [
                    ("sender", equal_to(TASK_ENVIRONMENT)),
                    ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
                    (
                        "category",
                        not_equal_to(NetworkRequestCategory.CONNECTIVITY_CHECK),
                    ),
                ],
            ),
            style=CellStyle.COUNT,
        ),
        "Lower-bound requests from the task environment that are no connectivity checks",
    )
    requested_item_trial_ids_by_category: dict[str, set[str]] = {}
    for key, trial_ids in counts.requested_item_trial_ids.items():
        requested_item_trial_ids_by_category.setdefault(
            key.registry_or_host_service_line_key.category, set()
        ).update(trial_ids)
    method_and_checks.add_zero_check(
        "Requested items: categories whose trials (Python) differ from Chart data",
        [
            f"(ABS({len(requested_item_trial_ids_by_category.get(category, set()))}-{category_count_formula_of(category)})>0)"
            for category in sorted(
                set(requested_item_trial_ids_by_category)
                | set(chart_data.category_trial_cells)
            )
        ],
        "From network_request_rows.csv against trial_category_measure_rows",
    )
    web_tools = checked_tabs.web_tools
    method_and_checks.add_zero_check(
        "Web tools: known senders whose lines sum below their trials or have a line above them",
        _group_line_violation_terms_of(
            web_tools,
            set(KNOWN_OUTSIDE_SENDERS),
            lambda sender: count_unique_ifs_formula(
                measure_rows,
                "trial_id",
                [
                    ("sender", equal_to(sender)),
                    ("request_measure_bound", equal_to(LOWER_AND_UPPER)),
                ],
            ),
        ),
        "Lower bounds. A trial may be in two lines",
    )
    bounds = checked_tabs.bounds
    method_and_checks.add_check(
        "Bounds: trials by cause = trials only in the upper bound",
        TabCell(
            len(upper_ids - lower_ids),
            formula=f"'{bounds.grid.name}'!{bounds.cause_total_cell}",
            style=CellStyle.COUNT,
        ),
        TabCell(
            len(upper_ids - lower_ids),
            formula=count_ifs_formula(
                trial_rows,
                [("any_category_request_measure_bound", equal_to(UPPER_ONLY))],
            ),
            style=CellStyle.COUNT,
        ),
        "Each trial by its first cause. The total sums the causes",
    )
    method_and_checks.add_check(
        "Bounds: trials by result = trials of the lower bound",
        TabCell(
            len(lower_ids),
            formula=f"SUM({bounds.result_trials_range()})",
            style=CellStyle.COUNT,
        ),
        lower_count_cell,
        "Each trial by the furthest of its requests",
    )


def _group_line_violation_terms_of(
    lines_tab: TrialCountLinesTab,
    groups: set[str],
    count_formula_of: Callable[[str], str],
) -> list[str]:
    """Give a term per group, e.g. a category, that is above 0 when the lines of the group sum below its count or one line is above it.

    The groups come from both sides, so a group with lines and no count fails as one with a count and no lines does.
    """
    group_range = lines_tab.column_range(lines_tab.category_or_sender_column)
    trials_range = lines_tab.column_range(lines_tab.trials_column)
    return [
        f"(SUMIFS({trials_range},{group_range},{equal_to(group)})<{count_formula_of(group)})"
        f"+(MAXIFS({trials_range},{group_range},{equal_to(group)})>{count_formula_of(group)})"
        for group in sorted(groups)
    ]


def _add_python_checks(
    method_and_checks: MethodAndChecksTab,
    row_files: RowFiles,
    counts: SpreadsheetPythonCounts,
    row_tabs: SpreadsheetRowTabs,
    chosen_rows: ChosenNetworkRequestRows,
) -> None:
    """Add the checks that only Python can make, on the full files of the run."""
    run_counts = {
        line["count_name"]: int(line["count"])
        for line in _plain_csv_dicts_of(row_files.summary)
    }
    method_and_checks.add_check(
        "trial_rows: rows = summary.csv of the run",
        TabCell(
            len(counts.task_by_trial_id),
            formula=trial_count_formula_of(row_tabs),
            style=CellStyle.COUNT,
        ),
        TabCell(run_counts["trial_rows"], style=CellStyle.PYTHON_COUNT),
        "",
    )
    method_and_checks.add_check(
        "equations.csv of the run: equations that do not hold",
        TabCell(
            sum(
                1
                for line in _plain_csv_dicts_of(row_files.equations)
                if line["holds"] != "yes"
            ),
            style=CellStyle.PYTHON_COUNT,
        ),
        TabCell(0, style=CellStyle.COUNT),
        "Each holds counts of two steps against each other",
    )
    method_and_checks.add_check(
        "task_category_measures.csv: lines that differ from trial_category_measure_rows",
        TabCell(
            differing_task_category_measure_line_count_of(row_files, counts),
            style=CellStyle.PYTHON_COUNT,
        ),
        TabCell(0, style=CellStyle.COUNT),
        "The count of each task that run_pipeline.py wrote",
    )
    request_rows = row_tabs.network_request_rows
    method_and_checks.add_check(
        "network_request_rows: rows = chosen rows of network_request_rows.csv",
        TabCell(
            len(chosen_rows.rows),
            formula=f"COUNTA({request_rows.column_range('trial_id')})",
            style=CellStyle.COUNT,
        ),
        TabCell(len(chosen_rows.rows), style=CellStyle.PYTHON_COUNT),
        f"Lower bound or web tool, of {chosen_rows.file_row_count:,} rows",
    )
    method_and_checks.add_check(
        "network_request_rows.csv: rows a formula reads that this file lacks",
        TabCell(
            chosen_rows.left_out_row_count_read_by_formulas,
            style=CellStyle.PYTHON_COUNT,
        ),
        TabCell(0, style=CellStyle.COUNT),
        "",
    )
    chosen_lower_trial_ids = {
        row["trial_id"]
        for row in chosen_rows.rows
        if row["sender"] == TASK_ENVIRONMENT
        and row["request_measure_bound"] == LOWER_AND_UPPER
    }
    method_and_checks.add_check(
        "Trials in the lower bound without their rows in this file",
        TabCell(
            len(
                counts.any_category_trial_ids[MainMeasure.REQUEST, CountedBound.LOWER]
                - chosen_lower_trial_ids
            ),
            style=CellStyle.PYTHON_COUNT,
        ),
        TabCell(0, style=CellStyle.COUNT),
        "",
    )


def _add_premise_table(grid: TabGrid, counts: SpreadsheetPythonCounts) -> None:
    """Add whether the tasks of each benchmark version have the same trials per harness, which comparing them rests on."""
    grid.add_row(
        TabCell(
            "Premises of comparing tasks (counted by Python)", style=CellStyle.SECTION
        )
    )
    grid.add_note(
        "Shares of tasks compare only where every task ran the same harnesses the same number of times, i.e. within a version whose last column is 0.",
        _NOTE_LAST_COLUMN,
    )
    grid.add_row(
        *(
            TabCell(text, style=CellStyle.HEADER)
            for text in (
                "benchmark_version",
                "Tasks",
                "Trials per task, fewest",
                "Trials per task, most",
                "Tasks whose trials per harness differ from those of the first task",
            )
        )
    )
    for version in sorted({task[0] for task in counts.tasks}):
        version_tasks = [task for task in counts.tasks if task[0] == version]
        trials_per_harness = [
            Counter(
                counts.harness_by_trial_id[trial_id]
                for trial_id in counts.trial_ids_of_task(task)
            )
            for task in version_tasks
        ]
        trial_counts = [len(counts.trial_ids_of_task(task)) for task in version_tasks]
        grid.add_row(
            TabCell(version),
            TabCell(len(version_tasks), style=CellStyle.PYTHON_COUNT),
            TabCell(min(trial_counts), style=CellStyle.PYTHON_COUNT),
            TabCell(max(trial_counts), style=CellStyle.PYTHON_COUNT),
            TabCell(
                sum(
                    1
                    for harness_counts in trials_per_harness
                    if harness_counts != trials_per_harness[0]
                ),
                style=CellStyle.PYTHON_COUNT,
            ),
        )


_CATALOGS_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "tb_internet_use"
    / "knowledge"
    / "catalogs"
)


def _add_catalog_review_table(
    grid: TabGrid, counts: SpreadsheetPythonCounts, row_tabs: SpreadsheetRowTabs
) -> None:
    """Add the limits that no check can show and the reviewed rows of each catalog."""
    grid.add_row(TabCell("What the rows rest on", style=CellStyle.SECTION))
    for text in (
        *(
            f"The trajectories of {harness} lack {missing_calls}, so its trials count fewer requests than they sent."
            for harness, missing_calls in _missing_calls_by_harness_of_run(
                counts
            ).items()
        ),
        (
            "This is the one list of harnesses whose trajectories lack calls that the tabs use. "
            if _missing_calls_by_harness_of_run(counts)
            else "No harness of this run is known to have trajectories that lack calls. "
        )
        + f"They take those of {', '.join(_harnesses_taken_to_hold_every_call_of(counts))} to hold every call.",
        "A request of a program that no catalog row covers, sent without a public URL in its words, is in no bound. A request of a script or binary whose content the trajectory does not show is in no bound either.",
        f"The tab {row_tabs.network_request_rows.name} holds only the rows whose request_measure_bound is lower_and_upper and the rows of web tools. The other rows are in network_request_rows.csv of the run folder.",
        "A host_service of unknown is a public host without a row of public_hosts.csv, and a sender of unknown a web tool without a row of harness_web_tools.csv. They are shown as they are.",
        "Each fact of a catalog says what it was checked against, and a person marks it reviewed. The steps use facts that no person reviewed yet.",
    ):
        grid.add_note(text, _NOTE_LAST_COLUMN)
    grid.add_row(
        *(
            TabCell(text, style=CellStyle.HEADER)
            for text in ("Catalog", "Rows", "Reviewed rows")
        )
    )
    for catalog_path in sorted(_CATALOGS_DIR.glob("*/*.csv")):
        catalog_rows = _plain_csv_dicts_of(catalog_path)
        grid.add_row(
            TabCell(f"{catalog_path.parent.name}/{catalog_path.name}"),
            TabCell(len(catalog_rows), style=CellStyle.PYTHON_COUNT),
            TabCell(
                sum(1 for row in catalog_rows if row.get("reviewed") == "yes"),
                style=CellStyle.PYTHON_COUNT,
            ),
        )


def _cannot_say_lines_of(counts: SpreadsheetPythonCounts) -> list[str]:
    """Give the lines of what the numbers cannot say, with one line per harness of the run whose trajectories lack calls."""
    missing_calls_by_harness = _missing_calls_by_harness_of_run(counts)
    return [
        *_CANNOT_SAY_LINES_BEFORE_HARNESSES,
        *(
            f"All requests of {harness}, whose trajectories lack {missing_calls}. Its trials count fewer requests than they sent."
            for harness, missing_calls in missing_calls_by_harness.items()
        ),
        *(
            []
            if missing_calls_by_harness
            else [
                "No harness of this run is known to have trajectories that lack calls."
            ]
        ),
        *_CANNOT_SAY_LINES_AFTER_HARNESSES,
    ]


def _missing_calls_by_harness_of_run(counts: SpreadsheetPythonCounts) -> dict[str, str]:
    """Give what the trajectory lacks of each harness of `MISSING_CALLS_BY_HARNESS` that has a trial in the run."""
    harnesses = set(counts.harness_by_trial_id.values())
    return {
        harness: missing_calls
        for harness, missing_calls in MISSING_CALLS_BY_HARNESS.items()
        if harness in harnesses
    }


def _harnesses_taken_to_hold_every_call_of(
    counts: SpreadsheetPythonCounts,
) -> list[str]:
    """Give the harnesses of the run outside `MISSING_CALLS_BY_HARNESS`, so that the note names a new harness taken to hold every call."""
    return sorted(
        set(counts.harness_by_trial_id.values()) - set(MISSING_CALLS_BY_HARNESS)
    )


def _add_judgment_rule_table(grid: TabGrid, row_files: RowFiles) -> None:
    """Add every judgment rule with its uses from `<step package>/judgment_rule_uses.csv` of the run."""
    grid.add_row(
        TabCell(
            "Judgment rules (choices that facts alone do not settle, as the run counted them)",
            style=CellStyle.SECTION,
        )
    )
    grid.add_note(
        "A provisional rule keeps the choice of earlier code, or the choice that claims least, so that lower bounds stay true. The user decides rules in the order of their uses.",
        _NOTE_LAST_COLUMN,
    )
    grid.add_row(
        *(
            TabCell(text, style=CellStyle.HEADER)
            for text in ("Rule", "Uses", "Trials", "Decided or provisional", "Step")
        )
    )
    for step_package, judgment_rules in JUDGMENT_RULES_BY_STEP_PACKAGE.items():
        uses_path = row_files.run_dir / step_package / "judgment_rule_uses.csv"
        uses = (
            {line["judgment_rule"]: line for line in _plain_csv_dicts_of(uses_path)}
            if uses_path.exists()
            else {}
        )
        for name in judgment_rule_names_of(judgment_rules):
            line = uses.get(name)
            grid.add_row(
                TabCell(name),
                TabCell(
                    int(line["use_count"]) if line else None,
                    style=CellStyle.PYTHON_COUNT,
                ),
                TabCell(
                    int(line["trial_count"]) if line else None,
                    style=CellStyle.PYTHON_COUNT,
                ),
                TabCell(_judgment_rule_mark_of(getattr(judgment_rules, name))),
                TabCell(step_package),
            )


def _judgment_rule_mark_of(judgment_rule: object) -> str:
    """Give `Decided` or `Provisional` from the last docstring paragraph of a judgment rule."""
    last_paragraph = (
        (getattr(judgment_rule, "__doc__", None) or "").strip().split("\n\n")[-1]
    )
    for mark in ("Decided", "Provisional"):
        if last_paragraph.strip().startswith(f"{mark}."):
            return mark
    raise ValueError(f"judgment rule without a mark: {judgment_rule!r}")


def _plain_csv_dicts_of(csv_path: Path) -> list[dict[str, str]]:
    """Read a CSV of the run or of a catalog, whose columns no row type fixes."""
    with csv_path.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))
