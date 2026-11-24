"""Answer the questions of `expand_tool_calls` about programs and the languages they run from the program catalogs, counting every use of a row and every input without one.

A blank cell is unknown only in the role columns, `visibility_of_piped_input`, the exit code columns, `options_end_at_first_argument`, `takes_one_letter_options_joined`, `takes_non_option_dash_words_as_arguments` and `default_run_file`. Every other fact column says what it means in a word, e.g. `no` or `none`, and a blank there fails the load, so that `ExpandedToolCallKnowledge` never reads a missing fact as a default. A blank `subcommand` names the row of the program without a subcommand.
"""

import functools
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tb_internet_use.expanded_tool_call.model import (
    CodeLanguage,
    OutputVisibility,
    ProgramArgumentWord,
    ProgramBehavior,
    ProgramOptionBehavior,
    ProgramOptionWord,
    ProgramOptionWordOption,
    ProgramWordRole,
    RanTextLanguage,
    SameAsArgumentRole,
    ShellLanguage,
    UnknownDefaultRunFile,
    UnknownExitsWithExitCodeOfNextProgram,
    UnknownOptionsEndAtFirstArgument,
    UnknownProgramBehavior,
    UnknownProgramOptionWord,
    UnknownProgramWordRole,
    UnknownRanTextLanguage,
    UnknownTakesNonOptionDashWordsAsArguments,
    UnknownTakesOneLetterOptionsJoined,
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
# The source name under which `ExpandedToolCallKnowledge` counts a name that it read without its version, keyed by the name as asked and the name without its version, e.g. `("python3.11", "python")`.
NAMES_READ_WITHOUT_VERSION = "names_read_without_version"
# The source name under which `ExpandedToolCallKnowledge` counts a blank cell of a program row that a word needed, keyed by the program name, the subcommand and the column, e.g. `("echo", "", "options_end_at_first_argument")`.
BLANK_PROGRAM_BEHAVIOR_CELLS = "blank_program_behavior_cells"
_OPTIONS_END_AT_FIRST_ARGUMENT_COLUMN = "options_end_at_first_argument"
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
    """Outside knowledge of `expand_tool_calls`, made for one trial and passed to it as `knowledge`, which it asks one question per method.

    An answer is a value or an `Unknown…` type of the step's model, never a default.
    `uses` counts every catalog row that answered and every input without one.
    The loaded catalogs are cached per process, so making one per trial is cheap.
    """

    def __init__(self, *, catalogs_dir: Path = EXPANDED_TOOL_CALL_CATALOGS_DIR) -> None:
        self.uses = KnowledgeUses()
        self._catalogs = _load_expanded_tool_call_catalogs(catalogs_dir)

    def program_behavior(
        self, program_name: str, words_after_program: Sequence[str]
    ) -> ProgramBehavior | UnknownProgramBehavior:
        """Answer how a program uses its words and stdin, from the row of its subcommand, or `UnknownProgramBehavior` for a program without a fitting row.

        `program_name` is the program word without its folder, e.g. python3.11 for `/usr/bin/python3.11`.
        The row is the one whose subcommand words all come right after the options of the program that stand before them, the longest such, and else the row without a subcommand.
        An option before the subcommand is read through the rows without a subcommand and skipped with its value, e.g. `-y` of `apt-get -y install curl` or `--prefix /app` of `npm --prefix /app install`. The first word that starts with `-` and that those rows do not cover ends the search, so the row without a subcommand answers and the word stays unread as an unknown option.
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
        subcommand_word_index = (
            _subcommand_word_index_of(row_keys[0][0], words_after_program, catalogs)
            if row_keys
            else 0
        )
        fitting_row_keys = [
            row_key
            for row_key in row_keys
            if _is_subcommand_of(
                row_key[1], words_after_program[subcommand_word_index:]
            )
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

    def program_option_word(
        self,
        program_behavior: ProgramBehavior,
        word: str,
        *,
        is_option_cluster: bool = False,
        is_before_subcommand: bool = False,
    ) -> ProgramOptionWord | ProgramArgumentWord | UnknownProgramOptionWord:
        """Answer which options of a program one word of a command holds, with the row of each and the value written in the word, or `UnknownProgramOptionWord` when the rows do not cover the word.

        `program_behavior` is the answer of `program_behavior` for the command, and `word` is the word as written, e.g. `-o`, `-fsSLoout`, `--output=f` or `+o`.
        The rows are searched in this order, as the reading of a command in `expand_tool_calls` gives it.

        1. `--name=value` holds the row of `--name`, with the attached value `value`.
        2. A word with a row of its own holds that row, e.g. `-pe` of node or `-maxdepth` of find.
        3. A `-` or `+` and several letters, when the program row says `yes` in `takes_one_letter_options_joined`, holds the row of each letter, e.g. `-f` and `-s` for `-fs`. The rest of the word after a letter that takes a value is that value, e.g. `out` of `-oout`.
        4. A word whose role is `OPTION_CLUSTER`, with `is_option_cluster`, holds the row of each letter named with a `-`, with no attached values, e.g. `-x`, `-z` and `-f` for `xzf` of tar.

        When `takes_one_letter_options_joined` is `no` or blank, a word of several letters without a row of its own is `UnknownProgramOptionWord`, e.g. `-af` of pgrep, since the letters are not read one by one.
        A word that starts with `+` is `ProgramArgumentWord` when no row of the program or its subcommand names an option that starts with `+`, e.g. `+x` of chmod.
        A word that starts with `-` and that the rows do not cover is `ProgramArgumentWord` when the program row says `yes` in `takes_non_option_dash_words_as_arguments`, e.g. `---` or `-nx` of echo, and `ExpandedToolCallKnowledge` then counts no unknown input, since the rows name every option of such a program.
        A row of the subcommand comes before a row of the program without a subcommand, e.g. `(git, clone, --depth)` before `(git, "", --depth)`.
        With `is_before_subcommand`, for a word between the program word and the subcommand, e.g. `-C` of `git -C /app log`, only the rows without a subcommand answer, read as the row of the program without a subcommand reads joined letters, since such a word is an option of the program and not of the subcommand.
        `ExpandedToolCallKnowledge` counts one use of a row per option it gives, and when the rows do not cover the word one unknown input under the word as written with the subcommand as asked, e.g. `(pgrep, "", -af)`, so that the list of unknown inputs holds only words without rows. For `--name=value` that input is `--name`, since a row is named without a value.
        """
        catalogs = self._catalogs
        program_name = program_behavior.program_name
        subcommand = (
            "" if is_before_subcommand else " ".join(program_behavior.subcommand_words)
        )
        takes_one_letter_options_joined = (
            catalogs.takes_one_letter_options_joined_by_program_name.get(
                program_name, UnknownTakesOneLetterOptionsJoined()
            )
            if is_before_subcommand
            else program_behavior.takes_one_letter_options_joined
        )
        if (
            word.startswith("+")
            and not is_option_cluster
            and (program_name, subcommand) not in catalogs.programs_with_plus_options
            and (program_name, "") not in catalogs.programs_with_plus_options
        ):
            return ProgramArgumentWord()
        asked_option_name = word.partition("=")[0] if word.startswith("--") else word
        option_parts = _option_parts_of_word(
            word,
            catalogs,
            program_name=program_name,
            subcommand=subcommand,
            takes_one_letter_options_joined=takes_one_letter_options_joined,
            is_option_cluster=is_option_cluster,
        )
        if option_parts is None:
            if (
                not is_option_cluster
                and program_behavior.takes_non_option_dash_words_as_arguments is True
            ):
                return ProgramArgumentWord()
            catalogs.program_option_behaviors.lookup(
                (program_name, subcommand, asked_option_name), self.uses
            )
            return UnknownProgramOptionWord()
        options: list[ProgramOptionWordOption] = []
        for option_name, row_key, attached_value in option_parts:
            row = catalogs.program_option_behaviors.lookup(row_key, self.uses)
            assert row is not None
            options.append(ProgramOptionWordOption(option_name, row, attached_value))
        return ProgramOptionWord(tuple(options))

    def options_end_at_first_argument(
        self, program_behavior: ProgramBehavior
    ) -> bool | UnknownOptionsEndAtFirstArgument:
        """Answer whether the options of a program end at its first argument, from the row that `program_behavior` holds, for a word after the first argument that may be an option, e.g. `-v` of `printf %s -v`.

        A known answer counts nothing, since `program_behavior` counted the row when it answered.
        A blank cell counts one unknown input `(program_name, subcommand, "options_end_at_first_argument")` under `BLANK_PROGRAM_BEHAVIOR_CELLS`, so that each word left unread for want of it shows in the list of unknown inputs.
        """
        options_end_at_first_argument = program_behavior.options_end_at_first_argument
        if isinstance(options_end_at_first_argument, UnknownOptionsEndAtFirstArgument):
            self.uses.unknown_input_counts[
                BLANK_PROGRAM_BEHAVIOR_CELLS,
                (
                    program_behavior.program_name,
                    " ".join(program_behavior.subcommand_words),
                    _OPTIONS_END_AT_FIRST_ARGUMENT_COLUMN,
                ),
            ] += 1
        return options_end_at_first_argument

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


def _option_parts_of_word(
    word: str,
    catalogs: _ExpandedToolCallCatalogs,
    *,
    program_name: str,
    subcommand: str,
    takes_one_letter_options_joined: bool | UnknownTakesOneLetterOptionsJoined,
    is_option_cluster: bool,
) -> list[tuple[str, KnowledgeRowKey, str | None]] | None:
    """Find the name, the row key and the attached value of each option that a word holds, in the order of `ExpandedToolCallKnowledge.program_option_word`, or None when a row is missing.

    It reads the keys and whether each option takes a value from the index made at load, so nothing is counted until `ExpandedToolCallKnowledge` knows the answer.
    """

    def row_key_for(option_name: str) -> KnowledgeRowKey | None:
        return next(
            (
                row_key
                for row_key in (
                    (program_name, subcommand, option_name),
                    (program_name, "", option_name),
                )
                if row_key in catalogs.option_takes_value_by_row_key
            ),
            None,
        )

    option_parts: list[tuple[str, KnowledgeRowKey, str | None]] = []
    if is_option_cluster:
        # The letters of a cluster take their values from the words after it, e.g. a.tgz for the f of `tar xzf a.tgz`.
        for letter in word:
            row_key = row_key_for(f"-{letter}")
            if row_key is None:
                return None
            option_parts.append((f"-{letter}", row_key, None))
        return option_parts or None
    if word.startswith("--"):
        option_name, has_attached_value, attached_value = word.partition("=")
        row_key = row_key_for(option_name)
        if row_key is None:
            return None
        return [(option_name, row_key, attached_value if has_attached_value else None)]
    row_key = row_key_for(word)
    if row_key is not None:
        return [(word, row_key, None)]
    # A blank cell reads no letter one by one, as `no` does, so that the word stays unknown.
    if takes_one_letter_options_joined is not True or len(word) <= 2:
        return None
    sign, letters = word[0], word[1:]
    for position, letter in enumerate(letters):
        row_key = row_key_for(sign + letter)
        if row_key is None:
            return None
        if not catalogs.option_takes_value_by_row_key[row_key]:
            option_parts.append((sign + letter, row_key, None))
            continue
        # The rest of the word after a letter that takes a value is that value, e.g. `out` of `-oout`.
        attached_value = letters[position + 1 :] or None
        option_parts.append((sign + letter, row_key, attached_value))
        break
    return option_parts


def _subcommand_word_index_of(
    program_name: str,
    words_after_program: Sequence[str],
    catalogs: _ExpandedToolCallCatalogs,
) -> int:
    """Find the 0-based index in `words_after_program` of the first word after the options that the rows of the program without a subcommand cover, with their values, e.g. 1 for `-y install curl` of apt-get and 2 for `--prefix /app install` of npm.

    The search stops at the first word that does not start with `-`, at a lone `-` or `--`, and at a word that those rows do not cover. It reads the index made at load and counts nothing, since the step asks for each option word again.
    """
    takes_one_letter_options_joined = (
        catalogs.takes_one_letter_options_joined_by_program_name.get(program_name)
    )
    if takes_one_letter_options_joined is None:
        # No row without a subcommand, so no option row without one either.
        return 0
    word_index = 0
    while word_index < len(words_after_program):
        word = words_after_program[word_index]
        if not word.startswith("-") or word in ("-", "--"):
            return word_index
        option_parts = _option_parts_of_word(
            word,
            catalogs,
            program_name=program_name,
            subcommand="",
            takes_one_letter_options_joined=takes_one_letter_options_joined,
            is_option_cluster=False,
        )
        if option_parts is None:
            return word_index
        _, last_row_key, last_attached_value = option_parts[-1]
        takes_next_word = (
            catalogs.option_takes_value_by_row_key[last_row_key]
            and last_attached_value is None
        )
        word_index += 2 if takes_next_word else 1
    return word_index


def _is_subcommand_of(subcommand: str, words_after_program: Sequence[str]) -> bool:
    """Tell whether the words of a subcommand cell all come first among the given words, which an empty cell always does."""
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
    takes_one_letter_options_joined_by_program_name: dict[
        str, bool | UnknownTakesOneLetterOptionsJoined
    ] = {}
    for program_name, subcommand in program_behaviors.row_keys:
        if subcommand == "":
            row = program_behaviors.lookup((program_name, subcommand), unused)
            assert row is not None
            takes_one_letter_options_joined_by_program_name[program_name] = (
                row.program_behavior.takes_one_letter_options_joined
            )
    option_takes_value_by_row_key: dict[KnowledgeRowKey, bool] = {}
    for row_key in program_option_behaviors.row_keys:
        option_row = program_option_behaviors.lookup(row_key, unused)
        assert option_row is not None
        option_takes_value_by_row_key[row_key] = option_row.takes_value
    return _ExpandedToolCallCatalogs(
        program_behaviors,
        program_option_behaviors,
        code_runners,
        _row_key_tuples_of(row_keys_by_program_name),
        _row_key_tuples_of(row_keys_allowing_version_by_program_name),
        option_takes_value_by_row_key,
        takes_one_letter_options_joined_by_program_name,
        frozenset(
            (program_name, subcommand)
            for program_name, subcommand, option_name in program_option_behaviors.row_keys
            if option_name.startswith("+")
        ),
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
    # The keys of the rows of each program name, so `ExpandedToolCallKnowledge` can pick the row of the subcommand before its one lookup.
    program_behavior_row_keys_by_program_name: Mapping[str, tuple[KnowledgeRowKey, ...]]
    # The keys of the rows that say `name_may_end_with_version`, by the program name without a version, since only they answer for a name with one.
    program_behavior_row_keys_allowing_version_by_program_name: Mapping[
        str, tuple[KnowledgeRowKey, ...]
    ]
    # Whether the option of each option row takes a value, so that `ExpandedToolCallKnowledge` can pick the rows of the options of a word, and where an attached value starts, before it counts any.
    option_takes_value_by_row_key: Mapping[KnowledgeRowKey, bool]
    # The `takes_one_letter_options_joined` of the row without a subcommand of each program that has one, so that `ExpandedToolCallKnowledge` reads the options before a subcommand as that row does.
    takes_one_letter_options_joined_by_program_name: Mapping[
        str, bool | UnknownTakesOneLetterOptionsJoined
    ]
    # The (program, subcommand) of the option rows whose option starts with `+`, e.g. `+o` of bash, since only for them a word such as `+x` is an option.
    programs_with_plus_options: frozenset[tuple[str, str]]
    # The keys of the code runner rows, so `ExpandedToolCallKnowledge` can try the name without its version.
    code_runner_row_keys: frozenset[KnowledgeRowKey]


@dataclass(frozen=True, slots=True)
class _ProgramBehaviorRow:
    """Checked values of one row of `program_behaviors.csv`, kept in its catalog, of which `ExpandedToolCallKnowledge` gives the `ProgramBehavior` as the answer."""

    program_behavior: ProgramBehavior
    # The row answers also for the program name with a version at its end, e.g. pip3 for pip.
    name_may_end_with_version: bool


def _program_behavior_row_from_columns(
    columns: Mapping[str, str],
) -> _ProgramBehaviorRow:
    """Read one row of `program_behaviors.csv`, raising ValueError on a value that no column allows, e.g. a blank `skips_assignment_words`."""
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
        options_end_at_first_argument=_yes_no_or_unknown_from_cell(
            columns,
            "options_end_at_first_argument",
            unknown=UnknownOptionsEndAtFirstArgument(),
        ),
        takes_one_letter_options_joined=_yes_no_or_unknown_from_cell(
            columns,
            "takes_one_letter_options_joined",
            unknown=UnknownTakesOneLetterOptionsJoined(),
        ),
        takes_non_option_dash_words_as_arguments=_yes_no_or_unknown_from_cell(
            columns,
            "takes_non_option_dash_words_as_arguments",
            unknown=UnknownTakesNonOptionDashWordsAsArguments(),
        ),
        runs_text_in_calling_shell=_yes_or_no_from_cell(
            columns, "runs_text_in_calling_shell"
        ),
        exits_with_exit_code_of_next_program=_exits_with_exit_code_of_next_program_from_cell(
            columns, "exits_with_exit_code_of_next_program"
        ),
        default_run_file=_default_run_file_from_cell(columns),
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


def _default_run_file_from_cell(
    columns: Mapping[str, str],
) -> str | UnknownDefaultRunFile | None:
    """Read `default_run_file`, in which `none` says the program runs no file when its words name none and a blank is unknown."""
    if columns["default_run_file"] == "":
        return UnknownDefaultRunFile()
    return _text_or_none_from_cell(columns, "default_run_file")


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
    """Raise ValueError on a row that does not say what it was checked against, or whose `reviewed` is none of empty, `yes` and `agents`."""
    if not columns["checked_against"]:
        raise ValueError("checked_against is empty")
    if columns["reviewed"] not in ("", "yes", "agents"):
        raise ValueError(f"reviewed is {columns['reviewed']!r}, not empty, yes or agents")


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
    return _yes_no_or_unknown_from_cell(
        columns, column, unknown=UnknownExitsWithExitCodeOfNextProgram()
    )


def _yes_no_or_unknown_from_cell[Unknown](
    columns: Mapping[str, str], column: str, *, unknown: Unknown
) -> bool | Unknown:
    """Read `yes` as True, `no` as False and a blank as the given unknown answer, raising ValueError on any other word."""
    if columns[column] == "":
        return unknown
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
