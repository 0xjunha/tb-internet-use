"""Compute the formulas of a spreadsheet file of `build_spreadsheet.py` and check them, since Google Sheets computes them only when it opens the file.

Run it as `uv run python -I scripts/check_spreadsheet_formulas.py <spreadsheet.xlsx>`. It prints the lines that disagree and exits with 1 if any does.
"""

import argparse
import dataclasses
import operator
import re
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

# `python -I` leaves this folder off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spreadsheet_cells import COUNT_TEXT_FORMAT, PYTHON_COPY_TAB_SUFFIX
from spreadsheet_tabs import METHOD_AND_CHECKS_TAB_NAME

# Python and a formula divide the same counts.
_NUMBER_TOLERANCE = 1e-9


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("spreadsheet_path", type=Path)
    formula_check = check_spreadsheet_formulas(parser.parse_args().spreadsheet_path)
    for line in formula_check.lines:
        if not line.agrees:
            print(*dataclasses.astuple(line), sep="\t")
    print(formula_check.summary_text())
    if not formula_check.is_passed():
        sys.exit(1)


@dataclass(frozen=True, slots=True)
class FormulaCheckLine:
    """Line of `formula_check.csv` for one formula cell, check or chart."""

    tab: str
    # A cell such as `C15`, or a chart file in the XLSX archive.
    place: str
    computed_value: object
    # None for a check or a chart.
    python_value: object
    agrees: bool


@dataclass(slots=True)
class FormulaCheck:
    """Result of `check_spreadsheet_formulas`."""

    lines: list[FormulaCheckLine] = field(default_factory=list)
    compared_cell_count: int = 0
    differing_cell_count: int = 0
    check_count: int = 0
    failing_check_count: int = 0
    chart_count: int = 0
    misaligned_chart_count: int = 0

    @staticmethod
    def line_columns() -> tuple[str, ...]:
        return tuple(
            line_field.name for line_field in dataclasses.fields(FormulaCheckLine)
        )

    def summary_text(self) -> str:
        return (
            f"{self.compared_cell_count} formula cells compared, {self.differing_cell_count} differ, "
            f"{self.check_count} checks, {self.failing_check_count} do not hold, "
            f"{self.chart_count} charts, {self.misaligned_chart_count} do not draw numbers from every row of their labels"
        )

    def is_passed(self) -> bool:
        return not (
            self.differing_cell_count
            or self.failing_check_count
            or self.misaligned_chart_count
        )


def check_spreadsheet_formulas(spreadsheet_path: Path) -> FormulaCheck:
    """Hold each formula against its copy in `<tab> (Python)`, each check of `Method & checks` against true and each chart against the rows of its labels."""
    spreadsheet = WrittenSpreadsheet.read(spreadsheet_path)
    formula_values = FormulaValues(spreadsheet)
    formula_check = FormulaCheck()
    for tab_name in spreadsheet.tab_names:
        python_copy_name = f"{tab_name}{PYTHON_COPY_TAB_SUFFIX}"
        if python_copy_name not in spreadsheet.tabs:
            continue
        for (row, column), formula in sorted(
            spreadsheet.tabs[tab_name].formulas.items()
        ):
            # `SPARKLINE` draws a bar and gives no value.
            if formula.startswith("SPARKLINE("):
                continue
            computed_value = formula_values.value_of(tab_name, row, column)
            python_value = spreadsheet.tabs[python_copy_name].value_at(row, column)
            agrees = _is_within_tolerance(computed_value, python_value)
            formula_check.compared_cell_count += 1
            formula_check.differing_cell_count += not agrees
            formula_check.lines.append(
                FormulaCheckLine(
                    tab_name,
                    _cell_name_of(row, column),
                    computed_value,
                    python_value,
                    agrees,
                )
            )
    for row, column in sorted(spreadsheet.tabs[METHOD_AND_CHECKS_TAB_NAME].formulas):
        computed_value = formula_values.value_of(
            METHOD_AND_CHECKS_TAB_NAME, row, column
        )
        is_check = isinstance(computed_value, bool)
        formula_check.check_count += is_check
        formula_check.failing_check_count += is_check and not computed_value
        formula_check.lines.append(
            FormulaCheckLine(
                METHOD_AND_CHECKS_TAB_NAME,
                _cell_name_of(row, column),
                computed_value,
                None,
                bool(computed_value) if is_check else True,
            )
        )
    for chart_file, chart_ranges in chart_ranges_of(spreadsheet_path).items():
        is_aligned = _is_chart_aligned(chart_ranges, formula_values)
        formula_check.chart_count += 1
        formula_check.misaligned_chart_count += not is_aligned
        formula_check.lines.append(
            FormulaCheckLine(
                "chart",
                chart_file,
                " ".join(chart_range.cell_range for chart_range in chart_ranges),
                None,
                is_aligned,
            )
        )
    return formula_check


def _is_chart_aligned(
    chart_ranges: Sequence[ChartRange], formula_values: FormulaValues
) -> bool:
    """Tell whether a chart draws every row of its labels and no header.

    A header is not a number, and a filled cell below the labels is a row left out.
    """
    nodes = [
        _reference_node_of(chart_range.cell_range.replace("$", ""))
        for chart_range in chart_ranges
    ]
    range_nodes = [
        node
        for node in nodes
        if isinstance(node, RangeNode) and node.tab_name is not None
    ]
    if len(range_nodes) != len(nodes) or not nodes:
        return False
    if len({(node.first_row, node.last_row) for node in range_nodes}) != 1:
        return False
    if range_nodes[0].first_row > range_nodes[0].last_row:
        return False
    for chart_range, node in zip(chart_ranges, range_nodes, strict=True):
        assert node.tab_name is not None
        if chart_range.role == ChartRangeRole.LABELS:
            if formula_values.value_of(
                node.tab_name, node.last_row + 1, node.first_column
            ) not in (None, ""):
                return False
            continue
        for row in range(node.first_row, node.last_row + 1):
            value = formula_values.value_of(node.tab_name, row, node.first_column)
            if not isinstance(value, int | float) or isinstance(value, bool):
                return False
    return True


def _is_within_tolerance(computed_value: object, python_value: object) -> bool:
    if isinstance(computed_value, int | float) and isinstance(
        python_value, int | float
    ):
        return abs(computed_value - python_value) < _NUMBER_TOLERANCE
    return computed_value == python_value


def _cell_name_of(row: int, column: int) -> str:
    return f"{get_column_letter(column)}{row}"


class ChartRangeRole(StrEnum):
    """Role of a chart range, valued as the chart XML names it."""

    LABELS = "cat"
    VALUES = "val"


@dataclass(frozen=True, slots=True)
class ChartRange:
    """Range that a chart reads."""

    role: ChartRangeRole
    # E.g. `'Chart data'!$A$2:$A$9`.
    cell_range: str


# Chart XML elements may carry the prefix `c:`.
_CHART_RANGE = re.compile(
    r"<(?:c:)?(cat|val)>.*?<(?:c:)?f>([^<]*)</(?:c:)?f>", re.DOTALL
)


def chart_ranges_of(spreadsheet_path: Path) -> dict[str, list[ChartRange]]:
    """Give the ranges of each chart, by its file in the XLSX archive."""
    with zipfile.ZipFile(spreadsheet_path) as archive:
        return {
            name: [
                ChartRange(ChartRangeRole(role), cell_range)
                for role, cell_range in _CHART_RANGE.findall(
                    archive.read(name).decode()
                )
            ]
            for name in sorted(archive.namelist())
            if re.fullmatch(r"xl/charts/chart\d+\.xml", name)
        }


@dataclass(slots=True)
class WrittenTab:
    """Tab of a spreadsheet file as written, with rows and columns numbered from 1."""

    values: list[list[object]]
    # Without the leading `=`.
    formulas: dict[tuple[int, int], str]

    def value_at(self, row: int, column: int) -> object:
        if row > len(self.values) or column > len(self.values[row - 1]):
            return None
        return self.values[row - 1][column - 1]


@dataclass(slots=True)
class WrittenSpreadsheet:
    """Spreadsheet file as written."""

    tab_names: list[str]
    tabs: dict[str, WrittenTab]

    @classmethod
    def read(cls, spreadsheet_path: Path) -> WrittenSpreadsheet:
        workbook = load_workbook(spreadsheet_path, read_only=True, data_only=False)
        tabs: dict[str, WrittenTab] = {}
        for sheet in workbook.worksheets:
            values: list[list[object]] = []
            formulas: dict[tuple[int, int], str] = {}
            for row_number, row in enumerate(sheet.iter_rows(), start=1):
                row_values: list[object] = []
                for column_number, cell in enumerate(row, start=1):
                    value = getattr(cell, "value", None)
                    if getattr(cell, "data_type", None) == "f" and isinstance(
                        value, str
                    ):
                        formulas[row_number, column_number] = value.removeprefix("=")
                        value = None
                    row_values.append(value)
                values.append(row_values)
            tabs[sheet.title] = WrittenTab(values, formulas)
        workbook.close()
        return cls([sheet.title for sheet in workbook.worksheets], tabs)


class FormulaValues:
    """Values of the formulas of a `WrittenSpreadsheet`, computed when first asked for."""

    def __init__(self, spreadsheet: WrittenSpreadsheet) -> None:
        self._spreadsheet = spreadsheet
        self._computed: dict[tuple[str, int, int], object] = {}
        self._parsed: dict[str, FormulaNode] = {}
        self._range_indexes: dict[RangeNode, RangeIndex] = {}

    def value_of(self, tab_name: str, row: int, column: int) -> object:
        """Give the value of a cell."""
        key = (tab_name, row, column)
        if key in self._computed:
            return self._computed[key]
        tab = self._spreadsheet.tabs[tab_name]
        formula = tab.formulas.get((row, column))
        if formula is None:
            value = tab.value_at(row, column)
        else:
            node = self._parsed.get(formula)
            if node is None:
                node = self._parsed[formula] = _parse_formula(formula)
            value = self._value_of_node(node, tab_name)
        self._computed[key] = value
        return value

    def _value_of_node(self, node: FormulaNode, tab_name: str) -> object:
        match node:
            case NumberNode(number):
                return number
            case TextNode(text):
                return text
            case CellNode(node_tab_name, row, column):
                return self.value_of(node_tab_name or tab_name, row, column)
            case RangeNode():
                return self._range_values_of(node, tab_name)
            case BinaryNode(binary_operator, left, right):
                return _binary_value_of(
                    binary_operator,
                    self._value_of_node(left, tab_name),
                    self._value_of_node(right, tab_name),
                )
            case CallNode(name, arguments):
                return self._call_value_of(name, arguments, tab_name)
            case ArrayNode():
                raise ValueError("an array constant outside SPARKLINE")

    def _range_values_of(self, node: RangeNode, tab_name: str) -> list[object]:
        node_tab_name = node.tab_name or tab_name
        return [
            self.value_of(node_tab_name, row, column)
            for row in range(node.first_row, node.last_row + 1)
            for column in range(node.first_column, node.last_column + 1)
        ]

    def _call_value_of(
        self, name: str, arguments: Sequence[FormulaNode], tab_name: str
    ) -> object:
        if name == "IF":
            # Only the branch taken is computed, as in Google Sheets.
            condition, value_if_true, value_if_false = arguments
            return self._value_of_node(
                value_if_true
                if _is_true(self._value_of_node(condition, tab_name))
                else value_if_false,
                tab_name,
            )
        if name in _FUNCTIONS_WITH_CRITERIA:
            counted_range = None if name == "COUNTIFS" else arguments[0]
            offsets = self._matching_offsets_of(
                arguments[0 if counted_range is None else 1 :], tab_name
            )
            if counted_range is None:
                return len(offsets)
            if not isinstance(counted_range, RangeNode):
                raise TypeError(f"{name} of something that is not a range")
            counted_values = self._range_values_of(counted_range, tab_name)
            # Assumed to keep letter case. If Google Sheets differs, `Method & checks` shows it.
            if name == "COUNTUNIQUEIFS":
                return len(
                    {
                        counted_values[offset]
                        for offset in offsets
                        if counted_values[offset] not in (None, "")
                    }
                )
            numbers = [_number_of(counted_values[offset]) for offset in offsets]
            if name == "SUMIFS":
                return sum(numbers)
            return max(numbers, default=0.0)
        values = [self._value_of_node(argument, tab_name) for argument in arguments]
        match name:
            case "COUNTA":
                return sum(
                    1
                    for value in _flattened_values_of(values)
                    if value not in (None, "")
                )
            case "SUM":
                return sum(_number_of(value) for value in _flattened_values_of(values))
            case "SUMPRODUCT":
                arrays = [
                    value if isinstance(value, list) else [value] for value in values
                ]
                total = 0.0
                for items in zip(*arrays, strict=True):
                    product = 1.0
                    for item in items:
                        product *= _number_of(item)
                    total += product
                return total
            case "ABS":
                return _elementwise_value_of(
                    lambda value: abs(_number_of(value)), values[0]
                )
            case "TEXT":
                return _count_text_of(*values)
            case "AND":
                return all(bool(value) for value in _flattened_values_of(values))
        raise ValueError(f"a function that this module does not compute: {name}")

    def _matching_offsets_of(
        self, pairs: Sequence[FormulaNode], tab_name: str
    ) -> set[int]:
        """Give the 0-based offsets that meet every criterion."""
        if not pairs or len(pairs) % 2:
            raise ValueError("criteria without a range")
        matching: set[int] | None = None
        for range_node, criterion_node in zip(pairs[::2], pairs[1::2], strict=True):
            if not isinstance(range_node, RangeNode):
                raise TypeError("a criterion range that is not a range")
            index_key = dataclasses.replace(
                range_node, tab_name=range_node.tab_name or tab_name
            )
            index = self._range_indexes.get(index_key)
            if index is None:
                index = self._range_indexes[index_key] = RangeIndex(
                    self._range_values_of(range_node, tab_name)
                )
            offsets = index.offsets_of(self._value_of_node(criterion_node, tab_name))
            matching = set(offsets) if matching is None else matching & offsets
        assert matching is not None
        return matching


# All but `COUNTIFS` take the range they count or sum first.
_FUNCTIONS_WITH_CRITERIA = ("COUNTIFS", "COUNTUNIQUEIFS", "SUMIFS", "MAXIFS")


class RangeIndex:
    """Index of the values of one range, matching text regardless of letter case as Google Sheets does."""

    def __init__(self, values: Sequence[object]) -> None:
        self._offsets_by_text: dict[str, set[int]] = {}
        self._offsets_by_number: dict[float, set[int]] = {}
        self._blank_offsets: set[int] = set()
        for offset, value in enumerate(values):
            if value is None or value == "":
                self._blank_offsets.add(offset)
            elif isinstance(value, int | float) and not isinstance(value, bool):
                self._offsets_by_number.setdefault(float(value), set()).add(offset)
            else:
                self._offsets_by_text.setdefault(str(value).lower(), set()).add(offset)
        self._all_offsets = set(range(len(values)))
        self._found_offsets: dict[tuple[type, object], set[int]] = {}

    def offsets_of(self, criterion: object) -> set[int]:
        """Give the offsets that a criterion matches."""
        key = (type(criterion), criterion)
        if key not in self._found_offsets:
            self._found_offsets[key] = self._offsets_found_for(criterion)
        return self._found_offsets[key]

    def _offsets_found_for(self, criterion: object) -> set[int]:
        if isinstance(criterion, int | float) and not isinstance(criterion, bool):
            return self._offsets_by_number.get(float(criterion), set())
        if not isinstance(criterion, str):
            raise TypeError(
                f"a criterion that is neither text nor number: {criterion!r}"
            )
        if set(criterion) & set("*?~"):
            raise ValueError(f"a wildcard criterion: {criterion!r}")
        operator_match = re.match(r"(<>|>=|<=|=|>|<)?(.*)", criterion, re.DOTALL)
        assert operator_match is not None
        comparison, operand = operator_match.group(1) or "", operator_match.group(2)
        number = _number_or_none_of(operand)
        if comparison in (">", "<", ">=", "<=") or (
            number is not None and comparison in ("", "=")
        ):
            if number is None:
                raise ValueError(f"a comparison with a text: {criterion!r}")
            compare = _COMPARISONS[comparison or "="]
            return {
                offset
                for number_value, offsets in self._offsets_by_number.items()
                if compare(number_value, number)
                for offset in offsets
            }
        if comparison == "<>":
            if operand == "":
                return self._all_offsets - self._blank_offsets
            return self._all_offsets - self._offsets_by_text.get(operand.lower(), set())
        if operand == "":
            return self._blank_offsets
        return self._offsets_by_text.get(operand.lower(), set())


_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "<>": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


def _number_or_none_of(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _number_of(value: object) -> float:
    """Read a value as a number the way spreadsheet arithmetic does."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool | int | float):
        return float(value)
    raise ValueError(f"arithmetic on a text: {value!r}")


def _count_text_of(value: object, text_format: object) -> str:
    """Compute `TEXT` for the one format the spreadsheet uses, refusing others and fractions rather than guess how Google Sheets rounds."""
    if text_format != COUNT_TEXT_FORMAT:
        raise ValueError(
            f"a format of TEXT that this module does not compute: {text_format!r}"
        )
    number = _number_of(value)
    if not number.is_integer():
        raise ValueError(f"TEXT of a number that is not whole: {number!r}")
    return f"{int(number):,}"


def _is_true(value: object) -> bool:
    """Read the condition of `IF`, refusing a text as `_number_of` does, since Google Sheets gives an error for it."""
    return _number_of(value) != 0


def _flattened_values_of(values: Sequence[object]) -> list[object]:
    return [
        item
        for value in values
        for item in (value if isinstance(value, list) else [value])
    ]


def _elementwise_value_of(
    function: Callable[[object], object], value: object
) -> object:
    if isinstance(value, list):
        return [function(item) for item in value]
    return function(value)


def _binary_value_of(binary_operator: str, left: object, right: object) -> object:
    """Apply an operator to two values, item by item for a range."""
    if isinstance(left, list) or isinstance(right, list):
        left_items = left if isinstance(left, list) else None
        right_items = right if isinstance(right, list) else None
        if (
            left_items is not None
            and right_items is not None
            and len(left_items) != len(right_items)
        ):
            raise ValueError("arrays of different lengths")
        length = len(left_items if left_items is not None else right_items or [])
        return [
            _binary_value_of(
                binary_operator,
                left_items[index] if left_items is not None else left,
                right_items[index] if right_items is not None else right,
            )
            for index in range(length)
        ]
    match binary_operator:
        case "&":
            return f"{_text_of(left)}{_text_of(right)}"
        case "+":
            return _number_of(left) + _number_of(right)
        case "-":
            return _number_of(left) - _number_of(right)
        case "*":
            return _number_of(left) * _number_of(right)
        case "/":
            divisor = _number_of(right)
            if divisor == 0:
                raise ZeroDivisionError("a formula divides by 0")
            return _number_of(left) / divisor
    return _COMPARISONS[binary_operator](_number_of(left), _number_of(right))


def _text_of(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class NumberNode:
    number: float


@dataclass(frozen=True, slots=True)
class TextNode:
    text: str


@dataclass(frozen=True, slots=True)
class CellNode:
    # None for the tab of the formula.
    tab_name: str | None
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class RangeNode:
    """Rectangle of cells, numbered from 1."""

    # None for the tab of the formula.
    tab_name: str | None
    first_row: int
    first_column: int
    last_row: int
    last_column: int


@dataclass(frozen=True, slots=True)
class BinaryNode:
    binary_operator: str
    left: FormulaNode
    right: FormulaNode


@dataclass(frozen=True, slots=True)
class CallNode:
    name: str
    arguments: tuple[FormulaNode, ...]


@dataclass(frozen=True, slots=True)
class ArrayNode:
    rows: tuple[tuple[FormulaNode, ...], ...]


type FormulaNode = (
    NumberNode | TextNode | CellNode | RangeNode | BinaryNode | CallNode | ArrayNode
)

_TOKEN = re.compile(
    r"""
    \s*(?:
      (?P<text>"(?:[^"]|"")*")
    | (?P<reference>(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
    | (?P<function>[A-Z][A-Z0-9.]*)\(
    | (?P<number>\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)
    | (?P<operator><>|>=|<=|[-+*/&=<>(),;{}])
    )
    """,
    re.VERBOSE,
)
_CELL = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")
# Operators by how tightly they bind, loosest first.
_OPERATOR_LEVELS = (("=", "<>", "<", ">", "<=", ">="), ("&",), ("+", "-"), ("*", "/"))


def _parse_formula(formula: str) -> FormulaNode:
    """Read a formula without its leading `=` into nodes."""
    tokens = _tokens_of(formula)
    parser = _FormulaParser(tokens)
    node = parser.expression(0)
    if parser.position != len(tokens):
        raise ValueError(f"text after the end of the formula {formula!r}")
    return node


def _tokens_of(formula: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while formula[position:].strip():
        match = _TOKEN.match(formula, position)
        if match is None or match.lastgroup is None:
            raise ValueError(
                f"an unreadable formula at {formula[position : position + 20]!r}"
            )
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        position = match.end()
    return tokens


class _FormulaParser:
    """Reader of the tokens of one formula."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.position = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> tuple[str, str]:
        token = self._peek()
        if token is None or (expected is not None and token[1] != expected):
            raise ValueError(f"expected {expected!r}, found {token!r}")
        self.position += 1
        return token

    def expression(self, level: int) -> FormulaNode:
        if level == len(_OPERATOR_LEVELS):
            return self._primary()
        node = self.expression(level + 1)
        while (
            (token := self._peek()) is not None
            and token[0] == "operator"
            and token[1] in _OPERATOR_LEVELS[level]
        ):
            self._take()
            node = BinaryNode(token[1], node, self.expression(level + 1))
        return node

    def _primary(self) -> FormulaNode:
        kind, text = self._take()
        if kind == "number":
            return NumberNode(float(text))
        if kind == "text":
            return TextNode(text[1:-1].replace('""', '"'))
        if kind == "reference":
            return _reference_node_of(text)
        if kind == "function":
            arguments: list[FormulaNode] = []
            if self._peek() != ("operator", ")"):
                arguments.append(self.expression(0))
                while self._peek() == ("operator", ","):
                    self._take()
                    arguments.append(self.expression(0))
            self._take(")")
            return CallNode(text, tuple(arguments))
        if text == "(":
            node = self.expression(0)
            self._take(")")
            return node
        if text == "{":
            rows: list[tuple[FormulaNode, ...]] = []
            items: list[FormulaNode] = [self.expression(0)]
            while (token := self._take())[1] != "}":
                if token[1] == ";":
                    rows.append(tuple(items))
                    items = []
                items.append(self.expression(0))
            rows.append(tuple(items))
            return ArrayNode(tuple(rows))
        raise ValueError(f"an unexpected token {text!r}")


def _reference_node_of(text: str) -> CellNode | RangeNode:
    tab_name: str | None = None
    if "!" in text:
        tab_text, text = text.rsplit("!", 1)
        tab_name = (
            tab_text[1:-1].replace("''", "'") if tab_text.startswith("'") else tab_text
        )
    corners = []
    for corner in text.split(":"):
        match = _CELL.fullmatch(corner)
        assert match is not None
        corners.append((int(match.group(2)), column_index_from_string(match.group(1))))
    if len(corners) == 1:
        return CellNode(tab_name, *corners[0])
    return RangeNode(tab_name, *corners[0], *corners[1])


if __name__ == "__main__":
    main()
