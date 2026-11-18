"""Answer the questions of `expand_tool_calls` about programs and the languages they run from the program catalogs, counting every use of a row and every input without one.

A blank cell is unknown only in the role columns, `visibility_of_piped_input` and the exit code columns. Every other column says what it means in a word, e.g. `none` or `unchanged`, and a blank there fails the load, since the door could not read the words of the program without it.
"""

import functools
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    OutputVisibility,
    ProgramBehavior,
    ProgramOptionBehavior,
    ProgramWordRole,
    RanTextLanguage,
    SameAsArgumentRole,
    ShellLanguage,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownProgramBehavior,
    UnknownProgramOptionBehavior,
    UnknownProgramWordRole,
    UnknownRanTextLanguage,
)
from tb_internet_use.knowledge.catalog import (
    Catalog,
    KnowledgeRowKey,
    KnowledgeUses,
    load_catalog,
)

EXPANDED_TOOL_CALL_CATALOGS_DIR = (
    Path(__file__).parent / "catalogs" / "expanded_tool_call"
)
PROGRAM_BEHAVIORS_CSV = "program_behaviors.csv"
PROGRAM_OPTION_BEHAVIORS_CSV = "program_option_behaviors.csv"
CODE_RUNNERS_CSV = "code_runners.csv"
# The source name under which the door counts a name that it read without its version, keyed by the name as asked and the name without its version, e.g. `("python3.11", "python")`.
NAMES_READ_WITHOUT_VERSION = "names_read_without_version"
# A version at the end of a program name, i.e. digits and dots with at most one dash before them, e.g. 3.11 in python3.11 or -12 in gcc-12.
_VERSION_AT_END = re.compile(r"-?\d+(?:\.\d+)*$")
# The values of `runner_kind` in `code_runners.csv`.
_PROGRAM_NAME_RUNNER_KIND = "program_name"
_FILE_EXTENSION_RUNNER_KIND = "file_extension"
# The words of a cell that are no role, and the value each gives.
_SAME = "same"
_UNCHANGED = "unchanged"
_NONE = "none"


class ExpandedToolCallKnowledge:
    """Door of `expand_tool_calls` to the outside knowledge, made for one trial and passed to `expand_tool_calls`, which asks it one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every catalog row that answered and every input without one.
    The loaded catalogs are cached per process, so making a door per trial is cheap.
    """

    def __init__(self, *, catalogs_dir: Path = EXPANDED_TOOL_CALL_CATALOGS_DIR) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_expanded_tool_call_catalogs(catalogs_dir)

    def program_behavior(
        self, program_name: str, words_after_program: Sequence[str]
    ) -> ProgramBehavior | UnknownProgramBehavior:
        """Answer how a program uses its words and stdin, from the row of its subcommand, or `UnknownProgramBehavior` for a program without a fitting row.

        `program_name` is the program word without its folder, e.g. python3.11 for `/usr/bin/python3.11`.
        The row is the one whose subcommand words all come right after the program word, the longest such, and else the row without a subcommand.
        A name without rows is read without its version, e.g. python for python3.11, but only through the rows that say `name_may_end_with_version`.
        One lookup counts the row, or the input `(program_name, "")` when no row fits.
        A name read without its version is also counted as a use of `(program_name, name without version)` under `NAMES_READ_WITHOUT_VERSION`, so the counts show which spellings rest on `name_may_end_with_version`.
        """
        catalogs = self._catalogs
        row_keys = catalogs.program_behavior_row_keys_by_program_name.get(program_name)
        if row_keys is None:
            row_keys = (
                catalogs.program_behavior_row_keys_allowing_version_by_program_name.get(
                    _VERSION_AT_END.sub("", program_name), ()
                )
            )
        fitting_row_keys = [
            row_key
            for row_key in row_keys
            if _is_subcommand_of(row_key[1], words_after_program)
        ]
        row_key = max(
            fitting_row_keys,
            key=lambda key: len(key[1].split()),
            default=(program_name, ""),
        )
        row = catalogs.program_behaviors.lookup(row_key, self.uses)
        if row is None:
            return UnknownProgramBehavior()
        if row_key[0] != program_name:
            self._count_name_read_without_version(program_name, row_key[0])
        return row.program_behavior

    def program_option_behavior(
        self, program_name: str, subcommand_words: Sequence[str], option_name: str
    ) -> ProgramOptionBehavior | UnknownProgramOptionBehavior:
        """Answer whether an option of a program takes a value and how it changes the roles of the other words, or `UnknownProgramOptionBehavior` for an option without a row.

        `program_name` and `subcommand_words` are those of the `ProgramBehavior` of the command, and `option_name` is the option as written, e.g. `-o` or `--output`.
        A row of the subcommand comes before a row of the program without a subcommand, e.g. `(git, clone, --depth)` before `(git, "", --depth)`.
        One lookup counts the row, or the input with the subcommand as asked when neither has a row.
        """
        catalogs = self._catalogs
        asked_row_key = (program_name, " ".join(subcommand_words), option_name)
        row_key = next(
            (
                row_key
                for row_key in (asked_row_key, (program_name, "", option_name))
                if row_key in catalogs.program_option_behavior_row_keys
            ),
            asked_row_key,
        )
        row = catalogs.program_option_behaviors.lookup(row_key, self.uses)
        if row is None:
            return UnknownProgramOptionBehavior()
        return row

    def ran_text_language_of_program(
        self, program_name: str
    ) -> RanTextLanguage | UnknownRanTextLanguage:
        """Answer which language the text that a program runs is in, or `UnknownRanTextLanguage` for a program without a row.

        `program_name` is a name as `ProgramBehavior.program_name` gives it, or as an interpreter line names it, e.g. python3 for `#!/usr/bin/env python3`.
        A name without a row is read without its version, e.g. python for python3, when a row of `program_behaviors.csv` for that name says `name_may_end_with_version`.
        One lookup counts the row `(program_name, name)`, or the name as asked when no row fits.
        A name read without its version is also counted under `NAMES_READ_WITHOUT_VERSION`, as `program_behavior` does.
        """
        catalogs = self._catalogs
        row_key = (_PROGRAM_NAME_RUNNER_KIND, program_name)
        unversioned_row_key = (
            _PROGRAM_NAME_RUNNER_KIND,
            _VERSION_AT_END.sub("", program_name),
        )
        if (
            row_key not in catalogs.code_runner_row_keys
            and unversioned_row_key in catalogs.code_runner_row_keys
            and unversioned_row_key[1]
            in catalogs.program_behavior_row_keys_allowing_version_by_program_name
        ):
            row_key = unversioned_row_key
            self._count_name_read_without_version(program_name, row_key[1])
        row = catalogs.code_runners.lookup(row_key, self.uses)
        return UnknownRanTextLanguage() if row is None else row

    def ran_text_language_of_file_extension(
        self, file_extension: str
    ) -> RanTextLanguage | UnknownRanTextLanguage:
        """Answer which language a file with this extension holds, e.g. Python for `.py`, or `UnknownRanTextLanguage` for an extension without a row.

        One lookup counts the row `(file_extension, extension)`, or the same key as an unknown input.
        """
        row = self._catalogs.code_runners.lookup(
            (_FILE_EXTENSION_RUNNER_KIND, file_extension), self.uses
        )
        return UnknownRanTextLanguage() if row is None else row

    def _count_name_read_without_version(
        self, program_name: str, unversioned_program_name: str
    ) -> None:
        """Count a name that a method read without its version, beside the row that answered."""
        self.uses.row_use_counts[
            NAMES_READ_WITHOUT_VERSION, (program_name, unversioned_program_name)
        ] += 1


def _is_subcommand_of(subcommand: str, words_after_program: Sequence[str]) -> bool:
    """Tell whether the words of a subcommand cell all come right after the program word, which an empty cell always does."""
    subcommand_words = tuple(subcommand.split())
    return tuple(words_after_program[: len(subcommand_words)]) == subcommand_words


@functools.cache
def _load_expanded_tool_call_catalogs(catalogs_dir: Path) -> _ExpandedToolCallCatalogs:
    """Load the three program CSVs of a folder once per process, raising ValueError on a row that `expand_tool_calls` cannot use."""
    program_behaviors = load_catalog(
        catalogs_dir / PROGRAM_BEHAVIORS_CSV,
        key_columns=("program_name", "subcommand"),
        row_from_columns=_program_behavior_row_from_columns,
    )
    program_option_behaviors = load_catalog(
        catalogs_dir / PROGRAM_OPTION_BEHAVIORS_CSV,
        key_columns=("program_name", "subcommand", "option_name"),
        row_from_columns=functools.partial(
            _program_option_behavior_from_columns,
            program_behavior_row_keys=frozenset(program_behaviors.row_keys),
        ),
    )
    code_runners = load_catalog(
        catalogs_dir / CODE_RUNNERS_CSV,
        key_columns=("runner_kind", "runner"),
        row_from_columns=_ran_text_language_from_columns,
    )
    # These lookups sort the rows when the file loads and answer no question of a step, so their counts are dropped.
    unused = KnowledgeUses()
    row_keys_by_program_name: dict[str, list[KnowledgeRowKey]] = {}
    row_keys_allowing_version_by_program_name: dict[str, list[KnowledgeRowKey]] = {}
    name_may_end_with_version_by_program_name: dict[str, bool] = {}
    for row_key in program_behaviors.row_keys:
        row_keys_by_program_name.setdefault(row_key[0], []).append(row_key)
        row = program_behaviors.lookup(row_key, unused)
        assert row is not None
        if (
            name_may_end_with_version_by_program_name.setdefault(
                row_key[0], row.name_may_end_with_version
            )
            != row.name_may_end_with_version
        ):
            raise ValueError(
                f"the rows of {row_key[0]} in {PROGRAM_BEHAVIORS_CSV} differ in name_may_end_with_version"
            )
        if row.name_may_end_with_version:
            row_keys_allowing_version_by_program_name.setdefault(row_key[0], []).append(
                row_key
            )
    return _ExpandedToolCallCatalogs(
        program_behaviors,
        program_option_behaviors,
        code_runners,
        _row_key_tuples_of(row_keys_by_program_name),
        _row_key_tuples_of(row_keys_allowing_version_by_program_name),
        frozenset(program_option_behaviors.row_keys),
        frozenset(code_runners.row_keys),
    )


def _row_key_tuples_of(
    lists_by_name: Mapping[str, list[KnowledgeRowKey]],
) -> Mapping[str, tuple[KnowledgeRowKey, ...]]:
    """Freeze the lists of row keys of each program name."""
    return {name: tuple(row_keys) for name, row_keys in lists_by_name.items()}


@dataclass(frozen=True, slots=True)
class _ExpandedToolCallCatalogs:
    """Loaded catalogs of `expand_tool_calls`, shared by every `ExpandedToolCallKnowledge` of a process."""

    program_behaviors: Catalog[_ProgramBehaviorRow]
    program_option_behaviors: Catalog[ProgramOptionBehavior]
    code_runners: Catalog[RanTextLanguage]
    # The keys of the rows of each program name, so the door can pick the row of the subcommand before its one lookup.
    program_behavior_row_keys_by_program_name: Mapping[str, tuple[KnowledgeRowKey, ...]]
    # The keys of the rows that say `name_may_end_with_version`, by the program name without a version, since only they answer for a name with one.
    program_behavior_row_keys_allowing_version_by_program_name: Mapping[
        str, tuple[KnowledgeRowKey, ...]
    ]
    # The keys of the option rows, so the door can try the row of the subcommand before the row without one.
    program_option_behavior_row_keys: frozenset[KnowledgeRowKey]
    # The keys of the code runner rows, so the door can try the name without its version.
    code_runner_row_keys: frozenset[KnowledgeRowKey]


@dataclass(frozen=True, slots=True)
class _ProgramBehaviorRow:
    """Checked values of one row of `program_behaviors.csv`, kept in its catalog, of which the door gives the `ProgramBehavior` as the answer."""

    program_behavior: ProgramBehavior
    # The row answers also for the program name with a version at its end, e.g. pip3 for pip.
    name_may_end_with_version: bool


def _program_behavior_row_from_columns(
    columns: Mapping[str, str],
) -> _ProgramBehaviorRow:
    """Read one row of `program_behaviors.csv`, raising ValueError on a value that no column allows, e.g. a blank `takes_one_letter_options_joined`."""
    _check_review_columns(columns)
    program_name = columns["program_name"]
    if not program_name:
        raise ValueError("program_name is empty")
    subcommand_words = tuple(columns["subcommand"].split())
    if " ".join(subcommand_words) != columns["subcommand"]:
        raise ValueError(
            f"subcommand {columns['subcommand']!r} is not words split by one space"
        )
    program_behavior = ProgramBehavior(
        program_name=program_name,
        subcommand_words=subcommand_words,
        argument_role=_role_from_cell(columns, "argument_role"),
        first_argument_role=_role_or_same_from_cell(columns, "first_argument_role"),
        last_argument_role=_role_or_same_from_cell(columns, "last_argument_role"),
        stdin_role=_role_or_none_from_cell(columns, "stdin_role"),
        visibility_of_piped_input=_visibility_from_cell(
            columns, "visibility_of_piped_input"
        ),
        gives_arguments_at_run_time=_yes_or_no_from_cell(
            columns, "gives_arguments_at_run_time"
        ),
        skips_assignment_words=_yes_or_no_from_cell(columns, "skips_assignment_words"),
        options_end_at_first_argument=_yes_or_no_from_cell(
            columns, "options_end_at_first_argument"
        ),
        takes_one_letter_options_joined=_yes_or_no_from_cell(
            columns, "takes_one_letter_options_joined"
        ),
        runs_text_in_calling_shell=_yes_or_no_from_cell(
            columns, "runs_text_in_calling_shell"
        ),
        exits_with_exit_code_of_next_program=_exits_with_exit_code_of_next_program_from_cell(
            columns, "exits_with_exit_code_of_next_program"
        ),
        default_run_file=_text_or_none_from_cell(columns, "default_run_file"),
    )
    return _ProgramBehaviorRow(
        program_behavior,
        _yes_or_no_from_cell(columns, "name_may_end_with_version"),
    )


def _program_option_behavior_from_columns(
    columns: Mapping[str, str], *, program_behavior_row_keys: frozenset[KnowledgeRowKey]
) -> ProgramOptionBehavior:
    """Read one row of `program_option_behaviors.csv`, raising ValueError on a program and subcommand without a row of `program_behaviors.csv`, on a value that no column allows and on end words of a next program that the option does not run."""
    _check_review_columns(columns)
    program_row_key = (columns["program_name"], columns["subcommand"])
    if program_row_key not in program_behavior_row_keys:
        raise ValueError(
            f"the program {program_row_key} has no row in {PROGRAM_BEHAVIORS_CSV}"
        )
    if not columns["option_name"]:
        raise ValueError("option_name is empty")
    argument_role_with_option = _changed_role_from_cell(
        columns, "argument_role_with_option", role_from_cell=_role_from_cell
    )
    next_program_end_words = _words_from_cell(columns, "next_program_end_words")
    if next_program_end_words and argument_role_with_option != ProgramWordRole.PROGRAM:
        raise ValueError(
            "next_program_end_words is not none, but argument_role_with_option is not program"
        )
    return ProgramOptionBehavior(
        takes_value=_yes_or_no_from_cell(columns, "takes_value"),
        value_role=_role_or_none_from_cell(columns, "value_role"),
        argument_role_with_option=argument_role_with_option,
        first_argument_role_with_option=_changed_role_from_cell(
            columns,
            "first_argument_role_with_option",
            role_from_cell=_role_or_same_from_cell,
        ),
        last_argument_role_with_option=_changed_role_from_cell(
            columns,
            "last_argument_role_with_option",
            role_from_cell=_role_or_same_from_cell,
        ),
        changed_option_name=_text_or_none_from_cell(columns, "changed_option_name"),
        changed_option_value_role=_role_or_none_from_cell(
            columns, "changed_option_value_role"
        ),
        gives_arguments_at_run_time=_yes_or_no_from_cell(
            columns, "gives_arguments_at_run_time"
        ),
        next_program_end_words=next_program_end_words,
        exits_with_exit_code_of_next_program_with_option=_exits_with_exit_code_of_next_program_with_option_from_cell(
            columns, "exits_with_exit_code_of_next_program_with_option"
        ),
    )


def _ran_text_language_from_columns(columns: Mapping[str, str]) -> RanTextLanguage:
    """Read one row of `code_runners.csv`, raising ValueError on a runner kind or language that is none of the allowed words and on a file extension without its dot."""
    _check_review_columns(columns)
    runner_kind = columns["runner_kind"]
    if runner_kind not in (_PROGRAM_NAME_RUNNER_KIND, _FILE_EXTENSION_RUNNER_KIND):
        raise ValueError(f"runner_kind {runner_kind!r} is not one of the two kinds")
    runner = columns["runner"]
    if not runner:
        raise ValueError("runner is empty")
    if runner_kind == _FILE_EXTENSION_RUNNER_KIND and not runner.startswith("."):
        raise ValueError(f"the file extension {runner!r} does not start with a dot")
    ran_text_language = columns["ran_text_language"]
    if ran_text_language == "shell":
        return ShellLanguage()
    return CodeLanguage(ran_text_language)


def _check_review_columns(columns: Mapping[str, str]) -> None:
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is neither empty nor `yes`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes"):
        raise ValueError(f"reviewed is {columns['reviewed']!r}, not empty or yes")


def _role_or_same_from_cell(
    columns: Mapping[str, str], column: str
) -> ProgramWordRole | UnknownProgramWordRole | SameAsArgumentRole:
    """Read a role cell of the first or last argument, in which `same` gives the role of the other arguments and a blank is unknown."""
    if columns[column] == _SAME:
        return SameAsArgumentRole()
    return _role_from_cell(columns, column)


def _role_or_none_from_cell(
    columns: Mapping[str, str], column: str
) -> ProgramWordRole | UnknownProgramWordRole | None:
    """Read a role cell in which `none` says there is nothing to have a role, e.g. a stdin that the program does not read, and a blank is unknown."""
    return None if columns[column] == _NONE else _role_from_cell(columns, column)


def _changed_role_from_cell[Role](
    columns: Mapping[str, str],
    column: str,
    *,
    role_from_cell: Callable[[Mapping[str, str], str], Role],
) -> Role | None:
    """Read a role cell of an option row, in which `unchanged` keeps the role of the program row."""
    if columns[column] == _UNCHANGED:
        return None
    return role_from_cell(columns, column)


def _role_from_cell(
    columns: Mapping[str, str], column: str
) -> ProgramWordRole | UnknownProgramWordRole:
    """Read a role cell, in which a blank is unknown, raising ValueError on a word that is no `ProgramWordRole`."""
    cell = columns[column]
    return UnknownProgramWordRole() if cell == "" else ProgramWordRole(cell)


def _visibility_from_cell(columns: Mapping[str, str], column: str) -> OutputVisibility:
    """Read `visibility_of_piped_input`, in which a blank and only a blank is unknown, raising ValueError on the word `unknown` and on any word that is no `OutputVisibility`."""
    cell = columns[column]
    if cell == OutputVisibility.UNKNOWN:
        raise ValueError(f"{column} is unknown only when blank")
    return OutputVisibility.UNKNOWN if cell == "" else OutputVisibility(cell)


def _exits_with_exit_code_of_next_program_with_option_from_cell(
    columns: Mapping[str, str], column: str
) -> bool | UnknownExitsWithExitCodeOfNextProgram | None:
    """Read the exit code cell of an option row, in which `unchanged` keeps the answer of the program row and a blank is unknown."""
    if columns[column] == _UNCHANGED:
        return None
    return _exits_with_exit_code_of_next_program_from_cell(columns, column)


def _exits_with_exit_code_of_next_program_from_cell(
    columns: Mapping[str, str], column: str
) -> bool | UnknownExitsWithExitCodeOfNextProgram:
    """Read an exit code cell of `yes`, `no` or a blank, which is unknown, raising ValueError on any other word."""
    if columns[column] == "":
        return UnknownExitsWithExitCodeOfNextProgram()
    return _yes_or_no_from_cell(columns, column)


def _yes_or_no_from_cell(columns: Mapping[str, str], column: str) -> bool:
    """Read `yes` as True and `no` as False, raising ValueError on any other cell, a blank included."""
    cell = columns[column]
    if cell not in ("yes", "no"):
        raise ValueError(f"{column} is {cell!r}, not yes or no")
    return cell == "yes"


def _words_from_cell(columns: Mapping[str, str], column: str) -> tuple[str, ...]:
    """Read a column of words split by spaces or `none`, raising ValueError on a blank."""
    text = _text_or_none_from_cell(columns, column)
    return () if text is None else tuple(text.split())


def _text_or_none_from_cell(columns: Mapping[str, str], column: str) -> str | None:
    """Read a column of a name or `none`, raising ValueError on a blank."""
    cell = columns[column]
    if cell == "":
        raise ValueError(f"{column} is blank, not a name or none")
    return None if cell == _NONE else cell
