"""Test `check_spreadsheet_formulas.py` on made-up spreadsheet files."""

from pathlib import Path
from typing import Any

import pytest
from conftest import script_module
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.worksheet.worksheet import Worksheet

check_spreadsheet_formulas = script_module("check_spreadsheet_formulas")
spreadsheet_cells = script_module("spreadsheet_cells")
spreadsheet_tabs = script_module("spreadsheet_tabs")

_ROWS = [
    ("name", "bound", "reward"),
    ("a", "lower_and_upper", 1.0),
    ("A", "upper_only", 0.5),
    ("b", "neither", None),
    (None, "lower_and_upper", 1),
    ("b", "lower_and_upper", 0),
]

# Formulas over `rows` and the values Google Sheets gives them.
COMPUTED_FORMULA_CASES = [
    pytest.param(
        'COUNTIFS(rows!$A$2:$A$6,"a")', 2, id="text criterion ignores letter case"
    ),
    pytest.param('COUNTIFS(rows!$A$2:$A$6,"<>")', 4, id="<> matches filled cells"),
    pytest.param('COUNTIFS(rows!$A$2:$A$6,"")', 1, id="empty text matches empty cells"),
    pytest.param(
        'COUNTIFS(rows!$A$2:$A$6,"<>b")', 3, id="<>text also matches empty cells"
    ),
    pytest.param("COUNTIFS(rows!$C$2:$C$6,1)", 2, id="number matches 1 and 1.0"),
    pytest.param('COUNTIFS(rows!$C$2:$C$6,">0")', 3, id="comparison with a number"),
    pytest.param(
        'COUNTIFS(rows!$A$2:$A$6,"b",rows!$B$2:$B$6,"lower_and_upper")',
        1,
        id="every pair must hold",
    ),
    pytest.param(
        'COUNTIFS(rows!$B$2:$B$6,"<>neither",rows!$B$2:$B$6,"<>upper_only")',
        3,
        id="two criteria on one range",
    ),
    pytest.param(
        'COUNTUNIQUEIFS(rows!$A$2:$A$6,rows!$B$2:$B$6,"<>neither")',
        3,
        id="distinct values keep their case and skip empty cells",
    ),
    pytest.param(
        'SUMIFS(rows!$C$2:$C$6,rows!$B$2:$B$6,"lower_and_upper")', 2, id="SUMIFS"
    ),
    pytest.param(
        'MAXIFS(rows!$C$2:$C$6,rows!$B$2:$B$6,"<>lower_and_upper")', 0.5, id="MAXIFS"
    ),
    pytest.param("COUNTA(rows!$A$2:$A$6)", 4, id="COUNTA skips empty cells"),
    pytest.param(
        "SUMPRODUCT((ABS(rows!$C$2:$C$6-1)>0.1)*1)",
        3,
        id="elementwise arithmetic and comparison, an empty cell as 0",
    ),
    pytest.param(
        "SUMPRODUCT(rows!$C$2:$C$6,rows!$C$2:$C$6)", 2.25, id="SUMPRODUCT of two ranges"
    ),
    pytest.param('rows!A2&" "&rows!B2', "a lower_and_upper", id="joins texts"),
    pytest.param("AND(1=1,2>1)", True, id="AND"),
    pytest.param("AND(1=1,2<1)", False, id="AND with a false argument"),
    pytest.param('IF(rows!C2=1,"yes","no")', "yes", id="IF gives its second argument"),
    pytest.param(
        'TEXT(21450,"#,##0")&" trials"',
        "21,450 trials",
        id="TEXT of a count with thousands separators",
    ),
    pytest.param(
        'IF(COUNTIFS(rows!$A$2:$A$6,"c")>0,1/0,"none")',
        "none",
        id="IF computes only the branch taken",
    ),
]


def _write_workbook(path: Path, tabs: dict[str, list[tuple[Any, ...]]]) -> Workbook:
    """Write tabs given as rows and give the workbook back for more changes."""
    workbook = Workbook()
    workbook.remove(workbook.worksheets[0])
    for name, rows in tabs.items():
        tab = workbook.create_sheet(name)
        for row in rows:
            tab.append(list(row))
    workbook.save(path)
    return workbook


def _computed_value_of(tmp_path: Path, formula: str) -> object:
    path = tmp_path / "book.xlsx"
    _write_workbook(path, {"front": [(f"={formula}",)], "rows": _ROWS})
    return check_spreadsheet_formulas.FormulaValues(
        check_spreadsheet_formulas.WrittenSpreadsheet.read(path)
    ).value_of("front", 1, 1)


@pytest.mark.parametrize(("formula", "expected_value"), COMPUTED_FORMULA_CASES)
def test_computes_a_formula_as_google_sheets_does(
    tmp_path: Path, formula: str, expected_value: object
):
    assert _computed_value_of(tmp_path, formula) == expected_value


@pytest.mark.parametrize(
    "formula",
    [
        pytest.param('COUNTIFS(rows!$A$2:$A$6,"a*")', id="wildcard criterion"),
        pytest.param("COUNTIF(rows!$A$2:$A$6,1)", id="function it does not know"),
        pytest.param('"a"="A"', id="comparison of texts"),
        pytest.param('IF("a",1,2)', id="IF on a text"),
        pytest.param('TEXT(1234,"0.0")', id="TEXT of another format"),
        pytest.param('TEXT(1.5,"#,##0")', id="TEXT of a fraction"),
    ],
)
def test_refuses_a_formula_it_cannot_compute_as_google_sheets_does(
    tmp_path: Path, formula: str
):
    with pytest.raises(ValueError):
        _computed_value_of(tmp_path, formula)


def test_counts_front_cells_that_differ_from_their_python_copy_and_checks_that_do_not_hold(
    tmp_path: Path,
):
    path = tmp_path / "book.xlsx"
    _write_workbook(
        path,
        {
            "Front": [("=1+1", "=2*2", '=SPARKLINE(A1:B1,{"charttype","bar"})')],
            spreadsheet_tabs.METHOD_AND_CHECKS_TAB_NAME: [
                ("=Front!A1=2", "=Front!B1=5", "=Front!A1+1")
            ],
            "Front (Python)": [(2, 5)],
        },
    )

    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(path)

    assert (formula_check.compared_cell_count, formula_check.differing_cell_count) == (
        2,
        1,
    )
    assert (formula_check.check_count, formula_check.failing_check_count) == (2, 1)
    assert check_spreadsheet_formulas.FormulaCheckLine("Front", "B1", 4, 5, False) in (
        formula_check.lines
    )


@pytest.mark.parametrize(
    ("label_rows", "value_rows", "is_aligned"),
    [
        pytest.param((2, 3), (2, 3), True, id="labels and values from the same rows"),
        pytest.param((2, 3), (1, 3), False, id="values from one row above the labels"),
        pytest.param((1, 3), (1, 3), False, id="the header among the rows"),
        pytest.param((2, 2), (2, 2), False, id="the last line left out"),
    ],
)
def test_a_chart_must_draw_numbers_from_every_row_of_its_labels(
    tmp_path: Path,
    label_rows: tuple[int, int],
    value_rows: tuple[int, int],
    is_aligned: bool,
):
    path = tmp_path / "book.xlsx"
    workbook = _write_workbook(
        path,
        {
            "Front": [("label", "count"), ("a", 1), ("b", 2)],
            spreadsheet_tabs.METHOD_AND_CHECKS_TAB_NAME: [("=1=1",)],
        },
    )
    front = workbook["Front"]
    assert isinstance(front, Worksheet)
    chart = BarChart()
    chart.add_data(
        Reference(front, min_col=2, min_row=value_rows[0], max_row=value_rows[1])
    )
    chart.set_categories(
        Reference(front, min_col=1, min_row=label_rows[0], max_row=label_rows[1])
    )
    chart.anchor = "D1"
    front.add_chart(chart)
    workbook.save(path)

    formula_check = check_spreadsheet_formulas.check_spreadsheet_formulas(path)

    assert formula_check.chart_count == 1
    assert formula_check.misaligned_chart_count == (0 if is_aligned else 1)
