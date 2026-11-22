"""Test the spreadsheet built from the made-up run and its checks."""

from pathlib import Path
from typing import Any

import pytest
from conftest import script_module
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell

build_spreadsheet = script_module("build_spreadsheet")
check_spreadsheet_formulas = script_module("check_spreadsheet_formulas")
publish_spreadsheet = script_module("publish_spreadsheet")
spreadsheet_python_counts = script_module("spreadsheet_python_counts")
spreadsheet_cells = script_module("spreadsheet_cells")
spreadsheet_tabs = script_module("spreadsheet_tabs")


def _build(run_dir: Path, tmp_path: Path) -> Path:
    path = tmp_path / "internet_use.xlsx"
    build_spreadsheet.build_spreadsheet(
        spreadsheet_python_counts.RowFiles(run_dir), path
    )
    return path


@pytest.fixture
def spreadsheet_path(made_up_run_dir: Path, tmp_path: Path) -> Path:
    return _build(made_up_run_dir, tmp_path)


def _python_copy_rows_of(spreadsheet_path: Path, tab: str) -> list[list[object]]:
    """Give the rows of the Python copy of a tab, or of the tab when it holds no formulas and so has no copy."""
    workbook = load_workbook(spreadsheet_path, read_only=True)
    copy_name = f"{tab}{spreadsheet_cells.PYTHON_COPY_TAB_SUFFIX}"
    sheet = workbook[copy_name if copy_name in workbook.sheetnames else tab]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _lines_by_label(
    spreadsheet_path: Path, tab: str, label_columns: int = 1
) -> dict[str, list[object]]:
    """Give the rows of the Python copy of a tab by label, the last of a repeated label winning."""
    return {
        " ".join(str(cell) for cell in row[:label_columns]): row
        for row in _python_copy_rows_of(spreadsheet_path, tab)
        if len(row) > label_columns and isinstance(row[0], str)
    }


def _computed_rows_of_method_and_checks(spreadsheet_path: Path) -> list[list[object]]:
    """Compute the rows of `Method & checks` as Google Sheets would."""
    spreadsheet = check_spreadsheet_formulas.WrittenSpreadsheet.read(spreadsheet_path)
    formula_values = check_spreadsheet_formulas.FormulaValues(spreadsheet)
    tab_name = spreadsheet_tabs.METHOD_AND_CHECKS_TAB_NAME
    return [
        [formula_values.value_of(tab_name, row, column) for column in range(1, 6)]
        for row in range(1, len(spreadsheet.tabs[tab_name].values) + 1)
    ]


def _rows_from_header_of(
    spreadsheet_path: Path, tab: str, first_header: str
) -> list[list[object]]:
    """Give the rows of the Python copy of a tab from the header that starts with `first_header` to the next empty row."""
    rows = _python_copy_rows_of(spreadsheet_path, tab)
    header_index = next(
        index for index, row in enumerate(rows) if row and row[0] == first_header
    )
    table: list[list[object]] = []
    for row in rows[header_index:]:
        if not row or row[0] is None:
            break
        table.append(row)
    return table


def test_every_formula_gives_the_value_python_counted_every_check_holds_and_charts_align(
    spreadsheet_path: Path,
):
    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(
        spreadsheet_path
    )

    assert [line for line in formula_check.lines if not line.agrees] == []
    assert formula_check.chart_count == 3


def test_chart_data_holds_the_tables_of_the_three_charts_of_overview(
    spreadsheet_path: Path,
):
    chart_ranges = check_spreadsheet_formulas.chart_ranges_of(spreadsheet_path)

    # Categories with a trial in the lower bound, from the largest, ties in the order of the categories.
    assert _rows_from_header_of(spreadsheet_path, "Chart data", "Category") == [
        ["Category", "Trials", "% of trials"],
        ["package", 3, 3 / 8],
        ["content_fetch", 1, 1 / 8],
        ["remote_api_call", 1, 1 / 8],
        ["other_web", 1, 1 / 8],
    ]
    # Shares of the lower bound 0, 0, 1/2 and 2/3, of the upper bound 1/2, 0, 1 and 2/3.
    bands = _rows_from_header_of(
        spreadsheet_path, "Chart data", "% of trials with a request"
    )
    assert len(bands) == 11
    assert {row[0]: row[1:] for row in bands[1:] if row[1] or row[2]} == {
        "0–10%": [2, 1],
        "50–60%": [1, 1],
        "60–70%": [1, 1],
        "90–100%": [0, 1],
    }
    assert _rows_from_header_of(
        spreadsheet_path, "Chart data", "Solved without a request?"
    )[1:] == [
        ["yes", 2],
        ["maybe", 2],
        ["no", 0],
        ["never solved", 0],
    ]
    assert [
        [chart_range.cell_range for chart_range in ranges]
        for ranges in chart_ranges.values()
    ] == [
        ["'Chart data'!$A$2:$A$5", "'Chart data'!$C$2:$C$5"],
        [
            "'Chart data'!$A$8:$A$17",
            "'Chart data'!$B$8:$B$17",
            "'Chart data'!$A$8:$A$17",
            "'Chart data'!$C$8:$C$17",
        ],
        ["'Chart data'!$A$20:$A$23", "'Chart data'!$B$20:$B$23"],
    ]


def test_overview_places_its_three_charts_side_by_side_on_one_row(
    spreadsheet_path: Path,
):
    sheet = load_workbook(spreadsheet_path)["Overview"]
    # The types of openpyxl leave out the charts that a loaded tab holds.
    charts = sheet._charts  # pyright: ignore[reportAttributeAccessIssue]
    anchors = [chart.anchor._from for chart in charts]
    lefts = [anchor.col * 10**9 + anchor.colOff for anchor in anchors]

    assert len({anchor.row for anchor in anchors}) == 1
    assert lefts == sorted(lefts)
    assert len(set(lefts)) == 3


def test_publishing_reads_every_check_of_the_built_tab_back(spreadsheet_path: Path):
    computed_rows = _computed_rows_of_method_and_checks(spreadsheet_path)
    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(
        spreadsheet_path
    )

    check_read_back = publish_spreadsheet.check_read_back_of(computed_rows)
    # The formula check also counts the cell of all checks.
    assert (
        check_read_back.all_checks_hold_value,
        check_read_back.check_count,
        check_read_back.failing_checks,
    ) == (True, formula_check.check_count - 1, [])

    check_row = next(
        row for row in computed_rows if row[0] == "Tasks: trials = rows of trial_rows"
    )
    check_row[3] = "#NAME?"
    assert publish_spreadsheet.check_read_back_of(computed_rows).failing_checks == [
        "Tasks: trials = rows of trial_rows"
    ]


def test_only_the_python_copies_are_hidden_and_tabs_come_in_order(
    spreadsheet_path: Path,
):
    workbook = load_workbook(spreadsheet_path, read_only=True)

    assert {
        sheet.title for sheet in workbook.worksheets if sheet.sheet_state == "hidden"
    } == {
        title
        for title in workbook.sheetnames
        if title.endswith(spreadsheet_cells.PYTHON_COPY_TAB_SUFFIX)
    }
    assert [
        title
        for title in workbook.sheetnames
        if not title.endswith(spreadsheet_cells.PYTHON_COPY_TAB_SUFFIX)
    ] == [
        "Overview",
        "Tasks",
        "Requested items",
        "Registries and hosts",
        "Web tools",
        "Bounds",
        "trial_rows",
        "trial_category_measure_rows",
        "network_request_rows",
        "Method & checks",
        "Chart data",
    ]


def test_overview_shows_both_bounds_of_every_key_number(spreadsheet_path: Path):
    lines = _lines_by_label(spreadsheet_path, "Overview")

    # Of the lower-bound trials t1, t3 and t5, t5 requested other categories in the lower bound and t1 only in the upper, so only t3 installed nothing but packages in both columns.
    # Tasks 4-0-0 0 and a have half or more in the lower bound, 3-0-0 a also in the upper.
    # Tasks 4-0-0 a and 3-0-0 b were solved without a request, 4-0-0 0 and 3-0-0 a only by trials in the upper bound alone.
    # t3 and t8 searched through the provider. In the upper bound t6 also fetched through the harness and t4 has an unreadable trajectory.
    assert {
        label: lines[label][1:3]
        for label in (
            "Trials with an internet request from the task environment",
            "… of them, trials that only installed packages",
            "Tasks where at least half of the trials sent a request",
            "Solved tasks that were solved at least once without a request",
            "Trials with a web tool request sent from outside the task environment",
        )
    } == {
        "Trials with an internet request from the task environment": [3 / 8, 5 / 8],
        "… of them, trials that only installed packages": [1 / 3, 2 / 3],
        "Tasks where at least half of the trials sent a request": [2, 3],
        "Solved tasks that were solved at least once without a request": [2, 4],
        "Trials with a web tool request sent from outside the task environment": [
            2 / 8,
            4 / 8,
        ],
    }
    assert lines["… of them, trials that only installed packages"][3:] == []
    assert (
        lines["Solved tasks that were solved at least once without a request"][3]
        == "of 4 solved tasks, see Tasks"
    )


def test_overview_lists_each_tab_by_its_name_as_plain_text(spreadsheet_path: Path):
    sheet = load_workbook(spreadsheet_path)["Overview"]
    tab_names = set(load_workbook(spreadsheet_path, read_only=True).sheetnames)
    listed = [
        row[0]
        for row in sheet.iter_rows()
        if isinstance(row[0].value, str) and row[0].value in tab_names
    ]

    # Google Sheets shows a link to a tab as `#gid=…` in place of its text.
    assert len(listed) == 10
    assert [cell.hyperlink for cell in listed] == [None] * 10


def test_tasks_has_a_line_per_task_sorted_by_version_and_then_by_the_lower_bound(
    spreadsheet_path: Path,
):
    header, *lines = _rows_from_header_of(
        spreadsheet_path, "Tasks", "benchmark_version"
    )
    line_by_task = {f"{line[0]} {line[1]}": dict(zip(header, line)) for line in lines}

    assert list(line_by_task) == [
        "3-0-0 a",
        "3-0-0 b",
        "4-0-0 a",
        "4-0-0 0a",
    ]
    assert header[2:14] == [
        "Trials",
        "Request, lower bound",
        "Request bounds",
        "Request, upper bound",
        "package",
        "content_fetch",
        "remote_api_call",
        "other_web",
        "Web tool from outside",
        "Reward=1",
        "Reward=1 without a request",
        "Solved without a request?",
    ]
    # t5 failed a clone. t4 passed, unreadable, and t5 did not.
    assert line_by_task["4-0-0 0a"] == dict(
        zip(header, ["4-0-0", "0a", 2, 1 / 2, None, 1])
    ) | {
        "package": 1 / 2,
        "content_fetch": 1 / 2,
        "remote_api_call": 1 / 2,
        "other_web": 1 / 2,
        "Web tool from outside": 0,
        "Reward=1": 1,
        "Reward=1 without a request": 0,
        "Solved without a request?": "maybe",
        "Bar, lower bound": 1 / 2,
        "Bar, upper bound only": 1 / 2,
    }
    # t3 searched through the provider. t2 of Devin passed with no request.
    assert [
        line_by_task["4-0-0 a"][column]
        for column in (
            "Request, lower bound",
            "Web tool from outside",
            "Reward=1",
            "Reward=1 without a request",
            "Solved without a request?",
        )
    ] == [2 / 3, 1 / 3, 2, 1, "yes"]
    # t6 sent from outside only with the sender unknown, which is in no lower bound.
    assert line_by_task["3-0-0 a"]["Web tool from outside"] == 0


def test_requested_items_join_versions_of_one_package_and_count_tasks_that_share_it(
    spreadsheet_path: Path,
):
    # `requests` of t1 and `Requests` of t3, and the requirements file of t5.
    assert _rows_from_header_of(
        spreadsheet_path, "Requested items", "benchmark_version"
    )[1:] == [
        [
            "4-0-0",
            "0a",
            "package",
            "pypi",
            "(named_in_file)",
            1,
            1 / 2,
            1,
        ],
        [
            "4-0-0",
            "0a",
            "content_fetch",
            "code_hosting",
            "github.com",
            1,
            1 / 2,
            1,
        ],
        [
            "4-0-0",
            "0a",
            "remote_api_call",
            "web_api",
            "api.github.com",
            1,
            1 / 2,
            1,
        ],
        ["4-0-0", "0a", "other_web", "unknown", "b.org", 1, 1 / 2, 1],
        ["4-0-0", "a", "package", "pypi", "requests", 2, 2 / 3, 1],
    ]


def test_registries_and_hosts_count_tasks_and_trials_per_host_service_and_per_registry_or_host(
    spreadsheet_path: Path,
):
    lines = _lines_by_label(spreadsheet_path, "Registries and hosts")

    # Tasks and trials of the lower-bound requests from the task environment. pypi is asked by t1 and t3 of one task and t5 of another.
    assert {
        label: line[1:3] for label, line in lines.items() if isinstance(line[2], int)
    } == {
        "package_registry": [2, 3],
        "pypi": [2, 3],
        "code_hosting": [1, 1],
        "github.com": [1, 1],
        "web_api": [1, 1],
        "api.github.com": [1, 1],
        "unknown": [1, 1],
        "b.org": [1, 1],
    }


def test_registries_and_hosts_draw_the_bar_of_each_line_from_its_own_row_on_the_scale_of_its_table(
    spreadsheet_path: Path,
):
    sheet = load_workbook(spreadsheet_path)["Registries and hosts"]
    bar_formulas_by_row = {
        row_number: row[3].value
        for row_number, row in enumerate(sheet.iter_rows(), start=1)
        if len(row) > 3
        and isinstance(row[3].value, str)
        and "SPARKLINE" in row[3].value
    }

    # Four lines of host services, then one line in the table of each service.
    first_row = min(bar_formulas_by_row)
    assert len(bar_formulas_by_row) == 8
    for row, bar_formula in bar_formulas_by_row.items():
        scale = (
            f"MAX($C${first_row}:$C${first_row + 3})"
            if row < first_row + 4
            else f"MAX($C${row}:$C${row})"
        )
        assert f'SPARKLINE(C{row},{{"charttype","bar";"max",{scale};' in bar_formula


def test_bounds_draw_a_bar_per_line_on_the_scale_of_its_table_and_none_for_the_total(
    spreadsheet_path: Path,
):
    sheet = load_workbook(spreadsheet_path)["Bounds"]
    bar_formulas_by_label = {
        row[0].value: row[3].value
        for row in sheet.iter_rows()
        if isinstance(row[0].value, str) and len(row) > 3
    }
    scales = {
        bar_formula.split('"max",')[1].split(";")[0]
        for bar_formula in bar_formulas_by_label.values()
        if isinstance(bar_formula, str) and "SPARKLINE" in bar_formula
    }

    assert bar_formulas_by_label["Total"] is None
    assert "SPARKLINE(C" in str(bar_formulas_by_label["Received what it asked for"])
    # One scale for the causes and one for the results.
    assert len(scales) == 2


def test_web_tools_count_known_senders_in_the_lower_bound_and_unknown_in_the_upper(
    spreadsheet_path: Path,
):
    assert _rows_from_header_of(spreadsheet_path, "Web tools", "Harness")[1:] == [
        ["codex", "web_search_call", "provider_server", "search", 1, 1, 1],
        ["cursor-cli", "web_search_call", "provider_server", "search", 1, 1, 1],
        ["codex", "exec", "unknown", "content_fetch", 1, 1, 1],
        ["codex", "exec", "unknown", "search", 1, 1, 1],
    ]


def test_bounds_split_trials_only_in_the_upper_bound_by_cause_and_the_lower_bound_by_result(
    spreadsheet_path: Path,
):
    causes = _rows_from_header_of(spreadsheet_path, "Bounds", "Cause")
    results = _rows_from_header_of(spreadsheet_path, "Bounds", "Result")

    # t4 is unreadable and t6 runs `npx`.
    assert [row[1:3] for row in causes[1:]] == [
        ["missing", 1],
        [None, 0],
        [None, 0],
        [None, 0],
        ["npx", 1],
        [None, 0],
        [None, 0],
        [None, 2],
    ]
    # t1 received, t5 reached the server of a page, t3 shows nothing.
    assert [row[2:5] for row in results[1:]] == [
        [1, None, 1 / 8],
        [1, None, 1 / 8],
        [0, None, 0],
        [1, None, 1 / 8],
    ]


def test_holds_only_the_request_rows_in_the_lower_bound_and_those_of_web_tools(
    spreadsheet_path: Path,
):
    sheet = load_workbook(spreadsheet_path, read_only=True)["network_request_rows"]

    # The retries of t1 come first in the file, and the failure of t6 is only in the upper bound.
    assert [row[:5:4] for row in sheet.iter_rows(min_row=2, values_only=True)] == [
        ("t1", 3),
        ("t1", 4),
        ("t1", 0),
        ("t3", 0),
        ("t3", 1),
        ("t5", 0),
        ("t5", 1),
        ("t5", 2),
        ("t5", 3),
        ("t6", 1),
        ("t6", 2),
        ("t6", 3),
        ("t8", 0),
    ]


def _method_and_checks_texts_of(spreadsheet_path: Path) -> list[str]:
    sheet = load_workbook(spreadsheet_path, read_only=True)[
        spreadsheet_tabs.METHOD_AND_CHECKS_TAB_NAME
    ]
    return [
        row[0]
        for row in sheet.iter_rows(values_only=True)
        if row and isinstance(row[0], str)
    ]


def test_names_only_the_harnesses_of_the_run_whose_trajectories_lack_calls(
    spreadsheet_path: Path,
):
    texts = _method_and_checks_texts_of(spreadsheet_path)
    harness_texts = [
        text for text in texts if "lack" in text and "trajectories" in text
    ]

    # The run has devin and cursor-cli of the harnesses that lack calls, and claude-code and codex outside them.
    assert harness_texts == [
        "All requests of devin, whose trajectories lack the calls of subagents and those before a compaction. Its trials count fewer requests than they sent.",
        "All requests of cursor-cli, whose trajectories lack the inner calls of subagents. Its trials count fewer requests than they sent.",
        "The trajectories of devin lack the calls of subagents and those before a compaction, so its trials count fewer requests than they sent.",
        "The trajectories of cursor-cli lack the inner calls of subagents, so its trials count fewer requests than they sent.",
        "This is the one list of harnesses whose trajectories lack calls that the tabs use. They take those of claude-code, codex to hold every call.",
    ]


def test_says_when_no_harness_of_the_run_lacks_calls(
    made_up_run_dir: Path, tmp_path: Path
):
    trial_rows = made_up_run_dir / "trial_rows.csv"
    trial_rows.write_text(
        trial_rows.read_text()
        .replace(",devin,", ",claude-code,")
        .replace(",cursor-cli,", ",codex,")
    )

    texts = _method_and_checks_texts_of(_build(made_up_run_dir, tmp_path))

    assert (
        "No harness of this run is known to have trajectories that lack calls." in texts
    )
    assert (
        "No harness of this run is known to have trajectories that lack calls. They take those of claude-code, codex to hold every call."
        in texts
    )
    assert not [text for text in texts if "devin" in text or "cursor-cli" in text]


def test_a_check_fails_when_an_equation_of_the_run_does_not_hold(
    made_up_run_dir: Path, tmp_path: Path
):
    equations = made_up_run_dir / "equations.csv"
    equations.write_text(equations.read_text().replace(",yes", ",no"))

    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(
        _build(made_up_run_dir, tmp_path)
    )

    # The check of the equations and the cell of all checks.
    assert formula_check.failing_check_count == 2


def _set_cell_in_tab_and_copy(
    spreadsheet_path: Path,
    tab: str,
    row_label: tuple[object, ...],
    column: int,
    value: int,
) -> None:
    """Set a plain value in a tab and its Python copy, in the first row whose first cells are `row_label`."""
    workbook = load_workbook(spreadsheet_path)
    for tab_name in (tab, f"{tab}{spreadsheet_cells.PYTHON_COPY_TAB_SUFFIX}"):
        if tab_name not in workbook.sheetnames:
            continue
        row = next(
            row
            for row in workbook[tab_name].iter_rows()
            if tuple(cell.value for cell in row[: len(row_label)]) == row_label
        )
        cell = row[column - 1]
        assert isinstance(cell, Cell)
        cell.value = value
    workbook.save(spreadsheet_path)


def _failing_checks_of(spreadsheet_path: Path) -> list[str]:
    return publish_spreadsheet.check_read_back_of(
        _computed_rows_of_method_and_checks(spreadsheet_path)
    ).failing_checks


def test_a_check_fails_when_the_request_rows_of_a_trial_of_registries_and_hosts_become_connectivity_checks(
    spreadsheet_path: Path,
):
    workbook = load_workbook(spreadsheet_path)
    sheet = workbook["network_request_rows"]
    columns = [cell.value for cell in sheet[1]]
    # t3 has only package requests, so without them it is in no line of the tab.
    for row in sheet.iter_rows(min_row=2):
        if row[columns.index("trial_id")].value == "t3":
            category_cell = row[columns.index("category")]
            assert isinstance(category_cell, Cell)
            category_cell.value = "connectivity_check"
    workbook.save(spreadsheet_path)

    assert (
        "Registries and hosts: trials of all lines (Python) = network_request_rows"
        in _failing_checks_of(spreadsheet_path)
    )


def test_a_check_fails_when_a_cause_of_bounds_changes(spreadsheet_path: Path):
    _set_cell_in_tab_and_copy(
        spreadsheet_path, "Bounds", ("The trajectory could not be read",), 3, 2
    )

    assert (
        "Bounds: trials by cause = trials only in the upper bound"
        in _failing_checks_of(spreadsheet_path)
    )


def test_a_check_fails_when_a_line_of_web_tools_is_above_the_trials_of_its_sender(
    spreadsheet_path: Path,
):
    # provider_server has 2 trials, t3 and t8.
    _set_cell_in_tab_and_copy(
        spreadsheet_path, "Web tools", ("codex", "web_search_call"), 5, 3
    )

    assert (
        "Web tools: known senders whose lines sum below their trials or have a line above them"
        in _failing_checks_of(spreadsheet_path)
    )


def test_a_check_fails_when_a_formula_differs_from_its_python_copy(
    spreadsheet_path: Path,
):
    workbook = load_workbook(spreadsheet_path)
    python_copy = workbook[f"Tasks{spreadsheet_cells.PYTHON_COPY_TAB_SUFFIX}"]
    trials = next(row[2] for row in python_copy.iter_rows() if row[1].value == "b")
    assert isinstance(trials, Cell)
    assert isinstance(trials.value, int)
    trials.value = trials.value + 1
    workbook.save(spreadsheet_path)

    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(
        spreadsheet_path
    )

    # The cell, the check of Tasks and the cell of all checks.
    assert formula_check.differing_cell_count == 1
    assert formula_check.failing_check_count == 2


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("4.1", id="number"),
        pytest.param("3-0-0", id="date"),
        pytest.param("TRUE", id="boolean"),
        pytest.param("<a", id="operator"),
        pytest.param("a*", id="wildcard"),
    ],
)
def test_refuses_a_criterion_that_google_sheets_would_not_read_as_plain_text(
    value: str,
):
    with pytest.raises(ValueError, match="plain text"):
        spreadsheet_cells.equal_to(value)


def test_writes_a_criterion_of_plain_text_quoted():
    assert spreadsheet_cells.equal_to('4-0-0 terminal-bench/"a"') == (
        '"4-0-0 terminal-bench/""a"""'
    )
    assert spreadsheet_cells.not_equal_to("neither") == '"<>neither"'


def test_refuses_lines_whose_keys_differ_only_in_letter_case():
    with pytest.raises(ValueError, match="letter case"):
        spreadsheet_cells.refuse_keys_equal_apart_from_case(
            [("devin", "WebFetch"), ("devin", "webfetch")]
        )
    spreadsheet_cells.refuse_keys_equal_apart_from_case(
        [("claude-code", "WebFetch"), ("devin", "webfetch")]
    )


@pytest.fixture
def one_version_spreadsheet_path(one_version_run_dir: Path, tmp_path: Path) -> Path:
    return _build(one_version_run_dir, tmp_path)


def test_with_one_version_every_formula_gives_the_value_python_counted_and_every_check_holds(
    one_version_spreadsheet_path: Path,
):
    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(
        one_version_spreadsheet_path
    )

    assert [line for line in formula_check.lines if not line.agrees] == []
    assert formula_check.chart_count == 3


def test_with_one_version_tasks_and_requested_items_name_a_task_by_task_name_alone(
    one_version_spreadsheet_path: Path,
):
    tasks_header, *task_lines = _rows_from_header_of(
        one_version_spreadsheet_path, "Tasks", "task_name"
    )
    items_header, *item_lines = _rows_from_header_of(
        one_version_spreadsheet_path, "Requested items", "task_name"
    )

    assert "benchmark_version" not in tasks_header + items_header
    # One version, so the lines go by the lower bound alone, and c and d of no request by name.
    assert [(line[0], line[2]) for line in task_lines] == [
        ("a", 2 / 3),
        ("0a", 1 / 2),
        ("c", 0),
        ("d", 0),
    ]
    assert item_lines[-1] == [
        "a",
        "package",
        "pypi",
        "requests",
        2,
        2 / 3,
        1,
    ]


def test_trial_rows_name_a_task_as_tasks_does(spreadsheet_path: Path):
    # The formulas of `Tasks` match its names to the `task_key` of the row tabs, which the formula check holds.
    header, *trial_lines = _rows_from_header_of(
        spreadsheet_path, "trial_rows", "trial_id"
    )
    task_name_index = header.index("task_name")

    assert {line[task_name_index] for line in trial_lines} == {"a", "b", "0a"}


def _column_by_header(sheet: Any, header_row: int) -> dict[str, str]:
    return {
        cell.value: cell.column_letter
        for cell in sheet[header_row]
        if isinstance(cell.value, str)
    }


def _header_row_of(sheet: Any, first_header: str) -> int:
    return next(row[0].row for row in sheet.iter_rows() if row[0].value == first_header)


@pytest.mark.parametrize(
    ("spreadsheet_fixture", "first_header"),
    [
        ("spreadsheet_path", "benchmark_version"),
        ("one_version_spreadsheet_path", "task_name"),
    ],
)
def test_frozen_panes_filters_hidden_columns_color_scales_and_bars_of_tasks_follow_its_headers(
    spreadsheet_fixture: str, first_header: str, request: pytest.FixtureRequest
):
    sheet = load_workbook(request.getfixturevalue(spreadsheet_fixture))["Tasks"]
    header_row = _header_row_of(sheet, first_header)
    column = _column_by_header(sheet, header_row)
    first_row, last_row = header_row + 1, sheet.max_row

    # The question above the header spans the frozen columns, which with one version is column A alone.
    assert {str(r) for r in sheet.merged_cells.ranges if r.min_row == 2} == (
        {"A2:B2"} if column["task_name"] == "B" else set()
    )
    assert sheet.freeze_panes == f"{column['Trials']}{first_row}"
    assert sheet.auto_filter.ref == (
        f"A{header_row}:{column['Solved without a request?']}{last_row}"
    )
    assert {
        letter
        for letter, dimension in sheet.column_dimensions.items()
        if dimension.hidden
    } == {column["Bar, lower bound"], column["Bar, upper bound only"]}
    assert [str(r.sqref) for r in sheet.conditional_formatting] == [
        f"{column['Request, lower bound']}{first_row}:{column['Request, lower bound']}{last_row}",
        f"{column['Request, upper bound']}{first_row}:{column['Web tool from outside']}{last_row}",
    ]
    assert sheet[f"{column['Request bounds']}{first_row}"].value.startswith(
        f"=SPARKLINE({column['Bar, lower bound']}{first_row}:{column['Bar, upper bound only']}{first_row},"
    )


@pytest.mark.parametrize(
    ("spreadsheet_fixture", "first_header"),
    [
        ("spreadsheet_path", "benchmark_version"),
        ("one_version_spreadsheet_path", "task_name"),
    ],
)
def test_frozen_pane_filter_and_color_scale_of_requested_items_follow_its_headers(
    spreadsheet_fixture: str, first_header: str, request: pytest.FixtureRequest
):
    sheet = load_workbook(request.getfixturevalue(spreadsheet_fixture))[
        "Requested items"
    ]
    header_row = _header_row_of(sheet, first_header)
    column = _column_by_header(sheet, header_row)
    first_row, last_row = header_row + 1, sheet.max_row

    assert sheet.freeze_panes == f"A{first_row}"
    assert sheet.auto_filter.ref == (
        f"A{header_row}:{column['Tasks that requested it']}{last_row}"
    )
    assert [str(r.sqref) for r in sheet.conditional_formatting] == [
        f"{column["% of the task's trials"]}{first_row}:{column["% of the task's trials"]}{last_row}"
    ]
