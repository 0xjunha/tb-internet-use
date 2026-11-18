"""Answer the questions of `decide_network_request_results` about output lines and program runs from the output line pattern declarations and the program output catalogs, counting every use of a pattern or row and every input without a row.

A blank cell of `printing_programs`, `prints_status_code` or `meaning` is unknown, and the door then answers with the `Unknown…` type of the method, never with a default. Every other cell says what it means in a word, e.g. `none` or `changes_nothing`, and a blank there fails the load.
"""

import functools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import ProgramInvocation, ProgramOption
from tb_internet_use.knowledge.catalog import (
    Catalog,
    KnowledgeRowKey,
    KnowledgeUses,
    load_catalog,
)
from tb_internet_use.knowledge.declarations.network_request_result.output_line_patterns import (
    PROGRAM_OUTPUT_LINE_PATTERNS,
    WEB_TOOL_RESULT_LINE_PATTERNS,
)
from tb_internet_use.network_request_result.model import (
    OutputLineMeaning,
    PrintingProgram,
    ProgramExitCodeMeaning,
    ProgramOutputLines,
    UnknownOutputLineMeaning,
    UnknownProgramExitCodeMeaning,
    UnknownProgramOutputLines,
)

# The name of the folder of the output line pattern declarations, which the counts of their uses carry.
OUTPUT_LINE_PATTERNS_DECLARATIONS = "output_line_patterns"
NETWORK_REQUEST_RESULT_CATALOGS_DIR = (
    Path(__file__).parent / "catalogs" / "network_request_result"
)
PROGRAM_OUTPUT_LINES_CSV = "program_output_lines.csv"
PROGRAM_EXIT_CODES_CSV = "program_exit_codes.csv"
# The word of an option row whose option leaves the cell of the program row as it is.
_CHANGES_NOTHING = "changes_nothing"
# The word of `printing_programs` for a program run that prints no line of a pattern.
_NONE = "none"


class NetworkRequestResultKnowledge:
    """Door of `decide_network_request_results` to the outside knowledge, made for one trial and passed to `decide_network_request_results`, which asks it one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every declared pattern that answered, every catalog row that answered and every program run, option or exit code without a row.
    A line without a pattern is not counted, since an output line has no name, so a missing pattern cannot be told apart from a line that means nothing.
    The loaded catalogs are cached per process, so making a door per trial is cheap.
    """

    def __init__(
        self, *, catalogs_dir: Path = NETWORK_REQUEST_RESULT_CATALOGS_DIR
    ) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_network_request_result_catalogs(catalogs_dir)

    def output_line_meaning(
        self, line: str, *, is_web_tool_result: bool
    ) -> OutputLineMeaning | UnknownOutputLineMeaning:
        """Answer what one output line means and which programs print it, from the first pattern that matches it, or `UnknownOutputLineMeaning` when no pattern does.

        `line` is one part of a line of a result, without ANSI control sequences, e.g. `Successfully installed x-1.0`.
        The result of a call made only of web tool actions is page text, so its lines are read with the web tool result patterns and no program output pattern.
        A matched line counts as a use of the row `(table, pattern)` under `OUTPUT_LINE_PATTERNS_DECLARATIONS`, e.g. `("program_output", "pip_already_satisfied")`.
        A line without a pattern gives `UnknownOutputLineMeaning` and is not counted, since an output line has no name that a missing pattern could be noticed for.
        """
        table = (
            WEB_TOOL_RESULT_LINE_PATTERNS
            if is_web_tool_result
            else PROGRAM_OUTPUT_LINE_PATTERNS
        )
        matched_output_line_pattern = table.matched_output_line_pattern_of(line)
        if matched_output_line_pattern is None:
            return UnknownOutputLineMeaning()
        row_key = (table.name, matched_output_line_pattern.output_line_pattern.name)
        self.uses.row_use_counts[OUTPUT_LINE_PATTERNS_DECLARATIONS, row_key] += 1
        return matched_output_line_pattern.output_line_meaning

    def program_output_lines(
        self, program_invocation: ProgramInvocation
    ) -> ProgramOutputLines | UnknownProgramOutputLines:
        """Answer which printing programs' lines one program run can print and whether it prints a bare status code, or `UnknownProgramOutputLines` for a run without the rows to tell.

        The answer joins the row of the program and subcommand with the row of each option of the run, e.g. `(curl, "", -i)` adds `HTTP_HEADERS` to the lines of curl.
        An option row with `option_value_part` changes nothing unless the value of the option holds one of its texts, e.g. `%{http_code}` or `%{response_code}` in the value of `-w`.
        Whether such a row applies is unknown, and so is the answer, when the option has no value or a value without those texts that holds a `$`, e.g. `-w "$FMT"`, whose text is set when it runs.
        A run prints a status code when any of its rows says `yes`.
        A blank cell in any row that applies makes the answer unknown.
        The rows and their misses are counted as `_find_and_count_rows_of_program_run` says.
        """
        rows = _find_and_count_rows_of_program_run(
            self._catalogs.program_output_lines, program_invocation, (), self.uses
        )
        if rows is None:
            return UnknownProgramOutputLines()
        program_row, option_rows = rows
        printing_programs = program_row.printing_programs
        prints_status_code = program_row.prints_status_code
        # A program row never holds `changes_nothing`, which the load refuses, so only a blank stays to rule out.
        if not isinstance(printing_programs, frozenset) or not isinstance(
            prints_status_code, bool
        ):
            return UnknownProgramOutputLines()
        for option_row, program_option in option_rows:
            is_option_row_applying = _is_option_row_applying_to(
                option_row, program_option
            )
            if isinstance(is_option_row_applying, UnknownProgramOutputLines):
                return UnknownProgramOutputLines()
            if not is_option_row_applying:
                continue
            if isinstance(
                option_row.printing_programs, UnknownProgramOutputLines
            ) or isinstance(option_row.prints_status_code, UnknownProgramOutputLines):
                return UnknownProgramOutputLines()
            if option_row.printing_programs is not None:
                printing_programs |= option_row.printing_programs
            prints_status_code = (
                prints_status_code or option_row.prints_status_code is True
            )
        return ProgramOutputLines(printing_programs, prints_status_code)

    def program_exit_code_meaning(
        self, program_invocation: ProgramInvocation, exit_code: int
    ) -> ProgramExitCodeMeaning | UnknownProgramExitCodeMeaning:
        """Answer what one exit code of a program run says of its request, or `UnknownProgramExitCodeMeaning` for a run and code without the rows to tell.

        The meaning of an option row that is not `changes_nothing` takes the place of that of the program row, e.g. `request_succeeded` for exit 0 of `curl -f` where curl alone says `server_answered`.
        Two such option rows that differ make the answer unknown.
        A blank meaning in any row of the run makes the answer unknown too, that of the program row included, since every row of the run applies.
        The rows and their misses are keyed by the exit code too, e.g. `(curl, "", "", "22")`, and counted as `_find_and_count_rows_of_program_run` says.
        """
        rows = _find_and_count_rows_of_program_run(
            self._catalogs.program_exit_codes,
            program_invocation,
            (str(exit_code),),
            self.uses,
        )
        if rows is None:
            return UnknownProgramExitCodeMeaning()
        program_row, option_rows = rows
        option_meanings = {
            option_row.meaning
            for option_row, _ in option_rows
            if option_row.meaning is not None
        }
        # A program row never holds `changes_nothing`, which the load refuses.
        assert program_row.meaning is not None
        if isinstance(program_row.meaning, UnknownProgramExitCodeMeaning) or any(
            isinstance(meaning, UnknownProgramExitCodeMeaning)
            for meaning in option_meanings
        ):
            return UnknownProgramExitCodeMeaning()
        if len(option_meanings) > 1:
            return UnknownProgramExitCodeMeaning()
        if option_meanings:
            return option_meanings.pop()
        return program_row.meaning


def _find_and_count_rows_of_program_run[Row](
    catalog: _ProgramRunCatalog[Row],
    program_invocation: ProgramInvocation,
    key_end: KnowledgeRowKey,
    uses: KnowledgeUses,
) -> tuple[Row, list[tuple[Row, ProgramOption]]] | None:
    """Find the row of a program run and the row of each of its options, each paired with its option, or None when a row is missing, and count the rows found or the keys missed in `uses`.

    The key of a row is the program name, the subcommand words split by one space, the option name, or a blank for the program row, and `key_end`.
    Nothing is counted until the door knows whether every row is there. Then each row found counts as a use. When a row is missing, only the missing keys count, as unknown inputs, e.g. `(curl, "", -L)`, and only the program row's key when that is missing.
    A run with `unread_words` misses a row too, since an option of it was not read. It counts the first unread word in place of an option name, e.g. `(curl, "", --foo)` for `curl --foo x u`, since no row can answer for options that nobody read.
    That count goes straight into `uses.unknown_input_counts`, since `Catalog.lookup` would count it as a use if a row had that word as its option.
    """
    program_name = program_invocation.program_name
    subcommand = " ".join(program_invocation.subcommand_words)
    program_row_key = (program_name, subcommand, "", *key_end)
    option_row_keys = [
        (program_name, subcommand, program_option.name, *key_end)
        for program_option in program_invocation.options
    ]
    if program_row_key not in catalog.row_keys:
        catalog.catalog.lookup(program_row_key, uses)
        return None
    missing_row_keys = [
        row_key for row_key in option_row_keys if row_key not in catalog.row_keys
    ]
    if missing_row_keys or program_invocation.unread_words:
        for row_key in missing_row_keys:
            catalog.catalog.lookup(row_key, uses)
        if program_invocation.unread_words:
            unread_row_key = (
                program_name,
                subcommand,
                program_invocation.unread_words[0],
                *key_end,
            )
            uses.unknown_input_counts[catalog.catalog.file_name, unread_row_key] += 1
        return None
    program_row = catalog.catalog.lookup(program_row_key, uses)
    assert program_row is not None
    option_rows: list[tuple[Row, ProgramOption]] = []
    for row_key, program_option in zip(
        option_row_keys, program_invocation.options, strict=True
    ):
        option_row = catalog.catalog.lookup(row_key, uses)
        assert option_row is not None
        option_rows.append((option_row, program_option))
    return program_row, option_rows


def _is_option_row_applying_to(
    option_row: _ProgramOutputLinesRow, program_option: ProgramOption
) -> bool | UnknownProgramOutputLines:
    """Tell whether an option row of `program_output_lines.csv` applies to an option, which it does unless it names texts of which the value of the option holds none.

    It is unknown for an option without a value and for a value that holds none of the texts but a `$`, e.g. `-w "$FMT"`, since the text of that value is set when it runs.
    """
    if not option_row.option_value_parts:
        return True
    value = program_option.value
    if value is None:
        return UnknownProgramOutputLines()
    if any(
        option_value_part in value
        for option_value_part in option_row.option_value_parts
    ):
        return True
    if "$" in value:
        return UnknownProgramOutputLines()
    return False


@functools.cache
def _load_network_request_result_catalogs(
    catalogs_dir: Path,
) -> _NetworkRequestResultCatalogs:
    """Load the two program output CSVs of a folder once per process, raising ValueError on a row that `decide_network_request_results` cannot use."""
    program_output_lines = load_catalog(
        catalogs_dir / PROGRAM_OUTPUT_LINES_CSV,
        key_columns=("program_name", "subcommand", "option_name"),
        row_from_columns=_program_output_lines_row_from_columns,
    )
    program_exit_codes = load_catalog(
        catalogs_dir / PROGRAM_EXIT_CODES_CSV,
        key_columns=("program_name", "subcommand", "option_name", "exit_code"),
        row_from_columns=_program_exit_code_row_from_columns,
    )
    return _NetworkRequestResultCatalogs(
        _program_run_catalog_of(program_output_lines),
        _program_run_catalog_of(program_exit_codes),
    )


def _program_run_catalog_of[Row](catalog: Catalog[Row]) -> _ProgramRunCatalog[Row]:
    """Index the keys of a program output catalog, raising ValueError on an option row without the program row it changes."""
    row_keys = frozenset(catalog.row_keys)
    for program_name, subcommand, option_name, *key_end in catalog.row_keys:
        if option_name and (program_name, subcommand, "", *key_end) not in row_keys:
            raise ValueError(
                f"the option row {(program_name, subcommand, option_name, *key_end)} of {catalog.file_name} has no program row"
            )
    return _ProgramRunCatalog(catalog, row_keys)


@dataclass(frozen=True, slots=True)
class _ProgramRunCatalog[Row]:
    """Catalog keyed by program, subcommand and option, with the set of its keys, so that the door can tell whether every row of a run is there before it counts any."""

    catalog: Catalog[Row]
    row_keys: frozenset[KnowledgeRowKey]


@dataclass(frozen=True, slots=True)
class _NetworkRequestResultCatalogs:
    """Loaded catalogs of `decide_network_request_results`, shared by every `NetworkRequestResultKnowledge` of a process."""

    program_output_lines: _ProgramRunCatalog[_ProgramOutputLinesRow]
    program_exit_codes: _ProgramRunCatalog[_ProgramExitCodeRow]


@dataclass(frozen=True, slots=True)
class _ProgramOutputLinesRow:
    """Checked cells of one row of `program_output_lines.csv`, in which None is `changes_nothing` of an option row and `UnknownProgramOutputLines` a blank."""

    # The texts of `option_value_part`, of which the value of the option must hold one for the row to apply. Empty when the row applies to every value.
    option_value_parts: tuple[str, ...]
    printing_programs: frozenset[PrintingProgram] | UnknownProgramOutputLines | None
    prints_status_code: bool | UnknownProgramOutputLines | None


@dataclass(frozen=True, slots=True)
class _ProgramExitCodeRow:
    """Checked cell of one row of `program_exit_codes.csv`, in which None is `changes_nothing` of an option row and `UnknownProgramExitCodeMeaning` a blank."""

    meaning: ProgramExitCodeMeaning | UnknownProgramExitCodeMeaning | None


def _program_output_lines_row_from_columns(
    columns: Mapping[str, str],
) -> _ProgramOutputLinesRow:
    """Read one row of `program_output_lines.csv`, raising ValueError on a word that no column allows, e.g. `changes_nothing` in a program row or `none` in an option row."""
    _check_field_count(columns)
    _check_key_columns(columns)
    _check_review_columns(columns)
    is_option_row = columns["option_name"] != ""
    option_value_part = columns["option_value_part"]
    if option_value_part and not is_option_row:
        raise ValueError("option_value_part is filled in a program row")
    option_value_parts = (
        tuple(option_value_part.split(" ")) if option_value_part else ()
    )
    if "" in option_value_parts:
        raise ValueError(
            f"option_value_part {option_value_part!r} is not texts split by one space"
        )
    return _ProgramOutputLinesRow(
        option_value_parts=option_value_parts,
        printing_programs=_fact_from_cell(
            columns,
            "printing_programs",
            is_option_row=is_option_row,
            value_from_cell=_printing_programs_from_cell,
            unknown=UnknownProgramOutputLines(),
        ),
        prints_status_code=_fact_from_cell(
            columns,
            "prints_status_code",
            is_option_row=is_option_row,
            value_from_cell=_yes_or_no_from_cell,
            unknown=UnknownProgramOutputLines(),
        ),
    )


def _program_exit_code_row_from_columns(
    columns: Mapping[str, str],
) -> _ProgramExitCodeRow:
    """Read one row of `program_exit_codes.csv`, raising ValueError on an exit code that is not written as a whole number and on a meaning that is no `ProgramExitCodeMeaning`."""
    _check_field_count(columns)
    _check_key_columns(columns)
    _check_review_columns(columns)
    is_option_row = columns["option_name"] != ""
    exit_code = columns["exit_code"]
    if not exit_code.isdigit() or str(int(exit_code)) != exit_code:
        raise ValueError(f"exit_code {exit_code!r} is not a whole number")
    return _ProgramExitCodeRow(
        _fact_from_cell(
            columns,
            "meaning",
            is_option_row=is_option_row,
            value_from_cell=ProgramExitCodeMeaning,
            unknown=UnknownProgramExitCodeMeaning(),
        )
    )


def _check_field_count(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row with more or fewer fields than the header, e.g. a `note` with an unquoted comma.

    `csv.DictReader` puts the fields beyond the header under the key None and gives None to the columns a short row lacks, so the load would otherwise drop or miss them without a word.
    """
    if None in columns or None in columns.values():
        raise ValueError("the row has more or fewer fields than the header")


def _check_key_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row with a blank `program_name` or a subcommand not split by one space."""
    if not columns["program_name"]:
        raise ValueError("program_name is empty")
    if " ".join(columns["subcommand"].split()) != columns["subcommand"]:
        raise ValueError(
            f"subcommand {columns['subcommand']!r} is not words split by one space"
        )


def _check_review_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is neither empty nor `yes`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes"):
        raise ValueError(f"reviewed is {columns['reviewed']!r}, not empty or yes")


def _fact_from_cell[Value, Unknown](
    columns: Mapping[str, str],
    column: str,
    *,
    is_option_row: bool,
    value_from_cell: Callable[[str], Value],
    unknown: Unknown,
) -> Value | Unknown | None:
    """Read the fact of a cell, which is `unknown` for a blank and None for `changes_nothing`, a word allowed only in an option row."""
    cell = columns[column]
    if cell == "":
        return unknown
    if cell == _CHANGES_NOTHING:
        if not is_option_row:
            raise ValueError(f"{column} is changes_nothing in a program row")
        return None
    if is_option_row and cell == _NONE:
        raise ValueError(f"{column} is none in an option row, not changes_nothing")
    return value_from_cell(cell)


def _printing_programs_from_cell(cell: str) -> frozenset[PrintingProgram]:
    """Read `PrintingProgram` values split by one space, or `none` for a run that prints no line of a pattern, raising ValueError on any other word."""
    if cell == _NONE:
        return frozenset()
    words: Sequence[str] = cell.split(" ")
    return frozenset(PrintingProgram(word) for word in words)


def _yes_or_no_from_cell(cell: str) -> bool:
    """Read `yes` as True and `no` as False, raising ValueError on any other word."""
    if cell not in ("yes", "no"):
        raise ValueError(f"{cell!r} is not yes or no")
    return cell == "yes"
