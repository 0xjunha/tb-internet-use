"""Build a spreadsheet from the row files of a run of `run_pipeline.py` and check its formulas against counts made by Python.

Run it as `uv run python -I scripts/build_spreadsheet.py <run_dir>`. It writes under `<run_dir>/spreadsheet/` unless `--out-dir` names another folder. `docs/spreadsheet.md` describes the tabs.
"""

import argparse
import dataclasses
import sys
from pathlib import Path

# `python -I` leaves the folder of this script off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_spreadsheet_formulas import check_spreadsheet_formulas
from spreadsheet_cells import python_copy_of, write_spreadsheet
from spreadsheet_method_and_checks_tab import (
    CheckedTabs,
    lay_out_method_and_checks_tab,
)
from spreadsheet_overview_tab import lay_out_chart_data_tab, lay_out_overview_tab
from spreadsheet_python_counts import RowFiles, count_spreadsheet_values
from spreadsheet_result_tabs import (
    lay_out_bounds_tab,
    lay_out_registries_and_hosts_tab,
    lay_out_requested_items_tab,
    lay_out_tasks_tab,
    lay_out_web_tools_tab,
)
from spreadsheet_row_tabs import choose_network_request_rows, lay_out_row_tabs
from trial_folders_and_csv_files import write_csv

SPREADSHEET_FILE_NAME = "internet_use.xlsx"
FORMULA_CHECK_FILE_NAME = "formula_check.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    arguments = parser.parse_args()
    out_dir = arguments.out_dir or arguments.run_dir / "spreadsheet"
    out_dir.mkdir(parents=True, exist_ok=True)
    spreadsheet_path = out_dir / SPREADSHEET_FILE_NAME
    build_spreadsheet(RowFiles(arguments.run_dir), spreadsheet_path)
    formula_check = check_spreadsheet_formulas(spreadsheet_path)
    write_csv(
        out_dir / FORMULA_CHECK_FILE_NAME,
        formula_check.line_columns(),
        [dataclasses.astuple(line) for line in formula_check.lines],
    )
    print(formula_check.summary_text())
    print(f"written under {out_dir}")
    if not formula_check.is_passed():
        sys.exit(1)


def build_spreadsheet(row_files: RowFiles, spreadsheet_path: Path) -> None:
    """Count the values with Python, lay out the tabs and write the spreadsheet file."""
    counts = count_spreadsheet_values(row_files)
    chosen_rows = choose_network_request_rows(row_files)
    row_tabs = lay_out_row_tabs(row_files, counts, chosen_rows)
    tasks = lay_out_tasks_tab(counts, row_tabs)
    chart_data = lay_out_chart_data_tab(counts, row_tabs, tasks)
    checked_tabs = CheckedTabs(
        overview=lay_out_overview_tab(counts, row_tabs, tasks, chart_data),
        tasks=tasks,
        requested_items=lay_out_requested_items_tab(counts),
        registries_and_hosts=lay_out_registries_and_hosts_tab(counts, row_tabs),
        web_tools=lay_out_web_tools_tab(counts, row_tabs),
        bounds=lay_out_bounds_tab(counts, row_tabs),
        chart_data=chart_data,
    )
    method_and_checks = lay_out_method_and_checks_tab(
        row_files, counts, row_tabs, chosen_rows, checked_tabs
    )
    write_spreadsheet(
        spreadsheet_path,
        checked_tabs.front_grids(),
        row_tabs.all(),
        [
            method_and_checks,
            chart_data.grid,
            *(python_copy_of(tab) for tab in checked_tabs.grids_with_formulas()),
        ],
    )


if __name__ == "__main__":
    main()
