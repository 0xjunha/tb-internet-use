"""Write tabs of cells as an XLSX file for Google Sheets, and give the text of formulas and criteria.

What each cell means lives in the modules that lay out the tabs, e.g. `spreadsheet_result_tabs.py`.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, Cell
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.legend import Legend
from openpyxl.chart.series_factory import SeriesFactory
from openpyxl.comments import Comment
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SPREADSHEET_TITLE = "Terminal-Bench 4.1 Internet Use"

# Read back by `publish_spreadsheet.py`.
ALL_CHECKS_HOLD_LABEL = "All checks hold"
HOLDS_HEADER = "Holds"
PYTHON_COPY_TAB_SUFFIX = " (Python)"

LOWER_BOUND_COLOR = "2B5C8A"
UPPER_BOUND_ONLY_COLOR = "A9C4E0"
# Lighter than the lower bound, so that the number stays readable on a share of 100%.
SHARE_COLOR_SCALE_END_COLOR = "5B9BD5"

# A default row in Google Sheets.
_ROW_HEIGHT_IN_POINTS = 15
_CM_PER_POINT = 2.54 / 72
_EMU_PER_CM = 360_000
_EMU_PER_PIXEL = 9_525
# Google Sheets shows a column of width w characters as about 7 w + 5 pixels.
_PIXELS_PER_WIDTH_CHARACTER = 7
_PIXELS_ADDED_TO_COLUMN_WIDTH = 5
_PIXELS_PER_CM = _EMU_PER_CM / _EMU_PER_PIXEL
# Between charts that stand side by side.
_CHART_GAP_IN_CM = 0.3

# The share of the values of a column of a row tab that its width fits.
_SHARE_OF_VALUES_A_ROW_TAB_COLUMN_FITS = 0.95

# Column widths in characters.
_NARROWEST_COLUMN_WIDTH = 6
_WIDEST_COLUMN_WIDTH = 60
# About the 100 pixels of a default column in Google Sheets.
_COLUMN_WIDTH_UNDER_CHART = 13
# Without these, Google Sheets splits header words such as `Lower`.
_BOLD_WIDTH_FACTOR = 1.2
_FILTER_BUTTON_WIDTH = 3

# openpyxl types a write-only sheet without its settings, e.g. column widths.
type WriteOnlySheet = Any


class CellStyle(Enum):
    """Look of a cell when written."""

    TEXT = "text"
    TITLE = "title"
    SECTION = "section"
    NOTE = "note"
    GROUP = "group"
    HEADER = "header"
    COUNT = "count"
    SHARE = "share"
    KEY_COUNT = "key_count"  # a count or share of the key numbers, in large type
    KEY_SHARE = "key_share"
    PYTHON_COUNT = "python_count"  # counted by Python, with no formula
    PYTHON_SHARE = "python_share"
    BAR = "bar"
    HOLDS = "holds"


@dataclass(frozen=True, slots=True)
class TabCell:
    """Cell of a tab."""

    value: str | int | float | bool | None  # for a formula, the value Python counted
    formula: str | None = None  # without the leading `=`
    style: CellStyle = CellStyle.TEXT


EMPTY_CELL = TabCell(None)


@dataclass(frozen=True, slots=True)
class BarChartSeries:
    """Series of a bar chart, drawn from one column of its table."""

    column: int  # 1-based
    title: str
    color: str


@dataclass(frozen=True, slots=True)
class BarChartSpec:
    """Bar chart with one bar per table row and series, the series of a row side by side."""

    title: str
    label_column: int  # columns are 1-based
    series: tuple[BarChartSeries, ...]
    first_row: int
    last_row: int
    width_in_cm: float
    height_in_cm: float
    has_vertical_bars: bool = False
    axis_number_format: str | None = None  # e.g. `0%`
    data_tab_name: str | None = None  # None for the tab of the chart

    @property
    def row_count(self) -> int:
        """Give the rows of default height that the chart covers."""
        return math.ceil(self.height_in_cm / (_ROW_HEIGHT_IN_POINTS * _CM_PER_POINT))


@dataclass(frozen=True, slots=True)
class ChartPlacement:
    """Place of a chart in its tab, kept until the column widths are known."""

    chart_spec: BarChartSpec
    row: int  # 1-based, the row of the top edge
    left_in_cm: float  # from the left edge of column A


@dataclass(slots=True)
class TabGrid:
    """Tab laid out by hand as rows of cells, numbered from 1."""

    name: str
    rows: list[list[TabCell]] = field(default_factory=list)
    # In characters.
    fixed_column_widths: dict[int, float] = field(default_factory=dict)
    hidden_columns: set[int] = field(default_factory=set)
    tab_color: str | None = None
    is_hidden: bool = False
    wrapped_rows: set[int] = field(default_factory=set)
    frozen_cell: str | None = None
    filter_range: str | None = None
    merged_ranges: list[str] = field(default_factory=list)
    # The last column each note spans, by row.
    note_last_columns: dict[int, int] = field(default_factory=dict)
    chart_placements: list[ChartPlacement] = field(default_factory=list)
    # Ranges of shares colored from white at 0 to the color of the lower bound at 1, e.g. `E6:I145`.
    share_color_scale_ranges: list[str] = field(default_factory=list)

    @property
    def next_row(self) -> int:
        return len(self.rows) + 1

    def add_row(self, *cells: TabCell) -> int:
        """Add a row and give its number."""
        self.rows.append(list(cells))
        return len(self.rows)

    def add_note(
        self, text: str | TabCell, last_column: int, *cells_after: TabCell
    ) -> int:
        """Add a row whose note spans the columns up to `last_column`, and give its number.

        A note given as a cell keeps its formula, e.g. a text joined from counts.
        """
        row = self.add_row(
            text if isinstance(text, TabCell) else TabCell(text, style=CellStyle.NOTE),
            *([EMPTY_CELL] * (last_column - 1)),
            *cells_after,
        )
        self.note_last_columns[row] = last_column
        return row

    def add_charts_below(self, *chart_specs: BarChartSpec) -> None:
        """Add charts side by side at the next row and empty rows for the tallest."""
        left_in_cm = 0.0
        for chart_spec in chart_specs:
            self.chart_placements.append(
                ChartPlacement(chart_spec, self.next_row, left_in_cm)
            )
            left_in_cm += chart_spec.width_in_cm + _CHART_GAP_IN_CM
        for _ in range(max(chart_spec.row_count for chart_spec in chart_specs) + 1):
            self.add_row()

    def column_widths(self) -> dict[int, float]:
        """Give each column's width, set by hand or fitting its longest value."""
        column_count = max((len(row) for row in self.rows), default=0)
        filter_header_row = (
            int(re.sub(r"[^0-9]", "", self.filter_range.split(":")[0]))
            if self.filter_range
            else None
        )
        longest_length_by_column: dict[int, float] = {}
        for row_number, row in enumerate(self.rows, start=1):
            if row_number in self.note_last_columns:
                continue
            for column, cell in enumerate(row, start=1):
                longest_length_by_column[column] = max(
                    longest_length_by_column.get(column, 0),
                    _shown_length_of(
                        cell, has_filter_button=row_number == filter_header_row
                    ),
                )
        widths = {
            column: self.fixed_column_widths.get(
                column, _column_width_for(longest_length_by_column.get(column, 0))
            )
            for column in range(1, column_count + 1)
        }
        # Columns under a chart get a width, so that where a chart sits does not rest on the default width of the app.
        right_edge_in_pixels = max(
            (
                (placement.left_in_cm + placement.chart_spec.width_in_cm)
                * _PIXELS_PER_CM
                for placement in self.chart_placements
            ),
            default=0,
        )
        column = 1
        while right_edge_in_pixels > 0:
            width = widths.setdefault(column, _COLUMN_WIDTH_UNDER_CHART)
            right_edge_in_pixels -= _pixels_of_column_width(width)
            column += 1
        return widths

    def width_of(self, first_column: int, last_column: int) -> float:
        widths = self.column_widths()
        return sum(
            widths.get(column, _NARROWEST_COLUMN_WIDTH)
            for column in range(first_column, last_column + 1)
        )

    def range_of(self, column: int, first_row: int, last_row: int) -> str:
        return tab_range_of(self.name, column, first_row, last_row)

    def numeric_formula_runs(self) -> list[tuple[int, int, int]]:
        """Give runs of numeric formula cells down a column, as the column, first row and last row."""
        cells = {
            (column, row_number)
            for row_number, row in enumerate(self.rows, start=1)
            for column, cell in enumerate(row, start=1)
            if cell.formula is not None
            and isinstance(cell.value, int | float)
            and not isinstance(cell.value, bool)
        }
        runs: list[tuple[int, int, int]] = []
        for column, row_number in sorted(cells):
            if runs and runs[-1][0] == column and runs[-1][2] == row_number - 1:
                runs[-1] = (column, runs[-1][1], row_number)
            else:
                runs.append((column, row_number, row_number))
        return runs


@dataclass(frozen=True, slots=True)
class RowTab:
    """Tab of the rows of one row file, which the formulas of other tabs count."""

    name: str
    columns: tuple[str, ...]
    rows: list[list[object]]  # in the order of `columns`, a formula as a `TabCell`
    header_note: str | None = None  # a comment on the first header cell
    tab_color: str | None = None

    def column_range(self, column: str) -> str:
        """Give a column's range below the header, e.g. `'trial_rows'!$A$2:$A$15991`."""
        return tab_range_of(
            self.name, self.columns.index(column) + 1, 2, max(len(self.rows), 1) + 1
        )


def python_copy_of(grid: TabGrid) -> TabGrid:
    """Copy a tab with Python's counts in place of formulas, for `Method & checks` to compare."""
    copy = TabGrid(f"{grid.name}{PYTHON_COPY_TAB_SUFFIX}")
    for row in grid.rows:
        copy.add_row(
            *(
                TabCell(
                    None if cell.style == CellStyle.BAR else cell.value,
                    style=cell.style,
                )
                for cell in row
            )
        )
    copy.fixed_column_widths = dict(grid.fixed_column_widths)
    copy.wrapped_rows = set(grid.wrapped_rows)
    copy.is_hidden = True
    copy.merged_ranges = list(grid.merged_ranges)
    copy.note_last_columns = dict(grid.note_last_columns)
    return copy


def count_ifs_formula(row_tab: RowTab, conditions: Sequence[tuple[str, str]]) -> str:
    """Give a `COUNTIFS` over a row tab, with criteria from `equal_to` and the like."""
    return f"COUNTIFS({_criteria_text_of(row_tab, conditions)})"


def count_unique_ifs_formula(
    row_tab: RowTab, counted_column: str, conditions: Sequence[tuple[str, str]]
) -> str:
    """Give a `COUNTUNIQUEIFS` of `counted_column` over the matching rows."""
    return f"COUNTUNIQUEIFS({row_tab.column_range(counted_column)},{_criteria_text_of(row_tab, conditions)})"


def _criteria_text_of(row_tab: RowTab, conditions: Sequence[tuple[str, str]]) -> str:
    if not conditions:
        raise ValueError("a count without criteria")
    return ",".join(
        f"{row_tab.column_range(column)},{criterion}"
        for column, criterion in conditions
    )


# Criteria of `COUNTIFS`.
NON_BLANK = '"<>"'
BLANK = '""'


def equal_to(value: str) -> str:
    """Give the criterion that matches a cell holding the text."""
    return formula_text_of(_criterion_text_of(value))


def not_equal_to(value: str) -> str:
    """Give the criterion for a cell not holding the text, empty ones included."""
    return formula_text_of("<>" + _criterion_text_of(value))


def equal_to_number(number: float) -> str:
    return repr(int(number)) if float(number).is_integer() else repr(number)


def equal_to_formula_value(formula: str, value: str) -> str:
    """Give a formula as a criterion, checking that `value`, its expected text, reads as plain text."""
    _criterion_text_of(value)
    return formula


# Texts a criterion does not read as plain text.
_NUMBER_OR_DATE_TEXT = re.compile(r"[\s\d.,:/+-]*\d[\s\d.,:/+-]*")
_BOOLEAN_TEXTS = {"true", "false"}
_CRITERION_OPERATOR_STARTS = ("=", "<", ">")
_WILDCARD_CHARACTERS = set("*?~")


def _criterion_text_of(value: str) -> str:
    """Give the text, refusing one a criterion would not read as plain text."""
    if (
        not value
        or _NUMBER_OR_DATE_TEXT.fullmatch(value)
        or value.lower() in _BOOLEAN_TEXTS
        or value.startswith(_CRITERION_OPERATOR_STARTS)
        or _WILDCARD_CHARACTERS & set(value)
    ):
        raise ValueError(f"a criterion would not read {value!r} as plain text")
    return value


def formula_text_of(text: str) -> str:
    """Give the text as a string of a formula, in double quotes with each double quote doubled."""
    return '"' + text.replace('"', '""') + '"'


def refuse_keys_equal_apart_from_case(keys: Sequence[tuple[str, ...]]) -> None:
    """Refuse keys that differ only in case, since `COUNTIFS` criteria ignore case."""
    lowered = Counter(tuple(part.lower() for part in key) for key in keys)
    repeated = [key for key in keys if lowered[tuple(part.lower() for part in key)] > 1]
    if repeated:
        raise ValueError(f"lines whose keys differ only in letter case: {repeated}")


def tab_range_of(tab_name: str, column: int, first_row: int, last_row: int) -> str:
    """Give an absolute range such as `'Tasks'!$C$6:$C$145`."""
    letter = get_column_letter(column)
    return f"'{tab_name}'!${letter}${first_row}:${letter}${last_row}"


def write_spreadsheet(
    spreadsheet_path: Path,
    grids_before_row_tabs: Sequence[TabGrid],
    row_tabs: Sequence[RowTab],
    grids_after_row_tabs: Sequence[TabGrid],
) -> None:
    """Write the tabs as one XLSX file, in write-only mode so that a million cells fit in memory."""
    workbook = Workbook(write_only=True)
    for grid in grids_before_row_tabs:
        _write_grid(workbook.create_sheet(grid.name), grid)
    for row_tab in row_tabs:
        _write_row_tab(workbook.create_sheet(row_tab.name), row_tab)
    for grid in grids_after_row_tabs:
        _write_grid(workbook.create_sheet(grid.name), grid)
    workbook.save(spreadsheet_path)


def _write_grid(sheet: WriteOnlySheet, grid: TabGrid) -> None:
    widths = grid.column_widths()
    for column, width in widths.items():
        dimension = sheet.column_dimensions[get_column_letter(column)]
        dimension.width = width
        dimension.hidden = column in grid.hidden_columns
    _write_tab_color_and_visibility(sheet, grid.tab_color, is_hidden=grid.is_hidden)
    if grid.frozen_cell:
        sheet.freeze_panes = grid.frozen_cell
    if grid.filter_range:
        sheet.auto_filter.ref = grid.filter_range
    for merged_range in grid.merged_ranges:
        sheet.merged_cells.add(merged_range)
    for row_number, last_column in grid.note_last_columns.items():
        # A note in column A alone needs no merge.
        if last_column > 1:
            sheet.merged_cells.add(
                f"A{row_number}:{get_column_letter(last_column)}{row_number}"
            )
        sheet.row_dimensions[row_number].height = _note_height_in_points_of(
            grid.rows[row_number - 1][0].value, grid.width_of(1, last_column)
        )
    for row_number, row in enumerate(grid.rows, start=1):
        is_row_wrapped = (
            row_number in grid.wrapped_rows
            or row_number in grid.note_last_columns
            or any(cell.style in (CellStyle.HEADER, CellStyle.GROUP) for cell in row)
        )
        sheet.append(
            [
                _written_cell_of(
                    sheet,
                    cell,
                    is_wrapped=is_row_wrapped
                    or (
                        cell.style not in _OVERFLOWING_STYLES
                        and _shown_length_of(cell) > widths[column]
                    ),
                )
                for column, cell in enumerate(row, start=1)
            ]
        )
    for cell_range in grid.share_color_scale_ranges:
        sheet.conditional_formatting.add(
            cell_range,
            ColorScaleRule(
                start_type="num",
                start_value=0,
                start_color="FFFFFF",
                end_type="num",
                end_value=1,
                end_color=SHARE_COLOR_SCALE_END_COLOR,
            ),
        )
    for chart_placement in grid.chart_placements:
        chart = _bar_chart_of(sheet, chart_placement.chart_spec)
        # openpyxl types the anchor as a cell name, though it also takes an anchor object.
        chart.anchor = _chart_anchor_of(chart_placement, widths)  # pyright: ignore[reportAttributeAccessIssue]
        sheet.add_chart(chart)


_OVERFLOWING_STYLES = (CellStyle.TITLE, CellStyle.SECTION, CellStyle.NOTE)
_KEY_NUMBER_FONT_SIZE = 14
# A key number is wider than text of the default size 10.
_KEY_WIDTH_FACTOR_BY_STYLE = {CellStyle.KEY_COUNT: 1.5, CellStyle.KEY_SHARE: 1.5}


def _chart_anchor_of(
    chart_placement: ChartPlacement, column_widths: dict[int, float]
) -> OneCellAnchor:
    """Anchor a chart at the column its left edge falls in, with the rest as an offset, since an anchor names a cell."""
    left_in_pixels = chart_placement.left_in_cm * _PIXELS_PER_CM
    column = 1
    while True:
        column_in_pixels = _pixels_of_column_width(
            column_widths.get(column, _COLUMN_WIDTH_UNDER_CHART)
        )
        if left_in_pixels < column_in_pixels:
            break
        left_in_pixels -= column_in_pixels
        column += 1
    chart_spec = chart_placement.chart_spec
    return OneCellAnchor(
        _from=AnchorMarker(
            col=column - 1,
            colOff=round(left_in_pixels * _EMU_PER_PIXEL),
            row=chart_placement.row - 1,
            rowOff=0,
        ),
        ext=XDRPositiveSize2D(
            round(chart_spec.width_in_cm * _EMU_PER_CM),
            round(chart_spec.height_in_cm * _EMU_PER_CM),
        ),
    )


def _pixels_of_column_width(width: float) -> float:
    return width * _PIXELS_PER_WIDTH_CHARACTER + _PIXELS_ADDED_TO_COLUMN_WIDTH


def _column_width_for(longest_length: float) -> float:
    """Give a column width with room on both sides of the longest value."""
    return min(
        max(math.ceil(longest_length) + 2, _NARROWEST_COLUMN_WIDTH),
        _WIDEST_COLUMN_WIDTH,
    )


def _shown_length_of(cell: TabCell, *, has_filter_button: bool = False) -> float:
    """Give the characters a cell needs in its column, only the longest word for a header or group label since it wraps."""
    if cell.style in _OVERFLOWING_STYLES or cell.value is None:
        return 0
    if cell.style in (CellStyle.HEADER, CellStyle.GROUP):
        return _header_length_of(str(cell.value), has_filter_button=has_filter_button)
    if isinstance(cell.value, bool):
        return 5
    if isinstance(cell.value, int | float):
        if cell.style in (CellStyle.SHARE, CellStyle.KEY_SHARE, CellStyle.PYTHON_SHARE):
            return len(f"{cell.value * 100:.1f}%") * _KEY_WIDTH_FACTOR_BY_STYLE.get(
                cell.style, 1
            )
        if cell.style == CellStyle.KEY_COUNT:
            return len(f"{cell.value:,.0f}") * _KEY_WIDTH_FACTOR_BY_STYLE[cell.style]
        return len(f"{cell.value:,.0f}")
    return len(str(cell.value))


def _header_length_of(text: str, *, has_filter_button: bool) -> float:
    """Give the room for the longest word of a bold header and its filter button."""
    longest_word_length = max((len(word) for word in text.split()), default=0)
    return longest_word_length * _BOLD_WIDTH_FACTOR + (
        _FILTER_BUTTON_WIDTH if has_filter_button else 0
    )


def _write_tab_color_and_visibility(
    sheet: WriteOnlySheet, tab_color: str | None, *, is_hidden: bool = False
) -> None:
    if tab_color is not None:
        sheet.sheet_properties.tabColor = tab_color
    if is_hidden:
        sheet.sheet_state = "hidden"


def _note_height_in_points_of(text: object, width: float) -> float:
    """Give the height of a note row, assuming each character fills one unit of column width, which most do not."""
    line_count = max(1, math.ceil(len(str(text or "")) / max(width, 1)))
    return line_count * _ROW_HEIGHT_IN_POINTS + 3


def _write_row_tab(sheet: WriteOnlySheet, row_tab: RowTab) -> None:
    _write_tab_color_and_visibility(sheet, row_tab.tab_color)
    for column, width in _row_tab_column_widths_of(row_tab).items():
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = (
        f"A1:{get_column_letter(len(row_tab.columns))}{len(row_tab.rows) + 1}"
    )
    header = [
        _written_cell_of(sheet, TabCell(name, style=CellStyle.HEADER))
        for name in row_tab.columns
    ]
    if row_tab.header_note:
        header[0].comment = Comment(row_tab.header_note, "build_spreadsheet.py")
    sheet.append(header)
    for row in row_tab.rows:
        sheet.append(
            [
                _written_cell_of(sheet, value)
                if isinstance(value, TabCell)
                else _written_value_of(sheet, value)
                for value in row
            ]
        )


def _row_tab_column_widths_of(row_tab: RowTab) -> dict[int, float]:
    """Give the column widths of a row tab, each fitting its header and the lengths of its values.

    A column fits the length that 95 of 100 of its values are within, so that a few long values do not widen it, e.g. a `target` of 388 characters. Its longer values are cut at the next cell.
    The header stays on one line, so a column is never narrower than its name, e.g. `received_content_destination` over values such as `saved`.
    """
    widths: dict[int, float] = {}
    for column, name in enumerate(row_tab.columns, start=1):
        value_lengths = sorted(
            _shown_length_of(value)
            if isinstance(value, TabCell)
            else len(_shown_text_of(value))
            for value in (row[column - 1] for row in row_tab.rows)
            if value is not None
        )
        fitted_length = (
            value_lengths[
                math.ceil(len(value_lengths) * _SHARE_OF_VALUES_A_ROW_TAB_COLUMN_FITS)
                - 1
            ]
            if value_lengths
            else 0
        )
        widths[column] = _column_width_for(
            max(fitted_length, _header_length_of(name, has_filter_button=True))
        )
    return widths


def _shown_text_of(value: object) -> str:
    """Give the text a plain value shows, e.g. `1,234` for a count."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "FALSE" if not value else "TRUE"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _written_value_of(sheet: WriteOnlySheet, value: object) -> object:
    """Give a value to write, keeping a text that starts with `=` as text."""
    if not isinstance(value, str):
        return value
    cell = WriteOnlyCell(sheet, value=_xml_safe_text_of(value))
    cell.data_type = "s"
    return cell


def _xml_safe_text_of(text: str) -> str:
    """Write characters that XML cannot hold as `\\x1b` and the like."""
    return ILLEGAL_CHARACTERS_RE.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def _written_cell_of(
    sheet: WriteOnlySheet, cell: TabCell, *, is_wrapped: bool = False
) -> Cell:
    if cell.formula is not None:
        written = WriteOnlyCell(sheet, value=f"={cell.formula}")
    elif isinstance(cell.value, str):
        written = WriteOnlyCell(sheet, value=_xml_safe_text_of(cell.value))
        written.data_type = "s"
    else:
        written = WriteOnlyCell(sheet, value=cell.value)
    _apply_cell_style(written, cell.style)
    if is_wrapped:
        written.alignment = Alignment(wrap_text=True, vertical="top")
    return written


_HEADER_FILL = PatternFill("solid", fgColor="E8EEF4")


def _apply_cell_style(written: Cell, style: CellStyle) -> None:
    match style:
        case CellStyle.TITLE:
            written.font = Font(bold=True, size=14)
        case CellStyle.SECTION:
            written.font = Font(bold=True, size=12)
        case CellStyle.NOTE:
            written.font = Font(color="555555")
        case CellStyle.GROUP | CellStyle.HEADER:
            written.font = Font(bold=True)
            written.fill = _HEADER_FILL
        case CellStyle.COUNT:
            written.number_format = "#,##0"
        case CellStyle.SHARE:
            written.number_format = "0.0%"
        case CellStyle.KEY_COUNT:
            written.font = Font(bold=True, size=_KEY_NUMBER_FONT_SIZE)
            written.number_format = "#,##0"
        case CellStyle.KEY_SHARE:
            written.font = Font(bold=True, size=_KEY_NUMBER_FONT_SIZE)
            written.number_format = "0.0%"
        case CellStyle.PYTHON_COUNT:
            written.font = Font(italic=True, color="777777")
            written.number_format = "#,##0"
        case CellStyle.PYTHON_SHARE:
            written.font = Font(italic=True, color="777777")
            written.number_format = "0.0%"
        case CellStyle.HOLDS:
            written.font = Font(bold=True)
        case CellStyle.TEXT | CellStyle.BAR:
            pass


def _bar_chart_of(sheet: WriteOnlySheet, chart_spec: BarChartSpec) -> BarChart:
    """Make the openpyxl chart of a spec."""
    chart = BarChart()
    chart.type = "col" if chart_spec.has_vertical_bars else "bar"
    chart.grouping = "clustered"
    chart.legend = Legend(legendPos="b") if len(chart_spec.series) > 1 else None
    chart.title = chart_spec.title
    chart.height = chart_spec.height_in_cm
    # openpyxl types the size as whole centimeters, though it writes any number.
    chart.width = chart_spec.width_in_cm  # pyright: ignore[reportAttributeAccessIssue]
    data_tab_name = chart_spec.data_tab_name or sheet.title
    for chart_series in chart_spec.series:
        series = SeriesFactory(
            Reference(
                range_string=tab_range_of(
                    data_tab_name,
                    chart_series.column,
                    chart_spec.first_row,
                    chart_spec.last_row,
                )
            ),
            title=chart_series.title,
        )
        series.graphicalProperties.solidFill = chart_series.color
        series.graphicalProperties.line.solidFill = chart_series.color
        chart.series.append(series)
    chart.set_categories(
        Reference(
            range_string=tab_range_of(
                data_tab_name,
                chart_spec.label_column,
                chart_spec.first_row,
                chart_spec.last_row,
            )
        )
    )
    if not chart_spec.has_vertical_bars:
        chart.x_axis.scaling.orientation = "maxMin"
    if chart_spec.axis_number_format is not None:
        chart.y_axis.number_format = chart_spec.axis_number_format
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    return chart


# The format of `TEXT` that `check_spreadsheet_formulas.py` computes, a whole number with thousands separators.
COUNT_TEXT_FORMAT = "#,##0"


def count_text_formula(count_formula: str) -> str:
    """Give a formula of a count as text with thousands separators, e.g. `21,450`, since a number joined to a text shows without them."""
    return f'TEXT({count_formula},"{COUNT_TEXT_FORMAT}")'


def count_text_of(count: int) -> str:
    """Give the text that `count_text_formula` shows for a count."""
    return f"{count:,}"


def sparkline_bar_formula(bound_range: str, *, scale_maximum: str = "1") -> str:
    """Give a `SPARKLINE` bar of the lower bound and the rest of the upper bound in a range.

    For counts, `scale_maximum` is a formula such as `MAX(F5:F40)` so that the bars of a table share one scale.
    """
    return (
        f"SPARKLINE({bound_range},"
        f'{{"charttype","bar";"max",{scale_maximum};"color1","#{LOWER_BOUND_COLOR}";"color2","#{UPPER_BOUND_ONLY_COLOR}"}})'
    )
