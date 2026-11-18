"""Tests for knowledge/expanded_tool_call_knowledge.py, with made-up catalogs, and of the rows that the real catalogs took over from the old program tables."""

import csv
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    OutputVisibility,
    ProgramArgumentWord,
    ProgramBehavior,
    ProgramOptionBehavior,
    ProgramOptionWord,
    ProgramOptionWordOption,
    ProgramWordRole,
    SameAsArgumentRole,
    ShellLanguage,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownProgramBehavior,
    UnknownProgramOptionWord,
    UnknownProgramWordRole,
    UnknownRanTextLanguage,
)
from tb_internet_use.interpret.callrun.code_program_tables import (
    CODE_PROGRAMS,
    LANGUAGE_OF_FILE_EXTENSION,
    SHELL_FILE_EXTENSIONS,
)
from tb_internet_use.knowledge.catalog import KnowledgeUses
from tb_internet_use.knowledge.expanded_tool_call_knowledge import (
    CODE_RUNNERS_CSV,
    EXPANDED_TOOL_CALL_CATALOGS_DIR,
    NAMES_READ_WITHOUT_VERSION,
    PROGRAM_BEHAVIORS_CSV,
    PROGRAM_OPTION_BEHAVIORS_CSV,
    ExpandedToolCallKnowledge,
)
from tb_internet_use.parse.program.catalog_loader import program_catalog
from tb_internet_use.parse.program.option_syntax_tables import OPTION_SYNTAX_OF_PROGRAM
from tb_internet_use.parse.shell.program_tables import (
    PROGRAMS_GIVING_RUN_TIME_ARGUMENTS,
    PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE,
    SHELL_PROGRAMS,
    VERSIONED_PROGRAMS,
    WRAPPERS,
)

# A program row of `prog` whose every cell differs from what a default would give, so that a door that drops a column fails.
_PROGRAM_ROW_CELLS = {
    "program_name": "prog",
    "subcommand": "",
    "argument_role": "read_file",
    "first_argument_role": "pattern",
    "last_argument_role": "same",
    "stdin_role": "none",
    "visibility_of_piped_input": "partial",
    "gives_arguments_at_run_time": "yes",
    "skips_assignment_words": "yes",
    "options_end_at_first_argument": "yes",
    "takes_one_letter_options_joined": "no",
    "runs_text_in_calling_shell": "yes",
    "exits_with_exit_code_of_next_program": "yes",
    "name_may_end_with_version": "no",
    "default_run_file": "Makefile",
    "checked_against": "a manual",
    "reviewed": "",
    "note": "",
}
_PROGRAM_BEHAVIOR = ProgramBehavior(
    program_name="prog",
    subcommand_words=(),
    argument_role=ProgramWordRole.READ_FILE,
    first_argument_role=ProgramWordRole.PATTERN,
    last_argument_role=SameAsArgumentRole(),
    stdin_role=None,
    visibility_of_piped_input=OutputVisibility.PARTIAL,
    gives_arguments_at_run_time=True,
    skips_assignment_words=True,
    options_end_at_first_argument=True,
    takes_one_letter_options_joined=False,
    runs_text_in_calling_shell=True,
    exits_with_exit_code_of_next_program=True,
    default_run_file="Makefile",
)
# An option row of `prog` whose cells all say something, read into `_PROGRAM_OPTION_BEHAVIOR`.
_OPTION_ROW_CELLS = {
    "program_name": "prog",
    "subcommand": "",
    "option_name": "-x",
    "takes_value": "yes",
    "value_role": "written_file",
    "argument_role_with_option": "program",
    "first_argument_role_with_option": "same",
    "last_argument_role_with_option": "copy_destination",
    "changed_option_name": "-f",
    "changed_option_value_role": "used_file",
    "gives_arguments_at_run_time": "yes",
    "exits_with_exit_code_of_next_program_with_option": "no",
    "next_program_end_words": "; +",
    "checked_against": "a manual",
    "reviewed": "yes",
    "note": "",
}
_PROGRAM_OPTION_BEHAVIOR = ProgramOptionBehavior(
    takes_value=True,
    value_role=ProgramWordRole.WRITTEN_FILE,
    argument_role_with_option=ProgramWordRole.PROGRAM,
    first_argument_role_with_option=SameAsArgumentRole(),
    last_argument_role_with_option=ProgramWordRole.COPY_DESTINATION,
    changed_option_name="-f",
    changed_option_value_role=ProgramWordRole.USED_FILE,
    gives_arguments_at_run_time=True,
    next_program_end_words=(";", "+"),
    exits_with_exit_code_of_next_program_with_option=False,
)
# An option row that changes nothing, which a test changes one cell of.
_UNCHANGING_OPTION_ROW_CELLS = {
    **_OPTION_ROW_CELLS,
    "takes_value": "no",
    "value_role": "none",
    "argument_role_with_option": "unchanged",
    "first_argument_role_with_option": "unchanged",
    "last_argument_role_with_option": "unchanged",
    "changed_option_name": "none",
    "changed_option_value_role": "none",
    "gives_arguments_at_run_time": "no",
    "exits_with_exit_code_of_next_program_with_option": "unchanged",
    "next_program_end_words": "none",
}
# What `_UNCHANGING_OPTION_ROW_CELLS` reads into, and the same with a value of unknown role.
_OPTION_TAKING_NO_VALUE = ProgramOptionBehavior(
    takes_value=False,
    value_role=None,
    argument_role_with_option=None,
    first_argument_role_with_option=None,
    last_argument_role_with_option=None,
    changed_option_name=None,
    changed_option_value_role=None,
    gives_arguments_at_run_time=False,
    next_program_end_words=(),
    exits_with_exit_code_of_next_program_with_option=None,
)
_OPTION_TAKING_A_VALUE = replace(
    _OPTION_TAKING_NO_VALUE, takes_value=True, value_role=UnknownProgramWordRole()
)
# Option rows of prog for the words of `program_option_word`. -s and -f take no value, and -o, --out and +o take one.
_OPTION_ROWS_OF_ONE_WORD: list[Mapping[str, str]] = [
    *(
        {**_UNCHANGING_OPTION_ROW_CELLS, "option_name": option_name}
        for option_name in ("-s", "-f")
    ),
    *(
        {
            **_UNCHANGING_OPTION_ROW_CELLS,
            "option_name": option_name,
            "takes_value": "yes",
            "value_role": "",
        }
        for option_name in ("-o", "--out", "+o")
    ),
]
_CODE_RUNNER_ROW_CELLS = {
    "runner_kind": "program_name",
    "runner": "prog",
    "ran_text_language": "python",
    "checked_against": "a manual",
    "reviewed": "",
    "note": "",
}

# (column of a program row, which is also the field of `ProgramBehavior` it fills, answer for a blank cell)
_BLANK_PROGRAM_CELLS_THAT_ARE_UNKNOWN = [
    ("argument_role", UnknownProgramWordRole()),
    ("first_argument_role", UnknownProgramWordRole()),
    ("last_argument_role", UnknownProgramWordRole()),
    ("stdin_role", UnknownProgramWordRole()),
    ("visibility_of_piped_input", OutputVisibility.UNKNOWN),
    (
        "exits_with_exit_code_of_next_program",
        UnknownExitsWithExitCodeOfNextProgram(),
    ),
]
# Columns of a program row in which a blank fails the load.
_PROGRAM_COLUMNS_THAT_CANNOT_BE_BLANK = [
    "gives_arguments_at_run_time",
    "skips_assignment_words",
    "options_end_at_first_argument",
    "takes_one_letter_options_joined",
    "runs_text_in_calling_shell",
    "name_may_end_with_version",
    "default_run_file",
    "checked_against",
]
# (column of an option row, which is also the field of `ProgramOptionBehavior` it fills, answer for a blank cell), on `_UNCHANGING_OPTION_ROW_CELLS`
_BLANK_OPTION_CELLS_THAT_ARE_UNKNOWN = [
    ("argument_role_with_option", UnknownProgramWordRole()),
    ("first_argument_role_with_option", UnknownProgramWordRole()),
    ("last_argument_role_with_option", UnknownProgramWordRole()),
    (
        "exits_with_exit_code_of_next_program_with_option",
        UnknownExitsWithExitCodeOfNextProgram(),
    ),
]
# Columns of an option row in which a blank fails the load. A blank `value_role` is unknown, which an option without a value cannot have.
_OPTION_COLUMNS_THAT_CANNOT_BE_BLANK = [
    "takes_value",
    "value_role",
    "changed_option_name",
    "gives_arguments_at_run_time",
    "next_program_end_words",
    "checked_against",
]
# (cells that differ from `_PROGRAM_ROW_CELLS`, a part of the error message)
_PROGRAM_ROWS_THAT_CANNOT_LOAD = [
    ({"argument_role": "file"}, "'file' is not a valid ProgramWordRole"),
    # Only the first and last argument can take the role of the other arguments.
    ({"argument_role": "same"}, "'same' is not a valid ProgramWordRole"),
    # Unknown is written as a blank, so that one cell means one thing.
    ({"visibility_of_piped_input": "unknown"}, "unknown only when blank"),
    ({"exits_with_exit_code_of_next_program": "maybe"}, "not yes or no"),
    ({"subcommand": "pip  install"}, "not words split by one space"),
    ({"reviewed": "no"}, "not empty or yes"),
    ({"program_name": ""}, "program_name is empty"),
]
# Rows of one program name that differ in `name_may_end_with_version`, so that the door could not tell whether pip3 is pip.
_PROGRAM_ROWS_THAT_DISAGREE_ON_A_VERSION = [
    {"program_name": "pip", "subcommand": "", "name_may_end_with_version": "yes"},
    {"program_name": "pip", "subcommand": "install", "name_may_end_with_version": "no"},
]
# (cells that differ from `_OPTION_ROW_CELLS`, a part of the error message)
_OPTION_ROWS_THAT_CANNOT_LOAD = [
    ({"program_name": "other"}, "has no row in program_behaviors.csv"),
    ({"subcommand": "run"}, "has no row in program_behaviors.csv"),
    # A value role on an option that takes no value, and an option that takes a value without a role for it.
    ({"takes_value": "no"}, "value role"),
    ({"value_role": "none"}, "value role"),
    ({"changed_option_value_role": "none"}, "changed option"),
    ({"argument_role_with_option": "same"}, "'same' is not a valid ProgramWordRole"),
    ({"option_name": ""}, "option_name is empty"),
    # End words of a next program on an option whose arguments do not become a next program.
    (
        {"argument_role_with_option": "changed_file"},
        "next_program_end_words",
    ),
]
# (cells that differ from `_CODE_RUNNER_ROW_CELLS`, a part of the error message)
_CODE_RUNNER_ROWS_THAT_CANNOT_LOAD = [
    ({"runner_kind": "program"}, "not one of the two kinds"),
    ({"ran_text_language": "ruby"}, "'ruby' is not a valid CodeLanguage"),
    ({"ran_text_language": ""}, "'' is not a valid CodeLanguage"),
    ({"runner": ""}, "runner is empty"),
    ({"runner_kind": "file_extension", "runner": "py"}, "does not start with a dot"),
]
# Programs of the old tables whose rows were left out, since a cell that cannot be blank could not be checked against a manual page of the implementation the trials run, e.g. no page of GNU tac says whether one-letter options join in one word.
_PROGRAMS_LEFT_OUT = frozenset(
    {
        "clang",
        "conda",
        "diff",
        "exec",
        "gh",
        "git",
        "setsid",
        "stdbuf",
        "strings",
        "tac",
        "time",
        "tsx",
        "xxd",
    }
)
# Options that the old tables gave every shell and that only bash has, since dash(1) lists no -O or +O.
_SHELL_OPTIONS_OF_BASH_ONLY = frozenset({"-O", "+O"})
# Programs whose row without a subcommand was left out while a subcommand row was kept, with the subcommand that took over the option rows of the old tables, or None when they were left out too.
_SUBCOMMAND_HOLDING_OPTIONS_BY_PROGRAM_NAME = {
    "bun": None,
    "npm": "exec",
    "pnpm": "exec",
    "uv": "run",
}
# Programs whose options_end_at_first_argument was checked on a page and differs from the old tables, since their synopsis puts the command or the files after the options, e.g. `pnpm [-r] [-c] exec <command> [args...]` of pnpm help exec and `mawk [-F value] 'program text' [file ...]`.
_PROGRAMS_WHOSE_OPTIONS_END_AT_FIRST_ARGUMENT_BY_THE_PAGE = frozenset(
    {"awk", "npx", "pnpm", "uv"}
)
# Options whose page says they take no value, which the old tables read as taking one, by program.
_OPTIONS_THAT_TAKE_NO_VALUE_BY_THE_PAGE = {
    # python -c and -m end the options of python, so they make the first argument the code or the module instead of taking a value.
    "python": {"-c", "-m"},
    # jq -f makes the filter argument the name of the file of the filter.
    "jq": {"-f", "--from-file"},
}


def _write_catalogs(
    tmp_path: Path,
    *,
    program_rows: list[Mapping[str, str]],
    option_rows: list[Mapping[str, str]] | None = None,
    code_runner_rows: list[Mapping[str, str]] | None = None,
) -> Path:
    """Write the three program CSVs into a folder and return the folder, with no option or code runner rows unless given."""
    for file_name, header, rows in (
        (PROGRAM_BEHAVIORS_CSV, _PROGRAM_ROW_CELLS, program_rows),
        (PROGRAM_OPTION_BEHAVIORS_CSV, _OPTION_ROW_CELLS, option_rows or []),
        (CODE_RUNNERS_CSV, _CODE_RUNNER_ROW_CELLS, code_runner_rows or []),
    ):
        with (tmp_path / file_name).open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, list(header))
            writer.writeheader()
            writer.writerows(rows)
    return tmp_path


def _program_row(**cells: str) -> dict[str, str]:
    return {**_PROGRAM_ROW_CELLS, **cells}


def _knowledge(
    tmp_path: Path, **rows: list[Mapping[str, str]]
) -> ExpandedToolCallKnowledge:
    rows.setdefault("program_rows", [_program_row()])
    return ExpandedToolCallKnowledge(catalogs_dir=_write_catalogs(tmp_path, **rows))


def _real_csv_rows(file_name: str) -> list[dict[str, str]]:
    with (EXPANDED_TOOL_CALL_CATALOGS_DIR / file_name).open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


@pytest.fixture(scope="module")
def real_knowledge() -> ExpandedToolCallKnowledge:
    return ExpandedToolCallKnowledge()


def _program_behavior_of(
    knowledge: ExpandedToolCallKnowledge, program_name: str, *subcommand_words: str
) -> ProgramBehavior:
    answer = knowledge.program_behavior(program_name, subcommand_words)
    assert isinstance(answer, ProgramBehavior), (program_name, subcommand_words)
    assert answer.subcommand_words == subcommand_words, (program_name, answer)
    return answer


def _option_behavior_of(
    knowledge: ExpandedToolCallKnowledge,
    program_behavior: ProgramBehavior,
    option_name: str,
) -> ProgramOptionBehavior:
    """Ask the door about a word that is one option name, and give the row of that option."""
    answer = knowledge.program_option_word(program_behavior, option_name)
    assert isinstance(answer, ProgramOptionWord), (program_behavior, option_name)
    (option,) = answer.options
    assert option.name == option_name and option.attached_value is None, answer
    return option.program_option_behavior


def _real_option_behavior_of(
    knowledge: ExpandedToolCallKnowledge,
    program_name: str,
    option_name: str,
    subcommand_words: tuple[str, ...] = (),
) -> ProgramOptionBehavior:
    """Ask the door about one option of a program of the real catalog, through the row of the program."""
    return _option_behavior_of(
        knowledge,
        _program_behavior_of(knowledge, program_name, *subcommand_words),
        option_name,
    )


def test_program_row_is_read_into_every_field_and_counted(tmp_path):
    knowledge = _knowledge(tmp_path)

    assert knowledge.program_behavior("prog", ("a.txt",)) == _PROGRAM_BEHAVIOR
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter({(PROGRAM_BEHAVIORS_CSV, ("prog", "")): 1})
    )


def test_longest_subcommand_whose_words_come_right_after_the_program_word_answers(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[
            _program_row(subcommand="", argument_role="other"),
            _program_row(subcommand="pip", argument_role="read_file"),
            _program_row(subcommand="pip install", argument_role="program"),
        ],
    )

    answers = [
        knowledge.program_behavior("prog", words)
        for words in (
            ("pip", "install", "x"),
            ("pip", "list"),
            ("run", "pip", "install"),
            (),
        )
    ]

    assert [
        (a.subcommand_words, a.argument_role)
        for a in answers
        if isinstance(a, ProgramBehavior)
    ] == [
        (("pip", "install"), ProgramWordRole.PROGRAM),
        (("pip",), ProgramWordRole.READ_FILE),
        # A subcommand after another word is no subcommand, e.g. `prog run pip install`.
        ((), ProgramWordRole.OTHER),
        ((), ProgramWordRole.OTHER),
    ]


def test_program_without_a_fitting_row_is_unknown_and_counted_without_its_words(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[_program_row(program_name="uv", subcommand="run")],
    )

    answers = [
        knowledge.program_behavior("mytool", ("run", "x")),
        # A program whose rows all have a subcommand that the words do not start with.
        knowledge.program_behavior("uv", ("sync",)),
    ]

    assert answers == [UnknownProgramBehavior(), UnknownProgramBehavior()]
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=Counter(
            {
                (PROGRAM_BEHAVIORS_CSV, ("mytool", "")): 1,
                (PROGRAM_BEHAVIORS_CSV, ("uv", "")): 1,
            }
        )
    )


@pytest.mark.parametrize(
    ("asked_name", "answered_name"),
    [
        ("pip3", "pip"),
        ("python3.11", "python"),
        ("gcc-12", "gcc"),
        # A name without a version keeps its own row.
        ("pip", "pip"),
        # Only a row that says `name_may_end_with_version` answers for a name with a version.
        ("base64", None),
        # A name with a row of its own is not read as a version of another name.
        ("tool2", "tool2"),
    ],
)
def test_name_with_a_version_is_answered_only_by_a_row_that_allows_one(
    tmp_path, asked_name, answered_name
):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[
            _program_row(program_name=name, name_may_end_with_version=versioned)
            for name, versioned in (
                ("pip", "yes"),
                ("python", "yes"),
                ("gcc", "yes"),
                ("base", "no"),
                ("tool", "yes"),
                ("tool2", "no"),
            )
        ],
    )

    answer = knowledge.program_behavior(asked_name, ())

    if answered_name is None:
        assert answer == UnknownProgramBehavior()
        assert knowledge.uses.unknown_input_counts == Counter(
            {(PROGRAM_BEHAVIORS_CSV, (asked_name, "")): 1}
        )
    else:
        assert isinstance(answer, ProgramBehavior)
        assert answer.program_name == answered_name
        # The spelling that was read without its version is counted beside the row.
        spelling_counts = (
            {(NAMES_READ_WITHOUT_VERSION, (asked_name, answered_name)): 1}
            if asked_name != answered_name
            else {}
        )
        assert knowledge.uses.row_use_counts == Counter(
            {(PROGRAM_BEHAVIORS_CSV, (answered_name, "")): 1, **spelling_counts}
        )


def test_name_with_a_version_is_answered_by_the_row_of_its_subcommand(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[
            _program_row(program_name="pip", name_may_end_with_version="yes"),
            _program_row(
                program_name="pip",
                subcommand="install",
                name_may_end_with_version="yes",
            ),
        ],
    )

    answer = knowledge.program_behavior("pip3", ("install", "x"))

    assert isinstance(answer, ProgramBehavior)
    assert answer.subcommand_words == ("install",)
    assert knowledge.uses.row_use_counts == Counter(
        {
            (PROGRAM_BEHAVIORS_CSV, ("pip", "install")): 1,
            (NAMES_READ_WITHOUT_VERSION, ("pip3", "pip")): 1,
        }
    )


def test_rows_of_one_program_that_differ_in_allowing_a_version_fail_the_load(
    tmp_path,
):
    catalogs_dir = _write_catalogs(
        tmp_path,
        program_rows=[
            _program_row(**cells) for cells in _PROGRAM_ROWS_THAT_DISAGREE_ON_A_VERSION
        ],
    )

    with pytest.raises(ValueError, match="differ in name_may_end_with_version"):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("column", "answer"), _BLANK_PROGRAM_CELLS_THAT_ARE_UNKNOWN)
def test_blank_role_visibility_or_exit_code_cell_of_a_program_row_is_unknown(
    tmp_path, column, answer
):
    knowledge = _knowledge(tmp_path, program_rows=[_program_row(**{column: ""})])

    program_behavior = knowledge.program_behavior("prog", ())

    assert getattr(program_behavior, column) == answer


@pytest.mark.parametrize("column", _PROGRAM_COLUMNS_THAT_CANNOT_BE_BLANK)
def test_blank_cell_of_a_program_row_that_says_how_to_read_words_fails_the_load(
    tmp_path, column
):
    catalogs_dir = _write_catalogs(
        tmp_path, program_rows=[_program_row(**{column: ""})]
    )

    with pytest.raises(ValueError, match=column):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("cells", "message"), _PROGRAM_ROWS_THAT_CANNOT_LOAD)
def test_program_row_that_expand_tool_calls_cannot_use_fails_the_load(
    tmp_path, cells, message
):
    catalogs_dir = _write_catalogs(tmp_path, program_rows=[_program_row(**cells)])

    with pytest.raises(ValueError, match=message):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def test_option_row_is_read_into_every_field_and_counted(tmp_path):
    knowledge = _knowledge(tmp_path, option_rows=[_OPTION_ROW_CELLS])

    assert knowledge.program_option_word(_PROGRAM_BEHAVIOR, "-x") == ProgramOptionWord(
        (ProgramOptionWordOption("-x", _PROGRAM_OPTION_BEHAVIOR, None),)
    )
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter({(PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", "-x")): 1})
    )


def test_option_row_of_the_subcommand_comes_before_the_row_of_the_program(tmp_path):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[_program_row(), _program_row(subcommand="clone")],
        option_rows=[
            {**_UNCHANGING_OPTION_ROW_CELLS, "option_name": "-q"},
            {
                **_UNCHANGING_OPTION_ROW_CELLS,
                "subcommand": "clone",
                "option_name": "-q",
                "argument_role_with_option": "other",
            },
        ],
    )

    of_clone = _option_behavior_of(
        knowledge, replace(_PROGRAM_BEHAVIOR, subcommand_words=("clone",)), "-q"
    )
    # A subcommand without option rows falls back to the rows of the program.
    of_fetch = _option_behavior_of(
        knowledge, replace(_PROGRAM_BEHAVIOR, subcommand_words=("fetch",)), "-q"
    )

    assert of_clone.argument_role_with_option == ProgramWordRole.OTHER
    assert of_fetch.argument_role_with_option is None
    assert knowledge.uses.row_use_counts == Counter(
        {
            (PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "clone", "-q")): 1,
            (PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", "-q")): 1,
        }
    )


def test_option_without_a_row_is_unknown_and_counted_with_the_subcommand_asked(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, option_rows=[_OPTION_ROW_CELLS])

    answers = [
        knowledge.program_option_word(
            replace(_PROGRAM_BEHAVIOR, subcommand_words=("pip", "install")), "--foo"
        ),
        # The row of one spelling does not answer for another, e.g. `-xy` for `-x`, since prog does not join one-letter options.
        knowledge.program_option_word(_PROGRAM_BEHAVIOR, "-xy"),
        knowledge.program_option_word(
            replace(_PROGRAM_BEHAVIOR, program_name="other"), "-x"
        ),
    ]

    assert answers == [UnknownProgramOptionWord()] * 3
    assert knowledge.uses == KnowledgeUses(
        unknown_input_counts=Counter(
            {
                (PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "pip install", "--foo")): 1,
                (PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", "-xy")): 1,
                (PROGRAM_OPTION_BEHAVIORS_CSV, ("other", "", "-x")): 1,
            }
        )
    )


@pytest.mark.parametrize(
    ("word", "options", "used_option_names", "unknown_option_name"),
    [
        (
            "-o",
            (("-o", _OPTION_TAKING_A_VALUE, None),),
            ("-o",),
            None,
        ),
        (
            "--out=f",
            (("--out", _OPTION_TAKING_A_VALUE, "f"),),
            ("--out",),
            None,
        ),
        # A value attached to a letter is the rest of the word.
        (
            "-oout",
            (("-o", _OPTION_TAKING_A_VALUE, "out"),),
            ("-o",),
            None,
        ),
        # The last letter takes a value and has none attached, so the next word is its value.
        (
            "-sfo",
            (
                ("-s", _OPTION_TAKING_NO_VALUE, None),
                ("-f", _OPTION_TAKING_NO_VALUE, None),
                ("-o", _OPTION_TAKING_A_VALUE, None),
            ),
            ("-s", "-f", "-o"),
            None,
        ),
        # A letter without a row is one unknown input under the word as written, and no row counts as used.
        ("-sz", None, (), "-sz"),
        ("--foo=f", None, (), "--foo"),
        # prog has the option `+o`, so a word that starts with + is read like one that starts with -.
        (
            "+o",
            (("+o", _OPTION_TAKING_A_VALUE, None),),
            ("+o",),
            None,
        ),
        ("+x", None, (), "+x"),
    ],
)
def test_word_is_answered_with_the_options_it_holds_counting_each_row_and_at_most_one_unknown_input(
    tmp_path, word, options, used_option_names, unknown_option_name
):
    knowledge = _knowledge(tmp_path, option_rows=_OPTION_ROWS_OF_ONE_WORD)
    program_behavior = replace(_PROGRAM_BEHAVIOR, takes_one_letter_options_joined=True)

    answer = knowledge.program_option_word(program_behavior, word)

    assert answer == (
        UnknownProgramOptionWord()
        if options is None
        else ProgramOptionWord(
            tuple(ProgramOptionWordOption(*option) for option in options)
        )
    )
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter(
            (PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", option_name))
            for option_name in used_option_names
        ),
        unknown_input_counts=Counter(
            {(PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", unknown_option_name)): 1}
            if unknown_option_name
            else {}
        ),
    )


def test_word_of_letters_is_unknown_when_the_program_does_not_join_one_letter_options(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, option_rows=_OPTION_ROWS_OF_ONE_WORD)

    assert (
        knowledge.program_option_word(_PROGRAM_BEHAVIOR, "-sf")
        == UnknownProgramOptionWord()
    )


def test_word_that_starts_with_a_plus_is_an_argument_when_the_program_has_no_plus_option(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[_program_row(), _program_row(program_name="other")],
        option_rows=_OPTION_ROWS_OF_ONE_WORD,
    )

    answer = knowledge.program_option_word(
        replace(_PROGRAM_BEHAVIOR, program_name="other"), "+x"
    )

    assert answer == ProgramArgumentWord()
    assert knowledge.uses == KnowledgeUses()


def test_cluster_word_holds_one_option_per_letter_whose_values_come_from_later_words(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, option_rows=_OPTION_ROWS_OF_ONE_WORD)

    cluster = knowledge.program_option_word(
        _PROGRAM_BEHAVIOR, "osf", is_option_cluster=True
    )
    cluster_with_a_letter_without_a_row = knowledge.program_option_word(
        _PROGRAM_BEHAVIOR, "sz", is_option_cluster=True
    )

    assert cluster == ProgramOptionWord(
        (
            ProgramOptionWordOption("-o", _OPTION_TAKING_A_VALUE, None),
            ProgramOptionWordOption("-s", _OPTION_TAKING_NO_VALUE, None),
            ProgramOptionWordOption("-f", _OPTION_TAKING_NO_VALUE, None),
        )
    )
    assert cluster_with_a_letter_without_a_row == UnknownProgramOptionWord()
    assert knowledge.uses.unknown_input_counts == Counter(
        {(PROGRAM_OPTION_BEHAVIORS_CSV, ("prog", "", "sz")): 1}
    )


@pytest.mark.parametrize(("column", "answer"), _BLANK_OPTION_CELLS_THAT_ARE_UNKNOWN)
def test_blank_role_or_exit_code_cell_of_an_option_row_is_unknown(
    tmp_path, column, answer
):
    knowledge = _knowledge(
        tmp_path, option_rows=[{**_UNCHANGING_OPTION_ROW_CELLS, column: ""}]
    )

    option_behavior = _option_behavior_of(knowledge, _PROGRAM_BEHAVIOR, "-x")

    assert getattr(option_behavior, column) == answer


def test_blank_value_role_of_an_option_that_takes_a_value_is_unknown(tmp_path):
    knowledge = _knowledge(
        tmp_path, option_rows=[{**_OPTION_ROW_CELLS, "value_role": ""}]
    )

    option_behavior = _option_behavior_of(knowledge, _PROGRAM_BEHAVIOR, "-x")

    assert option_behavior.value_role == UnknownProgramWordRole()


def test_option_row_that_changes_nothing_answers_none_for_each_unchanged_cell(
    tmp_path,
):
    knowledge = _knowledge(tmp_path, option_rows=[_UNCHANGING_OPTION_ROW_CELLS])

    assert (
        _option_behavior_of(knowledge, _PROGRAM_BEHAVIOR, "-x")
        == _OPTION_TAKING_NO_VALUE
    )


@pytest.mark.parametrize("column", _OPTION_COLUMNS_THAT_CANNOT_BE_BLANK)
def test_blank_cell_of_an_option_row_that_says_how_to_read_words_fails_the_load(
    tmp_path, column
):
    catalogs_dir = _write_catalogs(
        tmp_path,
        program_rows=[_program_row()],
        option_rows=[{**_UNCHANGING_OPTION_ROW_CELLS, column: ""}],
    )

    with pytest.raises(ValueError):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


@pytest.mark.parametrize(("cells", "message"), _OPTION_ROWS_THAT_CANNOT_LOAD)
def test_option_row_that_expand_tool_calls_cannot_use_fails_the_load(
    tmp_path, cells, message
):
    catalogs_dir = _write_catalogs(
        tmp_path,
        program_rows=[_program_row()],
        option_rows=[{**_OPTION_ROW_CELLS, **cells}],
    )

    with pytest.raises(ValueError, match=message):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def test_language_of_a_program_or_extension_is_answered_or_unknown_and_counted(
    tmp_path,
):
    knowledge = _knowledge(
        tmp_path,
        program_rows=[
            _program_row(program_name="python", name_may_end_with_version="yes"),
            _program_row(program_name="sh", name_may_end_with_version="no"),
        ],
        code_runner_rows=[
            {**_CODE_RUNNER_ROW_CELLS, "runner": "python"},
            {
                **_CODE_RUNNER_ROW_CELLS,
                "runner": "python2",
                "ran_text_language": "shell",
            },
            {**_CODE_RUNNER_ROW_CELLS, "runner": "sh", "ran_text_language": "shell"},
            {
                **_CODE_RUNNER_ROW_CELLS,
                "runner_kind": "file_extension",
                "runner": ".ts",
                "ran_text_language": "javascript",
            },
        ],
    )

    answers = [
        knowledge.ran_text_language_of_program("sh"),
        # A name with a version, as an interpreter line gives it.
        knowledge.ran_text_language_of_program("python3"),
        # A name with a version keeps a row of its own, here a made-up one, rather than the row without its version.
        knowledge.ran_text_language_of_program("python2"),
        # sh does not allow a version, so sh5 is another program.
        knowledge.ran_text_language_of_program("sh5"),
        knowledge.ran_text_language_of_program("gdb"),
        knowledge.ran_text_language_of_file_extension(".ts"),
        # A program row and an extension row are apart, even with the same text.
        knowledge.ran_text_language_of_file_extension("sh"),
    ]

    assert answers == [
        ShellLanguage(),
        CodeLanguage.PYTHON,
        ShellLanguage(),
        UnknownRanTextLanguage(),
        UnknownRanTextLanguage(),
        CodeLanguage.JAVASCRIPT,
        UnknownRanTextLanguage(),
    ]
    assert knowledge.uses == KnowledgeUses(
        row_use_counts=Counter(
            {
                (CODE_RUNNERS_CSV, ("program_name", "sh")): 1,
                (CODE_RUNNERS_CSV, ("program_name", "python")): 1,
                (NAMES_READ_WITHOUT_VERSION, ("python3", "python")): 1,
                (CODE_RUNNERS_CSV, ("program_name", "python2")): 1,
                (CODE_RUNNERS_CSV, ("file_extension", ".ts")): 1,
            }
        ),
        unknown_input_counts=Counter(
            {
                (CODE_RUNNERS_CSV, ("program_name", "sh5")): 1,
                (CODE_RUNNERS_CSV, ("program_name", "gdb")): 1,
                (CODE_RUNNERS_CSV, ("file_extension", "sh")): 1,
            }
        ),
    )


@pytest.mark.parametrize(("cells", "message"), _CODE_RUNNER_ROWS_THAT_CANNOT_LOAD)
def test_code_runner_row_that_expand_tool_calls_cannot_use_fails_the_load(
    tmp_path, cells, message
):
    catalogs_dir = _write_catalogs(
        tmp_path,
        program_rows=[_program_row()],
        code_runner_rows=[{**_CODE_RUNNER_ROW_CELLS, **cells}],
    )

    with pytest.raises(ValueError, match=message):
        ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)


def test_each_door_counts_only_its_own_lookups(tmp_path):
    catalogs_dir = _write_catalogs(tmp_path, program_rows=[_program_row()])
    first = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)
    second = ExpandedToolCallKnowledge(catalogs_dir=catalogs_dir)

    first.program_behavior("prog", ())

    assert second.uses == KnowledgeUses()


def test_door_module_can_be_the_first_import_of_a_process():
    # The door imports the model of its step, whose package imports the door under TYPE_CHECKING only, so a fresh process shows that no cycle runs.
    module = "tb_internet_use.knowledge.expanded_tool_call_knowledge"
    subprocess.run([sys.executable, "-I", "-c", f"import {module}"], check=True)


@pytest.mark.parametrize(
    "file_name", [PROGRAM_BEHAVIORS_CSV, PROGRAM_OPTION_BEHAVIORS_CSV, CODE_RUNNERS_CSV]
)
def test_real_catalog_holds_no_invisible_control_characters(file_name):
    # Bytes, since reading text would turn a CR into a line break.
    data = (EXPANDED_TOOL_CALL_CATALOGS_DIR / file_name).read_bytes()

    assert not [byte for byte in data if (byte < 0x20 and byte != 0x0A) or byte == 0x7F]


def test_real_catalogs_load(real_knowledge):
    # The load refuses a blank checked_against, a word that no column allows, two rows with one key and an option row whose program has no row.
    assert real_knowledge.program_behavior("cat", ()) != UnknownProgramBehavior()


# The tests below hold the real catalogs against the old program tables, so that a row lost in the move fails. They go with the old tables.


def test_programs_of_the_old_tables_are_kept_or_named_as_left_out():
    old_names = (
        set(WRAPPERS)
        | PROGRAMS_GIVING_RUN_TIME_ARGUMENTS
        | VERSIONED_PROGRAMS
        | SHELL_PROGRAMS
        | set(CODE_PROGRAMS)
        | set(OPTION_SYNTAX_OF_PROGRAM)
        | {
            name
            for name, rows in program_catalog().items()
            if any(row.reads_file_arguments or row.runs_next_program for row in rows)
        }
    )
    kept_names = {row["program_name"] for row in _real_csv_rows(PROGRAM_BEHAVIORS_CSV)}

    # A name both kept and left out would hide a row from the tests below.
    assert not kept_names & _PROGRAMS_LEFT_OUT
    assert old_names <= kept_names | _PROGRAMS_LEFT_OUT


def test_wrappers_of_the_old_tables_run_the_next_program_with_their_options(
    real_knowledge,
):
    for name, wrapper in WRAPPERS.items():
        if name in _PROGRAMS_LEFT_OUT:
            continue
        program_behavior = _program_behavior_of(real_knowledge, name)

        assert program_behavior.argument_role == ProgramWordRole.PROGRAM, name
        assert program_behavior.skips_assignment_words == wrapper.takes_assignments, (
            name
        )
        # The old wrapper reading took the words after the command as the command's.
        assert program_behavior.options_end_at_first_argument, name
        # A word before the command that is no option, e.g. 30 in `timeout 30 curl u`, is the first argument.
        assert program_behavior.first_argument_role == (
            ProgramWordRole.OTHER if wrapper.operand_count else SameAsArgumentRole()
        ), name
        for option_name in wrapper.options_with_value:
            assert _real_option_behavior_of(
                real_knowledge, name, option_name
            ).takes_value


def test_shells_and_code_programs_of_the_old_tables_run_their_texts(real_knowledge):
    for name in SHELL_PROGRAMS - _PROGRAMS_LEFT_OUT:
        program_behavior = _program_behavior_of(real_knowledge, name)
        assert program_behavior.first_argument_role == ProgramWordRole.RUN_FILE
        assert program_behavior.stdin_role == ProgramWordRole.RUN_TEXT
        shell_c = _real_option_behavior_of(real_knowledge, name, "-c")
        # The text after -c is the first argument and no value of -c, so that `bash -c -e a` runs a.
        assert not shell_c.takes_value
        assert shell_c.first_argument_role_with_option == ProgramWordRole.RUN_TEXT
        for option_name in ("-o", "+o", "-O", "+O"):
            if name != "bash" and option_name in _SHELL_OPTIONS_OF_BASH_ONLY:
                assert (
                    real_knowledge.program_option_word(
                        _program_behavior_of(real_knowledge, name), option_name
                    )
                    == UnknownProgramOptionWord()
                ), (name, option_name)
                continue
            assert _real_option_behavior_of(
                real_knowledge, name, option_name
            ).takes_value
        for option_name in ("-s", "-n"):
            assert not _real_option_behavior_of(
                real_knowledge, name, option_name
            ).takes_value
        # With -s the shell runs its stdin, so the first argument is no file.
        assert isinstance(
            _real_option_behavior_of(
                real_knowledge, name, "-s"
            ).first_argument_role_with_option,
            SameAsArgumentRole,
        )
    for name in SHELL_PROGRAMS:
        assert real_knowledge.ran_text_language_of_program(name) == ShellLanguage()
    for name in ("source", "."):
        program_behavior = _program_behavior_of(real_knowledge, name)
        assert program_behavior.runs_text_in_calling_shell
        assert program_behavior.first_argument_role == ProgramWordRole.RUN_FILE
        assert real_knowledge.ran_text_language_of_program(name) == ShellLanguage()
    eval_behavior = _program_behavior_of(real_knowledge, "eval")
    assert eval_behavior.runs_text_in_calling_shell
    assert eval_behavior.argument_role == ProgramWordRole.RUN_TEXT
    assert real_knowledge.ran_text_language_of_program("eval") == ShellLanguage()
    for name, code_program in CODE_PROGRAMS.items():
        assert (
            real_knowledge.ran_text_language_of_program(name)
            == code_program.language.value
        )
        if name in _PROGRAMS_LEFT_OUT | set(
            _SUBCOMMAND_HOLDING_OPTIONS_BY_PROGRAM_NAME
        ):
            continue
        assert (
            _program_behavior_of(real_knowledge, name).first_argument_role
            == ProgramWordRole.RUN_FILE
        ), name
        for option_name in code_program.inline_code_options:
            option_behavior = _real_option_behavior_of(
                real_knowledge, name, option_name
            )
            # python -c takes no value and makes the first argument the code, so that the words after it are not read as options of python.
            assert ProgramWordRole.RUN_TEXT in (
                option_behavior.value_role,
                option_behavior.first_argument_role_with_option,
            ), (name, option_name)
    assert (
        _real_option_behavior_of(
            real_knowledge, "python", "-m"
        ).first_argument_role_with_option
        == ProgramWordRole.PROGRAM
    )
    for option_name in PYTHON_OPTIONS_WITH_VALUE_BEFORE_MODULE:
        assert _real_option_behavior_of(
            real_knowledge, "python", option_name
        ).takes_value
    for extension, language in LANGUAGE_OF_FILE_EXTENSION.items():
        assert real_knowledge.ran_text_language_of_file_extension(extension) == (
            language.value
        )
    for extension in SHELL_FILE_EXTENSIONS:
        assert (
            real_knowledge.ran_text_language_of_file_extension(extension)
            == ShellLanguage()
        )


def test_versioned_programs_of_the_old_tables_are_the_rows_that_allow_a_version():
    versioned_names = {
        row["program_name"]
        for row in _real_csv_rows(PROGRAM_BEHAVIORS_CSV)
        if row["name_may_end_with_version"] == "yes"
    }

    assert versioned_names == VERSIONED_PROGRAMS - _PROGRAMS_LEFT_OUT


def test_option_syntax_of_the_old_tables_is_in_the_option_rows(real_knowledge):
    for name, syntax in OPTION_SYNTAX_OF_PROGRAM.items():
        if name in _PROGRAMS_LEFT_OUT:
            continue
        subcommand = _SUBCOMMAND_HOLDING_OPTIONS_BY_PROGRAM_NAME.get(name, "")
        if subcommand is None:
            continue
        subcommand_words = tuple(subcommand.split())
        program_behavior = _program_behavior_of(real_knowledge, name, *subcommand_words)
        assert program_behavior.options_end_at_first_argument == (
            syntax.options_end_at_first_plain_argument
            or name in _PROGRAMS_WHOSE_OPTIONS_END_AT_FIRST_ARGUMENT_BY_THE_PAGE
        ), name
        assert program_behavior.takes_one_letter_options_joined, name
        value_options = {f"-{letter}" for letter in syntax.short_options_with_value}
        value_options |= syntax.long_options_with_value
        taking_no_value = _OPTIONS_THAT_TAKE_NO_VALUE_BY_THE_PAGE.get(name, set())
        for option_name in value_options | syntax.script_options:
            option_behavior = _option_behavior_of(
                real_knowledge, program_behavior, option_name
            )
            assert option_behavior.takes_value != (option_name in taking_no_value), (
                name,
                option_name,
            )
        for option_name in syntax.one_dash_long_options:
            assert _option_behavior_of(
                real_knowledge, program_behavior, option_name
            ).takes_value
        for option_name in syntax.script_options - taking_no_value:
            # Without the script as the first argument, the first argument is one of the files.
            assert isinstance(
                _option_behavior_of(
                    real_knowledge, program_behavior, option_name
                ).first_argument_role_with_option,
                SameAsArgumentRole,
            ), (name, option_name)
        if syntax.script_options:
            assert program_behavior.first_argument_role == ProgramWordRole.PATTERN, name


def test_old_program_catalog_rows_that_read_files_or_run_the_next_program_are_kept(
    real_knowledge,
):
    for name, rows in program_catalog().items():
        if name in _PROGRAMS_LEFT_OUT:
            continue
        for row in rows:
            if row.reads_file_arguments:
                program_behavior = _program_behavior_of(real_knowledge, name)
                assert program_behavior.argument_role == ProgramWordRole.READ_FILE, name
                assert program_behavior.stdin_role == ProgramWordRole.READ_FILE, name
            if row.runs_next_program:
                program_behavior = _program_behavior_of(
                    real_knowledge, name, *row.subcommand_words
                )
                assert program_behavior.argument_role == ProgramWordRole.PROGRAM, name


def test_copies_of_the_old_code_are_in_the_rows(real_knowledge):
    program_behavior = _program_behavior_of(real_knowledge, "cp")
    assert program_behavior.argument_role == ProgramWordRole.COPY_SOURCE
    assert program_behavior.last_argument_role == ProgramWordRole.COPY_DESTINATION
